import json

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.patches import drop_markup_from_stored_html as patch
from helpdesk.test_utils import make_mention_html, make_ticket

ENCODED_IMG = "&lt;img src=x onerror=alert(1)&gt;"
PLANTED = (
    f'<p><span class="mention" data-id="a@b.c" data-value="{ENCODED_IMG}">@x</span>'
    f'<span class="mention">{ENCODED_IMG}</span></p>'
)


def escaped(text):
    return text.replace("<", chr(92) + "u003c").replace(">", chr(92) + "u003e")


class TestDropMarkupFromStoredHtml(FrappeTestCase):
    """Values stored before the sanitizer dropped markup from data-* attributes,
    mention text and JSON strings, written straight to the database as an
    older release would have stored them."""

    def setUp(self) -> None:
        self.ticket = make_ticket(subject="patch test", description="<p>x</p>")
        self.mention = f"<p>{make_mention_html('a@b.c', 'Ann Lee')} hi</p>"
        self.comment = frappe.get_doc(
            {
                "doctype": "HD Ticket Comment",
                "reference_ticket": self.ticket.name,
                "content": self.mention,
            }
        ).insert(ignore_permissions=True)
        frappe.db.set_value(
            "HD Ticket", self.ticket.name, "description", PLANTED, update_modified=False
        )
        self.workspace = frappe.get_doc(
            {
                "doctype": "Workspace",
                "title": "Patch Test",
                "label": "Patch Test",
                "public": 1,
                "content": "[]",
            }
        ).insert(ignore_permissions=True)
        self.content = escaped(
            json.dumps(
                [
                    {
                        "id": "b",
                        "type": "paragraph",
                        "data": {"text": "<img src=x onerror=alert(1)>", "col": 12},
                    }
                ]
            )
        )
        frappe.db.set_value(
            "Workspace",
            self.workspace.name,
            "content",
            self.content,
            update_modified=False,
        )
        self.modified = frappe.db.get_value("HD Ticket", self.ticket.name, "modified")

    def tearDown(self) -> None:
        frappe.db.rollback()

    def run_patch(self):
        # The patch commits each batch; keep the test's transaction.
        commit, frappe.db.commit = frappe.db.commit, lambda: None
        try:
            patch.execute()
        finally:
            frappe.db.commit = commit

    def test_planted_values_are_sanitized_and_real_mentions_kept(self) -> None:
        self.run_patch()
        description = frappe.db.get_value("HD Ticket", self.ticket.name, "description")
        self.assertNotIn("data-value", description)
        self.assertIn('<span class="mention" data-id="a@b.c">@x</span>', description)
        self.assertIn(f"<span>{ENCODED_IMG}</span>", description)
        self.assertEqual(
            frappe.db.get_value("HD Ticket", self.ticket.name, "modified"),
            self.modified,
        )
        self.assertEqual(
            frappe.db.get_value("HD Ticket Comment", self.comment.name, "content"),
            self.mention,
        )
        content = frappe.db.get_value("Workspace", self.workspace.name, "content")
        self.assertNotIn("onerror", json.loads(content)[0]["data"]["text"])

    def test_a_second_run_changes_nothing(self) -> None:
        self.run_patch()
        first = frappe.db.get_value("HD Ticket", self.ticket.name, "description")
        with self.assertNoWrites():
            self.run_patch()
        self.assertEqual(
            frappe.db.get_value("HD Ticket", self.ticket.name, "description"), first
        )

    def assertNoWrites(self):
        from unittest.mock import patch as mock_patch

        return mock_patch.object(
            patch,
            "write_if_unchanged",
            side_effect=AssertionError("the second run wrote a row"),
        )

    def test_other_shapes_and_fields_are_cleaned(self) -> None:
        # The class spelled with a character reference, a Comment (its own
        # sanitizer keeps mention markup), and a saved List Filter.
        encoded = f'<p><span class="&#109;ention">{ENCODED_IMG}</span></p>'
        frappe.db.set_value(
            "HD Ticket", self.ticket.name, "description", encoded, update_modified=False
        )
        comment = frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Comment",
                "reference_doctype": "HD Ticket",
                "reference_name": self.ticket.name,
                "content": "<p>x</p>",
            }
        ).insert(ignore_permissions=True)
        frappe.db.set_value(
            "Comment", comment.name, "content", PLANTED, update_modified=False
        )
        list_filter = frappe.get_doc(
            {
                "doctype": "List Filter",
                "reference_doctype": "HD Ticket",
                "filter_name": "patch test",
                "filters": "[]",
            }
        ).insert(ignore_permissions=True)
        planted_filter = escaped(
            json.dumps([["HD Ticket", "<img onerror=x>", "=", "1"]])
        )
        frappe.db.set_value(
            "List Filter",
            list_filter.name,
            "filters",
            planted_filter,
            update_modified=False,
        )
        self.run_patch()
        self.assertNotIn(
            "&#109;ention",
            frappe.db.get_value("HD Ticket", self.ticket.name, "description"),
        )
        content = frappe.db.get_value("Comment", comment.name, "content")
        self.assertNotIn("data-value", content)
        self.assertNotIn(f'class="mention">{ENCODED_IMG}', content)
        filters = frappe.db.get_value("List Filter", list_filter.name, "filters")
        self.assertNotIn("onerror", json.loads(filters)[0][1])

    def test_quotes_the_earlier_sanitizer_rewrote_are_put_back(self) -> None:
        mangled = json.dumps(
            [
                {
                    "id": "h",
                    "type": "header",
                    "data": {
                        "text": "<span class='\"h4\"'><a href='\"/helpdesk\"'>Go</a></span>"
                    },
                }
            ]
        )
        frappe.db.set_value(
            "Workspace", self.workspace.name, "content", mangled, update_modified=False
        )
        self.run_patch()
        text = json.loads(
            frappe.db.get_value("Workspace", self.workspace.name, "content")
        )[0]["data"]["text"]
        self.assertEqual(text, '<span class="h4"><a href="/helpdesk">Go</a></span>')

    def test_a_value_too_deep_to_clean_is_left_and_named(self) -> None:
        deep = "[" * 40 + '"' + escaped("<img onerror=x>") + '"' + "]" * 40
        frappe.db.set_value(
            "Workspace", self.workspace.name, "content", deep, update_modified=False
        )
        self.run_patch()
        self.assertEqual(
            frappe.db.get_value("Workspace", self.workspace.name, "content"), deep
        )

    def test_covers_the_text_editor_fields(self) -> None:
        fields = patch.text_editor_fields()
        for field in (
            ("HD Ticket", "description"),
            ("HD Ticket Comment", "content"),
            ("HD Article", "content"),
            ("HD Saved Reply", "message"),
            ("Communication", "content"),
        ):
            self.assertIn(field, fields)

    def test_a_value_changed_meanwhile_is_kept(self) -> None:
        frappe.db.set_value(
            "HD Ticket",
            self.ticket.name,
            "description",
            "<p>edited</p>",
            update_modified=False,
        )
        written = patch.write_if_unchanged(
            "HD Ticket", "description", self.ticket.name, PLANTED, "<p>clean</p>"
        )
        self.assertEqual(written, 0)
        self.assertEqual(
            frappe.db.get_value("HD Ticket", self.ticket.name, "description"),
            "<p>edited</p>",
        )

    def test_batches_cover_every_row(self) -> None:
        other = make_ticket(subject="patch test 2", description="<p>y</p>")
        frappe.db.set_value(
            "HD Ticket", other.name, "description", PLANTED, update_modified=False
        )
        size, patch.BATCH_SIZE = patch.BATCH_SIZE, 1
        try:
            self.run_patch()
        finally:
            patch.BATCH_SIZE = size
        for name in (self.ticket.name, other.name):
            self.assertNotIn(
                "data-value", frappe.db.get_value("HD Ticket", name, "description")
            )
