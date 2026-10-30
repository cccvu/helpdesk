from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.api.search import get_filter_options, search
from helpdesk.search_sqlite import HelpdeskSearch
from helpdesk.test_utils import (
    add_comment,
    add_message,
    create_user,
    make_agent,
    make_ticket,
)

RESTRICTED_USER = "helpdesk-search-user@example.com"


class TestSearchPermissionFilter(FrappeTestCase):
    """Under PREFILTER_LIMIT the permission filter binds exactly; over it,
    _drop_unpermitted gates the results instead."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # HD Customer grants doctype-level read; row visibility still comes from
        # the permission query. A role-less user cannot get_list at all.
        create_user(RESTRICTED_USER).add_roles("HD Customer")
        cls.own_ticket = make_ticket(
            subject="Search perm own", raised_by=RESTRICTED_USER
        )
        cls.other_ticket = make_ticket(subject="Search perm other")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_small_sites_bind_an_exact_prefilter(self):
        search = HelpdeskSearch()
        filters = search.get_search_filters()

        self.assertIn(self.own_ticket.name, filters["reference_ticket"])
        self.assertFalse(search.is_post_filter_required)

    def test_large_sites_skip_the_prefilter_and_flag_post_filtering(self):
        search = HelpdeskSearch()
        with patch("helpdesk.search_sqlite.PREFILTER_LIMIT", 1):
            filters = search.get_search_filters()

        self.assertEqual(filters, {})
        self.assertTrue(search.is_post_filter_required)

    def test_post_filter_drops_tickets_the_user_cannot_see(self):
        rows = [
            {"reference_ticket": self.own_ticket.name},
            {"reference_ticket": self.other_ticket.name},
            # Communication rows carry the ticket in reference_name only.
            {"reference_ticket": None, "reference_name": self.own_ticket.name},
            # No resolvable ticket: must fail closed.
            {"reference_ticket": None, "reference_name": None},
        ]

        frappe.set_user(RESTRICTED_USER)
        kept = HelpdeskSearch()._drop_unpermitted(rows)

        self.assertEqual(
            [HelpdeskSearch._ticket_of(r) for r in kept],
            [self.own_ticket.name, self.own_ticket.name],
        )

    def test_filter_options_bind_a_constant_number_of_variables(self):
        """Runs the json_each facets query for real."""
        options = HelpdeskSearch().get_filter_options()

        self.assertEqual(
            set(options), {"teams", "statuses", "priorities", "customers", "doctypes"}
        )


NOTE_WORD = "zebracornnote"
NOTE_INDEX = "test_note_search.db"
NOTE_AGENT = "helpdesk-search-agent@example.com"


class TestSearchHidesNotesFromNonAgents(FrappeTestCase):
    """Notes (HD Ticket Comment) are internal: search never finds them for
    anyone but agents, even on tickets they can read. Runs against a
    throwaway index so the site's own one is never touched."""

    def setUp(self):
        create_user(RESTRICTED_USER).add_roles("HD Customer")
        make_agent(NOTE_AGENT)
        self.index = HelpdeskSearch(db_name=NOTE_INDEX)
        self.index.drop_index()
        self.index._ensure_fts_table()
        self.addCleanup(self.index.drop_index)

        ticket = make_ticket(
            subject="Search note test",
            description=f"Ticket {NOTE_WORD}",
            raised_by=RESTRICTED_USER,
        )
        note = add_comment(ticket.name, f"Internal {NOTE_WORD}")
        add_message(ticket.name, "Sent", NOTE_AGENT, subject=f"Mail {NOTE_WORD}")
        mail = frappe.db.get_value(
            "Communication",
            {"reference_name": ticket.name, "subject": f"Mail {NOTE_WORD}"},
            "name",
        )
        for doctype, name in (
            ("HD Ticket", ticket.name),
            ("HD Ticket Comment", note.name),
            ("Communication", mail),
        ):
            self.index.index_doc(doctype, name)

        searches = patch(
            "helpdesk.search_sqlite.HelpdeskSearch",
            lambda: HelpdeskSearch(db_name=NOTE_INDEX),
        )
        searches.start()
        self.addCleanup(searches.stop)

    def tearDown(self):
        frappe.set_user("Administrator")

    def found_as(self, user: str, filters: str | None = None) -> tuple[list, dict]:
        frappe.set_user(user)
        result = search(NOTE_WORD, filters=filters)
        return [r["doctype"] for r in result["results"]], result["summary"]

    def test_agents_find_notes(self):
        doctypes, _ = self.found_as(NOTE_AGENT)
        self.assertIn("HD Ticket Comment", doctypes)
        self.assertIn("HD Ticket", doctypes)

    def test_others_find_their_tickets_but_no_notes(self):
        doctypes, summary = self.found_as(RESTRICTED_USER)
        self.assertIn("HD Ticket", doctypes)
        self.assertNotIn("HD Ticket Comment", doctypes)
        self.assertEqual(
            summary["total_matches"], len(doctypes), "no count of hidden notes"
        )

    def test_others_find_no_notes_when_results_are_filtered_after_search(self):
        with patch("helpdesk.search_sqlite.PREFILTER_LIMIT", 0):
            doctypes, summary = self.found_as(RESTRICTED_USER)
        self.assertNotIn("HD Ticket Comment", doctypes)
        self.assertEqual(summary["filtered_matches"], len(doctypes))

    def test_others_cannot_ask_for_notes(self):
        doctypes, _ = self.found_as(
            RESTRICTED_USER, filters='{"doctype": "HD Ticket Comment"}'
        )
        self.assertNotIn("HD Ticket Comment", doctypes)

    def test_filter_options_count_no_notes_for_others(self):
        frappe.set_user(RESTRICTED_USER)
        self.assertNotIn("HD Ticket Comment", get_filter_options()["doctypes"])
        frappe.set_user(NOTE_AGENT)
        self.assertIn("HD Ticket Comment", get_filter_options()["doctypes"])
