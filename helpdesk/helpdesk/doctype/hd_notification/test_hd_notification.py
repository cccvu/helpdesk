# Copyright (c) 2022, Frappe Technologies and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.client import get as client_get
from frappe.client import get_count as client_get_count
from frappe.client import get_list as client_get_list
from frappe.tests.utils import FrappeTestCase

from helpdesk.helpdesk.doctype.hd_notification.hd_notification import has_permission
from helpdesk.helpdesk.doctype.hd_notification.utils import clear
from helpdesk.helpdesk.doctype.hd_ticket_comment.hd_ticket_comment import (
    toggle_reaction,
)
from helpdesk.test_utils import (
    create_user,
    insert_as,
    make_agent,
    make_agent_manager,
    make_mention_html,
    make_ticket,
    set_value_as,
    share_doc_as,
    user_roles,
)


class TestHDNotification(FrappeTestCase):
    """Only server code creates notifications, users read their own, and a
    mention notifies an active agent on behalf of the user who wrote it."""

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.set_single_value("HD Settings", "skip_email_workflow", 0)
        self.author = make_agent("notification_author@example.com")
        self.other = make_agent("notification_other@example.com")
        self.manager = make_agent_manager("notification_manager@example.com")
        self.system_manager = make_agent("notification_sysman@example.com")
        frappe.get_doc("User", self.system_manager).add_roles("System Manager")
        self.inactive = make_agent("notification_inactive@example.com")
        frappe.db.set_value("HD Agent", self.inactive, "is_active", 0)
        self.non_agent = create_user("notification_user@example.com").name
        self.ticket = make_ticket(raised_by="notification_requester@example.com")

    def tearDown(self):
        frappe.set_user("Administrator")

    def post_note(self, user: str, content: str) -> str:
        """Post a note on the test ticket as `user`, the way the agent UI does."""
        frappe.set_user(user)
        try:
            frappe.get_doc("HD Ticket", self.ticket.name).new_comment(content)
        finally:
            frappe.set_user("Administrator")
        return frappe.get_last_doc(
            "HD Ticket Comment", {"reference_ticket": self.ticket.name}
        ).name

    def mentions(self, note: str) -> list:
        return frappe.get_all(
            "HD Notification",
            filters={"reference_comment": note, "notification_type": "Mention"},
            fields=["name", "user_from", "user_to"],
        )

    def notify(self, user_to: str) -> str:
        """An assignment notification to `user_to`, made as server code does."""
        frappe.get_doc("HD Ticket", self.ticket.name).notify_agent(user_to)
        return frappe.get_last_doc("HD Notification", {"user_to": user_to}).name

    def listed(self) -> set:
        """The test ticket's notifications that the session user can list."""
        rows = client_get_list(
            "HD Notification",
            filters={"reference_ticket": self.ticket.name},
            limit_page_length=0,
        )
        return {row["name"] for row in rows}

    def test_agent_mention_notifies_the_agent(self):
        self.assertEqual(user_roles(self.author) & {"System Manager"}, set())

        with patch("frappe.sendmail") as sendmail:
            note = self.post_note(
                self.author, f"<p>{make_mention_html(self.other)}</p>"
            )

        mentions = self.mentions(note)
        self.assertEqual(
            [(m.user_from, m.user_to) for m in mentions], [(self.author, self.other)]
        )
        sendmail.assert_called_once()
        self.assertEqual(sendmail.call_args.kwargs["recipients"], self.other)

    def test_mention_from_an_edit_is_from_the_editor(self):
        note = self.post_note(self.author, "<p>No mentions yet</p>")
        set_value_as(
            self.manager,
            "HD Ticket Comment",
            note,
            {"content": f"<p>{make_mention_html(self.other)}</p>"},
        )

        mentions = self.mentions(note)
        self.assertEqual(
            [(m.user_from, m.user_to) for m in mentions], [(self.manager, self.other)]
        )

    def test_only_active_agents_are_notified(self):
        content = "".join(
            make_mention_html(user)
            for user in (self.non_agent, self.inactive, None, "", self.author)
        )
        with patch("frappe.sendmail") as sendmail:
            note = self.post_note(self.author, f"<p>{content}</p>")

        self.assertEqual(self.mentions(note), [])
        sendmail.assert_not_called()

    def test_mention_is_matched_to_the_agent_case_insensitively(self):
        note = self.post_note(
            self.author, f"<p>{make_mention_html(self.other.upper())}</p>"
        )
        self.assertEqual([m.user_to for m in self.mentions(note)], [self.other])

    def test_one_notification_per_mention(self):
        mention = make_mention_html(self.other)
        note = self.post_note(self.author, f"<p>{mention} {mention}</p>")
        self.assertEqual(len(self.mentions(note)), 1)

    def test_agent_cannot_create_notifications(self):
        # the Agent role keeps create; the hook refuses it
        self.assertTrue(
            frappe.has_permission("HD Notification", "create", user=self.author)
        )
        with self.assertRaises(frappe.PermissionError):
            insert_as(
                self.author,
                {
                    "doctype": "HD Notification",
                    "user_from": self.manager,
                    "user_to": self.other,
                    "notification_type": "Mention",
                    "message": "<p>Inserted by an agent</p>",
                },
            )
        self.assertFalse(
            frappe.db.exists(
                "HD Notification", {"message": "<p>Inserted by an agent</p>"}
            )
        )

    def test_hook_refuses_agents_every_change(self):
        own = frappe.get_doc("HD Notification", self.notify(self.author))
        for ptype in ("create", "write", "delete", "share"):
            with self.subTest(ptype=ptype):
                self.assertFalse(has_permission(own, ptype=ptype, user=self.author))
        self.assertTrue(has_permission(own, ptype="read", user=self.author))

    def test_agent_cannot_change_or_share_notifications(self):
        own = self.notify(self.author)
        for name in (own, self.notify(self.other)):
            with self.subTest(name=name):
                with self.assertRaises(frappe.PermissionError):
                    set_value_as(
                        self.author, "HD Notification", name, {"message": "Changed"}
                    )
                with self.assertRaises(frappe.PermissionError):
                    share_doc_as(
                        self.author, "HD Notification", name, self.author, write=1
                    )
                self.assertFalse(
                    frappe.db.get_value("HD Notification", name, "message")
                )

    def test_agent_reads_only_own_notifications(self):
        own = self.notify(self.author)
        others = self.notify(self.other)

        frappe.set_user(self.author)
        try:
            self.assertEqual(client_get("HD Notification", own)["name"], own)
            with self.assertRaises(frappe.PermissionError):
                client_get("HD Notification", others)
            self.assertEqual(self.listed(), {own})
            self.assertEqual(
                client_get_count("HD Notification", {"user_to": self.other}), 0
            )
        finally:
            frappe.set_user("Administrator")

    def test_read_is_judged_by_the_stored_recipient(self):
        others = self.notify(self.other)
        doc = frappe.get_doc("HD Notification", others)
        doc.user_to = self.author
        self.assertFalse(has_permission(doc, ptype="read", user=self.author))
        self.assertTrue(has_permission(doc, ptype="read", user=self.other))

    def test_managers_list_only_their_own_but_system_managers_see_all(self):
        own = self.notify(self.manager)
        others = self.notify(self.other)

        def listed_as(user):
            frappe.set_user(user)
            try:
                return self.listed()
            finally:
                frappe.set_user("Administrator")

        self.assertEqual(listed_as(self.manager), {own})
        self.assertEqual(listed_as(self.system_manager), {own, others})
        self.assertEqual(listed_as("Administrator"), {own, others})

    def test_server_notifications_still_work(self):
        frappe.db.set_single_value("HD Settings", "enable_comment_reactions", 1)
        self.addCleanup(
            frappe.db.set_single_value, "HD Settings", "enable_comment_reactions", 0
        )
        note = self.post_note(self.author, "<p>React to this</p>")

        frappe.set_user(self.other)
        try:
            toggle_reaction(note, "👍")
        finally:
            frappe.set_user("Administrator")
        reaction = frappe.get_last_doc(
            "HD Notification",
            {"reference_comment": note, "notification_type": "Reaction"},
        )
        self.assertEqual(
            (reaction.user_from, reaction.user_to), (self.other, self.author)
        )

        assignment = self.notify(self.other)
        frappe.set_user(self.other)
        try:
            clear(ticket=self.ticket.name)
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("HD Notification", assignment, "read"), 1)
