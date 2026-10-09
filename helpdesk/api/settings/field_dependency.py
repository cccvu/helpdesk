import json
import re

import frappe
from frappe import _

# Only these HD Ticket fields can drive or be filtered by a field dependency.
DEPENDENCY_FIELDTYPES = ("Link", "Select")
# The trailer lines that keep the settings page's JSON in the script. They
# are matched at the start of a line, and the last one wins.
FIELDS_CRITERIA_LINE = re.compile(r"^//FieldsCriteria: (.*)$", re.M)
MAPPING_LINE = re.compile(r"^//JSON: (.*)$", re.M)


@frappe.whitelist()
def get_field_dependency(name: str):
    """
    Returns the field dependency for the given name.
    """
    if not name:
        return None

    doc = frappe.get_doc("HD Form Script", name)

    res = frappe._dict()
    res["name"] = doc.name
    res["parent_field"] = doc.name.split("-")[1]
    res["child_field"] = doc.name.split("-")[2]
    res["enabled"] = doc.enabled
    res["parent_child_mapping"] = get_parent_child_mapping(doc.script)
    res["fields_criteria"] = get_fields_criteria(doc.script)

    return res


def get_fields_criteria(script):
    return _read_trailer(FIELDS_CRITERIA_LINE, script)


def get_parent_child_mapping(script):
    return _read_trailer(MAPPING_LINE, script)


def _read_trailer(pattern, script):
    """Returns the JSON value of the last trailer line matching `pattern`,
    or None when there is no such line or it isn't valid JSON."""
    matches = pattern.findall(script or "")
    if not matches:
        return None
    try:
        return frappe.parse_json(matches[-1])
    except ValueError:
        return None


@frappe.whitelist()
def create_update_field_dependency(
    parent_field: str,
    child_field: str,
    parent_child_mapping: str,
    enabled: bool,
    fields_criteria: str,
):
    frappe.has_permission("HD Form Script", "create", throw=True)
    if not parent_field or not child_field or not parent_child_mapping:
        frappe.throw(
            _("Parent field, child field, and parent-child mapping are required.")
        )

    # Checks the fields and the mapping before anything is saved.
    script = build_field_dependency_script(
        parent_field, child_field, parent_child_mapping, fields_criteria
    )

    script_doc = get_or_create_standard_form_script(parent_field, child_field)
    script_doc.enabled = enabled
    script_doc.apply_on_new_page = 1

    old_fields_criteria = get_fields_criteria(script_doc.script)

    script_doc.script = script
    script_doc.save()

    handle_fields_criteria(
        parent_field, child_field, fields_criteria, old_fields_criteria
    )
    # To avoid the message "HD Ticket updated" from showing up
    # frappe.local.message_log = []


def get_or_create_standard_form_script(parent_field, child_field):
    name = f"Field Dependency-{parent_field}-{child_field}"
    if frappe.db.exists("HD Form Script", name):
        return frappe.get_doc("HD Form Script", name)
    else:
        doc = frappe.new_doc("HD Form Script")
        doc.is_standard = 1
        doc.name = name
        return doc


def build_field_dependency_script(
    parent_field, child_field, parent_child_mapping, fields_criteria
):
    """Returns the form script for a field dependency.

    `parent_child_mapping` and `fields_criteria` are the JSON strings the
    settings page sends. They are kept as they are in the trailer lines, so
    the page can show them again.
    """
    validate_dependency_fields(parent_field, child_field)
    mapping = parse_parent_child_mapping(parent_child_mapping)
    if fields_criteria is not None and not isinstance(fields_criteria, str):
        frappe.throw(
            _("Fields criteria must be a JSON string."), frappe.ValidationError
        )

    func = generate_on_change_function(
        parent_child_mapping=mapping,
        parent_field=parent_field,
        child_field=child_field,
    )
    script = add_function_to_script(
        parent_field,
        child_field,
        func,
    )
    # add JSON for UI
    script += "\n"
    script += "// This JSON is to render the field dependency in the UI.\n"
    script += "//FieldsCriteria: " + frappe.as_json(fields_criteria) + "\n"
    script += "//JSON: " + frappe.as_json(parent_child_mapping) + "\n"
    return script


