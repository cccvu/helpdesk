import re

from frappe.utils.html_utils import sanitize_html

# Fields the desk timeline renders as HTML, and whether Frappe linkifies each
HTML_FIELDS = {"content": True, "subject": False, "sender_full_name": False}

# Where a browser starts a tag, an end tag or a comment; any other "<" is text
MARKUP = re.compile(r"<[A-Za-z/!?]")


def sanitize_content(doc, method=None):
    """Sanitize a Communication's HTML-bearing fields on every save.

    Runs before validate, which ignore_validate doesn't skip, and again before
    save, after validate may have filled in the sender's name.

    Frappe v15's sanitize_html skips some values that carry HTML: a value that
    parses as JSON, and one in which BeautifulSoup finds no tag. Upstream
    develop sanitizes both (frappe/frappe#41626 and has_html_tags); drop this
    hook once v15 has both.
    """
    for fieldname, linkify in HTML_FIELDS.items():
        value = doc.get(fieldname)
        if isinstance(value, str) and MARKUP.search(value):
            doc.set(
                fieldname, sanitize_html(value, linkify=linkify, always_sanitize=True)
            )
