from helpdesk.patches.drop_markup_from_stored_html import (
    clean_json_html,
    column_exists,
    report,
    resanitize,
)

FIELDS = ("fields", "filters")


def execute():
    """Sanitize the strings in stored Kanban Board fields and filters.

    Both are Code fields the save-time sanitizer used to skip, and the Kanban
    view shows a card field or filter it doesn't know in a message as HTML
    (helpdesk.extends.document.JSON_HTML_FIELDS). Each row is written with what
    a save would store now, only if it changes and only if the value is still
    the one read; a second run changes nothing (see resanitize).
    """
    for fieldname in FIELDS:
        if column_exists("Kanban Board", fieldname):
            report(
                "Kanban Board",
                fieldname,
                resanitize("Kanban Board", fieldname, clean_json_html),
            )
