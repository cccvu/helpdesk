import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_absolute_url

from helpdesk.test_utils import get_html_links, make_agent, make_team

# Names that end the old single-quoted href early.
TEAM_NAMES = ("Test Escape Ops' title='x", "Test Escape R&D 'Ops'")


class TestAssignmentRuleMessages(FrappeTestCase):
    """Team names, users and conditions are shown as text in rule messages."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.member = make_agent("rule_escape_member@example.com")
        self.outsider = make_agent("rule_escape_outsider@example.com")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.clear_messages()
        for team in frappe.get_all(
            "HD Team", filters={"name": ["like", "Test Escape%"]}, pluck="name"
        ):
            frappe.delete_doc("HD Team", team, force=True, ignore_permissions=True)

    def save_rule_with_outsider(self, team_name: str, rule_type: str) -> str:
        team = make_team(team_name, [self.member])
        rule = frappe.get_doc("Assignment Rule", team.assignment_rule)
        rule.rule = rule_type
        if rule_type == "Weighted Distribution":
            rule.weighted_users = []
            for user in (self.member, self.outsider):
                rule.append("weighted_users", {"user": user, "weight": 1})
        else:
            rule.append("users", {"user": self.outsider})
        frappe.clear_messages()
        rule.save(ignore_permissions=True)
        messages = [m.get("message", "") for m in frappe.get_message_log()]
        self.assertEqual(len(messages), 1)
        return messages[0]

    def test_team_link_shows_the_name_as_text(self):
        for name in TEAM_NAMES:
            for rule_type in ("Round Robin", "Weighted Distribution"):
                with self.subTest(team=name, rule=rule_type):
                    message = self.save_rule_with_outsider(name, rule_type)
                    links = get_html_links(message)
                    self.assertEqual(len(links), 2)
                    for attrs, text in links:
                        self.assertEqual(
                            attrs, [("href", get_absolute_url("HD Team", name))]
                        )
                        self.assertEqual(text, name)
                    self.assertIn(self.outsider, message)
                    frappe.delete_doc(
                        "HD Team", name, force=True, ignore_permissions=True
                    )

    def test_invalid_condition_json_is_quoted_as_text(self):
        team = make_team("Test Escape Invalid JSON", [self.member], disabled=True)
        for field in ("assign_condition_json", "unassign_condition_json"):
            with self.subTest(field=field):
                rule = frappe.get_doc("Assignment Rule", team.assignment_rule)
                rule.set(field, "[<b>x</b>")
                with self.assertRaises(frappe.ValidationError) as refused:
                    rule.save(ignore_permissions=True)
                self.assertNotIn("<b>", str(refused.exception))
                self.assertIn("&lt;b&gt;", str(refused.exception))

    def test_condition_error_is_shown_as_text(self):
        rule = frappe.get_doc(
            {
                "doctype": "Assignment Rule",
                "document_type": "HD Ticket",
                "assign_condition": 'int("<img src=x>")',
            }
        )
        frappe.clear_messages()

        self.assertFalse(rule.safe_eval("assign_condition", {"status": "Open"}))

        messages = [m.get("message", "") for m in frappe.get_message_log()]
        self.assertEqual(len(messages), 1)
        self.assertNotIn("<img", messages[0])
        self.assertIn("&lt;img", messages[0])
