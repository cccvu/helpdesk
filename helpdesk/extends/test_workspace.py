import json

import frappe
from frappe.desk.doctype.workspace import workspace as frappe_workspace
from frappe.tests.utils import FrappeTestCase

from helpdesk.test_utils import insert_as, make_agent, set_value_as, share_doc_as

AGENT = "workspace.agent@example.com"
OTHER = "workspace.other@example.com"
MANAGER = "workspace.manager@example.com"
CONTENT = '[{"id":"b0","type":"paragraph","data":{"text":"hello","col":12}}]'


def private_page(title, user, **extra):
    return {
        "doctype": "Workspace",
        "title": title,
        "label": f"{title}-{user}",
        "for_user": user,
        "public": 0,
        "content": CONTENT,
        **extra,
    }


def as_user(user, method, *args, **kwargs):
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        return method(*args, **kwargs)
    finally:
        frappe.set_user(previous)


# As user, past Frappe's permission checks, as the sidebar's methods write: the
# guard ignores ignore_permissions, so these test it whatever the site's
# Workspace permissions are (a site may have taken Desk User's write).
def save_as(user, name, values):
    def save():
        doc = frappe.get_doc("Workspace", name)
        doc.update(values)
        return doc.save(ignore_permissions=True)

    return as_user(user, save)


def delete_as(user, name):
    return as_user(user, frappe.delete_doc, "Workspace", name, ignore_permissions=True)


def rename_as(user, name, new_name):
    from frappe.model.rename_doc import rename_doc

    return as_user(
        user,
        rename_doc,
        "Workspace",
        name,
        new_name,
        ignore_permissions=True,
        show_alert=False,
    )


def insert_past_permissions_as(user, page):
    return as_user(user, lambda: frappe.get_doc(page).insert(ignore_permissions=True))


