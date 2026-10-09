# Copyright (c) 2022, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from helpdesk.consts import DEFAULT_TICKET_TEMPLATE
from helpdesk.utils import capture_event


def allowed_url_method(value) -> str | None:
    """Return `value` if it is exactly one of the methods listed in the
    `helpdesk_ticket_option_methods` hook, else None. A field's URL/Method is
    called from every viewer's browser, so only methods an app has declared
    as option providers are allowed. Never imports the method and never
    raises."""
    try:
        if not isinstance(value, str) or not value:
            return None
        if value in frappe.get_hooks("helpdesk_ticket_option_methods"):
            return value
    except Exception:
        pass
    return None


class HDTicketTemplate(Document):
    def validate(self):
        self.verify_field_exists()
        self.validate_unallowed_fields()
        self.validate_url_methods()

    def validate_url_methods(self):
        for f in self.fields:
            if f.url_method and not allowed_url_method(f.url_method):
                text = _(
                    "Row {0}: URL/Method of field `{1}` must be a method listed in the helpdesk_ticket_option_methods hook"
                ).format(f.idx, f.fieldname)
                frappe.throw(text, frappe.ValidationError)

    def verify_field_exists(self):
        for f in self.fields:
            if not f.fieldname:
                continue
            exists = self.docfield_exists(f.fieldname) or self.custom_field_exists(
                f.fieldname
            )
            if not exists:
                text = _("Field `{0}` does not exist in Ticket").format(f.fieldname)
                frappe.throw(text)

    def docfield_exists(self, fieldname: str):
        return frappe.db.exists(
            {
                "doctype": "DocField",
                "fieldname": fieldname,
                "parent": "HD Ticket",
            }
        )

    def validate_unallowed_fields(self):
        unallowed_fields = ["status", "agreement_status"]
        for f in self.fields:
            if f.fieldname in unallowed_fields:
                text = _("Field `{0}` is not allowed in Ticket Template").format(
                    f.fieldname
                )
                frappe.throw(text)

    def custom_field_exists(self, fieldname: str):
        return frappe.db.exists(
            {
                "doctype": "Custom Field",
                "fieldname": fieldname,
                "dt": "HD Ticket",
            }
        )

    def on_update(self):
        capture_event("ticket_template_updated")

    def on_trash(self):
        self.prevent_default_delete()

    def prevent_default_delete(self):
        if self.name == DEFAULT_TICKET_TEMPLATE:
            text = _("Default template can not be deleted")
            frappe.throw(text, frappe.PermissionError)
