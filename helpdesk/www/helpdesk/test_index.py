import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.change_log import get_source_url

from helpdesk.www.helpdesk.index import get_site_boot


class TestSiteBoot(FrappeTestCase):
    def setUp(self) -> None:
        frappe.set_user("Administrator")
        frappe.db.set_single_value("HD Settings", "brand_name", "")
        frappe.db.set_single_value("HD Settings", "favicon", "")
        frappe.db.set_single_value("Website Settings", "favicon", "")
        frappe.db.set_single_value("System Settings", "disable_user_pass_login", 0)

    def tearDown(self) -> None:
        frappe.db.rollback()

    def test_unbranded_site_keeps_upstream_defaults(self):
        boot = get_site_boot()
        self.assertFalse(boot["brand_name"])
        self.assertFalse(boot["favicon"])
        self.assertEqual(boot["disable_user_pass_login"], 0)

    def test_brand_name_and_favicon_come_from_hd_settings(self):
        frappe.db.set_single_value("HD Settings", "brand_name", "Acme Support")
        frappe.db.set_single_value("HD Settings", "favicon", "/files/acme.png")
        frappe.db.set_single_value("Website Settings", "favicon", "/files/website.png")
        boot = get_site_boot()
        self.assertEqual(boot["brand_name"], "Acme Support")
        self.assertEqual(boot["favicon"], "/files/acme.png")

    def test_favicon_falls_back_to_website_settings(self):
        frappe.db.set_single_value("Website Settings", "favicon", "/files/website.png")
        self.assertEqual(get_site_boot()["favicon"], "/files/website.png")

    def test_password_login_setting_is_exposed(self):
        frappe.db.set_single_value("System Settings", "disable_user_pass_login", 1)
        self.assertEqual(get_site_boot()["disable_user_pass_login"], 1)

    def test_source_url_is_the_app_repository(self):
        self.assertEqual(get_site_boot()["source_url"], get_source_url("helpdesk"))
