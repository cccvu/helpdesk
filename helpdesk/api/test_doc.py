import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.api import doc
from helpdesk.api.knowledge_base import create_category
from helpdesk.api.onboarding import get_general_category_id
from helpdesk.test_utils import create_user, make_agent, make_ticket
from helpdesk.utils import contact_default_rows

AGENT = "list-group-agent@example.com"
NO_ROLE_USER = "list-group-user@example.com"

CATEGORY_VIEW = {"view_type": "group_by", "group_by_field": "category"}


class TestListGroupBy(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.original_user = frappe.session.user
        frappe.set_user("Administrator")
        make_agent(AGENT)
        create_user(NO_ROLE_USER)

        cls.general = get_general_category_id()
        if not cls.general:
            cls.general = (
                frappe.new_doc("HD Article Category", category_name="General")
                .insert()
                .name
            )
        cls.general_article = (
            frappe.new_doc(
                "HD Article", title="Grouped list article", category=cls.general
            )
            .insert()
            .name
        )
        accounts = create_category("Accounts")
        cls.accounts = accounts["category"]
        cls.accounts_article = accounts["article"]
        frappe.db.set_value(
            "HD Article Category", cls.accounts, "description", "Billing questions"
        )

    def setUp(self):
        frappe.set_user(AGENT)

    def tearDown(self):
        frappe.set_user(self.original_user or "Administrator")

    def get_article_groups(
        self, view=CATEGORY_VIEW, order_by="modified desc", articles=None
    ):
        articles = articles or [self.general_article, self.accounts_article]
        result = doc.get_list_data(
            "HD Article",
            filters=[["name", "in", articles]],
            order_by=order_by,
            view=view,
        )
        return [
            (option["label"], option["value"])
            for option in result["group_by_field"]["options"]
        ]

    def test_link_groups_are_labelled_with_titles(self):
        self.assertEqual(
            self.get_article_groups(),
            [("General", self.general), ("Accounts", self.accounts)],
        )

    def test_general_group_comes_first_in_either_order(self):
        for order_by in ("category asc", "category desc"):
            with self.subTest(order_by=order_by):
                self.assertEqual(
                    self.get_article_groups(order_by=order_by)[0],
                    ("General", self.general),
                )

    def test_view_label_keys_do_not_change_labels(self):
        view = {
            **CATEGORY_VIEW,
            "label_doc": "HD Article Category",
            "label_field": "description",
        }
        self.assertEqual(
            self.get_article_groups(view=view, articles=[self.accounts_article]),
            [("Accounts", self.accounts)],
        )

    def test_data_group_is_labelled_with_its_value(self):
        frappe.set_user("Administrator")
        ticket = make_ticket(subject="Grouped list subject")
        frappe.set_user(AGENT)

        result = doc.get_list_data(
            "HD Ticket",
            filters=[["name", "=", ticket.name]],
            view={
                "view_type": "group_by",
                "group_by_field": "subject",
                "label_doc": "HD Article Category",
                "label_field": "description",
            },
        )

        self.assertEqual(
            result["group_by_field"]["options"],
            [{"label": "Grouped list subject", "value": "Grouped list subject"}],
        )

    def test_link_title_field_follows_read_permission(self):
        self.assertEqual(
            doc.get_link_title_field("HD Article Category"), "category_name"
        )

        frappe.set_user(NO_ROLE_USER)
        self.assertIsNone(doc.get_link_title_field("HD Article Category"))

    def test_link_titles_include_only_readable_documents(self):
        frappe.set_user("Administrator")
        frappe.share.add("HD Article Category", self.accounts, NO_ROLE_USER, read=1)
        frappe.set_user(NO_ROLE_USER)

        titles = doc.get_link_titles(
            "HD Article Category", "category_name", {self.general, self.accounts}
        )

        self.assertEqual(titles, {self.accounts: "Accounts"})

    def test_link_title_field_is_none_without_a_listable_doctype(self):
        frappe.clear_messages()
        for doctype in (None, "", "No Such Doctype", "HD Settings"):
            with self.subTest(doctype=doctype):
                self.assertIsNone(doc.get_link_title_field(doctype))
        self.assertEqual(frappe.local.message_log, [])

    def test_default_contact_rows_stay_unchanged(self):
        expected = list(contact_default_rows)
        view = {"view_type": "group_by", "group_by_field": "status"}

        doc.get_list_data("Contact", is_default=True, view=view)
        with self.assertRaises(frappe.DoesNotExistError):
            doc.get_list_data(
                "Contact",
                is_default=True,
                view={"view_type": "group_by", "group_by_field": "no_such_table.name"},
            )
        doc.get_list_data("Contact", is_default=True)

        self.assertEqual(contact_default_rows, expected)
