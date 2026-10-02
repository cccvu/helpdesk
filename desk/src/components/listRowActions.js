/**
 * Pure logic behind list rows: which cells filter, what a click on a row or
 * on a filter value means, and the grid every row and the header share.
 *
 * Plain ESM with no imports, so `node --test` runs its tests with no build
 * step: node --test src/components/listRowActions.test.mjs
 */

/**
 * @typedef {{ key: string, type?: string, width?: number | string }} Column
 * @typedef {"title" | "filter" | "none"} CellAction
 * @typedef {[string, string, unknown]} Condition
 * @typedef {{ button: number, metaKey?: boolean, ctrlKey?: boolean,
 *   shiftKey?: boolean, altKey?: boolean }} ClickLike
 */

/**
 * Column types whose values filter on click. An allowlist: a type that is not
 * here never filters.
 * @type {ReadonlySet<string>}
 */
export const FILTER_TYPES = new Set([
  "Link",
  "Dynamic Link",
  "Select",
  "Check",
  "Date",
  "MultipleAvatar",
]);

/**
 * @param {unknown} v
 * @returns {boolean}
 */
export function isEmptyValue(v) {
  return (
    v === null ||
    v === undefined ||
    v === "" ||
    v === "[]" ||
    (Array.isArray(v) && v.length === 0)
  );
}

/**
 * Assignee names from an `_assign` value: a JSON string, an array of names or
 * an array of `{ name }` objects. Anything else gives no names.
 * @param {unknown} v
 * @returns {string[]}
 */
export function parseAssignees(v) {
  let list = v;
  if (typeof v === "string") {
    try {
      list = JSON.parse(v);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(list)) return [];
  return list
    .map((entry) => (entry && typeof entry === "object" ? entry.name : entry))
    .filter((name) => typeof name === "string" && name !== "");
}

/**
 * The key of the column that holds the row's link: `preferred` when a column
 * has it, otherwise the first column's.
 * @param {Column[]} columns
 * @param {string} [preferred]
 * @returns {string | undefined}
 */
export function resolveTitleKey(columns, preferred) {
  if (columns.some((column) => column.key === preferred)) return preferred;
  return columns[0]?.key;
}

/**
 * @param {Column} column
 * @param {unknown} value
 * @param {{ titleKey?: string, inlineFilters: boolean }} options
 * @returns {CellAction}
 */
export function cellAction(column, value, { titleKey, inlineFilters }) {
  if (column.key === titleKey) return "title";
  if (
    !inlineFilters ||
    !FILTER_TYPES.has(column.type) ||
    isEmptyValue(value) ||
    (column.type === "MultipleAvatar" && parseAssignees(value).length === 0)
  ) {
    return "none";
  }
  return "filter";
}

/**
 * The filter a click on a cell's value applies, or null for none.
 * @param {Column} column
 * @param {unknown} value
 * @param {{ assignee?: string }} [options] the clicked avatar's name
 * @returns {Condition | null}
 */
export function cellCondition(column, value, { assignee } = {}) {
  if (column.type === "MultipleAvatar") {
    return assignee && parseAssignees(value).includes(assignee)
      ? [column.key, "LIKE", `%${assignee}%`]
      : null;
  }
  if (isEmptyValue(value)) return null;
  return [column.key, "=", value];
}

/**
 * What a click on a filter value means. `lastPointerType` is the value
 * button's last `pointerdown` pointerType: a click's own is missing in older
 * Safari and Firefox.
 * @param {ClickLike} e
 * @param {string} [lastPointerType]
 * @returns {"filter" | "open" | "new-tab" | "ignore"}
 */
export function valueClickIntent(e, lastPointerType) {
  if (lastPointerType === "touch") return "open";
  if (e.button === 1) return "new-tab";
  if (e.button !== 0) return "ignore";
  if (e.metaKey || e.ctrlKey) return "new-tab";
  if (e.shiftKey || e.altKey) return "ignore";
  return "filter";
}

/**
 * What a click on the row surface (outside its link and controls) means.
 * @param {ClickLike} e
 * @returns {"open" | "new-tab" | "ignore"}
 */
export function rowClickIntent(e) {
  if (e.button === 1 || (e.button === 0 && (e.metaKey || e.ctrlKey))) {
    return "new-tab";
  }
  if (e.button === 0 && !e.shiftKey && !e.altKey) return "open";
  return "ignore";
}

/**
 * The selected names that are not among `rows`, flat or grouped
 * (`{ group, rows }`), in selection order.
 * @param {Iterable<string>} selected
 * @param {Array<Record<string, any>>} rows
 * @param {string} [rowKey]
 * @returns {string[]}
 */
export function trimSelections(selected, rows, rowKey = "name") {
  const present = new Set();
  for (const item of rows) {
    // frappe-ui ListView's own test for a group.
    const isGroup = item?.group && Array.isArray(item.rows);
    for (const row of isGroup ? item.rows : [item]) {
      if (row) present.add(row[rowKey]);
    }
  }
  return [...selected].filter((name) => !present.has(name));
}

/**
 * frappe-ui's ListView `getGridTemplateColumns`, copied verbatim in behaviour.
 * @param {Array<{ width?: number | string }>} columns
 * @param {boolean} [withCheckbox]
 * @returns {string}
 */
export function gridTemplateColumns(columns, withCheckbox = true) {
  const checkBoxWidth = withCheckbox ? "14px " : "";
  const columnsWidth = columns
    .map((col) => {
      const width = col.width || 1;
      if (typeof width === "number") {
        return width + "fr";
      }
      return width;
    })
    .join(" ");
  return checkBoxWidth + columnsWidth;
}
