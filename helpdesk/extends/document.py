import re

import frappe
from frappe.utils.html_utils import sanitize_html

# Where a browser starts a tag, an end tag or a comment; any other "<" is text,
# so plain prose such as "a < b" or "5 > 4" is kept as typed.
MARKUP = re.compile(r"<[A-Za-z/!?]")

# Field types Frappe's BaseDocument._sanitize_content never sanitizes.
NON_HTML_FIELDTYPES = {"Attach", "Attach Image", "Barcode", "Code"}


def sanitize_html_fields(doc, method=None):
    """Force-sanitize every HTML-bearing field on save, closing Frappe v15's gaps.

    Frappe v15's sanitize_html returns a value unchanged when it parses as JSON,
    and when BeautifulSoup finds no tag in it (for example "<!--><img ...>-->",
    which browsers end at "<!-->" and build live elements from). /app renders
    several stored fields as HTML in the live page (the Text Editor formatter's
    jQuery $(value), and list, report and timeline views after
    remove_script_and_style, which keeps on* handlers), so such a value runs
    there. This mirrors Frappe's own BaseDocument._sanitize_content field
    selection but forces sanitization with always_sanitize=True. It runs on
    before_validate (which ignore_validate keeps) and again on before_save, after
    a controller's validate may fill a field in (e.g. a Communication's sender
    name from its Contact).

    Upstream develop closes both gaps (frappe/frappe#41626 and has_html_tags);
    drop this, and the Communication recipient guard beside it, once version-15
    has them.
    """
    if frappe.flags.in_install:
        return
    meta = doc.meta
    for fieldname, value in doc.get_valid_dict(ignore_virtual=True).items():
        if not isinstance(value, str) or not MARKUP.search(value):
            continue
        if "<!-- markdown -->" in value and not _has_html_tag(value):
            # Frappe leaves markdown content to its own converter.
            continue
        df = meta.get_field(fieldname)
        if not df:
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


def _has_html_tag(value):
    from bs4 import BeautifulSoup

    return bool(BeautifulSoup(value, "html.parser").find())
