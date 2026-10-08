# Copyright (c) 2022, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.helpdesk.doctype.hd_ticket_activity.hd_ticket_activity import (
    log_ticket_activity,
)
from helpdesk.test_utils import (
    delete_doc_as,
    insert_as,
    make_agent,
    make_ticket,
    set_value_as,
    share_doc_as,
)


class TestHDTicketActivity(FrappeTestCase):
    """Agents add ticket activity but can't change, delete or share it."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = make_agent("activity_agent@example.com")
        self.ticket = make_ticket(raised_by="activity_requester@example.com").name
        self.activity = log_ticket_activity(self.ticket, "set status to Open").name

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_agent_can_add_activity(self):
        # as the agent UI logs an assignment
        activity = insert_as(
            self.agent,
            {
                "doctype": "HD Ticket Activity",
                "ticket": self.ticket,
                "action": "assigned to someone",
            },
        )
        self.assertEqual(
            frappe.db.get_value("HD Ticket Activity", activity["name"], "owner"),
            self.agent,
        )

    def test_agent_cannot_change_activity(self):
        with self.assertRaises(frappe.PermissionError):
            set_value_as(
                self.agent, "HD Ticket Activity", self.activity, {"action": "changed"}
            )
        self.assertEqual(
            frappe.db.get_value("HD Ticket Activity", self.activity, "action"),
            "set status to Open",
        )

    def test_agent_cannot_delete_activity(self):
        with self.assertRaises(frappe.PermissionError):
            delete_doc_as(self.agent, "HD Ticket Activity", self.activity)
        self.assertTrue(frappe.db.exists("HD Ticket Activity", self.activity))

    def test_agent_cannot_share_activity(self):
        with self.assertRaises(frappe.PermissionError):
            share_doc_as(
                self.agent, "HD Ticket Activity", self.activity, self.agent, write=1
            )
