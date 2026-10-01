import posixpath
from urllib.parse import unquote

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.handler import check_write_permission

LOCAL_PREFIXES = ("/files/", "/private/files/")


class HelpdeskFile(File):
    """File with access checks Frappe v15 doesn't make yet.

    Each check is its own method, and its docstring names the upstream change
    that makes it redundant, so it can be removed once that change is in the
    Frappe version Helpdesk runs on.
    """

    def before_insert(self):
        self.validate_canonical_file_url()
        super().before_insert()

    def validate(self):
        # The parent's validate moves files on disk when is_private changes,
        # so these run first.
        if not self.is_new():
            self.validate_fixed_fields()
            self.validate_reattachment()
            self.validate_unshared_privacy_change()
        super().validate()

    def validate_canonical_file_url(self):
        """Refuse a local file_url that isn't in canonical form.

        A URL such as `/private/files/./x` or `/private/files//x` reads the
        same file on disk as `/private/files/x` but doesn't match that File's
        file_url, so a lookup of existing Files by URL misses it. Frappe's
        `validate_file_path` only refuses `..` segments. Remove when Frappe
        refuses or normalises non-canonical local file URLs.
        """
        if not self.file_url or self.file_url.startswith(("http://", "https://")):
            return
        url = unquote(self.file_url)
        if (
            url.startswith("//")
            or posixpath.normpath(url) != url
            or unquote(url) != url
        ):
            frappe.throw(_("The File URL you've entered is incorrect"))

    def validate_fixed_fields(self):
        """Keep an existing File's file_url and owner as they are.

        Frappe doesn't enforce read-only fields on the server, and File
        permissions follow the owner and the URL, so changing either could
        grant access to another file. The privacy toggle changes file_url
        itself, after this check, inside the parent's validate. Remove when
        Frappe refuses these changes on update (no upstream change yet).
        """
        if frappe.session.user == "Administrator":
            return
        before = self.get_doc_before_save()
        if not before:
            return
        for fieldname in ("file_url", "owner"):
            if self.get(fieldname) != before.get(fieldname):
                frappe.throw(
                    _("{0} of a File can't be changed").format(
                        self.meta.get_label(fieldname)
                    ),
                    frappe.PermissionError,
                )

    def validate_reattachment(self):
        """Moving a File to another document needs write permission on the
        File as stored and on the new document.

        Frappe checks write on the File after the change is applied, so it
        reflects the new document only. Upstream develop checks the new
        document (frappe/frappe 6f23777977, v15 backport PR 43620); remove this
        once Frappe also checks the stored File.
        """
        if (
            self.flags.ignore_permissions
            or frappe.flags.in_install
            or frappe.flags.in_migrate
        ):
            return
        if not (
            self.has_value_changed("attached_to_doctype")
            or self.has_value_changed("attached_to_name")
        ):
            return
        before = self.get_doc_before_save()
        if before:
            before.check_permission("write")
        if self.attached_to_doctype and self.attached_to_name:
            check_write_permission(self.attached_to_doctype, self.attached_to_name)

    def validate_unshared_privacy_change(self):
        """Refuse a privacy change on a File whose stored file shares its URL
        or content with another File.

        Frappe v15 moves the file on disk and rewrites every File with the
        same content hash, including other users'. Remove when Frappe copies
        instead (frappe/frappe 8a0a5ae07f on develop).
        """
        if not self.has_value_changed("is_private"):
            return
        # the rewrite uses this document's content_hash, which the caller can set
        docs = [self, self.get_doc_before_save() or self]
        if any(self._shares_with_another_file(doc) for doc in docs):
            frappe.throw(
                _(
                    "This file is shared with other records, so its privacy can't be changed"
                )
            )

    def _shares_with_another_file(self, doc) -> bool:
        for fieldname in ("file_url", "content_hash"):
            value = doc.get(fieldname)
            if value and frappe.db.exists(
                "File", {"name": ("!=", self.name), fieldname: value}
            ):
                return True
        return False

    @frappe.whitelist()
    def optimize_file(self):
        """Optimize the File as stored, after checking write permission on it.

        The method can be called on a document built from the request, whose
        fields the caller chose. Frappe v15.121.2 checks only that its
        file_url matches the stored one; remove when Frappe works on the
        stored record.
        """
        if not self.name or not frappe.db.exists("File", self.name):
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        stored = frappe.get_doc("File", self.name)
        stored.check_permission("write")
        File.optimize_file(stored)
        self.reload()
