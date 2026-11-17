import json
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.patches import drop_markup_from_stored_html as shared
from helpdesk.patches import sanitize_kanban_board_json as patch

PAYLOAD = "<img src=x onerror=alert(1)>"


class TestSanitizeKanbanBoardJson(FrappeTestCase):
    """Kanban Board fields and filters stored before the sanitizer covered
    them, written straight to the database as an older release would have."""

    def setUp(self) -> None:
        self.planted = frappe.get_doc(
            {
                "doctype": "Kanban Board",
                "kanban_board_name": "kanban patch planted",
                "reference_doctype": "ToDo",
                "field_name": "status",
            }
        ).insert(ignore_permissions=True)
        self.fields = json.dumps([PAYLOAD])
        self.filters = json.dumps([["ToDo", PAYLOAD, "=", "x"]])
        frappe.db.set_value(
            "Kanban Board",
            self.planted.name,
            {"fields": self.fields, "filters": self.filters},
            update_modified=False,
        )
        self.plain_fields = '["description", "priority"]'
        self.plain_filters = '[["ToDo", "status", "=", "Open"]]'
        self.plain = frappe.get_doc(
            {
                "doctype": "Kanban Board",
                "kanban_board_name": "kanban patch plain",
                "reference_doctype": "ToDo",
                "field_name": "status",
                "fields": self.plain_fields,
                "filters": self.plain_filters,
            }
        ).insert(ignore_permissions=True)
        self.modified = frappe.db.get_value(
            "Kanban Board", self.planted.name, "modified"
        )

    def tearDown(self) -> None:
        frappe.db.rollback()

    def run_patch(self):
        # The patch commits each batch; keep the test's transaction.
        commit, frappe.db.commit = frappe.db.commit, lambda: None
        try:
            patch.execute()
        finally:
            frappe.db.commit = commit

    def stored(self, name):
        return frappe.db.get_value("Kanban Board", name, ["fields", "filters"])

    def test_planted_values_are_sanitized_and_others_kept(self) -> None:
        self.run_patch()
        fields, filters = self.stored(self.planted.name)
        self.assertNotIn("onerror", fields)
        self.assertNotIn("onerror", filters)
        self.assertEqual(len(json.loads(fields)), 1)
        self.assertEqual(json.loads(filters)[0][0], "ToDo")
        self.assertEqual(
            frappe.db.get_value("Kanban Board", self.planted.name, "modified"),
            self.modified,
        )
        self.assertEqual(
            self.stored(self.plain.name), (self.plain_fields, self.plain_filters)
        )

    def test_a_second_run_changes_nothing(self) -> None:
        self.run_patch()
        first = self.stored(self.planted.name)
        with mock_patch.object(
            shared,
            "write_if_unchanged",
            side_effect=AssertionError("the second run wrote a row"),
        ):
            self.run_patch()
        self.assertEqual(self.stored(self.planted.name), first)
