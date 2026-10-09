import frappe

from helpdesk.api.settings.field_dependency import (
    build_field_dependency_script,
    get_fields_criteria,
    get_parent_child_mapping,
)


def execute():
    """Rewrite each field-dependency form script with the current generator,
    from the mapping and criteria kept in its trailer lines, so values are
    written as JSON strings.

    A script whose mapping can't be read, or whose name doesn't name two
    different Link or Select fields of HD Ticket, is disabled and otherwise
    left as it is. A missing or unreadable criteria line is written as
    `null`, which reads back as no criteria, as before. Neither the form
    customization nor the modified time is touched, and a second run changes
    nothing.
    """
    scripts = frappe.get_all(
        "HD Form Script",
        filters={"name": ["like", "Field Dependency-%"], "is_standard": 1},
        fields=["name", "script", "enabled"],
    )
    for doc in scripts:
        script = rebuild_script(doc.name, doc.script)
        if script is None:
            if doc.enabled:
                frappe.db.set_value(
                    "HD Form Script", doc.name, "enabled", 0, update_modified=False
                )
                print(f"Disabled HD Form Script {doc.name}: it can't be regenerated")
        elif script != doc.script:
            frappe.db.set_value(
                "HD Form Script", doc.name, "script", script, update_modified=False
            )


def rebuild_script(name, script):
    """Returns the regenerated script, or None if it can't be rebuilt."""
    parts = name.split("-")
    if len(parts) != 3:
        return None
    _, parent_field, child_field = parts

    mapping = get_parent_child_mapping(script)
    if not isinstance(mapping, str):
        return None
    criteria = get_fields_criteria(script)
    if not isinstance(criteria, str):
        criteria = None

    try:
        return build_field_dependency_script(
            parent_field, child_field, mapping, criteria
        )
    except frappe.ValidationError:
        return None
