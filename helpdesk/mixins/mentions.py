import frappe

from helpdesk.utils import extract_mentions


class HasMentions:
    def notify_mentions(self, original_content=None):
        """
        Extract mentions from `mentions_field`, and notify.
        `mentions_field` must have `HTML` content.

        Only active agents are notified, and the notification is from the user
        who saved the content. Copies (flags.skip_mention_notifications) and
        Data Import notify no one. Runs twice on insert (after_insert and
        on_update), so the checks are here.
        """
        if self.flags.skip_mention_notifications or frappe.flags.in_import:
            return
        mentions_field = getattr(self, "mentions_field", None)
        if not mentions_field:
            return
        current_mentions = extract_mentions(self.get(mentions_field))
        if original_content:
            original_mentions = extract_mentions(original_content)
            original_emails = {m.email for m in original_mentions}
            # Only keep new mentions
            current_mentions = [
                m for m in current_mentions if m.email not in original_emails
            ]

        user_from = frappe.session.user
        for mention in current_mentions:
            user_to = get_active_agent_user(mention.email)
            # Why mention oneself?
            if not user_to or user_to.lower() == user_from.lower():
                continue
            values = frappe._dict(
                doctype="HD Notification",
                user_from=user_from,
                user_to=user_to,
                notification_type="Mention",
                message=self.content,
            )
            # Only comment (in tickets) has mentions as of now
            if self.doctype == "HD Ticket Comment":
                values.reference_comment = self.name
                values.reference_ticket = self.reference_ticket
            if frappe.db.exists(
                "HD Notification",
                {
                    "reference_comment": self.name,
                    "user_to": user_to,
                    "notification_type": "Mention",
                },
            ):
                # avoid loop of notification to quit at first mention
                continue
            frappe.get_doc(values).insert(ignore_permissions=True)


def get_active_agent_user(agent: str | None) -> str | None:
    """The user of the active HD Agent named `agent` (a mention's data-id),
    as stored, or None. An HD Agent is named after its user."""
    if not agent or not isinstance(agent, str):
        return None
    return frappe.db.get_value("HD Agent", {"name": agent, "is_active": 1}, "user")
