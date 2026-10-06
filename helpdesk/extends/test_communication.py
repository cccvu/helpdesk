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
            # The /app timeline splits on "," and renders each entry raw, so an
            # address that parses cleanly but trails markup is still a live sink.
            # getaddresses would accept both of these (it drops "(...)" comments);
            # the guard splits as the sink does and fails closed.
            "x <a@b.com>(<img src=x onerror=1>)",
            "a@b.com (<svg onload=1>)",
            # Markup in any one entry of a list fails the whole list.
            "a@b.com, x <c@d.com>(<img onerror=1>)",
        )
        for field in ("recipients", "cc", "bcc"):
            for payload in payloads:
                with self.subTest(field=field, payload=payload):
                    doc = automated_message(**{field: payload})
                    with self.assertRaises(frappe.ValidationError):
                        validate_recipients(doc)

    def test_rejects_an_invalid_bare_address(self) -> None:
        # No markup, but not an address either: fail closed rather than pass it on.
        doc = automated_message(recipients="not-an-address")
        with self.assertRaises(frappe.ValidationError):
            validate_recipients(doc)

    def test_allows_plain_named_and_parenthesised_addresses(self) -> None:
        doc = automated_message(
            recipients="a@b.com, c@d.com",
            cc='"John Doe" <john@example.com>',
            bcc="John (Admin) <john@example.com>",
        )
        validate_recipients(doc)  # does not raise

    def test_allows_empty_entries_and_trailing_commas(self) -> None:
        # The timeline drops empty entries, so an empty value or a trailing comma
        # must not be rejected.
        for value in ("", "a@b.com,", " a@b.com , c@d.com "):
            with self.subTest(value=value):
                validate_recipients(automated_message(recipients=value))

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
