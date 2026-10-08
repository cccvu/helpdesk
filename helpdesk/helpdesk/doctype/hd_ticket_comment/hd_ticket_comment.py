# Copyright (c) 2022, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from helpdesk.mixins.mentions import HasMentions
from helpdesk.utils import capture_event, get_doc_room, is_agent_manager, publish_event

PRESET_EMOJIS = ["👍", "👎", "❤️", "🎉", "👀", "✅"]

# Rights on a saved comment that only its author or a manager has. "create" is
# here because inserting a child row (a reaction) checks create on the parent.
AUTHOR_ONLY = ("write", "delete", "share", "create")


class HDTicketComment(HasMentions, Document):
    mentions_field = "content"

    def before_insert(self):
        # a comment is always the session user's own, whatever the client sent
        if not self._skips_author_checks():
            self.commented_by = frappe.session.user

    def validate(self):
        # Frappe already refuses a change of owner on update
        if self.is_new() or self._skips_author_checks():
            return
        previous = self.get_doc_before_save()
        # link validation may correct the case of a stored author
        if (
            previous
            and (previous.commented_by or "").lower()
            != (self.commented_by or "").lower()
        ):
            frappe.throw(
                _("A comment's author can't be changed."), frappe.PermissionError
            )

    def _skips_author_checks(self) -> bool:
        """Server code that saves with ignore_permissions (merge copies keep
        their authors, reactions save as the reacting user), Data Import and
        install, patch and migrate runs keep commented_by as given."""
        return bool(
            self.flags.ignore_permissions
            or frappe.flags.in_import
            or frappe.flags.in_install
            or frappe.flags.in_patch
            or frappe.flags.in_migrate
        )

    def on_update(self):
        if self.has_value_changed("content"):
            original_content = (
                self.get_doc_before_save().content
                if self.get_doc_before_save()
                else None
            )
            self.notify_mentions(original_content=original_content)

    def after_insert(self):
        event = "helpdesk:ticket-comment"
        data = {"ticket_id": self.reference_ticket}
        telemetry_event = "comment_added"

        room = get_doc_room("HD Ticket", self.reference_ticket)
        publish_event(
            event,
            room=room,
            data=data,
        )
        capture_event(telemetry_event)
        self.notify_mentions()

    def after_delete(self):
        event = "helpdesk:ticket-comment"
        data = {"ticket_id": self.reference_ticket}
        telemetry_event = "ticket_comment_deleted"

        room = get_doc_room("HD Ticket", self.reference_ticket)
        publish_event(event, room=room, data=data)
        capture_event(telemetry_event)


@frappe.whitelist()
def toggle_reaction(comment: str, emoji: str):
    # frappe.has_permission(doctype, perm, user=user, doc=doc, parent_doctype=parent)
    # frappe.has_permission("Email Account", "create", throw=True)
    ticket = frappe.get_value("HD Ticket Comment", comment, "reference_ticket")
    frappe.has_permission("HD Ticket", "read", ticket, throw=True)
    frappe.has_permission("HD Ticket", "write", ticket, throw=True)

    if not frappe.db.get_single_value("HD Settings", "enable_comment_reactions"):
        return

    if emoji not in PRESET_EMOJIS:
        frappe.throw(
            f"Invalid emoji. Only preset emojis are allowed: {', '.join(PRESET_EMOJIS)}"
        )

    if not frappe.db.exists("HD Ticket Comment", comment):
        frappe.throw(_("Comment not found"))

    user = frappe.session.user
    doc = frappe.get_doc("HD Ticket Comment", comment)

    existing_reaction = None
    for r in doc.reactions:
        if r.user == user:
            existing_reaction = r
            break

    if existing_reaction:
        if existing_reaction.emoji == emoji:
            doc.reactions.remove(existing_reaction)
            doc.save(ignore_permissions=True)
            action = "removed"
        else:
            existing_reaction.emoji = emoji
            doc.save(ignore_permissions=True)
            action = "changed"
            if doc.commented_by != user:
                notify_reaction(doc, emoji, user)
    else:
        doc.append("reactions", {"emoji": emoji, "user": user})
        doc.save(ignore_permissions=True)
        action = "added"
        if doc.commented_by != user:
            notify_reaction(doc, emoji, user)

    room = get_doc_room("HD Ticket", doc.reference_ticket)
    publish_event(
        "helpdesk:comment-reaction-update",
        room=room,
        data={"comment": comment, "ticket_id": doc.reference_ticket},
    )

    return {"action": action, "emoji": emoji}


@frappe.whitelist()
def get_reactions(comment: str):
    if not frappe.db.get_single_value("HD Settings", "enable_comment_reactions"):
        return []

    if not frappe.db.exists("HD Ticket Comment", comment):
        frappe.throw(_("Comment not found"))

    doc = frappe.get_doc("HD Ticket Comment", comment)
    current_user = frappe.session.user

    reactions_map = {}
    for r in doc.reactions:
        if r.emoji not in reactions_map:
            reactions_map[r.emoji] = {
                "emoji": r.emoji,
                "users": [],
                "current_user_reacted": False,
            }

        user_info = frappe.get_cached_doc("User", r.user)
        reactions_map[r.emoji]["users"].append(
            {
                "user": r.user,
                "full_name": user_info.full_name or r.user,
            }
        )

        if r.user == current_user:
            reactions_map[r.emoji]["current_user_reacted"] = True

    for emoji in reactions_map:
        reactions_map[emoji]["count"] = len(reactions_map[emoji]["users"])

    return list(reactions_map.values())


def notify_reaction(doc, emoji, user):
    reacting_users = set()
    for r in doc.reactions:
        if r.user != doc.commented_by:
            reacting_users.add(r.user)

    if not reacting_users:
        return

    count = len(reacting_users)
    if count == 1:
        message = _("1 person reacted to your comment")
    else:
        message = _("{} people reacted to your comment").format(count)

    existing = frappe.db.get_value(
        "HD Notification",
        {
            "reference_comment": doc.name,
            "user_to": doc.commented_by,
            "notification_type": "Reaction",
        },
        ["name"],
        as_dict=True,
    )

    if existing:
        frappe.db.set_value(
            "HD Notification",
            existing.name,
            {"message": message, "user_from": user, "read": 0},
        )
    else:
        frappe.get_doc(
            {
                "doctype": "HD Notification",
                "message": message,
                "notification_type": "Reaction",
                "reference_comment": doc.name,
                "reference_ticket": doc.reference_ticket,
                "user_from": user,
                "user_to": doc.commented_by,
            }
        ).insert(ignore_permissions=True)


@frappe.whitelist()
def get_preset_emojis():
    return PRESET_EMOJIS


def has_permission(doc, ptype="read", user=None):
    """Only a comment's author or a manager changes, deletes or shares it.

    Judged by the stored comment's author, so a save can't change what is
    checked. A comment that isn't stored yet (a new one, or an upload to an
    unsaved one) is left to the role permissions; before_insert makes it the
    session user's. Other rights are unchanged.
    """
    user = user or frappe.session.user
    if ptype not in AUTHOR_ONLY or not doc.name:
        return True
    stored = frappe.db.get_value(
        "HD Ticket Comment", doc.name, "commented_by", as_dict=True
    )
    if not stored:
        return True
    return is_agent_manager(user) or is_same_user(stored.commented_by, user)


def is_same_user(a: str | None, b: str | None) -> bool:
    """Whether two user names are the same user: names match case-insensitively,
    and an empty name matches no one."""
    return bool(a) and bool(b) and a.lower() == b.lower()
