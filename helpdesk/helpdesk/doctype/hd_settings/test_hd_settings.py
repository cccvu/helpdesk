# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.test_utils import (
    get_guest_ticket_permissions,
    make_agent,
    make_agent_manager,
    save_hd_settings_as,
    user_roles,
)


class TestHDSettings(FrappeTestCase):
    """
    Every HD Settings save syncs HD Ticket's Guest permission rule
    (before_save), so anyone who may save HD Settings must get through it.
    """

    def setUp(self):
        frappe.set_user("Administrator")
        self.manager = make_agent_manager(f"{self._testMethodName}@manager.test")
        frappe.get_doc("User", self.manager).add_roles("Agent")
        self.assertNotIn("System Manager", user_roles(self.manager))

    def tearDown(self):
        frappe.flags.in_test = True
        frappe.set_user("Administrator")
        settings = frappe.get_doc("HD Settings")
        settings.allow_anyone_to_create_tickets = 0
        settings.save()

    def test_agent_manager_can_save(self):
        save_hd_settings_as(
            self.manager, allow_anyone_to_create_tickets=0, brand_name="Desk"
        )

        self.assertEqual(
            frappe.db.get_single_value("HD Settings", "brand_name"), "Desk"
        )

    def test_agent_manager_turns_guest_tickets_off(self):
        save_hd_settings_as("Administrator", allow_anyone_to_create_tickets=1)
        guest_rules = get_guest_ticket_permissions()
        self.assertTrue(guest_rules)

        save_hd_settings_as(self.manager, allow_anyone_to_create_tickets=0)

        self.assertEqual(get_guest_ticket_permissions(), [])
        deleted = frappe.get_all(
            "Deleted Document",
            filters={
                "deleted_doctype": "Custom DocPerm",
                "deleted_name": ["in", guest_rules],
                "owner": self.manager,
            },
            pluck="data",
        )
        self.assertEqual(len(deleted), len(guest_rules))
        for data in deleted:
            rule = json.loads(data)
            self.assertEqual((rule["parent"], rule["role"]), ("HD Ticket", "Guest"))

    def test_agent_manager_cannot_turn_guest_tickets_on(self):
        save_hd_settings_as("Administrator", allow_anyone_to_create_tickets=0)

        with self.assertRaises(frappe.PermissionError):
            save_hd_settings_as(self.manager, allow_anyone_to_create_tickets=1)

        self.assertEqual(get_guest_ticket_permissions(), [])

    def test_agent_cannot_save(self):
        agent = make_agent(f"{self._testMethodName}@agent.test")

        with self.assertRaises(frappe.PermissionError):
            save_hd_settings_as(agent, allow_anyone_to_create_tickets=0)

    def test_save_copies_standard_ticket_permissions(self):
        frappe.db.delete("Custom DocPerm", {"parent": "HD Ticket"})

        save_hd_settings_as(self.manager, allow_anyone_to_create_tickets=0)

        standard, custom = (
            {
                (p.role, p.permlevel, p.if_owner)
                for p in frappe.get_all(
                    doctype,
                    filters={"parent": "HD Ticket"},
                    fields=["role", "permlevel", "if_owner"],
                )
            }
            for doctype in ("DocPerm", "Custom DocPerm")
        )
        self.assertTrue(standard)
        self.assertEqual(custom, standard)
