# Copyright (c) 2022, Frappe Technologies and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.client import get as client_get
from frappe.tests.utils import FrappeTestCase

from helpdesk.consts import DEFAULT_TICKET_TEMPLATE
from helpdesk.helpdesk.doctype.hd_ticket.api import get_ticket_customizations
from helpdesk.helpdesk.doctype.hd_ticket_template.api import (
    get_fields,
    get_fields_meta,
    get_one,
)
from helpdesk.helpdesk.doctype.hd_ticket_template.hd_ticket_template import (
    allowed_url_method,
)
from helpdesk.test_utils import (
    delete_doc_as,
    insert_as,
    make_agent,
    make_agent_manager,
    set_value_as,
    share_doc_as,
    user_roles,
)

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


OPTION_METHODS_HOOK = "helpdesk_ticket_option_methods"
LISTED_METHOD = "helpdesk.api.general.get_translations"
RIGHTS_TEMPLATE = "Test Template Rights"


@contextmanager
def option_methods(*methods):
    """Within the block, the helpdesk_ticket_option_methods hook lists exactly
    `methods`; every other hook is read as usual."""
    get_hooks = frappe.get_hooks

    def patched(hook=None, *args, **kwargs):
        if hook == OPTION_METHODS_HOOK:
            return list(methods)
        return get_hooks(hook, *args, **kwargs)

    with patch("frappe.get_hooks", side_effect=patched):
        yield


def save_url_method(template: str, url_method: str):
    """Set the first row's URL/Method as Administrator through a full save."""
    doc = frappe.get_doc("HD Ticket Template", template)
    doc.fields[0].url_method = url_method
    doc.save()


