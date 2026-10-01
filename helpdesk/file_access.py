import frappe


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
