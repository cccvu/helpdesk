import frappe
from frappe import _
from frappe.desk.doctype.workspace.workspace import is_workspace_manager
from frappe.utils import cint


def check_workspace_write(doc, method=None):
    """Let only Workspace Managers write a public Workspace or another user's
    private one, on every path.

    Frappe gives Desk User, so every System User, create, write and delete on
    every Workspace. Its own ownership checks are only in the sidebar's methods
    (new_page, update_page, hide_page, delete_page), and its validate checks only
    a public page's new value, so a save through REST or frappe.client could put
    a page in someone else's sidebar, overwrite or delete their page, or make a
    public page private. Everyone else may now insert, save, rename or delete
    only a private Workspace whose for_user is themselves, before and after the
    change. The sidebar's methods already keep to that, and save with
    ignore_permissions, which this check deliberately ignores.

    Drop this once Frappe checks a private page's owner on every write path.
    """
    if not _checked():
        return
    if not doc.is_new():
        stored = frappe.db.get_value(
            "Workspace", doc.name, ["public", "for_user"], as_dict=True
        )
        if stored and not _own_private(stored.public, stored.for_user):
            _refuse()
    if not _own_private(doc.public, doc.for_user):
        _refuse()


def check_workspace_change(doc, method=None, *args):
    """The same rule on rename (before_rename) and delete (on_trash), on the
    stored Workspace."""
    if _checked() and not _own_private(doc.public, doc.for_user):
        _refuse()


def _checked():
    flags = frappe.flags
    return not (
        flags.in_install
        or flags.in_uninstall
        or flags.in_migrate
        or flags.in_patch
        or flags.in_fixtures
        or is_workspace_manager()
    )


def _own_private(public, for_user):
    return not cint(public) and bool(for_user) and for_user == frappe.session.user


def _refuse():
    frappe.throw(
        _(
            "Only a Workspace Manager can change a public workspace or another user's private workspace"
        ),
        frappe.PermissionError,
    )
