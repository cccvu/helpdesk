"""Render templates that settings hold, such as mail contents, the Reply-To
address, the outside-hours banner and assignment descriptions, with the data
they are given and nothing else.

`frappe.render_template` gives a template Frappe's server-script globals
(`frappe.get_doc`, `frappe.db.sql`, `frappe.sendmail` and the like), so
whoever writes one can read or change any record. Managers write these
templates, so they render here instead: in a sandbox with no loader, no
Frappe globals and a context of plain values, plus a few read-only helpers
under `frappe.utils`.
"""

import datetime
import decimal
from types import MappingProxyType

import frappe
from frappe.utils import (
    add_days,
    cint,
    cstr,
    escape_html,
    flt,
    fmt_money,
    format_datetime,
    format_time,
    formatdate,
    get_datetime,
    get_url,
    getdate,
    global_date_format,
    markdown,
    now,
    nowdate,
    sha256_hash,
    strip_html,
)
from frappe.utils.safe_exec import UNSAFE_ATTRIBUTES
from frappe.website.utils import abs_url

# Values a template may see as they are. They are immutable and their
# methods only compute; anything else reaches a template as text.
PLAIN_TYPES = frozenset(
    {
        str,
        int,
        float,
        bool,
        type(None),
        decimal.Decimal,
        datetime.date,
        datetime.datetime,
        datetime.time,
        datetime.timedelta,
    }
)

# Read-only helpers under `frappe.utils`: they compute, or read
# configuration and defaults. Not Frappe's SAFE_DATA_UTILS, which reads files.
UTILS = MappingProxyType(
    {
        "sha256_hash": sha256_hash,
        "get_url": get_url,
        "formatdate": formatdate,
        "format_datetime": format_datetime,
        "format_time": format_time,
        "global_date_format": global_date_format,
        "getdate": getdate,
        "get_datetime": get_datetime,
        "nowdate": nowdate,
        "now": now,
        "add_days": add_days,
        "cint": cint,
        "flt": flt,
        "cstr": cstr,
        "fmt_money": fmt_money,
        "escape_html": escape_html,
        "strip_html": strip_html,
    }
)

# Frappe's own filters and its jinja hook filters, listed so no hook adds one
FILTERS = {
    "json": frappe.as_json,
    "len": len,
    "int": cint,
    "str": cstr,
    "flt": flt,
    "global_date_format": global_date_format,
    "markdown": markdown,
    "abs_url": abs_url,
}

_environment = None


def get_environment():
    global _environment
    if _environment is None:
        from jinja2 import DebugUndefined
        from jinja2.sandbox import ImmutableSandboxedEnvironment

        unsafe = UNSAFE_ATTRIBUTES - {"format", "format_map"}

        class DataEnvironment(ImmutableSandboxedEnvironment):
            def is_safe_attribute(self, obj, attr, value):
                if attr in unsafe:
                    return False
                return super().is_safe_attribute(obj, attr, value)

        # No loader: include, import and extends fail. DebugUndefined and no
        # autoescape match Frappe's environment, so output stays the same.
        env = DataEnvironment(undefined=DebugUndefined)
        env.globals.pop("lipsum", None)
        env.filters.update(FILTERS)
        _environment = env
    return _environment


def plain_data(value):
    """A copy of `value` holding only PLAIN_TYPES, lists and `frappe._dict`s
    (so a missing field reads as None, as in Frappe's templates): a document,
    an object with methods or a callable becomes its text."""
    if type(value) in PLAIN_TYPES:
        return value
    if isinstance(value, dict):
        return frappe._dict({cstr(k): plain_data(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return [plain_data(v) for v in value]
    return cstr(value)


def render_data_template(
    template: str | None,
    context: dict,
    *,
    fallback,
    title: str,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
):
    """Render `template` with a plain copy of `context` and `frappe.utils`
    (UTILS) only.

    A bare unknown `{{ name }}` renders as written and a missing field of a
    dict as None; calling or reading an attribute of anything else is an error. On
    any error the template is not shown to anyone: it is logged under
    `title` for System Managers, and `fallback` is returned.
    """
    if not template:
        return ""

    mute_messages = frappe.flags.mute_messages
    frappe.flags.mute_messages = True
    try:
        values = plain_data(dict(context))
        values["frappe"] = MappingProxyType({"utils": UTILS})
        values["_"] = frappe._
        return get_environment().from_string(template).render(values)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        # the transaction is lost; let the caller retry the whole request
        raise
    except Exception:
        frappe.log_error(
            title=title,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
        )
        return fallback
    finally:
        frappe.flags.mute_messages = mute_messages
