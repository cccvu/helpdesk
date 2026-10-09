import copy
import types
from collections import deque
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from helpdesk.data_template import (
    FILTERS,
    PLAIN_TYPES,
    UTILS,
    get_environment,
    render_data_template,
)
from helpdesk.helpdesk.doctype.hd_settings.helpers import (
    default_banner_msg,
    get_default_email_content,
)
from helpdesk.test_utils import make_ticket

TITLE = "Data template test"
FALLBACK = "FALLBACK"

EMAIL_CONTENT_TYPES = (
    "share_feedback",
    "acknowledgement",
    "reply_to_agents",
    "reply_via_agent",
)

PLUS_ADDRESS_TEMPLATE = (
    "{% if doc.key %}support+{{ doc.name }}-"
    '{{ frappe.utils.sha256_hash(doc.key ~ "salt")[:12] }}@example.com{% endif %}'
)

# Each renders as `fallback`, or as text that shows no value it reached for
HOSTILE_TEMPLATES = (
    '{{ frappe.get_doc("User", "Administrator") }}',
    '{{ frappe.db.sql("select 1") }}',
    '{{ frappe.sendmail(recipients=["a@example.com"], subject="x") }}',
    '{{ frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert() }}',
    '{% include "frappe/hooks.py" %}',
    '{% import "x" as y %}',
    "{{ ''.__class__ }}",
    "{{ doc.__class__ }}",
    '{{ doc.update({"x": 1}) }}',
    "{{ 1/0 }}",
    '{{ frappe.utils.getdate("junk") }}',
    '{{ "{0.__class__}".format(doc) }}',
    '{{ doc|attr("__class__") }}',
)

WRITE_COUNTED = ("Has Role", "ToDo", "Email Queue", "User")


def new_error_logs(before: set[str]) -> list[dict]:
    """Error Logs added since `before`, a set of Error Log names. Error Log rows
    outlive the test's rollback, so compare names, not counts."""
    return [
        log
        for log in frappe.get_all(
            "Error Log",
            fields=["name", "method", "reference_doctype", "reference_name"],
        )
        if log.name not in before
    ]


def error_log_names() -> set[str]:
    return set(frappe.get_all("Error Log", pluck="name"))


def captured_values(context: dict) -> dict:
    """The values render_data_template hands to the template for `context`."""
    seen = {}

    def from_string(template):
        def render(values):
            seen.update(values)
            return ""

        return MagicMock(render=render)

    with patch(
        "helpdesk.data_template.get_environment",
        return_value=MagicMock(from_string=from_string),
    ):
        render_data_template("x", context, fallback=None, title=TITLE)
    return seen


