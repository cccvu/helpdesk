# Copyright (c) 2022, Frappe Technologies and Contributors
# See license.txt

import json

import frappe
from frappe.client import get as client_get
from frappe.client import get_list as client_get_list
from frappe.model.rename_doc import rename_doc
from frappe.tests.utils import FrappeTestCase

from helpdesk.helpdesk.doctype.hd_team.hd_team import HDTeam, get_team_members
from helpdesk.test_utils import (
    delete_team_as,
    get_team_rule_state,
    make_agent,
    make_agent_manager,
    make_team,
    make_team_as,
    make_ticket,
    rename_team_as,
    share_team_as,
    update_team_as,
    user_roles,
)

# Team names that are fine to use but were pasted raw into rule conditions.
QUOTED_NAMES = (
    "Test Name O'Brien",
    "Test Name Sales' or 'Support",
    "Test Name R&D 'Ops'",
    "Test Name Jos\u00e9\u2019s Team",
)
# frappe.safe_eval NFKC-normalizes code, so a full-width apostrophe (U+FF07)
# turns into a quote there. Such names are refused as team names, but the
# condition builders must still quote them correctly.
FULL_WIDTH_NAME = "Test Name Sales\uff07 or \uff07Support"
# Names the team-name policy refuses.
REFUSED_NAMES = (
    'Test Name Q"A',
    "Test Name a\\b",
    "Test Name a\tb",
    "Test Name a\x01b",
    "Test Name a\u00a0b",
    "Test Name \uff26\uff55\uff4c\uff4c",
    FULL_WIDTH_NAME,
)


