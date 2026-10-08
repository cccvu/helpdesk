# Copyright (c) 2024, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.desk.form.assign_to import remove
from frappe.tests.utils import FrappeTestCase

from helpdesk.api.ticket import assign_ticket_to_agent
from helpdesk.helpdesk.doctype.hd_ticket.api import merge_ticket
from helpdesk.helpdesk.doctype.hd_ticket_comment.hd_ticket_comment import (
    AUTHOR_ONLY,
    PRESET_EMOJIS,
    get_reactions,
    has_permission,
    toggle_reaction,
)
from helpdesk.mixins.mentions import HasMentions
from helpdesk.test_utils import (
    create_agent,
    delete_doc_as,
    insert_as,
    insert_as_data_import,
    make_agent,
    make_agent_manager,
    make_mention_html,
    make_ticket,
    set_value_as,
    share_doc_as,
)


class TestHDTicketComment(FrappeTestCase):
    def setUp(self):
        frappe.db.set_single_value("HD Settings", "enable_comment_reactions", 1)

        if not frappe.db.exists("User", "test_user1@example.com"):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": "test_user1@example.com",
                    "first_name": "Test",
                    "last_name": "User One",
                    "send_welcome_email": 0,
                }
            ).insert(ignore_permissions=True)

        if not frappe.db.exists("User", "test_user2@example.com"):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": "test_user2@example.com",
                    "first_name": "Test",
                    "last_name": "User Two",
                    "send_welcome_email": 0,
                }
            ).insert(ignore_permissions=True)

        self.agent_emails = [f"agent{i}@example.com" for i in range(1, 13)]
        for email in self.agent_emails:
            create_agent(email)

        self.assigned_agents = set()

        self.test_ticket = frappe.get_doc(
            {
                "doctype": "HD Ticket",
                "subject": "Test Ticket for Reactions",
                "raised_by": "test_user1@example.com",
            }
        )
        self.test_ticket.insert(ignore_permissions=True)

        self.test_comment = frappe.get_doc(
            {
                "doctype": "HD Ticket Comment",
                "reference_ticket": self.test_ticket.name,
                "content": "<p>Test comment for reactions</p>",
                "commented_by": "test_user1@example.com",
            }
        )
        self.test_comment.insert(ignore_permissions=True)

    def assign_agent(self, user: str):
        assign_ticket_to_agent(self.test_ticket.name, user)
        self.assigned_agents.add(user)

    def unassign_agent(self, user: str):
        remove("HD Ticket", self.test_ticket.name, user)

    def tearDown(self):
        frappe.set_user("Administrator")

        for user in list(self.assigned_agents):
            self.unassign_agent(user)
        self.assigned_agents.clear()

        if hasattr(self, "test_comment") and self.test_comment:
            if frappe.db.exists("HD Ticket Comment", self.test_comment.name):
                frappe.delete_doc(
                    "HD Ticket Comment", self.test_comment.name, force=True
                )

        if hasattr(self, "test_ticket") and self.test_ticket:
            if frappe.db.exists("HD Ticket", self.test_ticket.name):
                frappe.delete_doc("HD Ticket", self.test_ticket.name, force=True)

        for email in self.agent_emails:
            if frappe.db.exists("User", email):
                frappe.delete_doc("User", email, force=True)

        frappe.db.set_single_value("HD Settings", "enable_comment_reactions", 0)

    def test_one_reaction_per_user(self):
        agent = self.agent_emails[0]
        frappe.set_user(agent)
        self.assign_agent(agent)

        toggle_reaction(self.test_comment.name, "👍")

        doc = frappe.get_doc("HD Ticket Comment", self.test_comment.name)
        self.assertEqual(len(doc.reactions), 1)
        self.assertEqual(doc.reactions[0].emoji, "👍")
        self.assertEqual(doc.reactions[0].user, agent)

        toggle_reaction(self.test_comment.name, "❤️")

        doc.reload()
        self.assertEqual(len(doc.reactions), 1)
        self.assertEqual(doc.reactions[0].emoji, "❤️")

        toggle_reaction(self.test_comment.name, "❤️")

        doc.reload()
        self.assertEqual(len(doc.reactions), 0)

        frappe.set_user("Administrator")

    def test_reaction_count_accuracy(self):
        users = self.agent_emails[1:11]

        for user_email in users:
            frappe.set_user(user_email)
            self.assign_agent(user_email)
            toggle_reaction(self.test_comment.name, "❤️")

        for user_email in users[:3]:
            frappe.set_user(user_email)
            toggle_reaction(self.test_comment.name, "👍")

        frappe.set_user("Administrator")

        reactions = get_reactions(self.test_comment.name)

        heart_reaction = next((r for r in reactions if r["emoji"] == "❤️"), None)
        thumbs_reaction = next((r for r in reactions if r["emoji"] == "👍"), None)

        self.assertIsNotNone(heart_reaction)
        self.assertEqual(heart_reaction["count"], 7)

        self.assertIsNotNone(thumbs_reaction)
        self.assertEqual(thumbs_reaction["count"], 3)

    def test_notification_created_on_reaction(self):
        frappe.set_user("test_user1@example.com")

        initial_count = frappe.db.count(
            "HD Notification",
            {
                "user_to": "test_user1@example.com",
                "notification_type": "Reaction",
                "reference_comment": self.test_comment.name,
            },
        )

        agent = self.agent_emails[0]
        frappe.set_user(agent)
        self.assign_agent(agent)
        toggle_reaction(self.test_comment.name, "👍")

        frappe.set_user("Administrator")

        final_count = frappe.db.count(
            "HD Notification",
            {
                "user_to": "test_user1@example.com",
                "notification_type": "Reaction",
                "reference_comment": self.test_comment.name,
            },
        )

        self.assertEqual(final_count, initial_count + 1)

        notification = frappe.get_last_doc(
            "HD Notification",
            {
                "user_to": "test_user1@example.com",
                "notification_type": "Reaction",
                "reference_comment": self.test_comment.name,
            },
        )

        self.assertEqual(notification.user_from, agent)
        self.assertEqual(notification.message, "1 person reacted to your comment")
        self.assertEqual(str(notification.reference_ticket), str(self.test_ticket.name))

        frappe.delete_doc("HD Notification", notification.name, force=True)

    def test_only_preset_emojis_allowed(self):
        agent = self.agent_emails[0]
        frappe.set_user(agent)
        self.assign_agent(agent)

        invalid_emojis = ["🔥", "💯", "🚨", "😂"]

        for invalid_emoji in invalid_emojis:
            with self.assertRaises(frappe.ValidationError):
                toggle_reaction(self.test_comment.name, invalid_emoji)

        doc = frappe.get_doc("HD Ticket Comment", self.test_comment.name)
        self.assertEqual(len(doc.reactions), 0)

        for preset_emoji in PRESET_EMOJIS:
            toggle_reaction(self.test_comment.name, preset_emoji)
            doc.reload()
            self.assertEqual(doc.reactions[0].emoji, preset_emoji)

        frappe.set_user("Administrator")

    def test_reaction_toggle_behavior(self):
        agent = self.agent_emails[0]
        frappe.set_user(agent)
        self.assign_agent(agent)

        result = toggle_reaction(self.test_comment.name, "👍")
        self.assertEqual(result["action"], "added")

        doc = frappe.get_doc("HD Ticket Comment", self.test_comment.name)
        self.assertEqual(len(doc.reactions), 1)

        result = toggle_reaction(self.test_comment.name, "👍")
        self.assertEqual(result["action"], "removed")

        doc.reload()
        self.assertEqual(len(doc.reactions), 0)

        frappe.set_user("Administrator")

    def test_get_reactions_returns_correct_data(self):
        agent_one = self.agent_emails[0]
        agent_two = self.agent_emails[1]
        frappe.set_user(agent_one)
        self.assign_agent(agent_one)
        toggle_reaction(self.test_comment.name, "👍")

        frappe.set_user(agent_two)
        self.assign_agent(agent_two)
        toggle_reaction(self.test_comment.name, "❤️")

        frappe.set_user("Administrator")

        reactions = get_reactions(self.test_comment.name)

        self.assertEqual(len(reactions), 2)

        for reaction in reactions:
            self.assertIn("emoji", reaction)
            self.assertIn("count", reaction)
            self.assertIn("users", reaction)
            self.assertIn("current_user_reacted", reaction)
            self.assertEqual(reaction["count"], len(reaction["users"]))

            for user in reaction["users"]:
                self.assertIn("user", user)
                self.assertIn("full_name", user)

    def test_no_notification_for_self_reaction(self):
        agent = self.agent_emails[2]
        agent_comment = frappe.get_doc(
            {
                "doctype": "HD Ticket Comment",
                "reference_ticket": self.test_ticket.name,
                "content": "<p>Agent self reaction test</p>",
                "commented_by": agent,
            }
        )
        agent_comment.insert(ignore_permissions=True)

        frappe.set_user(agent)
        self.assign_agent(agent)

        initial_count = frappe.db.count(
            "HD Notification",
            {
                "user_to": agent,
                "notification_type": "Reaction",
                "reference_comment": agent_comment.name,
            },
        )

        toggle_reaction(agent_comment.name, "👍")

        frappe.set_user("Administrator")

        final_count = frappe.db.count(
            "HD Notification",
            {
                "user_to": agent,
                "notification_type": "Reaction",
                "reference_comment": agent_comment.name,
            },
        )

        self.assertEqual(final_count, initial_count)

        frappe.delete_doc("HD Ticket Comment", agent_comment.name, force=True)

    def test_if_repeated_notification_sent_on_mention_add(self):
        agent_one, agent_two, agent_three = self.agent_emails[0:3]
        frappe.set_user(agent_one)
        self.assign_agent(agent_one)

        agent_comment = frappe.get_doc(
            {
                "doctype": "HD Ticket Comment",
                "reference_ticket": self.test_ticket.name,
                "content": f"<p>Hello {make_mention_html(agent_two)}</p>",
                "commented_by": agent_one,
                "owner": agent_one,
            }
        )

        agent_comment.insert(ignore_permissions=True)

        notifications = frappe.get_all(
            "HD Notification",
            filters={
                "reference_comment": agent_comment.name,
                "notification_type": "Mention",
            },
            fields=["name", "user_to", "user_from"],
        )
        # notification one created should be equal to 1
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].user_to, agent_two)
        self.assertEqual(notifications[0].user_from, agent_one)

        agent_comment.content = (
            f"<p>Hello {make_mention_html(agent_two)} "
            f"{make_mention_html(agent_three)}</p>"
        )

        agent_comment.save(ignore_permissions=True)
        agent_comment.reload()
        notifications_updated = frappe.get_all(
            "HD Notification",
            filters={
                "reference_comment": agent_comment.name,
                "notification_type": "Mention",
            },
            fields=["user_to"],
        )

        user_emails = {n.user_to for n in notifications_updated}

        self.assertEqual(len(notifications_updated), 2)
        self.assertIn(agent_two, user_emails)
        self.assertIn(agent_three, user_emails)

    def test_grouped_notifications(self):
        test_users = self.agent_emails[3:6]

        agent = self.agent_emails[0]
        frappe.set_user(agent)
        self.assign_agent(agent)
        toggle_reaction(self.test_comment.name, "👍")

        frappe.set_user("Administrator")

        notifications = frappe.get_all(
            "HD Notification",
            filters={
                "user_to": "test_user1@example.com",
                "notification_type": "Reaction",
                "reference_comment": self.test_comment.name,
            },
        )
        self.assertEqual(len(notifications), 1)

        frappe.set_user(test_users[0])
        self.assign_agent(test_users[0])
        toggle_reaction(self.test_comment.name, "❤️")

        frappe.set_user("Administrator")

        notifications = frappe.get_all(
            "HD Notification",
            filters={
                "user_to": "test_user1@example.com",
                "notification_type": "Reaction",
                "reference_comment": self.test_comment.name,
            },
        )
        self.assertEqual(len(notifications), 1)

        notification = frappe.get_doc("HD Notification", notifications[0].name)
        self.assertEqual(notification.message, "2 people reacted to your comment")

        frappe.delete_doc("HD Notification", notification.name, force=True)


