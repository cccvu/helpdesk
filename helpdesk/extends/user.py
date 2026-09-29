import frappe


def sync_agent_name(doc, method=None):
    """Keep an agent's HD Agent name equal to their full name.

    Pickers, mentions and the agent list show HD Agent.agent_name, so a rename on
    the Profile page or in /app/user must reach it. HD Agent's own before_save
    handles the other direction.
    """
    agent_name = frappe.db.get_value("HD Agent", doc.name, "agent_name")
    if agent_name is not None and agent_name != doc.full_name:
        frappe.db.set_value(
            "HD Agent", doc.name, "agent_name", doc.full_name, update_modified=False
        )
