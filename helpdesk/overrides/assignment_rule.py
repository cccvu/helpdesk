import frappe
from frappe import _
from frappe.automation.doctype.assignment_rule.assignment_rule import AssignmentRule
from frappe.desk.form import assign_to
from frappe.utils import escape_html

from helpdesk.data_template import render_data_template


def get_agents_by_category(category: str) -> set[str]:
    """User ids of HD Agents whose current status falls under the given category."""
    statuses = frappe.get_all(
        "HD Agent Status",
        filters={"category": category},
        pluck="name",
    )
    if not statuses:
        return set()
    return set(
        frappe.get_all(
            "HD Agent",
            filters={"availability": ["in", statuses]},
            pluck="user",
        )
    )


class HelpdeskAssignmentRule(AssignmentRule):
    def do_assignment(self, doc):
        """Frappe's do_assignment, with the description rendered as data
        (helpdesk.data_template) rather than with frappe.render_template.

        A copy of Frappe v15's method that differs only in the description:
        re-sync it whenever Frappe's method changes.
        """
        # clear existing assignment, to reassign
        assign_to.clear(doc.get("doctype"), doc.get("name"), ignore_permissions=True)

        user = self.get_user(doc)

        if not user or not frappe.db.exists("User", user):
            return False

        assign_to._add(
            dict(
                assign_to=[user],
                doctype=doc.get("doctype"),
                name=doc.get("name"),
                description=render_data_template(
                    self.description,
                    doc,
                    fallback=_("Automatic Assignment"),
                    title=_("Assignment description could not be rendered"),
                    reference_doctype=doc.get("doctype"),
                    reference_name=doc.get("name"),
                ),
                assignment_rule=self.name,
                notify=True,
                date=doc.get(self.due_date_based_on)
                if self.due_date_based_on
                else None,
            ),
            ignore_permissions=True,
        )

        # set for reference in round robin
        self.db_set("last_user", user)
        return True

    def safe_eval(self, fieldname, doc):
        """Frappe's safe_eval, but the error is shown as text: a condition's
        error message can carry markup, and msgprint renders HTML."""
        try:
            if self.get(fieldname):
                return frappe.safe_eval(self.get(fieldname), None, doc)
        except Exception as e:
            # when assignment fails, don't block the document as it may be
            # a part of the email pulling
            frappe.msgprint(
                frappe._("Auto assignment failed: {0}").format(escape_html(str(e))),
                indicator="orange",
            )

        return False

    def get_user(self, doc):
        """
        Override get_user method from framework.
        always Active agents are preferred; fall back to Away if no Active is available;
        fall back to the full pool (including Unavailable) only if no one else
        is available, so the ticket is never left unassigned.
        """

        away = get_agents_by_category("Away")
        unavailable = get_agents_by_category("Unavailable")
        if not away and not unavailable:
            return super().get_user(doc)

        # "Based on Field" assigns through the document field, so the
        # availability filter does not apply.
        if self.rule == "Weighted Distribution":
            user_pool_fieldname = "weighted_users"
        elif self.rule in ("Round Robin", "Load Balancing"):
            user_pool_fieldname = "users"
        else:
            return super().get_user(doc)

        original_pool = getattr(self, user_pool_fieldname)
        active_only = [
            u for u in original_pool if u.user not in away and u.user not in unavailable
        ]
        not_unavailable = [u for u in original_pool if u.user not in unavailable]

        # Tier: Active → Away → full pool (Unavailable as last resort)
        if active_only:
            preferred_pool = active_only
        elif not_unavailable:
            preferred_pool = not_unavailable
        else:
            preferred_pool = original_pool

        setattr(self, user_pool_fieldname, preferred_pool)
        try:
            return super().get_user(doc)
        finally:
            setattr(self, user_pool_fieldname, original_pool)
