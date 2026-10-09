import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.api.onboarding import mark_persona_captured
from helpdesk.overrides.user_invitation import HelpdeskUserInvitation
from helpdesk.test_utils import make_agent_manager

BRAND = "Acme Support"


class TestMarkPersonaCaptured(FrappeTestCase):
    def setUp(self) -> None:
        frappe.set_user("Administrator")
        frappe.db.set_single_value("HD Settings", "brand_name", "")
        frappe.db.set_single_value("HD Settings", "persona_captured", 0)
        frappe.db.set_single_value("Website Settings", "app_name", "")
        frappe.db.set_default("site_name", "")

    def tearDown(self) -> None:
        frappe.set_user("Administrator")
        frappe.db.rollback()
        # mark_persona_captured clears the cache; drop anything cached while
        # the rolled-back values were in place.
        frappe.clear_cache()

    def _state(self) -> dict:
        return {
            "brand_name": frappe.db.get_single_value("HD Settings", "brand_name"),
            "persona_captured": frappe.db.get_single_value(
                "HD Settings", "persona_captured"
            ),
            "app_name": frappe.db.get_single_value("Website Settings", "app_name"),
            "site_name": frappe.db.get_default("site_name"),
        }

    def _as_agent_manager(self) -> str:
        email = make_agent_manager(
            "onboarding.manager@example.com", first_name="Onboarding Manager"
        )
        roles = frappe.get_roles(email)
        self.assertIn("Agent Manager", roles)
        self.assertNotIn("System Manager", roles)
        frappe.set_user(email)
        return email

    def test_brand_name_written_to_settings(self):
        mark_persona_captured(brand_name=BRAND)
        self.assertEqual(frappe.db.get_single_value("HD Settings", "brand_name"), BRAND)
        self.assertEqual(
            frappe.db.get_single_value("Website Settings", "app_name"), BRAND
        )

    def test_site_name_set_for_welcome_email_subject(self):
        # Frappe builds the welcome email subject as "Welcome to <site_name>".
        mark_persona_captured(brand_name=BRAND)
        self.assertEqual(frappe.db.get_default("site_name"), BRAND)

    def test_persona_captured_flag_set(self):
        mark_persona_captured()
        self.assertTrue(frappe.db.get_single_value("HD Settings", "persona_captured"))

    def test_blank_brand_leaves_brand_untouched(self):
        mark_persona_captured(brand_name="   ")
        self.assertTrue(frappe.db.get_single_value("HD Settings", "persona_captured"))
        self.assertFalse(frappe.db.get_single_value("HD Settings", "brand_name"))

    def test_agent_manager_is_refused_and_nothing_changes(self):
        before = self._state()
        self._as_agent_manager()
        with self.assertRaises(frappe.PermissionError):
            mark_persona_captured(brand_name=BRAND)
        frappe.set_user("Administrator")
        self.assertEqual(self._state(), before)
        self.assertFalse(before["persona_captured"])

    def test_agent_manager_is_refused_after_the_flag_is_reset(self):
        # The questionnaire was completed once, then the flag was set back to 0.
        frappe.db.set_single_value("HD Settings", "persona_captured", 1)
        frappe.db.set_single_value("HD Settings", "persona_captured", 0)
        before = self._state()
        self._as_agent_manager()
        with self.assertRaises(frappe.PermissionError):
            mark_persona_captured(brand_name=BRAND)
        frappe.set_user("Administrator")
        self.assertEqual(self._state(), before)
        self.assertFalse(frappe.db.get_single_value("HD Settings", "persona_captured"))

    def test_second_call_changes_nothing(self):
        mark_persona_captured(brand_name=BRAND)
        before = self._state()
        mark_persona_captured(brand_name="Other Brand")
        self.assertEqual(self._state(), before)
        self.assertEqual(frappe.db.get_single_value("HD Settings", "brand_name"), BRAND)
        self.assertEqual(frappe.db.get_default("site_name"), BRAND)

    def test_markup_is_stored_as_text(self):
        cases = {
            "Acme <b>Desk</b>": "Acme Desk",
            "Acme </title": "Acme /title",
            "x > y": "x  y",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                frappe.db.set_single_value("HD Settings", "persona_captured", 0)
                mark_persona_captured(brand_name=raw)
                state = self._state()
                for field in ("brand_name", "app_name", "site_name"):
                    self.assertNotIn("<", state[field])
                    self.assertNotIn(">", state[field])
                self.assertEqual(state["brand_name"], expected)
                self.assertEqual(state["app_name"], expected)
                self.assertEqual(state["site_name"], expected)

    def test_markup_only_brand_is_treated_as_blank(self):
        mark_persona_captured(brand_name="<b></b>")
        self.assertTrue(frappe.db.get_single_value("HD Settings", "persona_captured"))
        self.assertFalse(frappe.db.get_single_value("HD Settings", "brand_name"))
        self.assertFalse(frappe.db.get_single_value("Website Settings", "app_name"))
        self.assertFalse(frappe.db.get_default("site_name"))

    def test_long_brand_is_capped(self):
        mark_persona_captured(brand_name="a" * 500)
        self.assertEqual(
            frappe.db.get_single_value("HD Settings", "brand_name"), "a" * 140
        )
        self.assertEqual(
            frappe.db.get_single_value("Website Settings", "app_name"), "a" * 140
        )
        self.assertEqual(frappe.db.get_default("site_name"), "a" * 140)


class TestInvitationTitleOverride(FrappeTestCase):
    def setUp(self) -> None:
        frappe.set_user("Administrator")
        frappe.db.set_single_value("HD Settings", "brand_name", "")

    def tearDown(self) -> None:
        frappe.db.rollback()

    def _invitation(self) -> HelpdeskUserInvitation:
        invitation = frappe.new_doc("User Invitation")
        invitation.app_name = "helpdesk"
        return invitation

    def test_override_is_registered(self):
        self.assertIsInstance(frappe.new_doc("User Invitation"), HelpdeskUserInvitation)

    def test_title_uses_brand_name(self):
        # Subject becomes "You've been invited to join <brand> on <app title>".
        frappe.db.set_single_value("HD Settings", "brand_name", BRAND)
        app_title = frappe.get_hooks("app_title", app_name="helpdesk")[0]
        self.assertEqual(
            self._invitation()._get_email_title(), f"{BRAND} on {app_title}"
        )

    def test_title_falls_back_to_app_title(self):
        self.assertEqual(
            self._invitation()._get_email_title(),
            frappe.get_hooks("app_title", app_name="helpdesk")[0],
        )

    def test_other_apps_keep_their_title(self):
        # The override is site-wide; a brand name must not leak into other
        # apps' invitation emails.
        frappe.db.set_single_value("HD Settings", "brand_name", BRAND)
        invitation = frappe.new_doc("User Invitation")
        invitation.app_name = "frappe"
        self.assertEqual(
            invitation._get_email_title(),
            frappe.get_hooks("app_title", app_name="frappe")[0],
        )
