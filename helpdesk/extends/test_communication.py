import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.extends.communication import sanitize_content

JSON_SHAPED = '["<img src=\\"x\\" onerror=\\"1\\">"]'
COMMENT_SHAPED = "<!--><img src=x onerror=1>-->"


def make_communication(content, **fields):
    return frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Email",
            "sent_or_received": "Received",
            "subject": "Sanitize content",
            "sender": "sanitize-sender@example.com",
            "content": content,
            **fields,
        }
    )


class TestSanitizeContent(FrappeTestCase):
    def assertSanitized(self, content):
        self.assertNotIn("onerror", content)
        self.assertIn("<img", content)

    def test_sanitizes_values_v15_skips(self) -> None:
        for value in (JSON_SHAPED, COMMENT_SHAPED):
            with self.subTest(value=value):
                doc = make_communication(value)
                sanitize_content(doc)
                self.assertSanitized(doc.content)

    def test_sanitizes_subject_and_sender_name(self) -> None:
        for value in (JSON_SHAPED, COMMENT_SHAPED):
            with self.subTest(value=value):
                doc = make_communication(
                    "<p>Hi</p>", subject=value, sender_full_name=value
                )
                sanitize_content(doc)
                self.assertSanitized(doc.subject)
                self.assertSanitized(doc.sender_full_name)

    def test_leaves_empty_content(self) -> None:
        doc = make_communication(None)
        sanitize_content(doc)
        self.assertIsNone(doc.content)

    def test_leaves_plain_text(self) -> None:
        for value in ("Thanks & regards, see you at 5 > 4", "a < b, <3 and <= 2"):
            with self.subTest(value=value):
                doc = make_communication(value, subject=value, sender_full_name=value)
                sanitize_content(doc)
                self.assertEqual(doc.content, value)
                self.assertEqual(doc.subject, value)
                self.assertEqual(doc.sender_full_name, value)

    def test_leaves_safe_html(self) -> None:
        value = "<p>Hi <b>there</b></p>"
        doc = make_communication(value)
        sanitize_content(doc)
        self.assertEqual(doc.content, value)

    def test_insert_stores_sanitized_fields(self) -> None:
        for value in (JSON_SHAPED, COMMENT_SHAPED):
            with self.subTest(value=value):
                doc = make_communication(value, subject=value, sender_full_name=value)
                doc.insert(ignore_permissions=True)
                stored = frappe.db.get_value(
                    "Communication",
                    doc.name,
                    ["content", "subject", "sender_full_name"],
                )
                for field in stored:
                    self.assertSanitized(field)

    def test_insert_sanitizes_sender_name_filled_in_from_contact(self) -> None:
        email = "sanitize-contact@example.com"
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Sanitize",
                "email_ids": [{"email_id": email, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)
        # A Contact's name is fixed at insert, so a later edit can carry markup
        contact.first_name = COMMENT_SHAPED
        contact.save(ignore_permissions=True)
        doc = make_communication("<p>Hi</p>", sender=email).insert(
            ignore_permissions=True
        )
        stored = frappe.db.get_value("Communication", doc.name, "sender_full_name")
        self.assertSanitized(stored)
