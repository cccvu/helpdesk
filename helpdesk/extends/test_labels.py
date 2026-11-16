import json

import frappe
from frappe.desk.doctype.kanban_board import kanban_board
from frappe.desk.doctype.tag import tag as frappe_tag
from frappe.tests.utils import FrappeTestCase

from helpdesk.api import tags as helpdesk_tags
from helpdesk.extends.labels import is_safe_label
from helpdesk.test_utils import (
    insert_as,
    make_agent,
    make_ticket,
    rename_doc_as,
    set_value_as,
)

AGENT = "labels.agent@example.com"

SAFE = ("R&D", "Dean's office", "Q & A", "a=b", "C++", "50%", "naïve", "a;b")
UNSAFE = (
    'x"y',
    "<b",
    "a>b",
    "&lt;img src=x onerror=alert(1)&gt;",
    "&quot;",
    "&#34;",
    "&#x22;",
    "&QUOT;",
    "&lt",
    "&amp",
    "x &amp; y",
    '   "quoted after spaces',
)
# What the write paths are refused with: a quote, a character reference
# (named, numeric, upper case, legacy without a semicolon) and markup.
BAD_TAGS = ('x" onmouseover="alert(1)', "&quot;x", "&#34;x", "&QUOT;x", "&lt", "<b>x")
# Frappe's own validate_name already refuses "<" and ">" in a new name
# (NameError), before the rule; any of these refusals will do.
REFUSED = (frappe.ValidationError, frappe.NameError)


def as_user(user, method, *args, **kwargs):
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        return method(*args, **kwargs)
    finally:
        frappe.set_user(previous)


class TestIsSafeLabel(FrappeTestCase):
    def test_accepted(self):
        for value in SAFE + ("a,b", "", None):
            with self.subTest(value=value):
                self.assertTrue(is_safe_label(value))

    def test_refused(self):
        for value in UNSAFE:
            with self.subTest(value=value):
                self.assertFalse(is_safe_label(value))
                self.assertFalse(is_safe_label(value, allow_comma=False))

    def test_commas_refused_only_when_asked(self):
        self.assertTrue(is_safe_label("a,b"))
        self.assertFalse(is_safe_label("a,b", allow_comma=False))
        self.assertTrue(is_safe_label("R&D", allow_comma=False))


