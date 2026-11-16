/*
 * Output escaping for Frappe v15 desk (/app) sinks that write stored names
 * into HTML unescaped.
 *
 * Frappe v15's desk interpolates some stored, user-controlled names (tags,
 * Kanban column names, document titles, record names, user full names) into
 * HTML attributes and text without escaping them. A plain `"` closes the
 * attribute, so a name like `x" onmouseover="..."` runs script for every
 * desk user who views it. Escaping at render covers existing data and every
 * write path.
 *
 * This file is loaded through `app_include_js`, after Frappe's own desk
 * bundles, which define every target below. Each piece is either a copy of
 * the v15 function with escaping added (markup, colours and translations
 * otherwise unchanged) or a wrapper that escapes a shallow copy of a
 * template's data. Every piece installs under a guard: if its target is
 * missing, its name is recorded in `frappe.ccc_escapes.missing` and logged
 * with `console.error`; installed pieces are recorded in
 * `frappe.ccc_escapes.installed` and the replacement carries
 * `__ccc_escaped = true`, so loading this file twice changes nothing.
 *
 * Upstream status, per piece (drop each once the pinned Frappe v15 escapes
 * it; a bump that changes a copied or wrapped piece must re-sync or drop it,
 * or values would be escaped twice):
 *
 * - get_tags_html (ListView.prototype): list Tags column and Kanban cards.
 *   Escaped on develop by frappe/frappe#46726; v15 backport
 *   frappe/frappe#47326 is open.
 * - Tag (frappe.form.formatters): report view and filter pills. Escaped on
 *   develop/v16 by frappe/frappe#39709, not on v15. This copy mirrors
 *   develop's markup.
 * - get_column_html (ListView.prototype): the Select and Link columns'
 *   `data-filter` value. Unescaped on v15; restructured on develop.
 * - get_dropdown_html (ListGroupBy.prototype): group-by sidebar values.
 *   Unescaped upstream.
 * - avatar_group (frappe): the "+N" title listing extra users' full names.
 *   Unescaped upstream.
 * - render_template (frappe), for three templates only:
 *   - list_sidebar_stat (tag label): escaped on develop by
 *     frappe/frappe#46726; v15 backport frappe/frappe#47326 is open.
 *   - kanban_card (title, image_url): title escaped on develop by
 *     frappe/frappe#36515, not on v15.
 *   - kanban_column (title): unescaped upstream.
 */
