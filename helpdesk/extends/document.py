import json
import re

import frappe
import html5lib
from frappe import _
from frappe.utils import cstr
from frappe.utils.html_utils import sanitize_html

# Where a browser starts a tag, an end tag or a comment; any other "<" is text,
# so plain prose such as "a < b" or "5 > 4" is kept as typed.
MARKUP = re.compile(r"<[A-Za-z/!?]")

# Field types Frappe's BaseDocument._sanitize_content never sanitizes, plus JSON.
# JSON is not in Frappe's list: Frappe's sanitize_html returns a JSON value
# unchanged (its is_json early return), so a JSON field is never bleached there.
# always_sanitize=True bypasses that early return, so without this a JSON field's
# value (structured config, never rendered as HTML) would be escaped on every
# save. A JSON-shaped *string* in a Data/Text/Text Editor field is still
# sanitized: only the "JSON" fieldtype is skipped, not JSON-looking content.
NON_HTML_FIELDTYPES = {"Attach", "Attach Image", "Barcode", "Code", "JSON"}

# A character that is markup once a browser has decoded an attribute value or an
# element's text. sanitize_html stores them there as "&lt;" and "&gt;".
DECODED_MARKUP = re.compile(r"[<>]")

# Fields that hold JSON whose strings the desk can render as HTML: the workspace
# editor puts its blocks' text into innerHTML, and the list view shows a saved
# filter's field name in a message as HTML. A JSON escape ("\u003c") hides markup
# from MARKUP, and sanitizing the JSON text as HTML mangles its quotes, so each
# string in it is sanitized instead (sanitize_json_html).
JSON_HTML_FIELDS = {("Workspace", "content"), ("List Filter", "filters")}

# Fields their controller sanitizes itself (ignore_xss_filter, so the hook
# otherwise leaves them alone) but that the desk loads into a Text Editor: /app's
# timeline puts every comment into a mention-enabled editor for every viewer.
# The hook still drops decoded markup from them (drop_markup_data).
CONTROLLER_SANITIZED_FIELDS = {("Comment", "content")}

# Deeper JSON in a JSON_HTML_FIELDS value is refused rather than walked: real
# values nest a few levels (a workspace block's data), and a depth near the
# recursion limit would otherwise escape the check.
MAX_JSON_DEPTH = 32

# How bleach.clean, which sanitize_html uses, writes HTML.
_SERIALIZER_OPTIONS = {
    "quote_attr_values": "always",
    "omit_optional_tags": False,
    "escape_lt_in_attrs": True,
    "resolve_entities": False,
    "alphabetical_attributes": False,
}


def sanitize_html_fields(doc, method=None):
    """Force-sanitize every HTML-bearing field on save, closing Frappe v15's gaps.

    Frappe v15's sanitize_html returns a value unchanged when it parses as JSON,
    and when BeautifulSoup finds no tag in it (for example "<!--><img ...>-->",
    which browsers end at "<!-->" and build live elements from). /app renders
    several stored fields as HTML in the live page (the Text Editor formatter's
    jQuery $(value), and list, report and timeline views after
    remove_script_and_style, which keeps on* handlers), so such a value runs
    there. This follows Frappe's own BaseDocument._sanitize_content field
    selection but forces sanitization with always_sanitize=True. It runs on
    before_validate (which ignore_validate keeps) and again on before_save, after
    a controller's validate may fill a field in (e.g. a Communication's sender
    name from its Contact), and it covers child-table rows too, which Frappe
    sanitizes in _validate but doc_events["*"] does not reach on its own.

    Two deliberate departures from _sanitize_content, both forced by
    always_sanitize=True:

    - It does not copy Frappe's "<!-- markdown -->" and-no-tag skip. That skip
      relies on the same tagless check that is the very gap this closes, so an
      attacker who prefixes the sentinel to a tagless payload would keep its
      skip. sanitize_html keeps HTML comments (strip_comments=False), so the
      markdown sentinel survives sanitization and the content stays markdown.

    - It skips a field with no meta (a default column such as name, or the JSON
      _comments/_assign columns on a special doctype) rather than sanitizing it
      as Frappe's else branch does. Under always_sanitize those JSON-shaped
      columns, which Frappe spares through its is_json early return, would be
      escaped and corrupted; the residual gap (a meta-less name holding markup)
      has no known HTML sink.

    Two additions on top of sanitize_html, for markup it keeps but the desk
    decodes back into live HTML: data-* values and mention text with markup
    (drop_markup_data), and JSON fields whose strings are HTML
    (JSON_HTML_FIELDS).

    Upstream develop closes both v15 gaps (frappe/frappe#41626 and
    has_html_tags); drop this, and the Communication recipient guard beside it,
    once version-15 has them. drop_markup_data can go once Frappe's mention
    blot writes its values as text, and JSON_HTML_FIELDS once the workspace
    blocks and the list view's filter message escape what they render.
    """
    if frappe.flags.in_install:
        return
    _sanitize_doc(doc)
    for child in doc.get_all_children():
        _sanitize_doc(child)


