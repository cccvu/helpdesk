from frappe.utils import get_url

DEFAULT_REDIRECT_TO_PATH = "/helpdesk"


def keep_redirect_on_site(doc, method=None):
    """Keep a Helpdesk invitation's redirect on this site.

    Accepting an invitation signs the invitee in and redirects them to
    `get_url(doc.get_redirect_to_path())`, which passes absolute URLs through
    and resolves scheme-relative ones off the site. Any redirect that would
    leave the site falls back to the Helpdesk home.

    This normalizes instead of throwing: accepting, cancelling and expiring an
    invitation all save it, and must keep working for a value stored earlier.
    """
    if doc.app_name != "helpdesk":
        return
    if not doc.redirect_to_path:
        doc.redirect_to_path = DEFAULT_REDIRECT_TO_PATH
        return

    base = get_url()
    try:
        target = get_url(doc.get_redirect_to_path())
    except ValueError:  # urljoin refuses a malformed host, such as "//[x"
        doc.redirect_to_path = DEFAULT_REDIRECT_TO_PATH
        return
    if target != base and not target.startswith(base.rstrip("/") + "/"):
        doc.redirect_to_path = DEFAULT_REDIRECT_TO_PATH
