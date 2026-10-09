import re

import frappe
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

    Upstream develop closes both v15 gaps (frappe/frappe#41626 and
    has_html_tags); drop this, and the Communication recipient guard beside it,
    once version-15 has them.
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
        if value is None or not MARKUP.search(value):
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
        doc.set(
            fieldname,
            sanitize_html(
                value, linkify=fieldtype == "Text Editor", always_sanitize=True
            ),
        )


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
