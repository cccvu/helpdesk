import frappe
from frappe import _

from helpdesk.file_access import can_read_file_url

ATTACH_FIELDTYPES = ("Attach", "Attach Image")


def validate_private_attachments(doc, method=None):
    """Refuse an Attach field set to a private file the user can't read.

    After save, Frappe's `attach_files_to_document` attaches the file named in
    an Attach field to the document: it moves an unattached File with that
    URL there, or copies the file into a new File. On Frappe v15 neither step
    checks the user's access to the file. Remove when Frappe does (the owner
    filter frappe/frappe cb620dc4ba on develop, and the insert check
    `validate_private_file_access` from v15.121.2).
    """
    if frappe.session.user == "Administrator":
        return
    for df in doc.meta.get("fields", {"fieldtype": ("in", ATTACH_FIELDTYPES)}):
        value = doc.get(df.fieldname)
        if not value or not str(value).startswith("/private/"):
            continue
        if not doc.has_value_changed(df.fieldname):
            continue
        if not can_read_file_url(value):
            frappe.throw(
                _("You do not have permission to access this file"),
                frappe.PermissionError,
            )
