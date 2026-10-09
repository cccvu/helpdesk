import html
import re

import frappe
from frappe import _
from frappe.utils import strip_html

from helpdesk.api.tags import update_tags
from helpdesk.helpdesk.doctype.hd_saved_reply.hd_saved_reply import (
    ACTIONS,
    action_key,
    is_action_valid,
    parse_actions,
)
from helpdesk.utils import agent_only

# `{{ field }}` or `{{ doc.field }}`, as the editor's placeholder menu inserts
PLACEHOLDER = re.compile(r"\{\{\s*(doc\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
# The signed-in user's fields a placeholder can name; mirrors `userFields` in
# desk/src/components/Settings/SavedReplies/savedReplies.ts
USER_FIELDS = (
    "email",
    "first_name",
    "middle_name",
    "last_name",
    "full_name",
    "username",
    "user_image",
    "phone",
    "location",
    "bio",
    "mobile_no",
)
RICH_TEXT_FIELDTYPES = ("Text Editor", "HTML Editor")
# The ticket's access key is a secret, not reply text
SECRET_TICKET_FIELDS = ("key",)


@frappe.whitelist()
@agent_only
def get_rendered_saved_reply(ticket_id: str, saved_reply_id: str | None = None):
    if not saved_reply_id:
        frappe.throw(_("Please provide saved_reply_id"))
    saved_reply = frappe.get_doc("HD Saved Reply", saved_reply_id)
    saved_reply.check_permission("read")
    ticket = frappe.get_doc("HD Ticket", ticket_id)
    ticket.check_permission("read")
    return {
        "title": saved_reply.title,
        "message": render_saved_reply(saved_reply.message, ticket),
        # Stale actions are dropped here so agents never stage one that
        # would fail after the email is already sent
        "actions": [
            serialize_action(action)
            for action in parse_actions(saved_reply.actions)
            if is_action_valid(action.get("action_type"), action.get("value"))
        ],
    }


def render_saved_reply(message: str | None, ticket) -> str:
    """Fill `{{ field }}` placeholders in a saved reply as escaped text.

    A bare name is one of the ticket's fields the user may read (`name` is
    the ticket's, its access key never is), or else one of USER_FIELDS of the
    signed-in user; `doc.name` reads the ticket only. Rich text is reduced to plain text and
    an empty value to "". Nothing is evaluated: unknown names and any other
    template syntax stay exactly as written.
    """
    if not message:
        return message or ""

    meta = ticket.meta
    ticket_fields = {
        "name",
        *meta.get_permitted_fieldnames(permission_type="read"),
    } - set(SECRET_TICKET_FIELDS)
    user = frappe.db.get_value("User", frappe.session.user, USER_FIELDS, as_dict=True)

    def as_text(value, fieldtype=None) -> str:
        if value is None:
            return ""
        text = str(value)
        if fieldtype in RICH_TEXT_FIELDTYPES:
            text = strip_html(text)
        # Stored text may already hold entities; escape it exactly once
        return html.escape(html.unescape(text))

    def fill(match: re.Match) -> str:
        on_ticket, fieldname = match.group(1), match.group(2)
        if fieldname in ticket_fields:
            df = meta.get_field(fieldname)
            return as_text(ticket.get(fieldname), df.fieldtype if df else None)
        if not on_ticket and user and fieldname in USER_FIELDS:
            return as_text(user.get(fieldname))
        return match.group(0)

    return PLACEHOLDER.sub(fill, message)


def serialize_action(action: dict) -> dict:
    action_type, value = action.get("action_type"), action.get("value") or ""
    label = value
    if action_type == "Assign Agent":
        label = frappe.db.get_value("HD Agent", value, "agent_name") or value
    elif action_type == "Add Comment":
        # Full plain text; the chip truncates visually and shows it in a tooltip
        label = strip_html(value)
    return {"action_type": action_type, "value": value, "label": label}


@frappe.whitelist(methods=["POST"])
@agent_only
def apply_saved_reply_actions(ticket_id: str, actions: list[dict] | str) -> dict:
    """Apply saved reply actions to a ticket, after its reply email is sent.

    Actions that are no longer valid are skipped and reported instead of
    raised — the email is already out by the time this runs.
    """
    parsed_actions = parse_actions(actions)
    ticket = frappe.get_doc("HD Ticket", ticket_id)
    ticket.check_permission("write")

    applied: list[dict] = []
    skipped: list[dict] = []
    assign_to = None
    comment = None
    added_tags: list[str] = []
    removed_tags: list[str] = []
    seen: set = set()
    for action in parsed_actions:
        action_type, value = action.get("action_type"), action.get("value")
        if not is_action_valid(action_type, value):
            skipped.append({"action_type": action_type, "value": value})
            continue
        # A repeat is shadowed by the last one, so it never applies
        key = action_key(action_type, value)
        if key in seen:
            skipped.append({"action_type": action_type, "value": value})
            continue
        seen.add(key)
        if action_type == "Assign Agent":
            assign_to = value
        elif action_type == "Assign to Me":
            if not frappe.db.exists(
                "HD Agent", {"name": frappe.session.user, "is_active": 1}
            ):
                skipped.append({"action_type": action_type, "value": value})
                continue
            assign_to = frappe.session.user
        elif action_type == "Add Tag":
            added_tags.append(value.strip())
        elif action_type == "Remove Tag":
            removed_tags.append(value.strip())
        elif action_type == "Add Comment":
            comment = value
        else:
            ticket.set(ACTIONS[action_type]["ticket_field"], value)
        applied.append({"action_type": action_type, "value": value})

    if any(ACTIONS[action["action_type"]]["kind"] == "field" for action in applied):
        ticket.save()
    # Assignment after save: an explicit assignment action wins over the
    # team-membership cleanup HD Ticket.on_update runs when the team changes
    if assign_to:
        ticket.assign_agent(assign_to)
    if added_tags or removed_tags:
        update_tags(
            ticket.doctype,
            ticket.name,
            added=[{"name": tag} for tag in added_tags],
            removed=removed_tags,
        )
    if comment:
        ticket.new_comment(comment)
    return {"applied": applied, "skipped": skipped}
