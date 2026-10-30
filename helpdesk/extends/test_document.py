import json

import frappe
from frappe.model.docstatus import DocStatus
from frappe.tests.utils import FrappeTestCase

from helpdesk.extends.document import (
    _sanitize_doc,
    drop_markup_data,
    sanitize_html_fields,
    sanitize_json_html,
)
from helpdesk.test_utils import make_mention_html

# Two values Frappe v15's sanitize_html returns unchanged: one parses as JSON,
# one is a single comment to BeautifulSoup but a live <img> to a browser.
JSON_SHAPED = '["<img src=\\"x\\" onerror=\\"1\\">"]'
COMMENT_SHAPED = "<!--><img src=x onerror=1>-->"
# The same tagless payload behind Frappe's "<!-- markdown -->" sentinel, which is
# attacker-controllable content, not a trusted field marker (issue 251).
MARKDOWN_SHAPED = "<!-- markdown --><!--><img src=x onerror=1>-->"
HOSTILE = (JSON_SHAPED, COMMENT_SHAPED, MARKDOWN_SHAPED)


class TestSanitizeHtmlFields(FrappeTestCase):
    def assertInert(self, value):
        self.assertNotIn("onerror", value)
        self.assertIn("<img", value)

    def _assert_field_sanitized(self, doctype, field, **extra):
        for payload in HOSTILE:
            with self.subTest(doctype=doctype, field=field, payload=payload):
                doc = frappe.get_doc({"doctype": doctype, field: payload, **extra})
                sanitize_html_fields(doc)
                self.assertInert(doc.get(field))

    # Rich-text (Text Editor) fields /app renders as HTML.
    def test_hd_ticket_description(self) -> None:
        self._assert_field_sanitized("HD Ticket", "description", subject="x")

    def test_hd_ticket_comment_content(self) -> None:
        self._assert_field_sanitized("HD Ticket Comment", "content")

    def test_hd_article_content(self) -> None:
        self._assert_field_sanitized("HD Article", "content", title="x")

    def test_hd_saved_reply_message(self) -> None:
        self._assert_field_sanitized("HD Saved Reply", "message", name="x")

    # Data / Small Text fields, the same v15 gap (issue 251, comment 1).
    def test_hd_ticket_subject_data_field(self) -> None:
        self._assert_field_sanitized("HD Ticket", "subject", description="x")

    def test_user_email_signature(self) -> None:
        self._assert_field_sanitized(
            "User", "email_signature", email="sig@example.com", first_name="Sig"
        )

    def test_communication_content_subject_and_sender(self) -> None:
        for field in ("content", "subject", "sender_full_name"):
            self._assert_field_sanitized(
                "Communication",
                field,
                communication_type="Communication",
                communication_medium="Email",
                sender="s@example.com",
            )

    def test_markdown_sentinel_does_not_bypass_sanitization(self) -> None:
        # The "<!-- markdown -->" sentinel must not let a tagless payload skip the
        # hook. sanitize_html keeps HTML comments, so a genuine markdown field is
        # still detected as markdown after sanitization (issue 251).
        doc = frappe.get_doc({"doctype": "HD Saved Reply", "message": MARKDOWN_SHAPED})
        sanitize_html_fields(doc)
        self.assertInert(doc.message)
        self.assertIn("<!-- markdown -->", doc.message)

    def test_plain_text_is_kept(self) -> None:
        for value in ("a < b, <3 and <= 2", "Thanks & regards, 5 > 4"):
            with self.subTest(value=value):
                doc = frappe.get_doc(
                    {"doctype": "HD Ticket", "subject": value, "description": value}
                )
                sanitize_html_fields(doc)
                self.assertEqual(doc.subject, value)
                self.assertEqual(doc.description, value)

    def test_safe_html_is_kept(self) -> None:
        value = "<p>Hi <b>there</b></p>"
        doc = frappe.get_doc(
            {"doctype": "HD Ticket", "description": value, "subject": "x"}
        )
        sanitize_html_fields(doc)
        self.assertEqual(doc.description, value)

    def test_code_fields_are_left_alone(self) -> None:
        # A Code field (HD Form Script.script) is JavaScript, not HTML; Frappe
        # skips it and so must we, or every script would be mangled.
        payload = "if (a < b) { doc.set('<x>', 1); }"
        doc = frappe.get_doc(
            {"doctype": "HD Form Script", "dt": "HD Ticket", "script": payload}
        )
        sanitize_html_fields(doc)
        self.assertEqual(doc.script, payload)

    def test_list_value_for_a_controller_converted_field_saves(self) -> None:
        # HD Saved Reply's validate turns an actions list into JSON text; the
        # hook runs first and must not refuse the list (the Settings UI sends one).
        doc = frappe.get_doc(
            {
                "doctype": "HD Saved Reply",
                "title": "sanitize-hook-list-test",
                "message": COMMENT_SHAPED,
                "actions": [],
            }
        ).insert(ignore_permissions=True)
        self.assertInert(frappe.db.get_value("HD Saved Reply", doc.name, "message"))
        self.assertEqual(
            frappe.db.get_value("HD Saved Reply", doc.name, "actions"), "[]"
        )

    def test_non_string_value_in_a_read_only_field_is_sanitized(self) -> None:
        # A save stores a Read Only field's non-string value as its text
        # (get_valid_dict's cstr), so the hook sanitizes that text too.
        doc = frappe.get_doc(
            {
                "doctype": "ToDo",
                "description": "sanitize-hook-read-only-test",
                "assigned_by_full_name": {"name": COMMENT_SHAPED},
            }
        ).insert(ignore_permissions=True)
        self.assertInert(frappe.db.get_value("ToDo", doc.name, "assigned_by_full_name"))

    def test_insert_runs_the_hook(self) -> None:
        # End to end: the registered "*" hook sanitizes on insert.
        doc = frappe.get_doc(
            {
                "doctype": "HD Saved Reply",
                "name": "sanitize-hook-test",
                "title": "sanitize-hook-test",
                "message": COMMENT_SHAPED,
            }
        ).insert(ignore_permissions=True)
        self.assertInert(frappe.db.get_value("HD Saved Reply", doc.name, "message"))


