from html import unescape

import frappe
from frappe.email.email_body import EMBED_PATTERN


def can_read_file_url(file_url: str, user: str | None = None) -> bool:
    """True when `user` (default: the session user) can read at least one File
    whose file_url is exactly `file_url`.

    This is the rule private file downloads use (frappe's `find_file_by_url`):
    rows that share a URL through content dedupe each grant access, so one
    readable row is enough.
    """
    if not file_url:
        return False
    user = user or frappe.session.user
    rows = frappe.get_all(
        "File", filters={"file_url": file_url}, fields=["name", "file_url"]
    )
    for row in rows:
        # the database compares case-insensitively; paths on disk don't
        if row.file_url != file_url:
            continue
        if frappe.get_doc("File", row.name).has_permission("read", user=user):
            return True
    return False


def disarm_embeds(html: str, keep: set[str] | frozenset[str] = frozenset()) -> str:
    """Break every `embed="<path>"` in `html` whose path isn't in `keep`.

    Frappe's mail builder reads every such path from disk into the mail,
    without a permission check, wherever the text appears in the HTML: on any
    tag, in an attribute value or as plain text (`EMBED_PATTERN` in
    frappe.email.email_body). `keep` holds decoded paths; each matched path
    is unescaped once, as the mail builder reads it, and never `keep` again:
    a decoded name can itself look like an entity. A zero-width space after "embed" stops the pattern
    matching, and survives the HTML being parsed and written again. Every
    position a match can start at is checked, so overlapping matches can't
    hide one another.
    """
    if not html:
        return html
    cuts = []
    pos = 0
    while match := EMBED_PATTERN.search(html, pos):
        if unescape(match.group(1)) not in keep:
            cuts.append(match.start() + len("embed"))
        pos = match.start() + 1
    if not cuts:
        return html
    # one join: inserting at each cut would copy the string once per match
    bounds = [0, *cuts, len(html)]
    return "\u200b".join(html[a:b] for a, b in zip(bounds, bounds[1:]))
