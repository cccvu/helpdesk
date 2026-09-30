# Copyright (c) 2022, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.helpdesk.doctype.hd_ticket_template.api import get_fields_meta

TEMPLATE = "Test Check Defaults"
CHECK_FIELD = "via_customer_portal"  # a standard Check whose default is 0


def template_field(fieldname: str) -> dict:
    fields = get_fields_meta(TEMPLATE)
    return next(f for f in fields if f.fieldname == fieldname)


class TestHDTicketTemplate(FrappeTestCase):
    def setUp(self):
        frappe.get_doc(
            {
                "doctype": "HD Ticket Template",
                "template_name": TEMPLATE,
                "fields": [{"fieldname": CHECK_FIELD}],
            }
        ).insert(ignore_if_duplicate=True)

    def test_fields_carry_their_default(self):
        self.assertEqual(template_field(CHECK_FIELD).default, "0")

    def test_customized_default_overrides_the_standard_one(self):
        frappe.make_property_setter(
            {
                "doctype": "HD Ticket",
                "fieldname": CHECK_FIELD,
                "property": "default",
                "value": "1",
            }
        )
        # rollback is per test class and leaves the meta cache behind, so
        # remove the customization now or later tests inherit the default
        self.addCleanup(
            frappe.delete_doc,
            "Property Setter",
            f"HD Ticket-{CHECK_FIELD}-default",
            force=True,
        )

        self.assertEqual(template_field(CHECK_FIELD).default, "1")