# Values that are markup only once the browser decodes them: in data-* attributes
# Frappe's mention blot reads (data-value, data-label as Helpdesk's own mentions
# write it, data-denotation-char), and in a mention's text, which the blot falls
# back to. sanitize_html keeps all four as they are, entity-encoded.
ENCODED_IMG = "&lt;img src=x onerror=alert(1)&gt;"
MENTION_DATA = {
    "data-value": f'<span class="mention" data-id="a@b.c" data-value="{ENCODED_IMG}">@x</span>',
    "data-label": (
        f'<span class="mention" data-type="mention" data-id="a@b.c" '
        f'data-label="{ENCODED_IMG}">@x</span>'
    ),
    "data-denotation-char": (
        f'<span class="mention" data-id="a@b.c" data-value="x" '
        f'data-denotation-char="{ENCODED_IMG}">@x</span>'
    ),
}
MENTION_TEXT = f'<p><span class="mention">{ENCODED_IMG}</span></p>'
# Frappe's own Text Editor writes its mentions like this.
QUILL_MENTION = (
    '<p><span class="mention" data-index="0" data-denotation-char="@" '
    'data-id="a@b.c" data-value="Ann Lee"><span contenteditable="false">'
    '<span class="ql-mention-denotation-char">@</span>Ann Lee</span></span> hi</p>'
)


