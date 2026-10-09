import frappe
from frappe import _
from frappe.utils import strip_html

from helpdesk.utils import agent_manager_only

# Longest brand name stored; it also becomes the site name in emails.
BRAND_NAME_MAX_LENGTH = 140


@frappe.whitelist(methods=["POST"])
def mark_persona_captured(brand_name: str | None = None) -> None:
    """Flag the onboarding persona questionnaire as done so it never re-prompts,
    and adopt the org name as the brand name.

    Only System Managers (and Administrator), who are the users shown the
    questionnaire, may complete it, and only once: when the flag is already
    set, nothing is written. The brand name is stored as plain text, without
    markup or angle brackets, and at most BRAND_NAME_MAX_LENGTH characters.
    """
    roles = frappe.get_roles()
    if "System Manager" not in roles and "Administrator" not in roles:
        frappe.throw(
            _("Only a System Manager can complete onboarding."),
            frappe.PermissionError,
        )

    if frappe.db.get_single_value("HD Settings", "persona_captured"):
        return

    frappe.db.set_single_value("HD Settings", "persona_captured", 1)
    brand_name = _clean_brand_name(brand_name)
    if brand_name:
        frappe.db.set_single_value("HD Settings", "brand_name", brand_name)
        frappe.db.set_single_value("Website Settings", "app_name", brand_name)
        # Display name in framework emails, e.g. the welcome mail "Welcome to <name>".
        frappe.db.set_default("site_name", brand_name)
        # set_single_value skips Website Settings' on_update, so clear the cache
        # ourselves for the new brand to show up in the desk/PWA/app identity.
        frappe.clear_cache()


def _clean_brand_name(brand_name: str | None) -> str:
    """Plain text of the brand name: tags removed, then any remaining angle
    brackets, trimmed and capped at BRAND_NAME_MAX_LENGTH characters."""
    text = strip_html(brand_name or "")
    text = text.replace("<", "").replace(">", "").strip()
    return text[:BRAND_NAME_MAX_LENGTH].strip()


@frappe.whitelist()
@agent_manager_only
def get_welcome_ticket() -> str | None:
    """Name of the seeded welcome ticket, if it still exists."""
    return frappe.db.get_value("HD Ticket", {"subject": "Welcome to Helpdesk"}, "name")


@frappe.whitelist()
def get_first_ticket(ticket: str | None = None):
    """Get first ticket created except the default ticket"""
    # If a cached ticket ID was passed, verify it still exists
    if ticket and frappe.db.exists("HD Ticket", ticket):
        return ticket

    result = frappe.get_all(
        "HD Ticket",
        filters={
            "subject": ["!=", "Welcome to Helpdesk"],
            "owner": ["=", frappe.session.user],
        },
        fields=["name"],
        order_by="creation asc",
        limit=1,
    )
    return result[0].name if result else None


@frappe.whitelist()
def get_general_category_id():
    """Get the id of the general category"""
    category = frappe.get_all(
        "HD Article Category",
        filters={"category_name": ["=", "General"]},
        pluck="name",
        order_by="creation asc",
        limit=1,
    )
    return category[0] if category else None