class TestTagLabels(FrappeTestCase):
    """Tags /app writes into HTML attributes: refused on every write path a
    plain agent has (issue 320)."""

    def setUp(self):
        make_agent(AGENT, "Labels Agent")
        self.ticket = make_ticket(subject="labels test", description="<p>x</p>")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def user_tags(self):
        return frappe.db.get_value("HD Ticket", self.ticket.name, "_user_tags")

    def assertRefused(self, method, *args, **kwargs):
        """method, as the agent, fails, and leaves nothing behind once the
        request's transaction is rolled back (as Frappe does on an error)."""
        before = self.user_tags()
        frappe.db.savepoint("label_test")
        with self.assertRaises(REFUSED):
            as_user(AGENT, method, *args, **kwargs)
        frappe.db.rollback(save_point="label_test")
        self.assertEqual(self.user_tags(), before)

    def test_add_tag_refuses_a_bad_new_tag(self):
        for bad in BAD_TAGS:
            with self.subTest(tag=bad):
                self.assertRefused(
                    frappe_tag.add_tag, bad, "HD Ticket", self.ticket.name
                )
                self.assertFalse(frappe.db.exists("Tag", bad))

    def test_add_tags_refuses_a_bad_tag(self):
        self.assertRefused(
            frappe_tag.add_tags,
            json.dumps(["fine", 'x"y']),
            "HD Ticket",
            json.dumps([self.ticket.name]),
        )

    def test_update_tags_refuses_a_bad_tag(self):
        for bad in BAD_TAGS:
            with self.subTest(tag=bad):
                self.assertRefused(
                    helpdesk_tags.update_tags,
                    "HD Ticket",
                    self.ticket.name,
                    added=[{"name": bad}],
                )

    def test_tag_insert_refused(self):
        for bad in BAD_TAGS + ("a,b",):
            with self.subTest(tag=bad), self.assertRaises(REFUSED):
                insert_as(AGENT, {"doctype": "Tag", "name": bad})
            with self.subTest(tag=bad), self.assertRaises(REFUSED):
                as_user(
                    AGENT,
                    lambda bad=bad: frappe.get_doc(
                        {"doctype": "Tag", "name": bad}
                    ).insert(),
                )

    def test_tag_rename_refused(self):
        frappe.get_doc({"doctype": "Tag", "name": "labels-rename"}).insert()
        with self.assertRaises(frappe.ValidationError):
            rename_doc_as(AGENT, "Tag", "labels-rename", 'x" onmouseover="1')
        with self.assertRaises(frappe.ValidationError):
            rename_doc_as(AGENT, "Tag", "labels-rename", "&lt;img&gt;")
        self.assertTrue(frappe.db.exists("Tag", "labels-rename"))
        rename_doc_as(AGENT, "Tag", "labels-rename", "labels R&D")
        self.assertTrue(frappe.db.exists("Tag", "labels R&D"))

    def test_a_legacy_bad_tag_cant_be_attached(self):
        # A Tag stored before this rule, past every hook
        legacy = 'legacy" onmouseover="alert(1)'
        frappe.get_doc({"doctype": "Tag", "name": legacy}).db_insert()
        self.assertRefused(frappe_tag.add_tag, legacy, "HD Ticket", self.ticket.name)
        self.assertRefused(
            helpdesk_tags.update_tags,
            "HD Ticket",
            self.ticket.name,
            added=[{"name": legacy}],
        )
        self.assertFalse(
            frappe.db.exists(
                "Tag Link", {"document_name": self.ticket.name, "tag": legacy}
            )
        )
        # Still editable as a Tag: only a new name is checked
        tag = frappe.get_doc("Tag", legacy)
        tag.description = "kept"
        tag.save()

    def test_legit_tags_are_kept_as_typed(self):
        for label in ("R&D", "Dean's office", "Q & A", "a=b"):
            as_user(AGENT, frappe_tag.add_tag, label, "HD Ticket", self.ticket.name)
        as_user(
            AGENT,
            helpdesk_tags.update_tags,
            "HD Ticket",
            self.ticket.name,
            added=[{"name": "C++"}],
        )
        self.assertEqual(
            self.user_tags().split(",")[1:],
            ["R&D", "Dean's office", "Q & A", "a=b", "C++"],
        )

    def test_communication_user_tags(self):
        comm = frappe.get_doc(
            {
                "doctype": "Communication",
                "communication_type": "Comment",
                "comment_type": "Comment",
                "subject": "labels test",
                "content": "x",
            }
        ).insert(ignore_permissions=True)
        comm.reload()
        comm._user_tags = ',fine,x"y'
        with self.assertRaises(frappe.ValidationError):
            comm.save(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Communication",
                    "communication_type": "Comment",
                    "comment_type": "Comment",
                    "subject": "labels test",
                    "content": "x",
                    "_user_tags": ",&lt;img&gt;",
                }
            ).insert(ignore_permissions=True)
        # A legacy value doesn't block a save; a new bad piece still does
        frappe.db.set_value(
            "Communication", comm.name, "_user_tags", ',legacy"x', update_modified=False
        )
        comm.reload()
        comm.subject = "labels test 2"
        comm.save(ignore_permissions=True)
        comm._user_tags = ',legacy"x,R&D'
        comm.save(ignore_permissions=True)
        comm._user_tags = ',legacy"x,R&D,&quot;'
        with self.assertRaises(frappe.ValidationError):
            comm.save(ignore_permissions=True)

    def test_record_names_with_quotes_still_save(self):
        # No restriction beyond tags and Kanban column names
        priority = frappe.get_doc(
            {"doctype": "HD Ticket Priority", "name": 'Labels "Urgent"'}
        ).insert(ignore_permissions=True)
        ticket_type = frappe.get_doc(
            {"doctype": "HD Ticket Type", "name": 'Labels "Type"'}
        ).insert(ignore_permissions=True)
        self.assertEqual(priority.name, 'Labels "Urgent"')
        self.assertEqual(ticket_type.name, 'Labels "Type"')


def board(name, columns=(), **extra):
    return {
        "doctype": "Kanban Board",
        "kanban_board_name": name,
        "reference_doctype": "ToDo",
        "field_name": "status",
        "columns": [{"column_name": column} for column in columns],
        **extra,
    }


