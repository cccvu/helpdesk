import frappe
from frappe.model.document import Document
from frappe.model.rename_doc import update_document_title
from frappe.tests.utils import FrappeTestCase

from helpdesk.overrides.document import ignore_client_validate_rename
from helpdesk.test_utils import get_team_rule_state, make_agent, make_team, make_ticket


class TestValidatedRename(FrappeTestCase):
    """Every rename a client asks for is validated: the caller's
    validate_rename and force are ignored."""

    def setUp(self):
        frappe.set_user("Administrator")
        ignore_client_validate_rename()
        self.agent = make_agent("validated_rename_agent@example.com")
        self.team = make_team("Test Rename Shim", [self.agent], disabled=True).name

    def tearDown(self):
        frappe.set_user("Administrator")
        for team in frappe.get_all(
            "HD Team", filters={"name": ["like", "Test Rename Shim%"]}, pluck="name"
        ):
            frappe.delete_doc("HD Team", team, force=True, ignore_permissions=True)

    def test_installer_is_idempotent(self):
        installed = Document.rename
        ignore_client_validate_rename()
        self.assertIs(Document.rename, installed)

    def test_rename_is_still_whitelisted(self):
        doc = frappe.get_doc("HD Team", self.team)
        frappe.is_whitelisted(doc.rename.__func__)

    def test_reader_cannot_skip_rename_validation(self):
        state = get_team_rule_state(self.team)
        frappe.db.savepoint("validated_rename")
        frappe.set_user(self.agent)
        try:
            doc = frappe.get_doc("HD Team", self.team)
            self.assertTrue(doc.has_permission("read"))
            # As run_doc_method calls it for a client.
            with self.assertRaisesRegex(frappe.ValidationError, "write permission"):
                doc.run_method(
                    "rename", name="Test Rename Shim 2", validate_rename=False
                )
        finally:
            frappe.set_user("Administrator")
            frappe.db.rollback(save_point="validated_rename")

        self.assertTrue(frappe.db.exists("HD Team", self.team))
        self.assertFalse(frappe.db.exists("HD Team", "Test Rename Shim 2"))
        self.assertEqual(get_team_rule_state(self.team), state)

    def test_writer_cannot_force_a_rename(self):
        ticket = make_ticket(subject="Test Rename Shim Ticket").name
        new_name = "Test Rename Shim Forced"
        frappe.db.savepoint("forced_rename")
        frappe.set_user(self.agent)
        try:
            doc = frappe.get_doc("HD Ticket", ticket)
            self.assertTrue(doc.has_permission("write"))
            # As run_doc_method calls it for a client.
            with self.assertRaisesRegex(
                frappe.ValidationError, "not allowed to be renamed"
            ):
                doc.run_method("rename", name=new_name, force=True)
        finally:
            frappe.set_user("Administrator")
            frappe.db.rollback(save_point="forced_rename")

        self.assertTrue(frappe.db.exists("HD Ticket", ticket))
        self.assertFalse(frappe.db.exists("HD Ticket", new_name))

    def test_validated_rename_still_works(self):
        doc = frappe.get_doc("HD Team", self.team)
        doc.rename("Test Rename Shim Renamed")

        self.assertEqual(doc.name, "Test Rename Shim Renamed")
        self.assertTrue(frappe.db.exists("HD Team", "Test Rename Shim Renamed"))

    def test_validated_merge_still_works(self):
        target = make_team("Test Rename Shim Target", [self.agent], disabled=True)
        doc = frappe.get_doc("HD Team", self.team)
        doc.rename(target.name, merge=True)

        self.assertFalse(frappe.db.exists("HD Team", self.team))
        self.assertTrue(frappe.db.exists("HD Team", target.name))

    def test_update_document_title_still_renames(self):
        name = update_document_title(
            doctype="HD Team", docname=self.team, name="Test Rename Shim Title"
        )

        self.assertEqual(name, "Test Rename Shim Title")
        self.assertTrue(frappe.db.exists("HD Team", "Test Rename Shim Title"))
