# Copyright (c) 2022, Frappe Technologies and contributors
# For license information, please see license.txt

import json
import unicodedata

import frappe
from frappe import _
from frappe.exceptions import DoesNotExistError
from frappe.model.document import Document
from frappe.model.naming import append_number_if_name_exists

from helpdesk.utils import agent_only, capture_event

ASSIGNMENT_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


# Characters a team name can't hold: they would need escaping in the rule
# conditions' consumers (the JSON copies, the Helpdesk condition editor, HTML).
FORBIDDEN_TEAM_NAME_CHARACTERS = frozenset('"\\<>')


class HDTeam(Document):
    def validate(self):
        if self.is_new():
            self.validate_team_name(self.name)
        else:
            self.validate_assignment_rule_link()

    def validate_assignment_rule_link(self):
        """Only System Managers point a team at another Assignment Rule: the
        team's hooks rewrite and delete its rule with ignore_permissions.
        Helpdesk links the rule it creates with db_set, which skips this."""
        if "System Manager" in frappe.get_roles():
            return
        before = self.get_doc_before_save()
        previous = (
            before.assignment_rule
            if before
            else frappe.db.get_value("HD Team", self.name, "assignment_rule")
        )
        if (self.assignment_rule or None) != (previous or None):
            frappe.throw(
                _("Only a System Manager can change a team's assignment rule"),
                frappe.PermissionError,
            )

    def before_rename(self, olddn, newdn, merge=False):
        self.validate_team_name(newdn)

    def after_insert(self):
        self.create_assignment_rule()
        self.capture_team_creation_event()

    def on_update(self):
        if not self.assignment_rule:
            return
        ar = frappe.get_doc("Assignment Rule", self.assignment_rule)
        self.sync_users(ar)
        # Follow the team only when it is enabled or disabled, so a member
        # change doesn't re-enable a rule an admin turned off.
        if self.has_value_changed("disabled"):
            ar.disabled = bool(self.disabled)
        ar.save(ignore_permissions=True)

    def on_trash(self):
        if not self.assignment_rule:
            return
        # A rule for other documents is a System Manager's: the team leaves it.
        document_type = frappe.db.get_value(
            "Assignment Rule", self.assignment_rule, "document_type"
        )
        if document_type and document_type != "HD Ticket":
            return
        try:
            frappe.delete_doc(
                "Assignment Rule",
                self.assignment_rule,
                ignore_permissions=True,
                force=True,
                ignore_on_trash=True,
            )
        except DoesNotExistError:
            frappe.log_error(
                title="Assignment Rule not found",
                message=f"Assignment Rule {self.assignment_rule} not found",
            )

    def after_rename(self, olddn, newdn, merge=False):
        if not self.assignment_rule:
            self.create_assignment_rule()
        ar = frappe.get_doc("Assignment Rule", self.assignment_rule)
        ar.assign_condition, ar.assign_condition_json = self.assign_condition(newdn)
        ar.unassign_condition, ar.unassign_condition_json = self.unassign_condition(
            newdn
        )
        ar.save(ignore_permissions=True)

    def create_assignment_rule(self):
        ar = frappe.new_doc("Assignment Rule")
        ar.name = append_number_if_name_exists(
            "Assignment Rule", f"{self.name} - Support Rotation"
        )
        ar.document_type = "HD Ticket"
        ar.assign_condition, ar.assign_condition_json = self.assign_condition(self.name)
        ar.unassign_condition, ar.unassign_condition_json = self.unassign_condition(
            self.name
        )
        ar.priority = 1
        ar.disabled = bool(self.disabled)

        for day in ASSIGNMENT_DAYS:
            ar.append("assignment_days", {"doctype": "Assignment Rule Day", "day": day})

        self.sync_users(ar)
        ar.save(ignore_permissions=True)
        self.db_set("assignment_rule", ar.name, update_modified=False)

    def sync_users(self, ar):
        members = [u.user for u in self.users if u.user]

        if ar.get("rule") == "Weighted Distribution":
            existing_weights = {
                row.user: row.weight for row in ar.weighted_users if row.user
            }
            ar.weighted_users = []
            for user in members:
                ar.append(
                    "weighted_users",
                    {"user": user, "weight": existing_weights.get(user, 1)},
                )
        else:
            ar.users = []
            for user in members:
                ar.append("users", {"user": user})

    def capture_team_creation_event(self):
        if self.name not in ["Product Experts", "Billing"]:
            capture_event("team_created")

    @staticmethod
    def validate_team_name(name: str) -> None:
        """Refuse a team name that can't be quoted safely everywhere it goes.

        Apostrophes, curly quotes and accented letters are allowed. The message
        doesn't repeat the name, which is shown as HTML.
        """
        name = str(name)
        if (
            any(
                ch in FORBIDDEN_TEAM_NAME_CHARACTERS or unicodedata.category(ch) == "Cc"
                for ch in name
            )
            or unicodedata.normalize("NFKC", name) != name
        ):
            frappe.throw(
                _(
                    "A team name can't contain double quotes, backslashes, angle brackets, control characters or characters that Unicode normalization changes, such as full-width letters."
                ),
                frappe.InvalidNameError,
                title=_("Invalid Team Name"),
            )

    # frappe.safe_eval NFKC-normalizes the code it runs, so repr() isn't enough:
    # a full-width apostrophe (U+FF07) in a repr()'d name would become a quote
    # there. ascii() escapes every non-ASCII character, so its literal is
    # NFKC-stable, and for plain ASCII names it equals the old output.
    @staticmethod
    def assign_condition(team_name: str) -> tuple[str, str]:
        condition = f"status == 'Open' and agent_group == {ascii(team_name)}"
        condition_json = json.dumps(
            [["status", "==", "Open"], "and", ["agent_group", "==", team_name]],
            separators=(",", ":"),
        )
        return condition, condition_json

    @staticmethod
    def unassign_condition(team_name: str) -> tuple[str, str]:
        condition = f"agent_group != {ascii(team_name)}"
        condition_json = json.dumps(
            [["agent_group", "!=", team_name]], separators=(",", ":")
        )
        return condition, condition_json


@frappe.whitelist()
@agent_only
def get_team_members(team: str):
    return frappe.get_all("HD Team Member", filters={"parent": team}, pluck="user")