class TestHDTicketCommentRights(FrappeTestCase):
    """Only a comment's author or a manager changes, deletes or shares it, and
    a comment's author is the user who posted it."""

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.set_single_value("HD Settings", "enable_comment_reactions", 1)
        self.addCleanup(
            frappe.db.set_single_value, "HD Settings", "enable_comment_reactions", 0
        )
        self.author = make_agent("comment_rights_author@example.com")
        self.other = make_agent("comment_rights_other@example.com")
        self.manager = make_agent_manager("comment_rights_manager@example.com")
        self.ticket = make_ticket(raised_by="comment_rights_requester@example.com")
        self.note = self.post_note(self.author, "<p>Author's note</p>")

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

    def stored(self, name: str | None = None) -> dict:
        return frappe.db.get_value(
            "HD Ticket Comment",
            name or self.note,
            ["content", "commented_by", "owner"],
            as_dict=True,
        )

    def test_note_is_posted_as_its_author(self):
        self.assertEqual(self.stored().commented_by, self.author)
        self.assertEqual(self.stored().owner, self.author)

    def test_other_agent_cannot_change_note(self):
        before = self.stored()
        changes = {
            "content": {"content": "<p>Changed</p>"},
            "commented_by": {"content": "<p>Changed</p>", "commented_by": self.other},
            "owner": {"content": "<p>Changed</p>", "owner": self.other},
        }
        for case, values in changes.items():
            with self.subTest(case=case):
                with self.assertRaises(frappe.PermissionError):
                    set_value_as(self.other, "HD Ticket Comment", self.note, values)
                self.assertEqual(self.stored(), before)

    def test_other_agent_cannot_delete_note(self):
        with self.assertRaises(frappe.PermissionError):
            delete_doc_as(self.other, "HD Ticket Comment", self.note)
        self.assertTrue(frappe.db.exists("HD Ticket Comment", self.note))

    def test_other_agent_cannot_share_note(self):
        with self.assertRaises(frappe.PermissionError):
            share_doc_as(
                self.other, "HD Ticket Comment", self.note, self.other, write=1
            )
        self.assertFalse(
            frappe.db.exists(
                "DocShare",
                {"share_doctype": "HD Ticket Comment", "share_name": self.note},
            )
        )

    def test_other_agent_cannot_insert_reaction_rows(self):
        row = {
            "doctype": "HD Comment Reaction",
            "parenttype": "HD Ticket Comment",
            "parent": self.note,
            "parentfield": "reactions",
            "user": self.author,
            "emoji": PRESET_EMOJIS[0],
        }
        with self.assertRaises(frappe.PermissionError):
            insert_as(self.other, row)

        frappe.set_user(self.other)
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(row).insert()
        finally:
            frappe.set_user("Administrator")

        self.assertFalse(frappe.get_doc("HD Ticket Comment", self.note).reactions)

    def test_other_agent_can_still_react(self):
        frappe.set_user(self.other)
        try:
            self.assertEqual(
                toggle_reaction(self.note, PRESET_EMOJIS[0])["action"], "added"
            )
        finally:
            frappe.set_user("Administrator")

        reactions = frappe.get_doc("HD Ticket Comment", self.note).reactions
        self.assertEqual([(r.user, r.emoji) for r in reactions], [(self.other, "👍")])

    def test_author_and_manager_can_change_and_delete(self):
        set_value_as(self.author, "HD Ticket Comment", self.note, {"content": "A"})
        self.assertEqual(self.stored().content, "A")
        set_value_as(self.manager, "HD Ticket Comment", self.note, {"content": "M"})
        self.assertEqual(self.stored().content, "M")
        self.assertEqual(self.stored().commented_by, self.author)

        delete_doc_as(self.manager, "HD Ticket Comment", self.note)
        self.assertFalse(frappe.db.exists("HD Ticket Comment", self.note))

        own = self.post_note(self.author, "<p>Another note</p>")
        delete_doc_as(self.author, "HD Ticket Comment", own)
        self.assertFalse(frappe.db.exists("HD Ticket Comment", own))

    def test_author_match_ignores_case(self):
        frappe.db.set_value(
            "HD Ticket Comment", self.note, "commented_by", self.author.upper()
        )
        set_value_as(self.author, "HD Ticket Comment", self.note, {"content": "A"})
        self.assertEqual(self.stored().content, "A")

    def test_insert_naming_someone_else_is_stored_as_poster(self):
        insert_as(
            self.other,
            {
                "doctype": "HD Ticket Comment",
                "reference_ticket": self.ticket.name,
                "content": "<p>Posted by other</p>",
                "commented_by": self.author,
            },
        )
        note = frappe.get_last_doc(
            "HD Ticket Comment", {"reference_ticket": self.ticket.name}
        )
        self.assertEqual(note.commented_by, self.other)
        self.assertEqual(note.owner, self.other)

    def test_nobody_changes_a_notes_author(self):
        # Frappe itself refuses a change of owner on update
        errors = {
            "commented_by": frappe.PermissionError,
            "owner": frappe.CannotChangeConstantError,
        }
        for user in (self.author, self.manager):
            for field, error in errors.items():
                with self.subTest(user=user, field=field):
                    with self.assertRaises(error):
                        set_value_as(
                            user, "HD Ticket Comment", self.note, {field: self.other}
                        )
                    self.assertEqual(self.stored().commented_by, self.author)
                    self.assertEqual(self.stored().owner, self.author)

    def test_merge_keeps_authors(self):
        target = make_ticket(raised_by="comment_rights_requester@example.com")

        frappe.set_user(self.other)
        try:
            merge_ticket(source=self.ticket.name, target=target.name)
        finally:
            frappe.set_user("Administrator")

        copies = frappe.get_all(
            "HD Ticket Comment",
            filters={"reference_ticket": target.name},
            fields=["commented_by", "owner"],
        )
        self.assertIn(
            (self.author, self.author), [(c.commented_by, c.owner) for c in copies]
        )

    def test_data_import_keeps_author(self):
        note = insert_as_data_import(
            {
                "doctype": "HD Ticket Comment",
                "reference_ticket": self.ticket.name,
                "content": "<p>Imported</p>",
                "commented_by": self.author,
            }
        )
        self.assertEqual(self.stored(note.name).commented_by, self.author)

    def test_upload_to_unsaved_note_is_allowed(self):
        from frappe.handler import check_write_permission

        frappe.set_user(self.other)
        try:
            check_write_permission("HD Ticket Comment", "new-hd-ticket-comment-1")
        finally:
            frappe.set_user("Administrator")

    def test_hook_judges_the_stored_author(self):
        doc = frappe.get_doc("HD Ticket Comment", self.note)
        doc.commented_by = self.other
        for ptype in AUTHOR_ONLY:
            with self.subTest(ptype=ptype):
                self.assertFalse(has_permission(doc, ptype=ptype, user=self.other))
                self.assertTrue(has_permission(doc, ptype=ptype, user=self.author))
        self.assertTrue(has_permission(doc, ptype="read", user=self.other))

    def test_manager_can_edit_note_without_author(self):
        frappe.db.set_value("HD Ticket Comment", self.note, "commented_by", None)
        set_value_as(self.manager, "HD Ticket Comment", self.note, {"content": "M"})
        self.assertEqual(self.stored().content, "M")
        self.assertIsNone(self.stored().commented_by)
        with self.assertRaises(frappe.PermissionError):
            set_value_as(self.author, "HD Ticket Comment", self.note, {"content": "A"})