class TestKanbanColumnLabels(FrappeTestCase):
    def setUp(self):
        make_agent(AGENT, "Labels Agent")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def make_board(self, name, columns=("Open", "Closed")):
        return insert_as(AGENT, board(name, columns))

    def test_board_insert_refused(self):
        for index, bad in enumerate(BAD_TAGS):
            with self.subTest(column=bad), self.assertRaises(frappe.ValidationError):
                self.make_board(f"labels insert {index}", ("Open", bad))

    def test_add_column(self):
        self.make_board("labels add")
        for bad in BAD_TAGS:
            with self.subTest(column=bad), self.assertRaises(frappe.ValidationError):
                as_user(AGENT, kanban_board.add_column, "labels add", bad)
        columns = as_user(AGENT, kanban_board.add_column, "labels add", "R&D, Q & A")
        self.assertEqual(columns[-1].column_name, "R&D, Q & A")

    def test_renaming_a_column_row_refused(self):
        self.make_board("labels rename")
        row = frappe.get_all(
            "Kanban Board Column",
            filters={"parent": "labels rename", "column_name": "Open"},
            pluck="name",
        )[0]
        with self.assertRaises(frappe.ValidationError):
            set_value_as(AGENT, "Kanban Board Column", row, {"column_name": '"><b>x'})
        with self.assertRaises(frappe.ValidationError):
            set_value_as(AGENT, "Kanban Board Column", row, {"column_name": "&#34;"})

    def test_a_legacy_column_doesnt_block_later_saves(self):
        self.make_board("labels legacy")
        legacy = 'Open" onmouseover="alert(1)'
        frappe.db.set_value(
            "Kanban Board Column",
            {"parent": "labels legacy", "column_name": "Open"},
            "column_name",
            legacy,
        )
        frappe.db.set_value(
            "Kanban Board Column",
            {"parent": "labels legacy", "column_name": "Closed"},
            "column_name",
            "&lt;img src=x onerror=alert(1)&gt;",
        )
        as_user(
            AGENT, kanban_board.update_order, "labels legacy", json.dumps({legacy: []})
        )
        as_user(AGENT, kanban_board.set_indicator, "labels legacy", legacy, "Red")
        as_user(
            AGENT,
            kanban_board.update_column_order,
            "labels legacy",
            json.dumps(["&lt;img src=x onerror=alert(1)&gt;", legacy]),
        )
        stored = frappe.get_all(
            "Kanban Board Column",
            filters={"parent": "labels legacy"},
            fields=["column_name", "indicator"],
            order_by="idx",
        )
        self.assertEqual(
            [(row.column_name, row.indicator) for row in stored],
            [("&lt;img src=x onerror=alert(1)&gt;", "Gray"), (legacy, "Red")],
        )
        # A new bad column on the same board is still refused
        with self.assertRaises(frappe.ValidationError):
            as_user(AGENT, kanban_board.add_column, "labels legacy", 'x"y')

    def test_quick_kanban_board(self):
        doc = as_user(
            AGENT, kanban_board.quick_kanban_board, "ToDo", "labels quick", "status"
        )
        self.assertEqual(
            [column.column_name for column in doc.columns],
            ["Open", "Closed", "Cancelled"],
        )


class TestKanbanBoardJson(FrappeTestCase):
    """A board's fields and filters are Code fields the Kanban view shows in a
    message as HTML when it doesn't know a value (issue 319's stored item)."""

    def setUp(self):
        make_agent(AGENT, "Labels Agent")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_markup_is_stored_inert(self):
        name = insert_as(
            AGENT,
            board(
                "labels json",
                fields='["<img src=x onerror=alert(1)>"]',
                filters='[["ToDo","<img src=x onerror=alert(1)>","=","x"]]',
            ),
        )["name"]
        fields, filters = frappe.db.get_value(
            "Kanban Board", name, ["fields", "filters"]
        )
        self.assertNotIn("onerror", fields)
        self.assertNotIn("onerror", filters)
        self.assertEqual(len(json.loads(fields)), 1)
        self.assertEqual(json.loads(filters)[0][0], "ToDo")
        # save_settings, the Kanban view's own card-field write
        as_user(
            AGENT,
            kanban_board.save_settings,
            name,
            json.dumps({"fields": ["<img src=x onerror=alert(2)>"], "show_labels": 0}),
        )
        self.assertNotIn("onerror", frappe.db.get_value("Kanban Board", name, "fields"))

    def test_a_normal_board_is_kept_byte_identical(self):
        fields = '["description", "priority"]'
        filters = '[["ToDo", "status", "=", "Open"]]'
        name = insert_as(
            AGENT, board("labels plain", ("Open",), fields=fields, filters=filters)
        )["name"]
        self.assertEqual(
            frappe.db.get_value("Kanban Board", name, ["fields", "filters"]),
            (fields, filters),
        )
