import frappe
from frappe.model.rename_doc import rename_doc
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_absolute_url

from helpdesk.api.assignment_rule import get_assignment_rules_list
from helpdesk.test_utils import (
    create_user,
    get_html_links,
    insert_as,
    make_agent,
    make_agent_manager,
    make_team,
    make_ticket,
    set_value_as,
    user_roles,
)

ASSIGNMENT_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def rule_dict(name: str, document_type: str, users=(), **values) -> dict:
    """An Assignment Rule as frappe.client.insert takes it."""
    return {
        "doctype": "Assignment Rule",
        "name": name,
        "document_type": document_type,
        "assign_condition": "1",
        "rule": "Round Robin",
        "priority": 0,
        "disabled": 1,
        "description": "Automatic Assignment",
        "users": [{"user": user} for user in users],
        "assignment_days": [{"day": day} for day in ASSIGNMENT_DAYS],
        **values,
    }


def make_system_manager(email: str) -> str:
    create_user(email).add_roles("System Manager")
    return email


def delete_test_rules():
    for name in frappe.get_all(
        "Assignment Rule", filters={"name": ["like", "Test AR %"]}, pluck="name"
    ):
        frappe.delete_doc(
            "Assignment Rule",
            name,
            force=True,
            ignore_permissions=True,
            ignore_on_trash=True,
        )


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


class TestAssignmentRuleDescription(FrappeTestCase):
    """A rule's description is rendered with the ticket's values only."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = make_agent("rule_description_agent@example.com")
        self.rule = frappe.get_doc(
            rule_dict("Test AR Description", "HD Ticket", [self.agent])
        ).insert(ignore_permissions=True)
        self.ticket = make_ticket(subject="Printer on fire")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.clear_messages()
        delete_test_rules()

    def assign(self, description):
        self.rule.description = description
        frappe.clear_messages()
        self.assertTrue(self.rule.do_assignment(self.ticket.as_dict()))
        todos = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "HD Ticket",
                "reference_name": self.ticket.name,
                "status": "Open",
            },
            fields=["allocated_to", "description", "assignment_rule"],
        )
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].allocated_to, self.agent)
        self.assertEqual(todos[0].assignment_rule, self.rule.name)
        return todos[0].description

    def test_ticket_fields_render(self):
        description = self.assign("Ticket {{ name }}: {{ subject }}")
        self.assertIn(f"Ticket {self.ticket.name}: Printer on fire", description)
        self.assertEqual(frappe.get_message_log(), [])

    def test_empty_description_keeps_the_default(self):
        description = self.assign("")
        self.assertIn(
            frappe._("Assignment for {0} {1}").format("HD Ticket", self.ticket.name),
            description,
        )

    def test_frappe_calls_fall_back(self):
        templates = (
            '{{ frappe.get_doc({"doctype": "ToDo", "description": "Test AR made"}).insert() }}',
            '{{ frappe.db.sql("select 1") }}',
            "{{ frappe.session.user }}",
            "{{ doc.subject }}{{ ''.__class__ }}",
        )
        for template in templates:
            with self.subTest(template=template):
                todos_before = frappe.db.count("ToDo")
                description = self.assign(template)
                self.assertEqual(description, "Automatic Assignment")
                self.assertEqual(frappe.get_message_log(), [])
                self.assertFalse(
                    frappe.db.exists("ToDo", {"description": "Test AR made"})
                )
                # the assignment replaced the ticket's open ToDo, so it is one
                # row more than before at most (the earlier one is cancelled)
                self.assertLessEqual(frappe.db.count("ToDo"), todos_before + 1)

    def test_rule_applies_on_ticket_insert(self):
        """Through Frappe's apply, as a ticket insert runs it."""
        from frappe.cache_manager import clear_doctype_map

        frappe.db.set_value(
            "Assignment Rule",
            {"document_type": "HD Ticket", "name": ["!=", self.rule.name]},
            "disabled",
            1,
        )
        clear_doctype_map("Assignment Rule", "HD Ticket")
        self.rule.description = "Ticket {{ subject }}"
        self.rule.disabled = 0
        self.rule.save(ignore_permissions=True)

        ticket = make_ticket(subject="Rule applies")

        self.assertEqual(
            frappe.get_all(
                "ToDo",
                filters={"reference_type": "HD Ticket", "reference_name": ticket.name},
                fields=["allocated_to", "description"],
            ),
            [{"allocated_to": self.agent, "description": "Ticket Rule applies"}],
        )