(function () {
  "use strict";

  if (typeof frappe === "undefined") {
    console.error("[ccc-desk] escaping shim: frappe missing");
    return;
  }

  const state = (frappe.ccc_escapes = frappe.ccc_escapes || {
    installed: [],
    missing: [],
  });

  function record(list, name) {
    if (!list.includes(name)) list.push(name);
  }

  function report_missing(name) {
    record(state.missing, name);
    console.error(`[ccc-desk] escaping shim: ${name} missing`);
  }

  // Replace owner[key] with make(original), keeping the property's
  // enumerability (class methods are non-enumerable).
  function install(name, get_owner, key, make) {
    let owner;
    try {
      owner = get_owner();
    } catch (e) {
      owner = null;
    }
    const original = owner ? owner[key] : undefined;
    if (typeof original !== "function") {
      report_missing(name);
      return;
    }
    if (original.__ccc_escaped) {
      record(state.installed, name);
      return;
    }
    const replacement = make(original);
    replacement.__ccc_escaped = true;
    const descriptor = Object.getOwnPropertyDescriptor(owner, key);
    if (descriptor && "value" in descriptor) {
      Object.defineProperty(owner, key, {
        value: replacement,
        writable: descriptor.writable,
        enumerable: descriptor.enumerable,
        configurable: descriptor.configurable,
      });
    } else {
      owner[key] = replacement;
    }
    record(state.installed, name);
  }

  if (!frappe.utils || typeof frappe.utils.escape_html !== "function") {
    [
      "get_tags_html",
      "Tag",
      "get_column_html",
      "get_dropdown_html",
      "avatar_group",
      "render_template",
    ].forEach(report_missing);
    return;
  }

  // Frappe v15.121.2, public/js/frappe/list/list_view.js, get_tags_html.
  // Change: the tag is escaped in the title and the text; the palette still
  // hashes the raw tag, so colours are unchanged.
  install(
    "get_tags_html",
    () => frappe.views.ListView.prototype,
    "get_tags_html",
    () =>
      function (user_tags, limit, colored = false) {
        let get_tag_html = (tag) => {
          let color = "",
            style = "";
          if (tag) {
            if (colored) {
              color = frappe.get_palette(tag);
              style = `background-color: var(${color[0]}); color: var(${color[1]})`;
            }

            const escaped_tag = frappe.utils.escape_html(tag);
            return `<div class="tag-pill ellipsis" title="${escaped_tag}" style="${style}">${escaped_tag}</div>`;
          }
        };
        return user_tags
          .split(",")
          .slice(1, limit + 1)
          .map(get_tag_html)
          .join("");
      }
  );

  // Frappe v15.121.2, public/js/frappe/form/formatters.js, formatters.Tag.
  // Change: develop's version (frappe/frappe#39709): the tag is escaped in
  // data-label and the text, and v15's stray `'` after data-label is gone.
  install(
    "Tag",
    () => frappe.form.formatters,
    "Tag",
    () =>
      function (value) {
        var html = "";
        $.each((value || "").split(","), function (i, v) {
          if (v) {
            let ev = frappe.utils.escape_html(v);
            html += `
				<span
					class="data-pill btn-xs align-center ellipsis"
					style="background-color: var(--control-bg); box-shadow: none; margin-right: 4px;"
					data-field="_user_tags" data-label="${ev}">
					${ev}
				</span>`;
          }
        });
        return html;
      }
  );

  // Frappe v15.121.2, public/js/frappe/list/list_view.js, get_column_html.
  // Change: `value` is escaped in the Select and Link branches' data-filter,
  // as the default branch already does.
  install(
    "get_column_html",
    () => frappe.views.ListView.prototype,
    "get_column_html",
    () =>
      function (col, doc) {
        if (col.type === "Status" || col.df?.options == "Workflow State") {
          let show_workflow_state = col.df?.options == "Workflow State";
          return `
				<div class="list-row-col hidden-xs ellipsis">
					${this.get_indicator_html(doc, show_workflow_state)}
				</div>
			`;
        }

        if (col.type === "Tag") {
          const tags_display_class = !this.tags_shown ? "hide" : "";
          let tags_html = doc._user_tags
            ? this.get_tags_html(doc._user_tags, 2, true)
            : '<div class="tags-empty">-</div>';
          return `
				<div class="list-row-col tag-col ${tags_display_class} hidden-xs ellipsis">
					${tags_html}
				</div>
			`;
        }

        const df = col.df || {};
        const label = df.label;
        const fieldname = df.fieldname;
        const link_title_fieldname = this.link_field_title_fields[fieldname];
        const value = doc[fieldname] || "";
        let value_display = link_title_fieldname
          ? doc[fieldname + "_" + link_title_fieldname] || value
          : value;

        let translated_doctypes = frappe.boot?.translated_doctypes || [];
        if (translated_doctypes.includes(df.options)) {
          value_display = __(value_display);
        }

        const format = () => {
          if (df.fieldtype === "Percent") {
            return `<div class="progress" style="margin: 0px;">
						<div class="progress-bar progress-bar-success" role="progressbar"
							aria-valuenow="${value}"
							aria-valuemin="0" aria-valuemax="100" style="width: ${Math.round(value)}%;">
						</div>
					</div>`;
          } else {
            return frappe.format(value, df, null, doc);
          }
        };

        const field_html = () => {
          let html;
          let _value;
          let strip_html_required =
            df.fieldtype == "Text Editor" ||
            (df.fetch_from && ["Text", "Small Text"].includes(df.fieldtype));

          if (strip_html_required) {
            _value = strip_html(value_display);
          } else {
            _value =
              typeof value_display === "string"
                ? frappe.utils.escape_html(value_display)
                : value_display;
          }

          if (df.fieldtype === "Rating") {
            let out_of_ratings = df.options || 5;
            _value = _value * out_of_ratings;
          }

          if (df.fieldtype === "Image") {
            html = df.options
              ? `<img src="${frappe.utils.escape_html(doc[df.options])}"
					style="max-height: 30px; max-width: 100%;">`
              : `<div class="missing-image small">
						${frappe.utils.icon("restriction")}
					</div>`;
          } else if (df.fieldtype === "Select") {
            html = `<span class="filterable indicator-pill ${frappe.utils.guess_colour(
              _value
            )} ellipsis"
					data-filter="${fieldname},=,${frappe.utils.escape_html(value)}">
					<span class="ellipsis"> ${__(_value)} </span>
				</span>`;
          } else if (df.fieldtype === "Link") {
            html = `<a class="filterable ellipsis"
					data-filter="${fieldname},=,${frappe.utils.escape_html(value)}">
					${_value}
				</a>`;
          } else if (frappe.model.html_fieldtypes.includes(df.fieldtype)) {
            html = `<span class="ellipsis">
					${_value}
				</span>`;
          } else {
            html = `<a class="filterable ellipsis"
					data-filter="${fieldname},=,${frappe.utils.escape_html(value)}">
					${format()}
				</a>`;
          }

          return `<span class="ellipsis"
				title="${__(label)}: ${frappe.utils.escape_html(_value)}">
				${html}
			</span>`;
        };

        const class_map = {
          Subject: "list-subject level",
          Field: "hidden-xs",
        };
        const css_class = [
          "list-row-col ellipsis",
          class_map[col.type],
          frappe.model.is_numeric_field(df) ? "text-right" : "",
        ].join(" ");

        let column_html;
        if (
          this.settings.formatters &&
          this.settings.formatters[fieldname] &&
          col.type !== "Subject"
        ) {
          column_html = this.settings.formatters[fieldname](value, df, doc);
        } else {
          column_html = {
            Subject: this.get_subject_element(doc, value_display).innerHTML,
            Field: field_html(),
          }[col.type];
        }

        return `
			<div class="${css_class}">
				${column_html}
			</div>
		`;
      }
  );

  // Frappe v15.121.2, public/js/frappe/list/list_sidebar_group_by.js,
  // get_dropdown_html. Change: the value is escaped in data-name and in the
  // label (translated first, so translations still match).
  install(
    "get_dropdown_html",
    () => frappe.views.ListGroupBy.prototype,
    "get_dropdown_html",
    () =>
      function (field, fieldtype, applied = false) {
        let label;
        if (field.name == null) {
          label = __("Not Set");
        } else if (field.name === frappe.session.user) {
          label = __("Me");
        } else if (fieldtype && fieldtype == "Check") {
          label = field.name == "0" ? __("No") : __("Yes");
        } else {
          label = frappe.utils.escape_html(__(field.name));
        }
        let name_attr =
          field.name == null
            ? field.name
            : frappe.utils.escape_html(field.name);
        let value = field.name == null ? "" : encodeURIComponent(field.name);
        let applied_html = applied
          ? `<span class="applied"> ${frappe.utils.icon("tick", "xs")} </span>`
          : "";
        return `<li class="group-by-item ${
          applied ? "selected" : ""
        }" data-value="${value}">
			<a class="dropdown-item" href="#" onclick="return false;">
				${applied_html}
				<span class="group-by-value ellipsis" data-name="${name_attr}">${label}</span>
				<span class="group-by-count">${field.count}</span>
			</a>
		</li>`;
      }
  );

  // Frappe v15.121.2, public/js/frappe/utils/common.js, avatar_group.
  // Change: the extra users' joined full names are escaped in the title.
  install(
    "avatar_group",
    () => frappe,
    "avatar_group",
    () =>
      function (users, limit = 4, options = {}) {
        let avatar_action_html = "";
        const display_users = users.slice(0, limit);
        const extra_users = users.slice(limit);
        const css_class = options.css_class || "";

        let html = display_users
          .map((user) =>
            frappe.avatar(
              user,
              "avatar-small " + css_class,
              null,
              null,
              false,
              options.filterable
            )
          )
          .join("");
        if (extra_users.length === 1) {
          html += frappe.avatar(
            extra_users[0],
            "avatar-small " + css_class,
            null,
            null,
            false,
            options.filterable
          );
        } else if (extra_users.length > 1) {
          html = `
			${html}
			<span class="avatar avatar-small ${css_class}">
				<div class="avatar-frame standard-image avatar-extra-count"
					title="${frappe.utils.escape_html(
            extra_users.map((u) => frappe.user_info(u).fullname).join(", ")
          )}">
					+${extra_users.length}
				</div>
			</span>
		`;
        }

        if (options.action_icon) {
          avatar_action_html = `
			<span class="avatar avatar-small">
				<div class="avatar-frame avatar-action">
					${frappe.utils.icon(options.action_icon, "sm")}
				</div>
			</span>
		`;
        }

        const $avatar_group = $(`<div class="avatar-group ${
          options.align || "right"
        } ${options.overlap != false ? "overlap" : ""}">
			${html}
			${avatar_action_html}
		</div>`);

        $avatar_group.find(".avatar-action").on("click", options.action);
        return $avatar_group;
      }
  );

  // frappe.render_template (Frappe v15.121.2, public/js/frappe/microtemplate.js)
  // interpolates `{{ }}` without escaping. For the three templates below,
  // escape a shallow copy of the values they write into HTML; the caller's
  // data (the Kanban store, the sidebar stats) keeps raw values. Strings are
  // escaped; null, numbers and booleans pass unchanged, so the templates'
  // truthiness checks behave as before.
  function escape_value(value) {
    if (
      value == null ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return value;
    }
    return frappe.utils.escape_html(value);
  }

  // A shallow copy of data with the named keys escaped (keys it lacks stay
  // absent).
  function escape_keys(data, keys) {
    const copy = Object.assign(
      Object.create(Object.getPrototypeOf(data)),
      data
    );
    for (const key of keys) {
      if (key in copy) copy[key] = escape_value(copy[key]);
    }
    return copy;
  }

  const template_escapes = {
    // list/list_sidebar_stat.html: stats[i][0] in data-label and the text.
    list_sidebar_stat(data) {
      if (!Array.isArray(data.stats)) return data;
      const copy = escape_keys(data, []);
      copy.stats = data.stats.map((row) =>
        Array.isArray(row) ? [escape_value(row[0]), ...row.slice(1)] : row
      );
      return copy;
    },
    // views/kanban/kanban_column.html: title in data-column-value, title
    // and the text.
    kanban_column(data) {
      return escape_keys(data, ["title"]);
    },
    // views/kanban/kanban_card.html: title in alt, title and the text;
    // image_url in src.
    kanban_card(data) {
      return escape_keys(data, ["title", "image_url"]);
    },
  };

  install(
    "render_template",
    () => frappe,
    "render_template",
    (original) =>
      function (name, data) {
        if (
          typeof name === "string" &&
          Object.prototype.hasOwnProperty.call(template_escapes, name) &&
          data &&
          typeof data === "object"
        ) {
          const args = Array.prototype.slice.call(arguments);
          args[1] = template_escapes[name](data);
          return original.apply(this, args);
        }
        return original.apply(this, arguments);
      }
  );
})();
