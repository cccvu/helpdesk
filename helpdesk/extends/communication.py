from email.utils import getaddresses

import frappe
from frappe import _
from frappe.utils import validate_email_address

# A Communication's address lists are Code fields Frappe never sanitizes.
ADDRESS_FIELDS = ("recipients", "cc", "bcc")


def validate_recipients(doc, method=None):
    """Refuse markup in an Automated Message's recipient, cc and bcc lists.

    /app's form timeline prints an Automated Message's recipients, cc and bcc as
    HTML, one entry at a time, through a microtemplate that doesn't escape
    ({{ frappe.user_info(email).fullname || email }}), and builds it with jQuery
    in the live page. The fields are Code fields Frappe never sanitizes, and
    Frappe validates addresses only for an outgoing "Communication" email, so any
    other type can store script that runs for whoever opens the referenced record.
    A content sanitizer can't cover this without mangling a
    '"Name" <addr>' recipient, so reject any entry whose address isn't an email
    or whose display name carries markup. Drop once Frappe escapes these values
    in the timeline template.
    """
    if doc.get("communication_type") != "Automated Message":
        # Only this type reaches the raw-HTML timeline branch; Frappe validates an
        # outgoing email's own addresses, and a received email's are left as sent.
        return
    for fieldname in ADDRESS_FIELDS:
        value = doc.get(fieldname)
        if not value:
            continue
        for name, addr in getaddresses([value]):
            if not name and not addr:
                continue
            if "<" in name or ">" in name or not validate_email_address(addr):
                frappe.throw(
                    _("An automated message has an invalid recipient address."),
                    title=_("Invalid Recipient"),
                )