class TestHDTicketTemplateRights(FrappeTestCase):
    """Only Agent Managers and System Managers create, change or delete ticket
    templates, and only System Managers share them. A field's URL/Method must
    be a method listed in the helpdesk_ticket_option_methods hook."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = make_agent("template_rights_agent@example.com")
        self.manager = make_agent_manager("template_rights_manager@example.com")
        if not frappe.db.exists("HD Ticket Template", DEFAULT_TICKET_TEMPLATE):
            frappe.get_doc(
                {
                    "doctype": "HD Ticket Template",
                    "template_name": DEFAULT_TICKET_TEMPLATE,
                }
            ).insert()
        frappe.get_doc(
            {
                "doctype": "HD Ticket Template",
                "template_name": RIGHTS_TEMPLATE,
                "fields": [{"fieldname": CHECK_FIELD}],
            }
        ).insert(ignore_if_duplicate=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        frappe.set_user("Administrator")
        for name in frappe.get_all(
            "HD Ticket Template",
            filters={"name": ["like", "Test Template Rights%"]},
            pluck="name",
        ):
            frappe.delete_doc(
                "HD Ticket Template", name, force=True, ignore_permissions=True
            )

    def stored_url_method(self, template: str = RIGHTS_TEMPLATE):
        return frappe.db.get_value(
            "HD Ticket Template Field", {"parent": template}, "url_method"
        )

    def test_agent_cannot_create_template(self):
        with self.assertRaises(frappe.PermissionError):
            insert_as(
                self.agent,
                {
                    "doctype": "HD Ticket Template",
                    "template_name": "Test Template Rights New",
                },
            )

        self.assertFalse(
            frappe.db.exists("HD Ticket Template", "Test Template Rights New")
        )

    def test_agent_cannot_change_templates(self):
        for template in (DEFAULT_TICKET_TEMPLATE, RIGHTS_TEMPLATE):
            with self.subTest(template=template):
                before = frappe.db.get_value(
                    "HD Ticket Template", template, "description_template"
                )
                with self.assertRaises(frappe.PermissionError):
                    set_value_as(
                        self.agent,
                        "HD Ticket Template",
                        template,
                        {"description_template": "<p>changed</p>"},
                    )
                self.assertEqual(
                    frappe.db.get_value(
                        "HD Ticket Template", template, "description_template"
                    ),
                    before,
                )

    def test_agent_cannot_delete_template(self):
        frappe.db.savepoint("template_rights_delete")
        try:
            with self.assertRaises(frappe.PermissionError):
                delete_doc_as(self.agent, "HD Ticket Template", RIGHTS_TEMPLATE)
        finally:
            frappe.db.rollback(save_point="template_rights_delete")

        self.assertTrue(frappe.db.exists("HD Ticket Template", RIGHTS_TEMPLATE))

    def test_only_system_managers_share_templates(self):
        for user in (self.agent, self.manager):
            with self.subTest(user=user):
                with self.assertRaises(frappe.PermissionError):
                    share_doc_as(
                        user, "HD Ticket Template", RIGHTS_TEMPLATE, user, write=1
                    )

        self.assertFalse(
            frappe.db.exists(
                "DocShare",
                {
                    "share_doctype": "HD Ticket Template",
                    "share_name": RIGHTS_TEMPLATE,
                },
            )
        )

    def test_agent_can_still_read_templates(self):
        frappe.set_user(self.agent)
        try:
            doc = client_get("HD Ticket Template", RIGHTS_TEMPLATE)
            self.assertEqual(doc["name"], RIGHTS_TEMPLATE)
            fields = get_one(RIGHTS_TEMPLATE)["fields"]
            self.assertEqual([f.fieldname for f in fields], [CHECK_FIELD])
        finally:
            frappe.set_user("Administrator")

    def test_agent_manager_can_change_templates(self):
        self.assertNotIn("System Manager", user_roles(self.manager))

        set_value_as(
            self.manager,
            "HD Ticket Template",
            RIGHTS_TEMPLATE,
            {"description_template": "<p>managed</p>"},
        )

        self.assertEqual(
            frappe.db.get_value(
                "HD Ticket Template", RIGHTS_TEMPLATE, "description_template"
            ),
            "<p>managed</p>",
        )

    def test_template_changes_are_tracked(self):
        def versions():
            return frappe.db.count(
                "Version",
                {"ref_doctype": "HD Ticket Template", "docname": RIGHTS_TEMPLATE},
            )

        before = versions()
        doc = frappe.get_doc("HD Ticket Template", RIGHTS_TEMPLATE)
        doc.description_template = "<p>tracked</p>"
        doc.save(ignore_version=False)

        self.assertEqual(versions(), before + 1)

    def test_unlisted_url_methods_are_refused(self):
        values = (
            "logout",
            LISTED_METHOD,  # a GET-only method, but not listed
            "frappe.auth.get_logged_user",
            "/api/method/x",
            "https://example.com/x",
            "//x",
        )
        with option_methods():
            for value in values:
                with self.subTest(value=value):
                    self.assertIsNone(allowed_url_method(value))
                    with self.assertRaises(frappe.ValidationError):
                        save_url_method(RIGHTS_TEMPLATE, value)
                    self.assertFalse(self.stored_url_method())

    def test_shipped_hook_lists_no_method(self):
        self.assertEqual(frappe.get_hooks(OPTION_METHODS_HOOK, app_name="helpdesk"), [])

    def test_only_an_exactly_listed_method_is_allowed(self):
        near_misses = (
            LISTED_METHOD.upper(),
            "helpdesk.api.general.Get_translations",
            f" {LISTED_METHOD}",
            f"{LISTED_METHOD} ",
            f"{LISTED_METHOD}?a=1",
            f"/api/method/{LISTED_METHOD}",
            f"{LISTED_METHOD}.x",
            "helpdesk.api.general",
        )
        with option_methods(LISTED_METHOD):
            for value in near_misses:
                with self.subTest(value=value):
                    self.assertIsNone(allowed_url_method(value))
                    with self.assertRaises(frappe.ValidationError):
                        save_url_method(RIGHTS_TEMPLATE, value)

            self.assertEqual(allowed_url_method(LISTED_METHOD), LISTED_METHOD)
            save_url_method(RIGHTS_TEMPLATE, LISTED_METHOD)
            self.assertEqual(self.stored_url_method(), LISTED_METHOD)
            fields = get_fields(RIGHTS_TEMPLATE, "DocField")
            self.assertEqual(fields[0].url_method, LISTED_METHOD)

    def test_helper_never_raises(self):
        for value in (None, "", 1, ["logout"], {"a": 1}):
            with self.subTest(value=value):
                self.assertIsNone(allowed_url_method(value))
        with patch("frappe.get_hooks", side_effect=RuntimeError):
            self.assertIsNone(allowed_url_method(LISTED_METHOD))

    def test_stored_unlisted_url_method_is_not_served(self):
        row = frappe.get_doc(
            {
                "doctype": "HD Ticket Template Field",
                "parent": DEFAULT_TICKET_TEMPLATE,
                "parenttype": "HD Ticket Template",
                "parentfield": "fields",
                "fieldname": CHECK_FIELD,
                "idx": 999,
            }
        )
        row.db_insert()
        self.addCleanup(frappe.db.delete, "HD Ticket Template Field", row.name)
        rows = frappe.get_all(
            "HD Ticket Template Field",
            filters={"parent": ["in", [RIGHTS_TEMPLATE, DEFAULT_TICKET_TEMPLATE]]},
            pluck="name",
        )

        with option_methods():
            for value in ("logout", "/api/method/logout?a=1", "https://example.com/x"):
                with self.subTest(value=value):
                    for name in rows:
                        frappe.db.set_value(
                            "HD Ticket Template Field", name, "url_method", value
                        )

                    frappe.set_user(self.agent)
                    try:
                        customizations = get_ticket_customizations()["custom_fields"]
                        one = get_one(RIGHTS_TEMPLATE)["fields"]
                        default = get_one(DEFAULT_TICKET_TEMPLATE)["fields"]
                    finally:
                        frappe.set_user("Administrator")

                    served = customizations + one + default
                    self.assertTrue(any(f.fieldname == CHECK_FIELD for f in served))
                    self.assertEqual([f.url_method for f in served if f.url_method], [])
                    self.assertEqual(self.stored_url_method(), value)