def _decoded(html):
    """Every attribute value and text node of html, as the browser decodes them."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    values = [soup.get_text()]
    for tag in soup.find_all(True):
        values += [
            " ".join(v) if isinstance(v, list) else v for v in tag.attrs.values()
        ]
    return values


class TestDropMarkupData(FrappeTestCase):
    def assertNoDecodedMarkup(self, html):
        for value in _decoded(html):
            if "mention" in html or "data-" in html:
                self.assertNotRegex(value, "[<>]", html)

    def test_markup_in_a_mention_data_attribute_is_dropped(self) -> None:
        for attribute, payload in MENTION_DATA.items():
            with self.subTest(attribute=attribute):
                doc = frappe.get_doc(
                    {"doctype": "HD Ticket", "subject": "x", "description": payload}
                )
                sanitize_html_fields(doc)
                self.assertNotIn(attribute + "=", doc.description)
                self.assertNotIn("&lt;img", doc.description)
                self.assertIn('class="mention"', doc.description)
                self.assertIn("@x", doc.description)

    def test_markup_in_a_mention_text_loses_the_mention_class(self) -> None:
        doc = frappe.get_doc({"doctype": "HD Ticket Comment", "content": MENTION_TEXT})
        sanitize_html_fields(doc)
        self.assertNotIn("mention", doc.content)
        # Kept as text, which the editor shows as typed.
        self.assertIn(ENCODED_IMG, doc.content)

    def test_markup_in_any_data_attribute_is_dropped(self) -> None:
        html = f'<p data-note="{ENCODED_IMG}" data-x="1">hi</p>'
        self.assertEqual(drop_markup_data(html), '<p data-x="1">hi</p>')
        self.assertEqual(drop_markup_data('<p data-note="a > b">hi</p>'), "<p>hi</p>")

    def test_a_mention_keeps_its_other_classes(self) -> None:
        html = f'<span class="x mention y">{ENCODED_IMG}</span>'
        self.assertEqual(
            drop_markup_data(html), f'<span class="x y">{ENCODED_IMG}</span>'
        )

    def test_real_mentions_are_kept_exactly(self) -> None:
        helpdesk = f"<p>{make_mention_html('agent@example.com', 'Ann Lee')} hi</p>"
        for html in (helpdesk, QUILL_MENTION):
            with self.subTest(html=html):
                self.assertEqual(drop_markup_data(html), html)
                doc = frappe.get_doc(
                    {"doctype": "HD Ticket", "subject": "x", "description": html}
                )
                sanitize_html_fields(doc)
                self.assertEqual(doc.description, html)

    def test_the_rest_of_a_changed_value_is_written_as_it_was(self) -> None:
        # Attribute order, void elements and text survive the rewrite.
        real = make_mention_html("agent@example.com", "Ann Lee")
        html = (
            f'<p>{real}<br><img src="x" alt="a">'
            f'<span data-note="{ENCODED_IMG}">Café &amp; co</span></p>'
        )
        self.assertEqual(
            drop_markup_data(html),
            f'<p>{real}<br><img src="x" alt="a"><span>Café &amp; co</span></p>',
        )

    def test_text_without_markup_in_a_mention_or_data_is_kept(self) -> None:
        for html in (
            '<p data-x="a &amp; b">x</p>',
            '<span class="mention">@a &amp; b</span>',
            "<p>a &lt; b, no data attribute</p>",
            "<p>a mention of mentions</p>",
        ):
            with self.subTest(html=html):
                self.assertIs(drop_markup_data(html), html)


def _json_escaped(text):
    """text with "<" and ">" written as JSON escapes, as JSON.stringify can."""
    return text.replace("<", chr(92) + "u003c").replace(">", chr(92) + "u003e")


HEADER = '<span class="h4"><b>Reports &amp; Masters</b></span>'


def workspace_content(*texts):
    return json.dumps(
        [
            {"id": f"b{i}", "type": "paragraph", "data": {"text": text, "col": 12}}
            for i, text in enumerate(texts)
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )


class TestSanitizeJsonHtml(FrappeTestCase):
    def test_escaped_markup_in_a_workspace_block_is_sanitized(self) -> None:
        content = _json_escaped(workspace_content("<img src=x onerror=alert(1)>"))
        self.assertNotIn("<", content)  # MARKUP would not see it
        doc = frappe.get_doc(
            {"doctype": "Workspace", "title": "x", "label": "x", "content": content}
        )
        sanitize_html_fields(doc)
        text = json.loads(doc.content)[0]["data"]["text"]
        self.assertIn("<img", text)
        self.assertNotIn("onerror", text)

    def test_quotes_and_safe_markup_are_kept(self) -> None:
        # Sanitizing the JSON text as HTML wrote class="h4" as class='"h4"'.
        content = workspace_content(HEADER, "Plain text, a < b", "Café")
        doc = frappe.get_doc(
            {"doctype": "Workspace", "title": "x", "label": "x", "content": content}
        )
        sanitize_html_fields(doc)
        self.assertEqual(doc.content, content)
        self.assertEqual(json.loads(doc.content)[0]["data"]["text"], HEADER)

    def test_only_the_strings_with_markup_change(self) -> None:
        content = workspace_content(HEADER, "<b onclick=x>bold</b>", "Café")
        cleaned = json.loads(sanitize_json_html(content))
        self.assertEqual(
            [block["data"]["text"] for block in cleaned],
            [HEADER, "<b>bold</b>", "Café"],
        )

    def test_escaped_markup_in_a_saved_list_filter_is_sanitized(self) -> None:
        filters = _json_escaped(
            json.dumps([["HD Ticket", "<img src=x onerror=alert(1)>", "=", "1"]])
        )
        doc = frappe.get_doc(
            {
                "doctype": "List Filter",
                "reference_doctype": "HD Ticket",
                "filter_name": "x",
                "filters": filters,
            }
        )
        sanitize_html_fields(doc)
        self.assertNotIn("onerror", json.loads(doc.filters)[0][1])
        plain = json.dumps([["HD Ticket", "status", "=", "Open"]])
        doc.filters = plain
        sanitize_html_fields(doc)
        self.assertEqual(doc.filters, plain)

    def test_mention_data_in_a_block_is_dropped(self) -> None:
        content = workspace_content(MENTION_DATA["data-value"])
        self.assertNotIn("data-value", sanitize_json_html(content))

    def test_nested_values_are_sanitized(self) -> None:
        content = json.dumps({"a": [{"b": ["<img src=x onerror=1>"]}], "n": 1})
        self.assertEqual(
            json.loads(sanitize_json_html(content)),
            {"a": [{"b": ['<img src="x">']}], "n": 1},
        )

    def test_a_value_that_is_not_json_is_sanitized_as_html(self) -> None:
        self.assertNotIn("onerror", sanitize_json_html("<img src=x onerror=1> ["))
        self.assertEqual(sanitize_json_html("not json"), "not json")


class _FakeMeta:
    def __init__(self, fields):
        self._fields = fields

    def get_field(self, fieldname):
        return self._fields.get(fieldname)

    def get_valid_columns(self):
        return list(self._fields)


class _FakeDoc:
    """A document with controlled field metadata, so each skip branch of
    _sanitize_doc can be exercised without depending on a real doctype having a
    field with that exact fieldtype, option or flag."""

    doctype = "Fake"

    def __init__(self, values, fields, docstatus=0, children=None):
        self._values = dict(values)
        self.meta = _FakeMeta(fields)
        self.docstatus = DocStatus(docstatus)
        self._children = children or []

    def get_all_children(self):
        return list(self._children)

    def get(self, fieldname):
        return self._values.get(fieldname)

    def set(self, fieldname, value):
        self._values[fieldname] = value


HTML = frappe._dict(fieldtype="Text Editor")
PAYLOAD = COMMENT_SHAPED


class TestSanitizeSkipBranches(FrappeTestCase):
    """Each branch that must NOT sanitize keeps the value verbatim; deleting any
    one would silently over-sanitize an intended-raw field with the suite green."""

    def _kept(self, fields, **doc_args):
        doc = _FakeDoc({"f": PAYLOAD}, fields, **doc_args)
        _sanitize_doc(doc)
        self.assertEqual(doc.get("f"), PAYLOAD)

    def test_sanitizes_a_plain_html_field(self) -> None:
        doc = _FakeDoc({"f": PAYLOAD}, {"f": HTML})
        _sanitize_doc(doc)
        self.assertNotIn("onerror", doc.get("f"))

    def test_skips_field_without_meta(self) -> None:
        # A default column (e.g. name) has no docfield; sanitizing it under
        # always_sanitize would corrupt JSON columns like _comments/_assign that
        # Frappe spares via its is_json early return (issue 251 review).
        self._kept({"f": None})

    def test_skips_virtual_fields(self) -> None:
        # A virtual field has no stored column; its value is computed on read.
        self._kept({"f": frappe._dict(fieldtype="Text Editor", is_virtual=1)})

    def test_read_only_field_sanitizes_the_text_a_save_stores(self) -> None:
        for value in ({"k": PAYLOAD}, (PAYLOAD,)):
            with self.subTest(value=value):
                doc = _FakeDoc({"f": value}, {"f": frappe._dict(fieldtype="Read Only")})
                _sanitize_doc(doc)
                self.assertIsInstance(doc.get("f"), str)
                self.assertNotIn("onerror", doc.get("f"))

    def test_other_non_string_values_are_left_for_the_save_to_check(self) -> None:
        # A save refuses a list in any non-table field (get_valid_dict) and a
        # dict outside Read Only (the database driver), so the hook leaves them.
        cases = [
            ("Data", {"k": PAYLOAD}),
            ("Data", [PAYLOAD]),
            ("Data", 5),
            ("Data", None),
            ("Read Only", [PAYLOAD]),
            ("Read Only", None),
        ]
        for fieldtype, value in cases:
            with self.subTest(fieldtype=fieldtype, value=value):
                doc = _FakeDoc({"f": value}, {"f": frappe._dict(fieldtype=fieldtype)})
                _sanitize_doc(doc)
                self.assertEqual(doc.get("f"), value)

    def test_skips_ignore_xss_filter(self) -> None:
        self._kept({"f": frappe._dict(fieldtype="Text Editor", ignore_xss_filter=1)})

    def test_skips_non_html_fieldtypes(self) -> None:
        for fieldtype in ("Code", "Attach", "Attach Image", "Barcode", "JSON"):
            with self.subTest(fieldtype=fieldtype):
                self._kept({"f": frappe._dict(fieldtype=fieldtype)})

    def test_skips_email_option_text_fields(self) -> None:
        for fieldtype in ("Data", "Small Text", "Text"):
            with self.subTest(fieldtype=fieldtype):
                self._kept({"f": frappe._dict(fieldtype=fieldtype, options="Email")})

    def test_skips_cancelled_documents(self) -> None:
        self._kept({"f": HTML}, docstatus=2)

    def test_skips_submitted_without_allow_on_submit(self) -> None:
        self._kept({"f": frappe._dict(fieldtype="Text Editor")}, docstatus=1)

    def test_sanitizes_submitted_with_allow_on_submit(self) -> None:
        doc = _FakeDoc(
            {"f": PAYLOAD},
            {"f": frappe._dict(fieldtype="Text Editor", allow_on_submit=1)},
            docstatus=1,
        )
        _sanitize_doc(doc)
        self.assertNotIn("onerror", doc.get("f"))

    def test_json_shaped_string_in_a_text_field_is_still_sanitized(self) -> None:
        # Only the JSON *fieldtype* is skipped; a JSON-shaped value in a normal
        # field is the v15 gap this closes, so it must be sanitized (issue 251).
        doc = _FakeDoc({"f": JSON_SHAPED}, {"f": frappe._dict(fieldtype="Data")})
        _sanitize_doc(doc)
        self.assertNotIn("onerror", doc.get("f"))

    def test_sanitizes_child_table_rows(self) -> None:
        # doc_events["*"] reaches only the parent; the hook sanitizes children too
        # (Frappe sanitizes them in _validate). A child's HTML field is a sink
        # wherever /app renders it.
        child = _FakeDoc({"f": PAYLOAD}, {"f": HTML})
        parent = _FakeDoc(
            {"f": "plain"}, {"f": frappe._dict(fieldtype="Data")}, children=[child]
        )
        sanitize_html_fields(parent)
        self.assertNotIn("onerror", child.get("f"))
