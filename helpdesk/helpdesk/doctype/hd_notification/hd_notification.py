import frappe
from frappe.model.document import Document

from helpdesk.file_access import disarm_embeds


class HDNotification(Document):
    def format_message(self):
        user_from = self.get_from()
        if self.notification_type == "Mention":
            if self.reference_comment:
                return f"{user_from} mentioned you in a comment"
            return f"{user_from} mentioned you"
        return ""

    def get_from(self):
        return frappe.db.get_value(
            "User", {"name": self.user_from}, fieldname="full_name"
        )

    def get_button_label(self):
        if self.reference_comment:
            return "See Comment"
        return "Visit"

    def get_url(self):
        res = "/helpdesk"
        if self.reference_ticket:
            res += "/tickets/" + str(self.reference_ticket)
        if self.reference_comment:
            res += "#" + self.reference_comment
        return frappe.utils.get_url(res)

    def parse_html(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(self.message, "html.parser")
        if soup.find("img"):
            img = soup.find("img")
            img["src"] = ("").join([frappe.utils.get_url(), img["src"]])
        # the comment goes into the mail, which embeds any embed="..." path
        return disarm_embeds(str(soup))

    def get_args(self):
        if self.notification_type == "Mention":
            return {
                # the title names the user, whose name they set themselves
                "title": disarm_embeds(self.format_message()),
                "button_label": self.get_button_label(),
                "callback_url": self.get_url(),
                "comment": self.parse_html(),
            }

    def after_insert(self):
        if self.notification_type == "Mention":
            skip_email_workflow = frappe.db.get_single_value(
                "HD Settings", "skip_email_workflow"
            )

            if skip_email_workflow:
                return

            frappe.sendmail(
                recipients=self.user_to,
                subject="New notification",
                message=disarm_embeds(self.format_message()),
                template="notification",
                args=self.get_args(),
            )


# Notifications are made by server code (mentions, assignments, reactions),
# which inserts them with ignore_permissions. The Agent DocPerm row keeps
# create so the previous release's mentions code, which inserts as the agent,
# works during a rolling deploy or after a rollback; this hook refuses it.
SERVER_ONLY = ("create", "write", "delete", "share", "submit", "cancel", "amend")


def has_permission(doc, ptype=None, user=None):
    """A user reads only the notifications sent to them, and only server code
    creates or changes notifications. System Managers are unrestricted.
    Judged by the stored recipient when the notification is stored."""
    user = user or frappe.session.user
    if "System Manager" in frappe.get_roles(user):
        return True
    if ptype in SERVER_ONLY:
        return False
    stored = (
        frappe.db.get_value("HD Notification", doc.name, "user_to", as_dict=True)
        if doc.name
        else None
    )
    user_to = stored.user_to if stored else doc.user_to
    return (user_to or "").lower() == user.lower()


def permission_query(user=None):
    """List only the user's own notifications, except for System Managers.
    Also called for Administrator, who has every role."""
    user = user or frappe.session.user
    if "System Manager" in frappe.get_roles(user):
        return ""
    return f"`tabHD Notification`.user_to = {frappe.db.escape(user)}"
