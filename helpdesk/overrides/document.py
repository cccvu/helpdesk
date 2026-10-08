"""Always validate a rename a client asks for.

Frappe v15's whitelisted Document.rename passes the caller's validate_rename
and force on to rename_doc, and run_doc_method checks only read permission
before calling it. A client could therefore rename a document without the
write check, allow_rename, before_rename or the name rules (validate_rename),
or rename a document whose DocType doesn't allow it (force). Frappe develop
drops validate_rename (frappe/frappe#44068; version-15 backport
frappe/frappe#44076) but still forwards force.

This backports that change and also ignores a client's force: drop this
module, its before_request hook and its tests once the pinned Frappe's
whitelisted rename ignores both.
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

    validate_rename and force are accepted for compatibility and ignored, so
    every rename a client asks for checks write permission, allow_rename and
    the name rules. Server code that must force a rename calls _rename or
    frappe.rename_doc.
    """
    return self._rename(name=name, merge=merge)


rename._ignores_validate_rename = True


def ignore_client_validate_rename():
    """Install the rename above on Document, once per process.

    Runs as a before_request hook, before any handler.
    """
    if getattr(Document.rename, "_ignores_validate_rename", False):
        return
    Document.rename = rename
