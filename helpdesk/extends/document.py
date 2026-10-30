import json
import re

import frappe
from bs4 import BeautifulSoup
from bs4.dammit import EntitySubstitution
from bs4.formatter import HTMLFormatter
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
    neither. HTML that needs no change is returned exactly as given.
    """
    if "data-" not in html and "mention" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    changed = False
    for tag in soup.find_all(True):
        for name, value in list(tag.attrs.items()):
            if name.startswith("data-") and DECODED_MARKUP.search(_attr_text(value)):
                del tag[name]
                changed = True
        classes = tag.get("class") or []
        if "mention" in classes and DECODED_MARKUP.search(tag.get_text()):
            rest = [name for name in classes if name != "mention"]
            if rest:
                tag["class"] = rest
            else:
                del tag["class"]
            changed = True
    return soup.decode(formatter=_AS_PARSED) if changed else html


class _AsParsed(HTMLFormatter):
    """BeautifulSoup's minimal formatter, but with attributes in their own order
    (the default sorts them) and void elements as HTML writes them (<br>)."""

    def attributes(self, tag):
        return list(tag.attrs.items())


_AS_PARSED = _AsParsed(
    entity_substitution=EntitySubstitution.substitute_xml,
    void_element_close_prefix=None,
)


def _attr_text(value):
    return " ".join(value) if isinstance(value, list) else value


def sanitize_json_html(value):
    """Sanitize each string in a JSON value whose strings are HTML.

    Only strings with markup change, and the JSON is written again only if one
    did, so a value without markup is kept exactly as given. A value that isn't
    JSON is sanitized as HTML, as any other field is.
    """
    try:
        data = json.loads(value)
    except (ValueError, RecursionError):
        return sanitize_markup(value) if MARKUP.search(value) else value
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

    try:
        data = clean(data)
    except RecursionError:
        return sanitize_markup(value)
    if not changed:
        return value
    # As the desk's JSON.stringify writes it.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


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