def _sanitize_doc(doc):
    meta = doc.meta
    # Read stored columns directly: get_valid_dict would also reject values
    # the controller converts later in validate (a list in a JSON-text field)
    for fieldname in meta.get_valid_columns():
        df = meta.get_field(fieldname)
        if not df or df.get("is_virtual"):
            continue
        value = _stored_text(df, doc.get(fieldname))
        if value is None:
            continue
        is_json_html = (doc.doctype, fieldname) in JSON_HTML_FIELDS
        if not is_json_html and not MARKUP.search(value):
            continue
        fieldtype = df.get("fieldtype")
        if (doc.doctype, fieldname) in CONTROLLER_SANITIZED_FIELDS:
            doc.set(fieldname, drop_markup_data(value))
            continue
        if (
            df.get("ignore_xss_filter")
            or fieldtype in NON_HTML_FIELDTYPES
            or (
                fieldtype in ("Data", "Small Text", "Text")
                and df.get("options") == "Email"
            )
            or doc.docstatus.is_cancelled()
            or (doc.docstatus.is_submitted() and not df.get("allow_on_submit"))
        ):
            continue
        if is_json_html:
            doc.set(fieldname, sanitize_json_html(value))
        else:
            doc.set(
                fieldname, sanitize_markup(value, linkify=fieldtype == "Text Editor")
            )


def sanitize_markup(value, linkify=False):
    """Frappe's sanitize_html, forced, then drop_markup_data."""
    return drop_markup_data(sanitize_html(value, linkify=linkify, always_sanitize=True))


def drop_markup_data(html):
    """Remove from sanitized HTML what the desk would turn back into markup.

    sanitize_html keeps every data-* attribute and a text's "<" as escaped text,
    and a browser decodes both (dataset, textContent). Frappe's Text Editor
    (Quill) makes a mention of any element with the "mention" class, and writes
    its data-value, data-label or data-denotation-char, or failing those its
    text, into innerHTML. So each data-* attribute whose decoded value holds "<"
    or ">" is dropped, and an element whose decoded text holds one loses the
    "mention" class (it stays as plain text). A real mention, a name, has
    neither.

    The check runs on the tree an HTML5 parser builds, as the browser does:
    character references decoded, and SVG and MathML content parsed as foreign
    content. HTML that needs no change is returned exactly as given. Otherwise
    the changed tree is written out and sanitized again, so bleach writes the
    stored value, and checked again; HTML that still doesn't settle after a few
    passes is stored with every tag escaped.
    """
    if "<" not in html:
        return html
    fragment = parse_fragment(html)
    if not _defuse(fragment):
        return html
    for _attempt in range(3):
        html = sanitize_html(serialize_fragment(fragment), always_sanitize=True)
        fragment = parse_fragment(html)
        if not _defuse(fragment):
            return html
    return sanitize_html(html, always_sanitize=True, disallowed_tags="*")


