import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.extends.document import sanitize_html_fields

# Two values Frappe v15's sanitize_html returns unchanged: one parses as JSON,
# one is a single comment to BeautifulSoup but a live <img> to a browser.
JSON_SHAPED = '["<img src=\\"x\\" onerror=\\"1\\">"]'
COMMENT_SHAPED = "<!--><img src=x onerror=1>-->"
HOSTILE = (JSON_SHAPED, COMMENT_SHAPED)


class TestSanitizeHtmlFields(FrappeTestCase):
    def assertInert(self, value):
        self.assertNotIn("onerror", value)
        self.assertIn("<img", value)

    def _assert_field_sanitized(self, doctype, field, **extra):
        for payload in HOSTILE:
            with self.subTest(doctype=doctype, field=field, payload=payload):
                doc = frappe.get_doc({"doctype": doctype, field: payload, **extra})
                sanitize_html_fields(doc)
                self.assertInert(doc.get(field))

    # Rich-text (Text Editor) fields /app renders as HTML.
    def test_hd_ticket_description(self) -> None:
        self._assert_field_sanitized("HD Ticket", "description", subject="x")

    def test_hd_ticket_comment_content(self) -> None:
        self._assert_field_sanitized("HD Ticket Comment", "content")

    def test_hd_article_content(self) -> None:
        self._assert_field_sanitized("HD Article", "content", title="x")

    def test_hd_saved_reply_message(self) -> None:
        self._assert_field_sanitized("HD Saved Reply", "message", name="x")

    # Data / Small Text fields, the same v15 gap (issue 251, comment 1).
    def test_hd_ticket_subject_data_field(self) -> None:
        self._assert_field_sanitized("HD Ticket", "subject", description="x")

    def test_user_email_signature(self) -> None:
        self._assert_field_sanitized(
            "User", "email_signature", email="sig@example.com", first_name="Sig"
        )

    def test_communication_content_subject_and_sender(self) -> None:
        for field in ("content", "subject", "sender_full_name"):
            self._assert_field_sanitized(
                "Communication",
                field,
                communication_type="Communication",
                communication_medium="Email",
                sender="s@example.com",
            )

    def test_plain_text_is_kept(self) -> None:
        for value in ("a < b, <3 and <= 2", "Thanks & regards, 5 > 4"):
            with self.subTest(value=value):
                doc = frappe.get_doc(
                    {"doctype": "HD Ticket", "subject": value, "description": value}
                )
                sanitize_html_fields(doc)
                self.assertEqual(doc.subject, value)
                self.assertEqual(doc.description, value)

    def test_safe_html_is_kept(self) -> None:
        value = "<p>Hi <b>there</b></p>"
        doc = frappe.get_doc(
            {"doctype": "HD Ticket", "description": value, "subject": "x"}
        )
        sanitize_html_fields(doc)
        self.assertEqual(doc.description, value)

    def test_code_fields_are_left_alone(self) -> None:
        # A Code field (HD Form Script.script) is JavaScript, not HTML; Frappe
        # skips it and so must we, or every script would be mangled.
        payload = "if (a < b) { doc.set('<x>', 1); }"
        doc = frappe.get_doc(
            {"doctype": "HD Form Script", "dt": "HD Ticket", "script": payload}
        )
        sanitize_html_fields(doc)
        self.assertEqual(doc.script, payload)

    def test_insert_runs_the_hook(self) -> None:
        # End to end: the registered "*" hook sanitizes on insert.
        doc = frappe.get_doc(
            {
                "doctype": "HD Saved Reply",
                "name": "sanitize-hook-test",
                "message": COMMENT_SHAPED,
            }
        ).insert(ignore_permissions=True)
        self.assertInert(frappe.db.get_value("HD Saved Reply", doc.name, "message"))