def validate_dependency_fields(parent_field, child_field):
    """Both fields must be different Link or Select fields of HD Ticket."""
    meta = frappe.get_meta("HD Ticket")
    for fieldname in (parent_field, child_field):
        field = (
            meta.get_field(fieldname)
            if isinstance(fieldname, str) and fieldname.isidentifier()
            else None
        )
        if not field or field.fieldtype not in DEPENDENCY_FIELDTYPES:
            frappe.throw(
                _("Field dependencies can only use Link and Select fields of tickets."),
                frappe.ValidationError,
            )
    if parent_field == child_field:
        frappe.throw(
            _("The parent and child fields must be different."),
            frappe.ValidationError,
        )


def parse_parent_child_mapping(parent_child_mapping):
    """Returns the mapping as a dict of parent value to a list of child values."""
    try:
        mapping = json.loads(parent_child_mapping)
    except (TypeError, ValueError):
        mapping = None

    if not (
        isinstance(mapping, dict)
        and mapping
        and all(
            isinstance(children, list)
            and all(isinstance(child, str) for child in children)
            for children in mapping.values()
        )
    ):
        frappe.throw(
            _(
                "The parent-child mapping must map each parent value to a list of child values."
            ),
            frappe.ValidationError,
        )
    return mapping


def js_string(value):
    """Returns `value` as a JavaScript string literal."""
    return json.dumps(str(value))


def generate_on_change_function(parent_child_mapping, parent_field, child_field):
    validate_dependency_fields(parent_field, child_field)
    script = f"function update_{child_field}(value){{\n"
    first = True
    for parent, children in parent_child_mapping.items():
        options = ",".join([js_string(child) for child in children])
        if first:
            script += f"        if(value=={js_string(parent)}) {{\n"
            first = False
        else:
            script += f"        else if(value=={js_string(parent)}) {{\n"

        script += f"            options = [{options}]\n"
        script += f"            applyFilters({js_string(child_field)},options)\n"
        script += "        }\n"
        script += "\n"
    script += "        else {\n"
    script += f"            applyFilters({js_string(child_field)},[])\n"
    script += "        }\n"

    script += "    }\n"
    script += "\n"
    return script


def add_function_to_script(parent_field, child_field, func):
    validate_dependency_fields(parent_field, child_field)
    script = "// This script is auto-generated by the Field Dependency feature. \n"
    script += "// It is not meant to be modified directly. \n"
    script += "\n"

    script += "function setupForm({doc, updateField, call, router, toast, $dialog, createToast ,applyFilters}) {"
    script += "\n"
    script += "\n"
    script += f"    {func}"
    script += "\n"
    script += f"""   return {{
        onChange: {{
            {parent_field}: (newVal) => update_{child_field}(newVal)
        }}
    }}
    """
    script += "\n"
    script += "}"
    return script


def handle_fields_criteria(
    parent_field, child_field, fields_criteria, old_fields_criteria
):

    if frappe.as_json(fields_criteria) == frappe.as_json(old_fields_criteria):
        return
    # A script saved without criteria has nothing to apply.
    if not fields_criteria:
        return

    fields_criteria = frappe.parse_json(fields_criteria)
    if not isinstance(fields_criteria, dict):
        return
    display_depends_on = fields_criteria.get("display") or {}
    mandatory_depends_on = fields_criteria.get("mandatory") or {}

    if not display_depends_on and not mandatory_depends_on:
        return

    display_expression = get_df_expression(
        parent_field, child_field, display_depends_on
    )
    mandatory_expression = get_df_expression(
        parent_field, child_field, mandatory_depends_on
    )

    handle_form_customization(child_field, display_expression, mandatory_expression)


def get_df_expression(parent_field, child_field, criteria):
    if not isinstance(criteria, dict) or not criteria.get("enabled", False):
        return None
    values = criteria.get("value") or []

    values = [
        v.get("value")
        for v in values
        if isinstance(v, dict) and isinstance(v.get("value"), str)
    ]
    if len(values) == 0:
        return None
    # The expression names the parent field, and the values are written
    # with repr, which quotes and escapes them.
    validate_dependency_fields(parent_field, child_field)
    expression = ""
    if values[0] == "Any":
        expression = f"eval:doc.{parent_field} != ''"
    else:
        expression = f"eval:{values}.includes(doc.{parent_field})"

    return expression


def handle_form_customization(field, display_expression, mandatory_expression):
    cf = frappe.get_doc("Customize Form")
    cf.doc_type = "HD Ticket"
    cf.fetch_to_customize()
    for f in cf.fields:
        if f.fieldname == field:
            f.depends_on = display_expression
            f.mandatory_depends_on = mandatory_expression

    cf.save_customization()
    frappe.clear_cache("HD Ticket")