class TestDataTemplate(FrappeTestCase):
    def setUp(self):
        self.ticket = make_ticket(subject="Data <b>template</b> & co")
        self.ticket.reload()

    def tearDown(self):
        frappe.set_user("Administrator")

    def render(self, template, context, **kwargs):
        kwargs.setdefault("fallback", FALLBACK)
        kwargs.setdefault("title", TITLE)
        return render_data_template(template, context, **kwargs)

    def email_context(self):
        return {
            "doc": self.ticket.as_dict(),
            "url": "https://example.com/ticket-feedback/new?key=abc",
            "message": "<p>Hello & <b>welcome</b></p>",
            "ticket_url": "https://example.com/helpdesk/tickets/1",
        }

    def test_default_email_contents_render_as_frappe_renders_them(self):
        context = self.email_context()
        for content_type in EMAIL_CONTENT_TYPES:
            content = get_default_email_content(content_type)
            self.assertEqual(
                self.render(content, context),
                frappe.render_template(content, context),
                content_type,
            )

    def test_default_banner_renders_as_frappe_renders_it(self):
        response_by = get_datetime("2026-10-12 09:30:00")
        for next_working_day_dt in (response_by, None):
            context = {
                "ticket": self.ticket.as_dict(),
                "next_working_daytime": next_working_day_dt,
                "next_working_day": next_working_day_dt
                and next_working_day_dt.strftime("%A, %d %b"),
                "next_working_date": None,
                "expected_response": None,
            }
            self.assertEqual(
                self.render(default_banner_msg, context),
                frappe.render_template(default_banner_msg, context),
            )

    def test_plus_address_template_renders_as_frappe_renders_it(self):
        context = {"doc": self.ticket.as_dict()}
        self.assertTrue(self.ticket.key)
        rendered = self.render(PLUS_ADDRESS_TEMPLATE, context)
        self.assertTrue(rendered.startswith(f"support+{self.ticket.name}-"))
        self.assertEqual(
            rendered, frappe.render_template(PLUS_ADDRESS_TEMPLATE, context)
        )

    def test_empty_template_renders_empty(self):
        for template in (None, ""):
            self.assertEqual(self.render(template, {}), "")

    def test_hostile_templates_change_nothing_and_show_nothing(self):
        context = {"doc": self.ticket.as_dict()}
        counts = {doctype: frappe.db.count(doctype) for doctype in WRITE_COUNTED}
        messages = len(frappe.get_message_log())

        for template in HOSTILE_TEMPLATES:
            rendered = self.render(template, context)
            self.assertNotIn(template, rendered, template)
            if rendered != FALLBACK:
                self.assertTrue(rendered.startswith("{{ undefined value"), rendered)
                self.assertNotIn("<class", rendered, template)

        self.assertEqual(
            {doctype: frappe.db.count(doctype) for doctype in WRITE_COUNTED}, counts
        )
        self.assertEqual(len(frappe.get_message_log()), messages)

    def test_template_calls_and_loads_fail_to_the_fallback(self):
        context = {"doc": self.ticket.as_dict()}
        for template in (
            '{{ frappe.get_doc("User", "Administrator") }}',
            '{{ frappe.db.sql("select 1") }}',
            '{% include "frappe/hooks.py" %}',
            '{% import "x" as y %}',
            '{{ doc.update({"x": 1}) }}',
            '{{ frappe.utils.getdate("junk") }}',
        ):
            self.assertEqual(self.render(template, context), FALLBACK, template)

    def test_a_template_path_is_text(self):
        template = "templates/emails/password_reset.html"
        self.assertEqual(self.render(template, {}), template)

    def test_an_error_is_logged_once_against_the_reference(self):
        before = error_log_names()
        rendered = self.render(
            "{{ 1/0 }}",
            {},
            reference_doctype="HD Ticket",
            reference_name=self.ticket.name,
        )
        self.assertEqual(rendered, FALLBACK)
        self.assertEqual(
            [
                (log.method, log.reference_doctype, log.reference_name)
                for log in new_error_logs(before)
            ],
            [(TITLE, "HD Ticket", self.ticket.name)],
        )

    def test_a_render_logs_nothing(self):
        before = error_log_names()
        self.render("{{ doc.name }} {{ missing }}", {"doc": self.ticket.as_dict()})
        self.assertEqual(new_error_logs(before), [])

    def test_the_callers_context_is_unchanged(self):
        doc = self.ticket.as_dict()
        context = {"doc": doc, "rows": [frappe._dict(a=1)], "message": "<p>x</p>"}
        expected = copy.deepcopy(context)
        for template in (
            "{{ doc.name }}",
            '{{ doc.update({"subject": "x"}) }}',
            '{{ doc.pop("name") }}',
            "{{ rows.append(1) }}",
            '{{ rows[0].update({"a": 2}) }}',
            '{% set doc = {"name": "x"} %}{{ doc.name }}',
        ):
            self.render(template, context)
            self.assertEqual(context, expected, template)
            self.assertIs(context["doc"], doc)

    def test_a_document_reaches_the_template_as_text(self):
        values = captured_values({"live": self.ticket, "nested": [{"d": self.ticket}]})
        self.assertIsInstance(values["live"], str)
        self.assertIsInstance(values["nested"][0]["d"], str)

    def test_helpers_are_plain_functions(self):
        for name, value in [*UTILS.items(), *FILTERS.items()]:
            self.assertIsInstance(
                value, (types.FunctionType, types.BuiltinFunctionType), name
            )
            self.assertEqual(
                [attr for attr in dir(value) if not attr.startswith("_")], [], name
            )

    def test_the_template_reaches_only_plain_values(self):
        """Walk everything a template can reach from its context: items of
        dicts and lists, and each public attribute the sandbox allows."""
        doc = self.ticket.as_dict()
        # HD Ticket has no child table, so stand in for one
        doc["rows"] = [
            frappe._dict(idx=1, value=get_datetime("2026-10-09 10:00:00")),
            {"idx": 2, "nested": [{"deep": 1.5}]},
        ]
        values = captured_values(
            {"doc": doc, "live": self.ticket, "message": "<p>x</p>"}
        )

        env = get_environment()
        helpers = {id(v) for v in (*UTILS.values(), *FILTERS.values(), frappe._)}
        containers = (list, frappe._dict, MappingProxyType)
        receivers = (*PLAIN_TYPES, *containers, dict)

        def is_pure_method(value):
            if not isinstance(
                value,
                (types.BuiltinMethodType, types.MethodType, types.MethodWrapperType),
            ):
                return False
            owner = getattr(value, "__self__", None)
            return isinstance(owner, receivers) or owner in receivers

        def check(value, path):
            if type(value) in PLAIN_TYPES or isinstance(value, containers):
                return True
            if id(value) in helpers or is_pure_method(value):
                return False
            self.fail(f"{path} reaches {type(value).__name__}: {value!r}")

        queue = deque([(values, "values", 0)])
        seen = set()
        while queue:
            value, path, depth = queue.popleft()
            if id(value) in seen or depth > 4:
                continue
            seen.add(id(value))

            children = []
            if isinstance(value, (dict, MappingProxyType)):
                children += [(v, f"{path}[{k!r}]") for k, v in value.items()]
            elif isinstance(value, list):
                children += [(v, f"{path}[{i}]") for i, v in enumerate(value)]
            for attr in dir(value):
                if attr.startswith("_"):
                    continue
                try:
                    child = getattr(value, attr)
                except Exception:
                    continue
                if env.is_safe_attribute(value, attr, child):
                    children.append((child, f"{path}.{attr}"))

            for child, child_path in children:
                if check(child, child_path):
                    queue.append((child, child_path, depth + 1))

    def test_a_deadlock_reaches_the_caller(self):
        for error in (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
            env = MagicMock()
            env.from_string.side_effect = error
            before = error_log_names()
            with (
                patch("helpdesk.data_template.get_environment", return_value=env),
                self.assertRaises(error),
            ):
                self.render("{{ doc.name }}", {})
            self.assertEqual(new_error_logs(before), [])

    def test_messages_stay_muted_and_are_restored(self):
        frappe.flags.mute_messages = False
        self.render('{{ frappe.utils.getdate("junk") }}', {})
        self.assertFalse(frappe.flags.mute_messages)