class TestAssignmentRuleRights(FrappeTestCase):
    """Agent Managers manage ticket rules only; rules for other documents are
    System Managers'."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = make_agent("rule_rights_agent@example.com")
        self.manager = make_agent_manager("rule_rights_manager@example.com")
        self.system_manager = make_system_manager("rule_rights_sm@example.com")
        self.assertNotIn("System Manager", user_roles(self.manager))

    def tearDown(self):
        frappe.set_user("Administrator")
        delete_test_rules()

    def assertRefused(self, call, *args):
        frappe.db.savepoint("rule_rights")
        try:
            with self.assertRaisesRegex(frappe.PermissionError, "System Manager"):
                call(*args)
        finally:
            frappe.db.rollback(save_point="rule_rights")

    def test_manager_cannot_create_rules_for_other_documents(self):
        for document_type in ("User", "OAuth Bearer Token", "HD Agent"):
            with self.subTest(document_type=document_type):
                name = f"Test AR {document_type}"
                self.assertRefused(
                    insert_as, self.manager, rule_dict(name, document_type)
                )
                self.assertFalse(frappe.db.exists("Assignment Rule", name))

    def test_manager_cannot_change_rules_for_other_documents(self):
        name = frappe.get_doc(rule_dict("Test AR User Rule", "User")).insert().name
        before = frappe.get_doc("Assignment Rule", name).as_dict()
        changes = (
            {"description": "{{ name }}"},
            {"disabled": 0},
            {"users": [{"user": self.manager}]},
            {"document_type": "HD Ticket"},
        )
        for values in changes:
            with self.subTest(values=values):
                self.assertRefused(
                    set_value_as, self.manager, "Assignment Rule", name, values
                )
                after = frappe.get_doc("Assignment Rule", name)
                self.assertEqual(after.document_type, "User")
                self.assertEqual(after.description, before.description)
                self.assertEqual(after.disabled, 1)
                self.assertEqual(after.users, [])

    def test_manager_cannot_delete_rules_for_other_documents(self):
        name = frappe.get_doc(rule_dict("Test AR User Delete", "User")).insert().name

        def delete_as_manager():
            frappe.set_user(self.manager)
            try:
                frappe.delete_doc("Assignment Rule", name)
            finally:
                frappe.set_user("Administrator")

        self.assertRefused(delete_as_manager)
        self.assertTrue(frappe.db.exists("Assignment Rule", name))

    def test_manager_cannot_move_a_ticket_rule_to_other_documents(self):
        name = insert_as(self.manager, rule_dict("Test AR Moved", "HD Ticket"))["name"]
        self.assertRefused(
            set_value_as,
            self.manager,
            "Assignment Rule",
            name,
            {"document_type": "User"},
        )
        self.assertEqual(
            frappe.db.get_value("Assignment Rule", name, "document_type"), "HD Ticket"
        )

    def test_manager_cannot_rename_or_merge_into_rules_for_other_documents(self):
        """A rename skips validate, and a merge points the old rule's links
        (a team's) at the rule it merges into."""
        other = frappe.get_doc(rule_dict("Test AR Rename User", "User")).insert().name
        ticket = insert_as(
            self.manager, rule_dict("Test AR Rename Ticket", "HD Ticket")
        )["name"]

        def rename_as_manager(old, new, merge=False):
            frappe.set_user(self.manager)
            try:
                rename_doc("Assignment Rule", old, new, merge=merge)
            finally:
                frappe.set_user("Administrator")

        self.assertRefused(rename_as_manager, ticket, other, True)
        self.assertRefused(rename_as_manager, other, "Test AR Renamed User")
        self.assertTrue(frappe.db.exists("Assignment Rule", ticket))
        self.assertEqual(
            frappe.db.get_value("Assignment Rule", other, "document_type"), "User"
        )

        rename_as_manager(ticket, "Test AR Renamed Ticket")
        self.assertTrue(frappe.db.exists("Assignment Rule", "Test AR Renamed Ticket"))

    def test_hooks_saving_as_a_manager_are_checked(self):
        """The check runs on saves with ignore_permissions too."""
        frappe.set_user(self.manager)
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(rule_dict("Test AR Hook", "User")).insert(
                    ignore_permissions=True
                )
        finally:
            frappe.set_user("Administrator")

    def test_manager_manages_ticket_rules(self):
        name = insert_as(
            self.manager,
            rule_dict("Test AR Ticket Rule", "HD Ticket", [self.agent]),
        )["name"]
        set_value_as(
            self.manager,
            "Assignment Rule",
            name,
            {"description": "Ticket {{ subject }}", "priority": 2},
        )
        set_value_as(self.manager, "Assignment Rule", name, {"disabled": 0})
        set_value_as(self.manager, "Assignment Rule", name, {"disabled": 1})
        rule = frappe.get_doc("Assignment Rule", name)
        self.assertEqual(rule.description, "Ticket {{ subject }}")
        self.assertEqual(rule.priority, 2)
        self.assertEqual(rule.disabled, 1)

    def test_system_manager_creates_rules_for_other_documents(self):
        name = insert_as(self.system_manager, rule_dict("Test AR SM User", "User"))[
            "name"
        ]
        set_value_as(
            self.system_manager, "Assignment Rule", name, {"description": "Changed"}
        )
        self.assertEqual(
            frappe.db.get_value("Assignment Rule", name, "description"), "Changed"
        )

    def test_rules_list_shows_managers_ticket_rules_only(self):
        frappe.get_doc(rule_dict("Test AR Listed User", "User")).insert()
        frappe.get_doc(rule_dict("Test AR Listed Ticket", "HD Ticket")).insert()

        def listed(user):
            frappe.set_user(user)
            try:
                return {
                    r["name"]
                    for r in get_assignment_rules_list()
                    if r["name"].startswith("Test AR Listed")
                }
            finally:
                frappe.set_user("Administrator")

        self.assertEqual(listed(self.manager), {"Test AR Listed Ticket"})
        self.assertEqual(
            listed(self.system_manager),
            {"Test AR Listed Ticket", "Test AR Listed User"},
        )
