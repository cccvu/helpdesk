"""Always validate a rename a client asks for.

Frappe v15's whitelisted Document.rename passes the caller's validate_rename
and force on to rename_doc, and run_doc_method checks only read permission
before calling it. A client could therefore rename a document without the
write check, allow_rename, before_rename or the name rules (validate_rename),
or rename a document whose DocType doesn't allow it (force). Frappe develop
drops validate_rename (frappe/frappe#44068; version-15 backport
frappe/frappe#44076) but still forwards force.

The whitelisted frappe.rename_doc also passes a client's force and
ignore_if_exists on, so a client that can write a document could rename it
although its DocType doesn't allow renaming, or onto an existing name.

This module backports frappe/frappe#44068 and also ignores a client's force
and ignore_if_exists: Document.rename is replaced in each process, and
frappe.rename_doc only for clients, through the override_whitelisted_methods
hook (/api/method, cmd and /api/v2/method all apply it), because server code
calls it with force legitimately. Drop this module, its hooks and its tests
once the pinned Frappe ignores a client's force everywhere (Document.rename
and frappe.rename_doc) and a client's ignore_if_exists.
"""

import frappe
from frappe.model.document import Document
from frappe.model.rename_doc import rename_doc as _rename_doc


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


@frappe.whitelist(methods=["POST", "PUT"])
def rename_doc(
    doctype: str,
    old: str,
    new: str,
    force: bool = False,
    merge: bool = False,
    *,
    ignore_if_exists: bool = False,
    show_alert: bool = True,
    rebuild_search: bool = True,
) -> str:
    """frappe.rename_doc for clients: rename doc(doctype, old) to new.

    force and ignore_if_exists are accepted for compatibility and ignored, so
    every rename a client asks for checks write permission, allow_rename, an
    existing name and the name rules. Server code that must force a rename
    calls frappe.rename_doc, which this replaces only for HTTP requests.
    """
    return _rename_doc(
        doctype=doctype,
        old=old,
        new=new,
        merge=merge,
        show_alert=show_alert,
        rebuild_search=rebuild_search,
    )