class TestHDTeam(FrappeTestCase):
    def test_assignment_rule_created_on_team_insert(self):
        team = make_team("Test AR Creation")
        self.assertTrue(team.assignment_rule)
        self.assertTrue(frappe.db.exists("Assignment Rule", team.assignment_rule))

    def test_conditions_set_on_creation(self):
        team = make_team("Test Conditions Creation")
        ar = frappe.get_doc("Assignment Rule", team.assignment_rule)

        self.assertEqual(
            ar.assign_condition,
            f"status == 'Open' and agent_group == '{team.name}'",
        )
        self.assertIn(team.name, ar.assign_condition_json)

        self.assertEqual(ar.unassign_condition, f"agent_group != '{team.name}'")
        self.assertIn(team.name, ar.unassign_condition_json)
        self.assertIn("!=", ar.unassign_condition_json)

    def test_conditions_updated_on_rename(self):
        team = make_team("Test Conditions Rename Old")
        ar_name = team.assignment_rule
        new_name = "Test Conditions Rename New"

        frappe.rename_doc("HD Team", team.name, new_name)

        ar = frappe.get_doc("Assignment Rule", ar_name)
        self.assertEqual(
            ar.assign_condition,
            f"status == 'Open' and agent_group == '{new_name}'",
        )
        self.assertIn(new_name, ar.assign_condition_json)
        self.assertEqual(ar.unassign_condition, f"agent_group != '{new_name}'")
        self.assertIn(new_name, ar.unassign_condition_json)

    def test_round_robin_users_synced(self):
        agent1 = make_agent("rr_sync_1@example.com")
        agent2 = make_agent("rr_sync_2@example.com")
        team = make_team("Test RR Sync", [agent1, agent2])

        # Both members should be in AR users
        ar = frappe.get_doc("Assignment Rule", team.assignment_rule)
        ar_users = {u.user for u in ar.users}
        self.assertEqual(ar_users, {agent1, agent2})

        # Remove agent2 from team
        team.reload()
        team.users = [u for u in team.users if u.user != agent2]
        team.save(ignore_permissions=True)

        ar.reload()
        ar_users = {u.user for u in ar.users}
        self.assertIn(agent1, ar_users)
        self.assertNotIn(agent2, ar_users)

    def test_weighted_users_synced(self):
        agent1 = make_agent("wd_sync_1@example.com")
        agent2 = make_agent("wd_sync_2@example.com")
        agent3 = make_agent("wd_sync_3@example.com")
        team = make_team("Test Weighted Sync", [agent1, agent2])

        # Switch AR to Weighted Distribution
        ar = frappe.get_doc("Assignment Rule", team.assignment_rule)
        ar.rule = "Weighted Distribution"
        ar.save(ignore_permissions=True)

        # Trigger sync by saving team
        team.reload()
        team.save(ignore_permissions=True)

        ar.reload()
        ar_weighted = {u.user for u in ar.weighted_users}
        self.assertEqual(ar_weighted, {agent1, agent2})

        # Set agent1's weight directly in DB — no hooks triggered
        row = next(r for r in ar.weighted_users if r.user == agent1)
        frappe.db.set_value("Assignment Rule User", row.name, "weight", 5)

        # Add agent3 — triggers resync
        team.reload()
        team.append("users", {"user": agent3})
        team.save(ignore_permissions=True)

        ar.reload()
        preserved = next((r for r in ar.weighted_users if r.user == agent1), None)
        self.assertIsNotNone(preserved)
        self.assertEqual(preserved.weight, 5)

        added = next((r for r in ar.weighted_users if r.user == agent3), None)
        self.assertIsNotNone(added)
        self.assertEqual(added.weight, 1)

        # Remove agent2 — triggers resync
        team.reload()
        team.users = [u for u in team.users if u.user != agent2]
        team.save(ignore_permissions=True)

        ar.reload()
        ar_weighted = {u.user for u in ar.weighted_users}
        self.assertIn(agent1, ar_weighted)
        self.assertIn(agent3, ar_weighted)
        self.assertNotIn(agent2, ar_weighted)

    def test_assignment_rule_enabled_disabled(self):
        team = make_team("Test AR Enable Disable")
        ar = frappe.get_doc("Assignment Rule", team.assignment_rule)
        self.assertFalse(ar.disabled)

        team.disabled = True
        team.save(ignore_permissions=True)
        ar.reload()
        self.assertTrue(ar.disabled)

        team.disabled = False
        team.save(ignore_permissions=True)
        ar.reload()
        self.assertFalse(ar.disabled)

        team2 = make_team("Test AR Enable Disable 2", disabled=True)
        ar2 = frappe.get_doc("Assignment Rule", team2.assignment_rule)
        self.assertTrue(ar2.disabled)

    def test_member_change_keeps_rule_disabled(self):
        team = make_team("Test AR Keep Disabled")
        frappe.db.set_value("Assignment Rule", team.assignment_rule, "disabled", 1)

        agent = make_agent("keep_disabled_agent@example.com")
        team.reload()
        team.append("users", {"user": agent})
        team.save(ignore_permissions=True)

        ar = frappe.get_doc("Assignment Rule", team.assignment_rule)
        self.assertTrue(ar.disabled)
        self.assertIn(agent, [u.user for u in ar.users])


