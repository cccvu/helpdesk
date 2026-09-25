import frappe
from frappe import _
from frappe.integrations.frappe_providers.frappecloud_billing import is_fc_site
from frappe.utils import cint, get_system_timezone
from frappe.utils.change_log import get_source_url
from frappe.utils.jinja_globals import is_rtl
from frappe.utils.telemetry import capture

from helpdesk.utils import get_agent_name

no_cache = 1


def get_context(context):
    frappe.db.commit()
    context.boot = get_boot()

    # telemetry
    if frappe.session.user != "Guest":
        capture("active_site", "helpdesk")
    return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
    if not frappe.conf.developer_mode:
        frappe.throw(_("This method is only meant for developer mode"))
    return get_boot()


def get_boot():
    return frappe._dict(
        {
            "default_route": get_default_route(),
            "site_name": frappe.local.site,
            "read_only_mode": frappe.flags.read_only,
            "csrf_token": frappe.sessions.get_csrf_token(),
            "setup_complete": cint(frappe.get_system_settings("setup_complete")),
            "is_fc_site": is_fc_site(),
            "session_user": frappe.session.user,
            "agent": get_agent_name(),
            "date_format": frappe.get_system_settings("date_format"),
            "time_format": frappe.get_system_settings("time_format"),
            "default_country": frappe.db.get_default("country"),
            "timezone": {
                "system": get_system_timezone(),
                "user": frappe.db.get_value("User", frappe.session.user, "time_zone")
                or get_system_timezone(),
            },
            "lang": frappe.local.lang,
            "dir": "rtl" if is_rtl() else "ltr",
            "apps": frappe.get_installed_apps(),
            "telemetry": get_telemetry_boot(),
            **get_site_boot(),
        }
    )


def get_site_boot():
    """Site branding and sign-in settings, rendered into index.html so the tab
    shows the site's name and icon before the app loads (None keeps the
    upstream defaults)."""
    return {
        "brand_name": frappe.db.get_single_value("HD Settings", "brand_name"),
        # Same precedence as helpdesk.api.config.get_config, minus its default.
        "favicon": frappe.db.get_single_value("HD Settings", "favicon")
        or frappe.db.get_single_value("Website Settings", "favicon"),
        "disable_user_pass_login": cint(
            frappe.get_system_settings("disable_user_pass_login")
        ),
        "source_url": get_source_url("helpdesk"),
    }


def get_default_route():
    return "/helpdesk"


def get_telemetry_boot():
    """Direct-mode config for the browser telemetry client, as a boot value.

    Telemetry must never break the page: older frappe versions have no pulse
    module, and any boot_config error degrades to "disabled". The key it
    ships is a public write-only ingest key (same as desk boot).
    """
    try:
        from frappe.utils.telemetry.pulse.client import boot_config

        return boot_config()
    except Exception:
        return {"enabled": False}
