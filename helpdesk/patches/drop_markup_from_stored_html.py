import json

import frappe
from frappe.utils.html_utils import sanitize_html

from helpdesk.extends.document import (
    CONTROLLER_SANITIZED_FIELDS,
    JSON_HTML_FIELDS,
    MARKUP,
    drop_markup_data,
    iter_elements,
    parse_fragment,
    sanitize_json_html,
    sanitize_markup,
    serialize_fragment,
)

BATCH_SIZE = 500
# What a value drop_markup_data changes must contain: a data-* attribute, the
# mention class, or a character reference that could spell either.
NEEDLES = ("data-", "mention", "&#")


def execute():
    """Sanitize stored values again where the save-time sanitizer now does more.

    Text Editor fields (standard and custom), and the fields their controller
    sanitizes (CONTROLLER_SANITIZED_FIELDS), whose value has a data-* attribute
    or mention text with markup (helpdesk.extends.document.drop_markup_data);
    then the JSON fields whose strings are HTML (JSON_HTML_FIELDS), whose
    attribute quotes the earlier whole-value sanitizing rewrote
    (class='"h4"') are put back too. Only rows whose value changes are
    written, each with what a save would store now, and only if the value is
    still the one read, so an edit made meanwhile by a running release is kept.
    Unlike a save, this also cleans cancelled and submitted rows: a stored
    value runs wherever it is shown. The modified time is not touched, and a
    second run changes nothing. Rows are read in batches of BATCH_SIZE, and
    only those whose value could need it. A value that can't be cleaned (JSON
    nested too deeply) is named and left for a person.
    """
    fields = [(dt, f, clean_text_editor) for dt, f in text_editor_fields()]
    fields += [
        (dt, f, clean_controller_sanitized)
        for dt, f in sorted(CONTROLLER_SANITIZED_FIELDS)
    ]
    for doctype, fieldname, clean in fields:
        if column_exists(doctype, fieldname):
            report(doctype, fieldname, resanitize(doctype, fieldname, clean, NEEDLES))
    for doctype, fieldname in sorted(JSON_HTML_FIELDS):
        if column_exists(doctype, fieldname):
            report(doctype, fieldname, resanitize(doctype, fieldname, clean_json_html))


def column_exists(doctype, fieldname):
    return frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, fieldname)


def report(doctype, fieldname, changed):
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


def clean_controller_sanitized(value):
    cleaned = drop_markup_data(value)
    return cleaned if cleaned != value else None


def clean_json_html(value):
    """sanitize_json_html, after putting back the attribute quotes the earlier
    whole-value sanitizing rewrote."""
    repaired = sanitize_json_html(value)
    try:
        data = json.loads(repaired)
    except ValueError:
        return repaired if repaired != value else None
    fixed = _map_strings(data, unquote_attributes)
    if fixed != data:
        repaired = json.dumps(fixed, ensure_ascii=False, separators=(",", ":"))
    return repaired if repaired != value else None


def _map_strings(node, fn):
    if isinstance(node, str):
        return fn(node)
    if isinstance(node, list):
        return [_map_strings(item, fn) for item in node]
    if isinstance(node, dict):
        return {key: _map_strings(item, fn) for key, item in node.items()}
    return node


def unquote_attributes(html):
    """html with each attribute value wrapped in literal double quotes unwrapped:
    sanitizing a JSON text as HTML read class=\\"h4\\" as the value "h4",
    quotes included. Sanitized again, so bleach writes the result."""
    if not MARKUP.search(html):
        return html
    fragment = parse_fragment(html)
    changed = False
    for element in iter_elements(fragment):
        for name, value in list(element.attrib.items()):
            if len(value) >= 2 and value[0] == value[-1] == '"':
                element.set(name, value[1:-1])
                changed = True
    return sanitize_markup(serialize_fragment(fragment)) if changed else html


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
            try:
                cleaned = clean(value) if isinstance(value, str) else None
            except frappe.ValidationError:
                print(f"Left {doctype} {name}: its {fieldname} can't be cleaned")
                frappe.clear_messages()
                cleaned = None
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
