import time
from html import unescape

import frappe
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.email.email_body import EMBED_PATTERN
from frappe.tests.utils import FrappeTestCase

from helpdesk.file_access import can_read_file_url, disarm_embeds
from helpdesk.test_utils import make_agent, make_private_file, make_ticket

OWNER = "file-owner@example.com"
OTHER = "file-other@example.com"


class TestFileAccess(FrappeTestCase):
    """The File access checks in helpdesk.overrides.file and
    helpdesk.extends.attach_field, and the helper they share."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        make_agent(OWNER, first_name="File Owner")
        make_agent(OTHER, first_name="File Other")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_can_read_file_url(self):
        mine = make_private_file(OWNER)
        self.assertTrue(can_read_file_url(mine.file_url, user=OWNER))
        self.assertTrue(can_read_file_url(mine.file_url, user="Administrator"))
        self.assertFalse(can_read_file_url(mine.file_url, user=OTHER))
        self.assertFalse(can_read_file_url("/private/files/missing.txt", user=OWNER))
        self.assertFalse(can_read_file_url("", user=OWNER))
        # the database matches file_url case-insensitively; files on disk don't
        self.assertFalse(can_read_file_url(mine.file_url.upper(), user=OWNER))

    def test_identical_bytes_from_two_users_share_a_readable_url(self):
        content = frappe.generate_hash().encode()
        first = make_private_file(OWNER, content=content)
        second = make_private_file(OTHER, content=content)
        self.assertEqual(second.file_url, first.file_url)
        self.assertTrue(can_read_file_url(second.file_url, user=OTHER))

        # and the second uploader can still use it in an Attach field
        ticket = make_ticket()
        frappe.set_user(OTHER)
        ticket.reload()
        ticket.attachment = second.file_url
        ticket.save()

    def test_file_url_and_owner_cannot_change(self):
        victim = make_private_file(OWNER)
        ticket = make_ticket()
        mine = make_private_file(
            OTHER, attached_to_doctype="HD Ticket", attached_to_name=ticket.name
        )
        frappe.set_user(OTHER)
        for fieldname, value in (("file_url", victim.file_url), ("owner", OWNER)):
            with self.subTest(fieldname):
                doc = frappe.get_doc("File", mine.name)
                doc.set(fieldname, value)
                with self.assertRaises(frappe.PermissionError):
                    doc.save()
        self.assertEqual(frappe.db.get_value("File", mine.name, "owner"), OTHER)

    def test_reattachment_needs_write_on_the_file_and_the_new_document(self):
        ticket = make_ticket()
        victim = make_private_file(OWNER)
        mine = make_private_file(OTHER)
        frappe.set_user(OTHER)

        # someone else's unattached file, onto a ticket the caller can write
        doc = frappe.get_doc("File", victim.name)
        doc.attached_to_doctype, doc.attached_to_name = "HD Ticket", ticket.name
        with self.assertRaises(frappe.PermissionError):
            doc.save()

        # the caller's own file, onto a document the caller can't write
        doc = frappe.get_doc("File", mine.name)
        doc.attached_to_doctype, doc.attached_to_name = "User", OWNER
        with self.assertRaises(frappe.PermissionError):
            doc.save()

        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.get_value("File", victim.name, "attached_to_name"))
        self.assertFalse(frappe.db.get_value("File", mine.name, "attached_to_name"))

    def test_own_file_can_be_attached_to_a_writable_ticket(self):
        ticket = make_ticket()
        mine = make_private_file(OTHER)
        frappe.set_user(OTHER)
        doc = frappe.get_doc("File", mine.name)
        doc.attached_to_doctype, doc.attached_to_name = "HD Ticket", ticket.name
        doc.save()
        self.assertEqual(
            frappe.db.get_value("File", mine.name, "attached_to_name"), ticket.name
        )

    def test_privacy_change_refused_on_a_shared_file(self):
        content = frappe.generate_hash().encode()
        victim = make_private_file(OWNER, content=content)
        twin = make_private_file(OTHER, content=content)
        frappe.set_user(OTHER)

        doc = frappe.get_doc("File", twin.name)
        doc.is_private = 0
        with self.assertRaises(frappe.ValidationError):
            doc.save()

        # a content_hash set by the caller counts too: the rewrite uses it
        doc = frappe.get_doc("File", make_private_file(OTHER).name)
        doc.content_hash = victim.content_hash
        doc.is_private = 0
        with self.assertRaises(frappe.ValidationError):
            doc.save()

        self.assertEqual(
            frappe.db.get_value("File", victim.name, ["is_private", "file_url"]),
            (1, victim.file_url),
        )

    def test_privacy_change_on_an_unshared_own_file(self):
        mine = make_private_file(OWNER)
        frappe.set_user(OWNER)
        doc = frappe.get_doc("File", mine.name)
        doc.is_private = 0
        doc.save()
        # the class's rollback moves the file back to private
        self.assertTrue(doc.file_url.startswith("/files/"))

    def test_optimize_file_works_on_the_stored_record(self):
        victim = make_private_file(OWNER)
        frappe.set_user(OTHER)
        # run_doc_method can build the document from the request
        forged = frappe.get_doc({**victim.as_dict(), "owner": OTHER})
        with self.assertRaises(frappe.PermissionError):
            forged.optimize_file()

    def test_non_canonical_file_url_refused(self):
        victim = make_private_file(OWNER)
        name = victim.file_url.rsplit("/", 1)[1]
        frappe.set_user(OTHER)
        for url in (
            f"/private/files/./{name}",
            f"/private/files//{name}",
            f"/private/files/%2e/{name}",
            f"/private/files/%252e/{name}",
            f"//private/files/{name}",
        ):
            with self.subTest(url):
                file = frappe.get_doc(
                    {"doctype": "File", "file_url": url, "is_private": 1}
                )
                with self.assertRaises(frappe.ValidationError):
                    file.insert(ignore_permissions=True)

    def test_attach_field_refuses_an_unreadable_private_file(self):
        ticket = make_ticket()
        victim = make_private_file(OWNER)
        frappe.set_user(OTHER)
        ticket.reload()
        ticket.attachment = victim.file_url
        with self.assertRaises(frappe.PermissionError):
            ticket.save()
        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.get_value("File", victim.name, "attached_to_name"))

    def test_attach_field_takes_own_upload(self):
        ticket = make_ticket()
        mine = make_private_file(OWNER)
        frappe.set_user(OWNER)
        ticket.reload()
        ticket.attachment = mine.file_url
        ticket.save()
        self.assertEqual(
            frappe.db.get_value("File", mine.name, "attached_to_name"), ticket.name
        )

    def test_case_variant_upload_gets_its_own_url(self):
        """The database matches file_url case-insensitively, so a new file
        whose URL differs from another's only in case would share its rows."""
        name = f"probe{frappe.generate_hash(length=6)}"
        first = make_private_file(OWNER, file_name=f"{name}.txt")
        second = make_private_file(OTHER, file_name=f"{name}.txt".upper())

        self.assertNotEqual(second.file_url.lower(), first.file_url.lower())
        self.assertFalse(can_read_file_url(first.file_url, user=OTHER))
        self.assertFalse(frappe.has_permission("File", "read", doc=first, user=OTHER))
        frappe.set_user(OTHER)
        self.assertIsNone(find_file_by_url(first.file_url))

    def test_file_without_url_or_content_refused(self):
        victim = make_private_file(OWNER)
        frappe.set_user(OTHER)
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": victim.file_url.rsplit("/", 1)[1],
                "is_private": 1,
            }
        )
        with self.assertRaises(frappe.ValidationError):
            file.insert(ignore_permissions=True)

    def test_file_name_fixed_on_a_file_without_url(self):
        """Such a File is read from disk by its file_name."""
        victim = make_private_file(OWNER)
        # made before this check existed, or by a path that skips it
        stray = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "stray.txt",
                "is_private": 1,
            }
        )
        stray.name = frappe.generate_hash(length=10)
        stray.db_insert()
        frappe.db.set_value("File", stray.name, "owner", OTHER)

        frappe.set_user(OTHER)
        doc = frappe.get_doc("File", stray.name)
        doc.file_name = victim.file_url.rsplit("/", 1)[1]
        with self.assertRaises(frappe.PermissionError):
            doc.save()

    def test_disarm_embeds(self):
        kept = "/private/files/kept.png"
        html = (
            # an attribute value hiding a second match inside the first
            "<p title=\"embed='/private/files/a'\" embed=\"embed='/private/files/b'\">"
            f'<img embed="{kept}"></p>'
        )
        self.assertEqual(EMBED_PATTERN.findall(disarm_embeds(html, {kept})), [kept])
        self.assertIsNone(EMBED_PATTERN.search(disarm_embeds(html)))
        self.assertEqual(disarm_embeds(""), "")

    def test_disarm_embeds_compares_unescaped_paths(self):
        """The mail builder unescapes the path it reads."""
        kept = "/private/files/Q&A.png"
        html = '<img embed="/private/files/Q&amp;A.png">'
        self.assertEqual(disarm_embeds(html, {kept}), html)
        self.assertEqual(disarm_embeds(html, {"/private/files/Q&amp;A.png"}), html)
        self.assertIsNone(EMBED_PATTERN.search(disarm_embeds(html)))

    def test_disarm_embeds_matches_inserting_at_each_match(self):
        """Cutting once at the end gives what inserting at each match gave."""

        def reference(html, keep):
            pos = 0
            while match := EMBED_PATTERN.search(html, pos):
                if unescape(match.group(1)) not in keep:
                    cut = match.start() + len("embed")
                    html = html[:cut] + "\u200b" + html[cut:]
                pos = match.start() + 1
            return html

        kept = "/private/files/kept.png"
        html = (
            "<p title=\"embed='/private/files/a'\" embed=\"embed='/private/files/b'\">"
            f'embed="{kept}" text embed=\'/files/c\' <img data-embed="{kept}">'
            "embedembed='x' embed=\"unclosed</p>"
        )
        for keep in (set(), {kept}):
            with self.subTest(keep=keep):
                self.assertEqual(disarm_embeds(html, keep), reference(html, keep))

    def test_disarm_embeds_is_linear(self):
        chunk = '<p embed="/private/files/x.png">a</p>'
        html = chunk * (2**20 // len(chunk))  # about 1 MiB, 28,000 embeds
        started = time.monotonic()
        disarmed = disarm_embeds(html)
        # copying the string once per match took about 30 s
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNone(EMBED_PATTERN.search(disarmed))

    def test_privacy_toggle_cannot_make_a_case_variant_url(self):
        """Frappe's toggle only checks that the exact path is free on disk."""
        name = f"probe{frappe.generate_hash(length=6)}"
        victim = make_private_file(OWNER, file_name=f"{name}.txt")
        public = make_private_file(OTHER, file_name=f"{name}.txt".upper(), is_private=0)
        # a public URL doesn't clash with the private one, so no rename
        self.assertEqual(public.file_url, "/files/" + f"{name}.txt".upper())
        frappe.set_user(OTHER)

        doc = frappe.get_doc("File", public.name)
        doc.is_private = 1
        with self.assertRaises(frappe.ValidationError):
            doc.save()

        frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("File", public.name, "file_url"), public.file_url
        )
        self.assertEqual(
            frappe.db.get_value("File", victim.name, "file_url"), victim.file_url
        )

    def test_mention_mail_embeds_nothing(self):
        notification = frappe.get_doc(
            {
                "doctype": "HD Notification",
                "message": '<p>embed="/private/files/x.png"</p>',
            }
        )
        self.assertIsNone(EMBED_PATTERN.search(notification.parse_html()))