class TestHDTeamRights(FrappeTestCase):
    """Only Agent Managers and System Managers create, change, rename, share or
    delete teams. A team's hooks rewrite its Assignment Rule with
    ignore_permissions, so team rights are routing rights."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = make_agent("team_rights_agent@example.com")
        self.member = make_agent("team_rights_member@example.com")
        self.manager = make_agent_manager("team_rights_manager@example.com")
        self.team = make_team("Test Rights Team", [self.member], disabled=True).name
        self.rule_state = get_team_rule_state(self.team)

    def tearDown(self):
        frappe.set_user("Administrator")
        for team in frappe.get_all(
            "HD Team", filters={"name": ["like", "Test Rights%"]}, pluck="name"
        ):
            frappe.delete_doc("HD Team", team, force=True, ignore_permissions=True)

    def assertTeamUnchanged(self):
        self.assertTrue(frappe.db.exists("HD Team", self.team))
        self.assertEqual(get_team_rule_state(self.team), self.rule_state)
        team = frappe.get_doc("HD Team", self.team)
        self.assertEqual([row.user for row in team.users], [self.member])
        self.assertEqual(team.disabled, 1)
        self.assertEqual(team.ignore_restrictions, 0)

    def test_agent_cannot_create_team(self):
        with self.assertRaises(frappe.PermissionError):
            make_team_as(self.agent, "Test Rights New", [self.agent])

        self.assertFalse(frappe.db.exists("HD Team", "Test Rights New"))

    def test_agent_cannot_update_team(self):
        changes = {
            "users": {"users": [{"user": self.member}, {"user": self.agent}]},
            "ignore_restrictions": {"ignore_restrictions": 1},
            "disabled": {"disabled": 0},
        }
        for field, values in changes.items():
            with self.subTest(field=field):
                frappe.db.savepoint("team_rights_update")
                try:
                    with self.assertRaises(frappe.PermissionError):
                        update_team_as(self.agent, self.team, **values)
                finally:
                    frappe.db.rollback(save_point="team_rights_update")
                self.assertTeamUnchanged()

    def test_agent_cannot_rename_team(self):
        frappe.db.savepoint("team_rights_rename")
        try:
            with self.assertRaisesRegex(frappe.ValidationError, "write permission"):
                rename_team_as(self.agent, self.team, "Test Rights Renamed")
        finally:
            frappe.db.rollback(save_point="team_rights_rename")

        self.assertFalse(frappe.db.exists("HD Team", "Test Rights Renamed"))
        self.assertTeamUnchanged()

    def test_agent_cannot_delete_team(self):
        frappe.db.savepoint("team_rights_delete")
        try:
            with self.assertRaises(frappe.PermissionError):
                delete_team_as(self.agent, self.team)
        finally:
            frappe.db.rollback(save_point="team_rights_delete")

        self.assertTeamUnchanged()

    def test_agent_cannot_share_team(self):
        with self.assertRaises(frappe.PermissionError):
            share_team_as(self.agent, self.team, self.agent)

        self.assertFalse(
            frappe.db.exists(
                "DocShare", {"share_doctype": "HD Team", "share_name": self.team}
            )
        )

    def test_agent_can_still_read_teams(self):
        frappe.set_user(self.agent)
        try:
            self.assertEqual(client_get("HD Team", self.team)["name"], self.team)
            rows = client_get_list("HD Team", filters={"name": self.team})
            self.assertEqual([row["name"] for row in rows], [self.team])
            self.assertEqual(get_team_members(self.team), [self.member])
        finally:
            frappe.set_user("Administrator")

    def test_agent_manager_can_manage_teams(self):
        self.assertNotIn("System Manager", user_roles(self.manager))

        make_team_as(self.manager, "Test Rights Managed", [self.member])
        self.assertTrue(frappe.db.exists("HD Team", "Test Rights Managed"))

        update_team_as(
            self.manager,
            "Test Rights Managed",
            users=[{"user": self.member}, {"user": self.agent}],
            ignore_restrictions=1,
            disabled=1,
        )
        state = get_team_rule_state("Test Rights Managed")
        self.assertEqual(state["users"], sorted([self.member, self.agent]))
        self.assertEqual(state["disabled"], 1)

        rename_team_as(self.manager, "Test Rights Managed", "Test Rights Renamed")
        self.assertTrue(frappe.db.exists("HD Team", "Test Rights Renamed"))
        rule = get_team_rule_state("Test Rights Renamed")["name"]

        delete_team_as(self.manager, "Test Rights Renamed")
        self.assertFalse(frappe.db.exists("HD Team", "Test Rights Renamed"))
        self.assertFalse(frappe.db.exists("Assignment Rule", rule))

    def test_team_changes_are_tracked(self):
        def versions():
            return frappe.db.count(
                "Version", {"ref_doctype": "HD Team", "docname": self.team}
            )

        before = versions()
        team = frappe.get_doc("HD Team", self.team)
        team.ignore_restrictions = 1
        team.save(ignore_permissions=True, ignore_version=False)

        self.assertEqual(versions(), before + 1)


class TestHDTeamNames(FrappeTestCase):
    """A team's rule conditions are built from its quoted name, so any name
    routes only its own tickets, and names that can't be quoted safely
    everywhere are refused."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.agent = make_agent("team_names_agent@example.com")

    def tearDown(self):
        frappe.set_user("Administrator")
        # Crafted names: never leave their rules behind for other modules.
        for team in frappe.get_all(
            "HD Team", filters={"name": ["like", "Test Name%"]}, pluck="name"
        ):
            frappe.delete_doc("HD Team", team, force=True, ignore_permissions=True)

    def assertRoutesOnly(self, state: dict, team_name: str):
        others = (*QUOTED_NAMES, FULL_WIDTH_NAME, "Test Name Other", "Support")
        for other in others:
            ticket = {"status": "Open", "agent_group": other}
            with self.subTest(team=team_name, ticket_team=other):
                self.assertEqual(
                    bool(frappe.safe_eval(state["assign_condition"], None, ticket)),
                    other == team_name,
                )
                self.assertEqual(
                    bool(frappe.safe_eval(state["unassign_condition"], None, ticket)),
                    other != team_name,
                )
        closed = {"status": "Closed", "agent_group": team_name}
        self.assertFalse(frappe.safe_eval(state["assign_condition"], None, closed))
        self.assertEqual(
            json.loads(state["assign_condition_json"]),
            [["status", "==", "Open"], "and", ["agent_group", "==", team_name]],
        )
        self.assertEqual(
            json.loads(state["unassign_condition_json"]),
            [["agent_group", "!=", team_name]],
        )

    def test_quoted_names_route_only_their_own_tickets(self):
        for name in QUOTED_NAMES:
            make_team(name, [self.agent], disabled=True)
            self.assertRoutesOnly(get_team_rule_state(name), name)

    def test_renamed_quoted_names_route_only_their_own_tickets(self):
        for i, name in enumerate(QUOTED_NAMES):
            old = make_team(f"Test Name Plain {i}", [self.agent], disabled=True).name
            frappe.rename_doc("HD Team", old, name)
            self.assertRoutesOnly(get_team_rule_state(name), name)

    def test_condition_builders_quote_any_name(self):
        for name in (*QUOTED_NAMES, *REFUSED_NAMES):
            condition, condition_json = HDTeam.assign_condition(name)
            unassign, unassign_json = HDTeam.unassign_condition(name)
            self.assertRoutesOnly(
                {
                    "assign_condition": condition,
                    "assign_condition_json": condition_json,
                    "unassign_condition": unassign,
                    "unassign_condition_json": unassign_json,
                },
                name,
            )

    def test_refused_names_on_insert(self):
        for name in REFUSED_NAMES:
            with self.subTest(name=name):
                with self.assertRaises(frappe.InvalidNameError):
                    make_team(name, [self.agent], disabled=True)
                self.assertFalse(frappe.db.exists("HD Team", name))

    def test_refused_names_on_rename(self):
        old = make_team("Test Name Before Rename", [self.agent], disabled=True).name
        state = get_team_rule_state(old)
        for name in REFUSED_NAMES:
            with self.subTest(name=name):
                frappe.db.savepoint("team_name_rename")
                try:
                    with self.assertRaises(frappe.InvalidNameError):
                        frappe.rename_doc("HD Team", old, name)
                finally:
                    frappe.db.rollback(save_point="team_name_rename")
                self.assertTrue(frappe.db.exists("HD Team", old))
                self.assertFalse(frappe.db.exists("HD Team", name))
                self.assertEqual(get_team_rule_state(old), state)

    def test_policy_message_does_not_echo_the_name(self):
        for name in ("Test Name <b>x</b>", "Test Name a>b", *REFUSED_NAMES):
            with self.subTest(name=name):
                with self.assertRaises(frappe.InvalidNameError) as refused:
                    HDTeam.validate_team_name(name)
                self.assertNotIn("Test Name", str(refused.exception))

    def test_allowed_names_pass_the_policy(self):
        for name in (*QUOTED_NAMES, "Test Name Caf\u00e9", "Test Name \u201cA\u201d"):
            with self.subTest(name=name):
                HDTeam.validate_team_name(name)

    def test_existing_team_with_a_refused_name_still_saves(self):
        old = make_team("Test Name Legacy", [self.agent], disabled=True).name
        # As if the team predates the policy: a server-side rename skips it.
        legacy = "Test Name Legacy\u00a0Team"
        rename_doc("HD Team", old, legacy, validate=False)

        team = frappe.get_doc("HD Team", legacy)
        team.ignore_restrictions = 1
        team.save(ignore_permissions=True)

        self.assertEqual(
            frappe.db.get_value("HD Team", legacy, "ignore_restrictions"), 1
        )
