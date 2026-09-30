import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.auth import authenticate
from helpdesk.test_utils import create_user


class TestAuthenticate(FrappeTestCase):
    def setUp(self):
        self.portal_user = create_user("portal.caller@example.com").name
        frappe.db.set_value("User", self.portal_user, "user_type", "Website User")
        conf = frappe.local.conf
        had, before = "block_endpoints" in conf, conf.get("block_endpoints")
        conf.block_endpoints = 1
        self.addCleanup(
            lambda: conf.update(block_endpoints=before)
            if had
            else conf.pop("block_endpoints", None)
        )
        self.addCleanup(frappe.set_user, "Administrator")

    def call(self, user, **form):
        frappe.set_user(user)
        frappe.local.form_dict = frappe._dict(cmd="run_doc_method", **form)
        authenticate()

    def test_a_portal_user_cant_run_a_method_on_a_client_built_document(self):
        with self.assertRaises(frappe.PermissionError):
            self.call(self.portal_user, docs='{"doctype": "HD Ticket", "name": "1"}')

    def test_a_portal_user_can_run_a_method_by_doctype_and_name(self):
        self.call(self.portal_user, dt="HD Ticket", dn="1")

    def test_a_system_user_can_still_send_a_document(self):
        self.call("Administrator", docs='{"doctype": "HD Ticket", "name": "1"}')