def parse_fragment(html):
    """html as an HTML5 parser builds it, as an ElementTree fragment."""
    return html5lib.parseFragment(
        html, treebuilder="etree", namespaceHTMLElements=False
    )


def serialize_fragment(fragment):
    """A fragment written as bleach writes HTML."""
    walker = html5lib.getTreeWalker("etree")
    return html5lib.serializer.HTMLSerializer(**_SERIALIZER_OPTIONS).render(
        walker(fragment)
    )


def iter_elements(fragment):
    """Every element under fragment, in any namespace (comments skipped),
    without recursion."""
    stack = list(fragment)
    while stack:
        node = stack.pop()
        if isinstance(node.tag, str):
            yield node
            stack.extend(node)


def _text(element):
    """Every text node under element, as textContent has them (order aside),
    without recursion."""
    parts = [element.text or ""]
    stack = list(element)
    while stack:
        node = stack.pop()
        if isinstance(node.tag, str):
            parts.append(node.text or "")
            stack.extend(node)
        parts.append(node.tail or "")
    return "".join(parts)


def _defuse(fragment):
    """Drop decoded markup in place (see drop_markup_data); True if any."""
    changed = False
    for element in iter_elements(fragment):
        for name, value in list(element.attrib.items()):
            local = name.rsplit("}", 1)[-1]
            if local.startswith("data-") and DECODED_MARKUP.search(value):
                del element.attrib[name]
                changed = True
        classes = (element.get("class") or "").split()
        if "mention" in classes and DECODED_MARKUP.search(_text(element)):
            rest = " ".join(name for name in classes if name != "mention")
            if rest:
                element.set("class", rest)
            else:
                del element.attrib["class"]
            changed = True
    return changed


def sanitize_json_html(value):
    """Sanitize each string in a JSON value whose strings are HTML.

    Only strings with markup change, and the JSON is written again only if one
    did, so a value without markup is kept exactly as given. A value that isn't
    JSON is sanitized as HTML, as any other field is. JSON nested deeper than
    MAX_JSON_DEPTH is refused rather than stored unchecked.
    """
    try:
        data = json.loads(value)
    except RecursionError:
        _refuse_nesting()
    except ValueError:
        return sanitize_markup(value) if MARKUP.search(value) else value
    if _depth(data) > MAX_JSON_DEPTH:
        _refuse_nesting()
    changed = False

    def clean(node):
        nonlocal changed
        if isinstance(node, str):
            if not MARKUP.search(node):
                return node
            cleaned = sanitize_markup(node)
            changed = changed or cleaned != node
            return cleaned
        if isinstance(node, list):
            return [clean(item) for item in node]
        if isinstance(node, dict):
            return {key: clean(item) for key, item in node.items()}
        return node

    data = clean(data)
    if not changed:
        return value
    # As the desk's JSON.stringify writes it.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _depth(data):
    """How deeply lists and dicts nest in data, without recursion."""
    deepest, stack = 0, [(data, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, (list, dict)):
            deepest = max(deepest, depth)
            items = node.values() if isinstance(node, dict) else node
            stack.extend((item, depth + 1) for item in items)
    return deepest


def _refuse_nesting():
    frappe.throw(_("This value is nested too deeply to save"), frappe.ValidationError)


def _stored_text(df, value):
    """Return the text a save stores for value, or None if it stores no text.

    BaseDocument.get_valid_dict, which db_insert and db_update use, refuses a
    list in a non-table field and turns any other non-string value in a Read
    Only field into text with cstr. Elsewhere a dict is refused by the database
    driver, and numbers and None carry no markup, so only these become text.
    """
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, list) or df.get("fieldtype") != "Read Only":
        return None
    return cstr(value)
