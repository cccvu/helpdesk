import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.extends.communication import validate_recipients


def automated_message(**fields):
    return frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Automated Message",
            "subject": "Alert",
            "content": "<p>Hi</p>",
            **fields,
        }
    )


class TestValidateRecipients(FrappeTestCase):
    def test_rejects_markup_in_each_address_field(self) -> None:
        payloads = (
            "<img src=x onerror=1>",
            '"<img onerror=1>" <a@b.com>',
            "<!--><img onerror=1>-->",
        )
        for field in ("recipients", "cc", "bcc"):
            for payload in payloads:
                with self.subTest(field=field, payload=payload):
                    doc = automated_message(**{field: payload})
                    with self.assertRaises(frappe.ValidationError):
                        validate_recipients(doc)

    def test_allows_plain_and_named_addresses(self) -> None:
        doc = automated_message(
            recipients="a@b.com, c@d.com",
            cc='"John Doe" <john@example.com>',
            bcc="",
        )
        validate_recipients(doc)  # does not raise

    def test_only_automated_messages_are_checked(self) -> None:
        # A normal email isn't this sink; Frappe validates its own addresses, and
        # we must not refuse the display names it may carry.
        doc = frappe.get_doc(
            {
                "doctype": "Communication",
                "communication_type": "Communication",
                "communication_medium": "Email",
                "recipients": "<img onerror=1>",
                "subject": "x",
                "content": "<p>Hi</p>",
            }
        )
        validate_recipients(doc)  # does not raise

    def test_insert_refuses_markup(self) -> None:
        doc = automated_message(recipients="<img src=x onerror=1>")
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
