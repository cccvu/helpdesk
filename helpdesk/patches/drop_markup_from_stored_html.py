import frappe
from frappe.utils.html_utils import sanitize_html

from helpdesk.extends.document import (
    JSON_HTML_FIELDS,
    drop_markup_data,
    sanitize_json_html,
)

BATCH_SIZE = 500


def execute():
    """Sanitize stored values again where the save-time sanitizer now does more.

    Text Editor fields (standard and custom) whose value has a data-* attribute
    or mention text with markup (helpdesk.extends.document.drop_markup_data),
    and the JSON fields whose strings are HTML (JSON_HTML_FIELDS). Only rows
    whose value changes are written, each with what a save would store now,
    and only if the value is still the one read, so an edit made meanwhile by a
    running release is kept. The modified time is not touched, and a second run
    changes nothing. Rows are read in batches of BATCH_SIZE, and only those
    whose value could need it.
    """
    for doctype, fieldname in text_editor_fields():
        changed = resanitize(
            doctype, fieldname, clean_text_editor, ("data-", "mention")
        )
        if changed:
            print(f"Sanitized {changed} {doctype}.{fieldname} value(s) again")
    for doctype, fieldname in sorted(JSON_HTML_FIELDS):
        if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, fieldname):
            changed = resanitize(doctype, fieldname, clean_json_html)
            if changed:
                print(f"Sanitized {changed} {doctype}.{fieldname} value(s) again")


def text_editor_fields():
    """(doctype, fieldname) of every stored Text Editor field the sanitizer covers."""
    rows = frappe.get_all(
        "DocField", filters={"fieldtype": "Text Editor"}, fields=["parent", "fieldname"]
    ) + frappe.get_all(
        "Custom Field",
        filters={"fieldtype": "Text Editor"},
        fields=["dt as parent", "fieldname"],
    )
    fields = set()
    for row in rows:
        if not frappe.db.exists("DocType", row.parent):
            continue
        meta = frappe.get_meta(row.parent)
        df = meta.get_field(row.fieldname)
        if (
            meta.issingle
            or meta.is_virtual
            or not df
            or df.get("is_virtual")
            or df.get("ignore_xss_filter")
            or not frappe.db.table_exists(row.parent)
            or not frappe.db.has_column(row.parent, row.fieldname)
        ):
            continue
        fields.add((row.parent, row.fieldname))
    return sorted(fields)


def clean_text_editor(value):
    """What a save would store, if it differs only because of drop_markup_data."""
    sanitized = sanitize_html(value, linkify=True, always_sanitize=True)
    cleaned = drop_markup_data(sanitized)
    return cleaned if cleaned != sanitized else None


def clean_json_html(value):
    cleaned = sanitize_json_html(value)
    return cleaned if cleaned != value else None


def resanitize(doctype, fieldname, clean, needles=()):
    """Write clean(value) over each row of doctype.fieldname it returns a value
    for, in batches by name. With needles, only rows whose value contains one
    of them are read. Returns how many rows were written."""
    table = frappe.qb.DocType(doctype)
    column = table[fieldname]
    condition = column.isnotnull()
    if needles:
        matches = [column.like(f"%{needle}%") for needle in needles]
        condition = matches[0]
        for match in matches[1:]:
            condition = condition | match
    changed = 0
    last = None
    while True:
        query = frappe.qb.from_(table).select(table.name, column).where(condition)
        if last is not None:
            query = query.where(table.name > last)
        rows = query.orderby(table.name).limit(BATCH_SIZE).run()
        if not rows:
            return changed
        for name, value in rows:
            cleaned = clean(value) if isinstance(value, str) else None
            if cleaned is not None:
                changed += write_if_unchanged(doctype, fieldname, name, value, cleaned)
        last = rows[-1][0]
        # Keep transactions short: the site serves while this runs.
        frappe.db.commit()  # nosemgrep


def write_if_unchanged(doctype, fieldname, name, old, new):
    """Set the value only if it is still old; returns 1 if it was written."""
    table = frappe.qb.DocType(doctype)
    column = table[fieldname]
    frappe.qb.update(table).set(column, new).where(table.name == name).where(
        column == old
    ).run()
    if frappe.db.get_value(doctype, name, fieldname) == new:
        return 1
    return 0
