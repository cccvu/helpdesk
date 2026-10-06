import re

import frappe
from frappe import _
from frappe.utils import validate_email_address

# A Communication's address lists are Code fields Frappe never sanitizes.
ADDRESS_FIELDS = ("recipients", "cc", "bcc")

# An entry the timeline can render safely: a bare address, or "Display Name
# <address>" with the one "<...>" pair wrapping the address and no "<" or ">"
# anywhere else. The address itself carries no space, "@"-count trouble or
# bracket. Parentheses are allowed in a display name (they render as text), but
# never angle brackets.
_NAMED_ADDRESS = re.compile(r"^[^<>]*<(?P<addr>[^<>()\s@]+@[^<>()\s@]+)>$")


def validate_recipients(doc, method=None):
    """Refuse markup in an Automated Message's recipient, cc and bcc lists.

    /app's form timeline prints an Automated Message's recipients, cc and bcc as
    HTML, one entry at a time, through a microtemplate that doesn't escape
    ({{ frappe.user_info(email).fullname || email }}), and builds it with jQuery
    in the live page. The fields are Code fields Frappe never sanitizes, and
    Frappe validates addresses only for an outgoing "Communication" email, so any
    other type can store script that runs for whoever opens the referenced record.

    The timeline splits each list on "," and renders every entry raw, so validate
    with the same split and fail closed: an entry must be empty, a bare address,
    or "Name <address>" with no "<"/">" but the one pair wrapping the address.
    email.utils.getaddresses is unsafe here — it drops RFC 2822 "(...)" comments
    (so "a@b.com (<img onerror=1>)" would pass with its markup intact) and returns
    ("", "") for hostile input (so the guard would skip it) — both of which carry
    markup past the check to the sink.

    Drop once Frappe escapes these values in the timeline template.
    """
    if doc.get("communication_type") != "Automated Message":
        # Only this type reaches the raw-HTML timeline branch; Frappe validates an
        # outgoing email's own addresses, and a received email's are left as sent.
        return
    for fieldname in ADDRESS_FIELDS:
        value = doc.get(fieldname)
        if not value:
            continue
        for entry in value.split(","):
            if not _is_safe_recipient(entry):
                frappe.throw(
                    _("An automated message has an invalid recipient address."),
                    title=_("Invalid Recipient"),
                )


def _is_safe_recipient(entry):
    entry = entry.strip()
    if not entry:
        # The timeline drops empty entries (e.g. a trailing comma).
        return True
    if "<" in entry or ">" in entry:
        match = _NAMED_ADDRESS.match(entry)
        return bool(match) and bool(validate_email_address(match.group("addr")))
    # No angle brackets: a bare address, which must be a valid email. Any markup
    # character would already have been caught above.
    return bool(validate_email_address(entry))
