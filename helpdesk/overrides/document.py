"""Always validate a rename a client asks for.

Frappe v15's whitelisted Document.rename passes the caller's validate_rename on
to rename_doc, and run_doc_method checks only read permission before calling
it. A client could therefore rename a document without the write check,
allow_rename, before_rename or the name rules. Frappe develop drops the
argument (frappe/frappe#44068; version-15 backport frappe/frappe#44076).

This is an interim backport of that change: drop this module, its
before_request hook and its tests once the pinned Frappe includes it.
"""

import frappe
from frappe.model.document import Document


@frappe.whitelist()
def rename(
    self,
    name: str | int,
    merge: bool = False,
    force: bool = False,
    validate_rename: bool = True,
):
    """Rename the document to `name`. This transforms the current object.

    validate_rename is accepted for compatibility and ignored, as upstream does.
    """
    return self._rename(name=name, merge=merge, force=force)


rename._ignores_validate_rename = True


def ignore_client_validate_rename():
    """Install the rename above on Document, once per process.

    Runs as a before_request hook, after authentication and before any handler.
    """
    if getattr(Document.rename, "_ignores_validate_rename", False):
        return
    Document.rename = rename