class TestWorkspaceOwnership(FrappeTestCase):
    """Only Workspace Managers write a public Workspace or another user's private
    one. Frappe's own public check is off under tests (disable_saving_as_public),
    so every refusal here is the fork's."""

    def setUp(self) -> None:
        make_agent(AGENT, "Workspace Agent")
        make_agent(OTHER, "Workspace Other")
        make_agent(MANAGER, "Workspace Manager")
        frappe.get_doc("User", MANAGER).add_roles("Workspace Manager")
        self.others = frappe.get_doc(private_page("Others Page", OTHER)).insert(
            ignore_permissions=True
        )
        self.public = frappe.get_doc(
            {
                "doctype": "Workspace",
                "title": "Shared Test Page",
                "label": "Shared Test Page",
                "public": 1,
                "content": CONTENT,
            }
        ).insert(ignore_permissions=True)
        self.own = frappe.get_doc(private_page("Own Page", AGENT)).insert(
            ignore_permissions=True
        )

    def tearDown(self) -> None:
        frappe.db.rollback()
        frappe.set_user("Administrator")

    def assertRefused(self, method, *args, **kwargs):
        with self.assertRaises(frappe.PermissionError):
            method(*args, **kwargs)

    def test_agent_can_not_create_a_page_for_someone_else(self) -> None:
        # Desk User keeps create, so over REST too.
        self.assertRefused(insert_as, AGENT, private_page("Planted", OTHER))
        for page in (private_page("Planted", OTHER), private_page("Nobody", "")):
            self.assertRefused(insert_past_permissions_as, AGENT, page)

    def test_agent_can_not_create_a_public_page(self) -> None:
        page = private_page("Public Try", AGENT, public=1)
        self.assertRefused(insert_past_permissions_as, AGENT, page)

    def test_agent_can_not_change_someone_elses_page(self) -> None:
        self.assertRefused(save_as, AGENT, self.others.name, {"content": "[]"})
        self.assertRefused(save_as, AGENT, self.others.name, {"for_user": AGENT})

    def test_agent_can_not_make_a_public_page_private(self) -> None:
        self.assertRefused(save_as, AGENT, self.public.name, {"public": 0})
        self.assertRefused(
            save_as,
            AGENT,
            self.public.name,
            {"public": 0, "for_user": AGENT},
        )
        self.assertEqual(
            frappe.db.get_value("Workspace", self.public.name, "public"), 1
        )

    def test_agent_can_not_move_or_publish_their_own_page(self) -> None:
        self.assertRefused(save_as, AGENT, self.own.name, {"for_user": OTHER})
        self.assertRefused(save_as, AGENT, self.own.name, {"public": 1})

    def test_a_share_with_write_does_not_help(self) -> None:
        # Desk User may share any Workspace, and a share with write grants write.
        share_doc_as("Administrator", "Workspace", self.others.name, AGENT, write=1)
        self.assertRefused(
            set_value_as, AGENT, "Workspace", self.others.name, {"content": "[]"}
        )

    def test_agent_can_not_delete_or_rename_someone_elses_page(self) -> None:
        self.assertRefused(delete_as, AGENT, self.others.name)
        # Frappe's own on_trash refuses a public page first.
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            delete_as(AGENT, self.public.name)
        self.assertRefused(rename_as, AGENT, self.others.name, f"Mine-{AGENT}")
        self.assertTrue(frappe.db.exists("Workspace", self.others.name))
        self.assertTrue(frappe.db.exists("Workspace", self.public.name))

    def test_agent_changes_their_own_page(self) -> None:
        save_as(AGENT, self.own.name, {"content": "[]"})
        self.assertEqual(
            frappe.db.get_value("Workspace", self.own.name, "content"), "[]"
        )
        delete_as(AGENT, self.own.name)
        self.assertFalse(frappe.db.exists("Workspace", self.own.name))

    def test_the_sidebar_methods_still_work_for_an_agent(self) -> None:
        name = f"Sidebar Page-{AGENT}"
        new = {
            "title": "Sidebar Page",
            "icon": "",
            "indicator_color": "",
            "parent_page": "",
            "public": 0,
            "for_user": AGENT,
            "label": name,
            "content": "[]",
        }
        as_user(AGENT, frappe_workspace.new_page, json.dumps(new))
        header = '<span class="h4"><b>Mine</b></span>'
        blocks = json.dumps(
            [{"id": "h", "type": "header", "data": {"text": header, "col": 12}}]
        )
        as_user(AGENT, frappe_workspace.save_page, "Sidebar Page", 0, "{}", blocks)
        stored = json.loads(frappe.db.get_value("Workspace", name, "content"))
        self.assertEqual(stored[0]["data"]["text"], header)
        as_user(AGENT, frappe_workspace.hide_page, name)
        self.assertEqual(frappe.db.get_value("Workspace", name, "is_hidden"), 1)
        as_user(AGENT, frappe_workspace.unhide_page, name)
        as_user(
            AGENT, frappe_workspace.update_page, name, "Renamed Page", "", "", "", 0
        )
        renamed = f"Renamed Page-{AGENT}"
        self.assertTrue(frappe.db.exists("Workspace", renamed))
        page = {"name": renamed, "public": 0, "title": "Renamed Page"}
        as_user(AGENT, frappe_workspace.delete_page, json.dumps(page))
        self.assertFalse(frappe.db.exists("Workspace", renamed))

    def test_update_page_is_refused_when_it_would_move_someone_elses_page(self):
        # Frappe's update_page re-saves every private page whose parent_page is
        # the edited page's title, whoever owns it. The guard refuses the whole
        # call rather than let one agent re-parent another's page (AGENTS.md,
        # Known behaviour); the other user's page is left as it was.
        frappe.get_doc(private_page("Child", OTHER, parent_page="Own Page")).insert(
            ignore_permissions=True
        )
        with self.assertRaises(frappe.PermissionError) as refused:
            as_user(
                AGENT,
                frappe_workspace.update_page,
                self.own.name,
                "Own Page",
                "",
                "",
                "",
                0,
            )
        self.assertIn(f"Child-{OTHER}", str(refused.exception))
        self.assertEqual(
            frappe.db.get_value("Workspace", f"Child-{OTHER}", "parent_page"),
            "Own Page",
        )

    def test_the_refusal_names_the_page_as_text(self) -> None:
        # The message is shown as HTML; names can't hold "<" but can hold "&".
        page = private_page("Q & A", OTHER)
        with self.assertRaises(frappe.PermissionError) as refused:
            insert_past_permissions_as(AGENT, page)
        self.assertIn(f"Q &amp; A-{OTHER}", str(refused.exception))

    def test_a_workspace_manager_may_change_any_page(self) -> None:
        save_as(MANAGER, self.others.name, {"content": "[]"})
        save_as(MANAGER, self.public.name, {"is_hidden": 1})
        delete_as(MANAGER, self.others.name)
        self.assertFalse(frappe.db.exists("Workspace", self.others.name))
