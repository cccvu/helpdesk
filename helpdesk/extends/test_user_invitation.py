from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.extends.user_invitation import keep_redirect_on_site

SITE = "https://helpdesk.example"

ON_SITE = [
    "/helpdesk",
    "/helpdesk/tickets/42?tab=activity#c1",
    "/helpdesk/kb/a.b-c%20d",
    "/app/hd-ticket",
    "//x",
]

OFF_SITE = [
    "https://evil.example",
    "/https://evil.example",
    "/HTTPS://evil.example",
    "///evil.example",
    "/ //evil.example",
    "/\t//evil.example",
    "/http:evil.example",
    "javascript:alert(1)",
]


def make_invitation(redirect_to_path, app_name="helpdesk"):
    # never inserted, so no invitation mail is sent
    return frappe.get_doc(
        {
            "doctype": "User Invitation",
            "app_name": app_name,
            "email": "redirect-invitee@example.com",
            "roles": [{"role": "Agent"}],
            "redirect_to_path": redirect_to_path,
        }
    )


class TestKeepRedirectOnSite(FrappeTestCase):
    def setUp(self) -> None:
        # get_url() builds the site URL from these, so the decisions don't
        # depend on the test site's scheme or port
        conf = {"host_name": SITE, "webserver_port": None, "http_port": None}
        patcher = patch.dict(frappe.local.conf, conf)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keeps_on_site_paths(self) -> None:
        for value in ON_SITE:
            with self.subTest(value=value):
                doc = make_invitation(value)
                keep_redirect_on_site(doc)
                self.assertEqual(doc.redirect_to_path, value)

    def test_normalizes_off_site_redirects(self) -> None:
        for value in OFF_SITE:
            with self.subTest(value=value):
                doc = make_invitation(value)
                # the redirect accept_invitation would send without the hook
                self.assertEqual(frappe.utils.get_url(), SITE)
                self.assertFalse(
                    frappe.utils.get_url(doc.get_redirect_to_path()).startswith(
                        SITE + "/"
                    )
                )
                keep_redirect_on_site(doc)
                self.assertEqual(doc.redirect_to_path, "/helpdesk")

    def test_normalizes_a_redirect_get_url_cannot_parse(self) -> None:
        doc = make_invitation("///[evil.example")
        with self.assertRaises(ValueError):
            frappe.utils.get_url(doc.get_redirect_to_path())
        keep_redirect_on_site(doc)
        self.assertEqual(doc.redirect_to_path, "/helpdesk")

    def test_fills_a_missing_redirect(self) -> None:
        for value in ("", None):
            with self.subTest(value=value):
                doc = make_invitation(value)
                keep_redirect_on_site(doc)
                self.assertEqual(doc.redirect_to_path, "/helpdesk")

    def test_leaves_other_apps_alone(self) -> None:
        doc = make_invitation("https://evil.example", app_name="frappe")
        keep_redirect_on_site(doc)
        self.assertEqual(doc.redirect_to_path, "https://evil.example")

    def test_runs_on_validate(self) -> None:
        doc = make_invitation("https://evil.example")
        doc.run_method("validate")
        self.assertEqual(doc.redirect_to_path, "/helpdesk")
