"""Tag and Kanban column names that can't break out of /app's HTML attributes.

Frappe v15's desk writes tag names (the list view's tags, the Tag formatter,
the sidebar's tag stats) and Kanban Board column names (the column header)
into HTML attributes without escaping them. A double quote closes the
attribute, and a character reference such as "&lt;" turns into markup when the
desk reads the attribute back and renders it again. The save-time sanitizer
(helpdesk.extends.document) acts only on markup, so it never sees either.

These two are free-form labels nothing legitimate writes those characters in,
so a new or changed one is refused here; stored values are left alone (the
desk escaping shim neutralizes them where they render). Record names and user
names get no such rule.

Drop the tag rules once the pinned Frappe escapes tags in /app (upstream
frappe#46726; its version-15 backport frappe#47326 is open), and the Kanban
column rule once it escapes a Kanban column's name (not fixed upstream).
"""

import html

import frappe
from frappe import _

UNSAFE_LABEL_CHARS = '"<>'


def is_safe_label(value: str, allow_comma: bool = True) -> bool:
    """Whether value has no double quote, "<" or ">" (or comma, unless
    allow_comma), and no character reference a browser would decode: "&lt;",
    "&#34;", "&QUOT;" and legacy forms without a semicolon such as "&lt".
    Plain ampersands ("R&D", "Q & A") are fine. An empty or non-string value
    is safe: the caller decides what it means."""
    if not isinstance(value, str) or not value:
        return True
    if any(char in value for char in UNSAFE_LABEL_CHARS):
        return False
    if not allow_comma and "," in value:
        return False
    return html.unescape(value) == value


def check_tag(doc, method=None):
    """Tag before_validate: a new Tag's name. A save can't change the name
    (a rename can: check_tag_rename), so a legacy Tag can still be edited."""
    if _checked() and doc.is_new() and not is_safe_label(doc.name, allow_comma=False):
        _refuse(tag=True)


def check_tag_rename(doc, method=None, old=None, new=None, merge=False):
    """Tag before_rename: the new name. Frappe calls it as
    (doc, method, old, new, merge)."""
    if _checked() and not is_safe_label(new, allow_comma=False):
        _refuse(tag=True)


def check_tag_link(doc, method=None):
    """Tag Link before_validate: the tag a document is given.

    Frappe's add_tag, add_tags and Helpdesk's update_tags write _user_tags
    with frappe.db.set_value (no document hooks), then insert a Tag Link for
    each newly attached tag in the same transaction, even when the Tag already
    exists (a legacy one stored before this rule). Refusing the link fails the
    request, and the transaction is rolled back with it.
    """
    if not _checked() or is_safe_label(doc.tag, allow_comma=False):
        return
    if doc.is_new() or frappe.db.get_value("Tag Link", doc.name, "tag") != doc.tag:
        _refuse(tag=True)


def check_user_tags(doc, method=None):
    """ "*" before_validate: a new or changed _user_tags value, on a doctype
    whose _user_tags is a real field (Communication), so a document save could
    set it. Each comma-separated piece is a tag; pieces already stored are
    not checked again."""
    if not _checked() or not doc.meta.get_field("_user_tags"):
        return
    value = doc.get("_user_tags")
    if not isinstance(value, str):
        return
    unsafe = {piece for piece in _pieces(value) if not is_safe_label(piece)}
    if not unsafe:
        return
    if not doc.is_new():
        unsafe -= set(_pieces(frappe.db.get_value(doc.doctype, doc.name, "_user_tags")))
    if unsafe:
        _refuse(tag=True)


def check_kanban_columns(doc, method=None):
    """Kanban Board before_validate: each column name the board didn't have.

    Compared by name with the stored board, not by row: update_column_order
    rebuilds every column as a new row. A legacy column stored before this
    rule is never refused, so card moves (update_order, which saves the whole
    board) keep working on such a board.
    """
    if not _checked():
        return
    stored = set()
    if not doc.is_new():
        stored = set(
            frappe.get_all(
                "Kanban Board Column",
                filters={"parent": doc.name, "parenttype": "Kanban Board"},
                pluck="column_name",
            )
        )
    for column in doc.get("columns") or []:
        name = column.get("column_name")
        if name not in stored and not is_safe_label(name):
            _refuse(tag=False)


def _pieces(value):
    return [piece for piece in (value or "").split(",") if piece]


def _checked():
    flags = frappe.flags
    return not (
        flags.in_install or flags.in_migrate or flags.in_patch or flags.in_fixtures
    )


def _refuse(tag):
    # Never echo the value: /app renders msgprint as HTML
    if tag:
        message = _(
            "A tag can't contain commas, double quotes, < or >, or an HTML character reference"
        )
    else:
        message = _(
            "A Kanban column name can't contain double quotes, < or >, or an HTML character reference"
        )
    frappe.throw(message, frappe.ValidationError)
