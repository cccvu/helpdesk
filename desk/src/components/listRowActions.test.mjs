/**
 * Truth tables for listRowActions.js. Run with:
 *   node --test src/components/listRowActions.test.mjs
 * The parent repo's heavy tests run it with the production image's Node.
 */
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  FILTER_TYPES,
  cellAction,
  cellCondition,
  gridTemplateColumns,
  isEmptyValue,
  parseAssignees,
  resolveTitleKey,
  rowClickIntent,
  trimSelections,
  valueClickIntent,
} from "./listRowActions.js";

const EMPTY = [null, undefined, "", "[]", []];
const ALL_TYPES = [
  "Link",
  "Dynamic Link",
  "Select",
  "Check",
  "Date",
  "MultipleAvatar",
  "Data",
  "Datetime",
  "Small Text",
  "Int",
  "Rating",
  "status",
  undefined,
];
const NON_EMPTY = {
  Link: "Acme",
  "Dynamic Link": "Acme",
  Select: "Open",
  Check: 1,
  Date: "2026-10-01",
  MultipleAvatar: '["a@x"]',
  Data: "text",
  Datetime: "2026-10-01 10:00:00",
  "Small Text": "text",
  Int: 3,
  Rating: 0.8,
  status: "Open",
  undefined: "value",
};

describe("FILTER_TYPES", () => {
  test("is exactly the allowlist", () => {
    assert.deepEqual(
      [...FILTER_TYPES].sort(),
      [
        "Check",
        "Date",
        "Dynamic Link",
        "Link",
        "MultipleAvatar",
        "Select",
      ].sort()
    );
  });
});

describe("isEmptyValue", () => {
  for (const v of EMPTY) {
    test(`${JSON.stringify(v)} is empty`, () => {
      assert.equal(isEmptyValue(v), true);
    });
  }
  for (const v of [0, false, "0", " ", "a", ["a"], '["a"]', {}, "null"]) {
    test(`${JSON.stringify(v)} is not empty`, () => {
      assert.equal(isEmptyValue(v), false);
    });
  }
});

describe("parseAssignees", () => {
  const cases = [
    ['["a@x"]', ["a@x"]],
    ['["a@x","b@x"]', ["a@x", "b@x"]],
    ["[]", []],
    [
      ["a@x", "b@x"],
      ["a@x", "b@x"],
    ],
    [
      [{ name: "a@x" }, { name: "b@x", image: null }],
      ["a@x", "b@x"],
    ],
    ['[{"name":"a@x"}]', ["a@x"]],
    [
      ["a@x", { name: "b@x" }],
      ["a@x", "b@x"],
    ],
    [[], []],
    // Invalid input gives no names.
    ["a@x", []],
    ["not json", []],
    ['["a@x"', []],
    ["null", []],
    ['{"name":"a@x"}', []],
    ['"a@x"', []],
    [null, []],
    [undefined, []],
    [42, []],
    [{ name: "a@x" }, []],
    [[null, 1, "", {}, { name: 3 }, { name: "" }, "a@x"], ["a@x"]],
  ];
  for (const [input, expected] of cases) {
    const name = `${JSON.stringify(input)} → ${JSON.stringify(expected)}`;
    test(name, () => {
      assert.deepEqual(parseAssignees(input), expected);
    });
  }
});

describe("resolveTitleKey", () => {
  const columns = [{ key: "name" }, { key: "subject" }, { key: "status" }];
  test("the preferred key when a column has it", () => {
    assert.equal(resolveTitleKey(columns, "subject"), "subject");
  });
  test("column 0 when no column has the preferred key", () => {
    assert.equal(resolveTitleKey(columns, "title"), "name");
  });
  test("column 0 when nothing is preferred", () => {
    assert.equal(resolveTitleKey(columns), "name");
    assert.equal(resolveTitleKey(columns, undefined), "name");
  });
  test("undefined with no columns", () => {
    assert.equal(resolveTitleKey([], "subject"), undefined);
    assert.equal(resolveTitleKey([]), undefined);
  });
});

describe("cellAction", () => {
  const on = { titleKey: "subject", inlineFilters: true };
  const off = { titleKey: "subject", inlineFilters: false };

  for (const type of ALL_TYPES) {
    const column = { key: "field", type };
    const filters = FILTER_TYPES.has(type);
    test(`${type}: non-empty → ${filters ? "filter" : "none"}`, () => {
      assert.equal(
        cellAction(column, NON_EMPTY[type], on),
        filters ? "filter" : "none"
      );
    });
    for (const v of EMPTY) {
      test(`${type}: ${JSON.stringify(v)} → none`, () => {
        assert.equal(cellAction(column, v, on), "none");
      });
    }
    test(`${type}: inlineFilters false → none`, () => {
      assert.equal(cellAction(column, NON_EMPTY[type], off), "none");
    });
    test(`${type}: the title column → title, whatever the value`, () => {
      const title = { key: "subject", type };
      assert.equal(cellAction(title, NON_EMPTY[type], on), "title");
      assert.equal(cellAction(title, NON_EMPTY[type], off), "title");
      assert.equal(cellAction(title, null, on), "title");
    });
  }

  test("column 0 is the title when it is the resolved title key", () => {
    const columns = [
      { key: "name", type: "Link" },
      { key: "status", type: "Select" },
    ];
    const titleKey = resolveTitleKey(columns, "subject");
    const opts = { titleKey, inlineFilters: true };
    assert.equal(cellAction(columns[0], "42", opts), "title");
    assert.equal(cellAction(columns[1], "Open", opts), "filter");
  });

  test("a MultipleAvatar value with no names → none", () => {
    const column = { key: "_assign", type: "MultipleAvatar" };
    for (const v of ["not json", "null", "{}", '["",null]', [{}], 7]) {
      assert.equal(cellAction(column, v, on), "none", JSON.stringify(v));
    }
    assert.equal(cellAction(column, [{ name: "a@x" }], on), "filter");
    assert.equal(cellAction(column, ["a@x"], on), "filter");
  });

  test("Check 0 is a value, so it filters", () => {
    assert.equal(cellAction({ key: "c", type: "Check" }, 0, on), "filter");
  });
});

describe("cellCondition", () => {
  const avatar = { key: "_assign", type: "MultipleAvatar" };

  test("a value filters with =", () => {
    for (const type of ALL_TYPES.filter((t) => t !== "MultipleAvatar")) {
      const column = { key: "field", type };
      assert.deepEqual(cellCondition(column, NON_EMPTY[type]), [
        "field",
        "=",
        NON_EMPTY[type],
      ]);
    }
    assert.deepEqual(cellCondition({ key: "c", type: "Check" }, 0), [
      "c",
      "=",
      0,
    ]);
  });

  test("an empty value gives no condition", () => {
    for (const type of ALL_TYPES) {
      for (const v of EMPTY) {
        assert.equal(
          cellCondition({ key: "field", type }, v, { assignee: "a@x" }),
          null,
          `${type} ${JSON.stringify(v)}`
        );
      }
    }
  });

  test("an avatar filters LIKE its own name", () => {
    const value = '["a@x","b@x"]';
    assert.deepEqual(cellCondition(avatar, value, { assignee: "b@x" }), [
      "_assign",
      "LIKE",
      "%b@x%",
    ]);
    assert.deepEqual(
      cellCondition(avatar, [{ name: "a@x" }], { assignee: "a@x" }),
      ["_assign", "LIKE", "%a@x%"]
    );
    assert.deepEqual(cellCondition(avatar, ["a@x"], { assignee: "a@x" }), [
      "_assign",
      "LIKE",
      "%a@x%",
    ]);
  });

  test('regression: never %["a@x"]% (the JSON string as the assignee)', () => {
    const value = '["a@x"]';
    assert.equal(cellCondition(avatar, value, { assignee: value }), null);
    assert.equal(cellCondition(avatar, value), null);
    assert.equal(cellCondition(avatar, value, {}), null);
    assert.equal(cellCondition(avatar, value, { assignee: "" }), null);
    assert.deepEqual(cellCondition(avatar, value, { assignee: "a@x" }), [
      "_assign",
      "LIKE",
      "%a@x%",
    ]);
  });

  test('an assignee that is not in the value, or "null", gives none', () => {
    assert.equal(cellCondition(avatar, '["a@x"]', { assignee: "c@x" }), null);
    assert.equal(cellCondition(avatar, '["a@x"]', { assignee: "null" }), null);
    assert.equal(cellCondition(avatar, '["a@x"]', { assignee: null }), null);
    assert.equal(cellCondition(avatar, "not json", { assignee: "a@x" }), null);
  });
});

describe("valueClickIntent", () => {
  const MODIFIERS = [
    ["none", {}],
    ["meta", { metaKey: true }],
    ["ctrl", { ctrlKey: true }],
    ["shift", { shiftKey: true }],
    ["alt", { altKey: true }],
    ["meta+shift", { metaKey: true, shiftKey: true }],
    ["ctrl+alt", { ctrlKey: true, altKey: true }],
  ];
  const POINTERS = ["touch", "mouse", "pen", undefined];

  /** @returns {string} the expected intent, from the interaction spec */
  function expected(button, mods, pointer) {
    if (pointer === "touch") return "open";
    if (button === 1) return "new-tab";
    if (button !== 0) return "ignore";
    if (mods.metaKey || mods.ctrlKey) return "new-tab";
    if (mods.shiftKey || mods.altKey) return "ignore";
    return "filter";
  }

  for (const button of [0, 1, 2]) {
    for (const [label, mods] of MODIFIERS) {
      for (const pointer of POINTERS) {
        const want = expected(button, mods, pointer);
        test(`button ${button}, ${label}, ${pointer} → ${want}`, () => {
          assert.equal(valueClickIntent({ button, ...mods }, pointer), want);
        });
      }
    }
  }

  test("spot checks of the spec", () => {
    assert.equal(valueClickIntent({ button: 0 }, "mouse"), "filter");
    assert.equal(valueClickIntent({ button: 0 }, undefined), "filter");
    assert.equal(valueClickIntent({ button: 0 }), "filter");
    assert.equal(valueClickIntent({ button: 0 }, "touch"), "open");
    assert.equal(valueClickIntent({ button: 0, metaKey: true }), "new-tab");
    assert.equal(valueClickIntent({ button: 0, ctrlKey: true }), "new-tab");
    assert.equal(valueClickIntent({ button: 1 }, "mouse"), "new-tab");
    assert.equal(valueClickIntent({ button: 0, shiftKey: true }), "ignore");
    assert.equal(valueClickIntent({ button: 0, altKey: true }), "ignore");
    assert.equal(valueClickIntent({ button: 2 }, "mouse"), "ignore");
    assert.equal(valueClickIntent({ button: 0 }, "pen"), "filter");
  });
});

describe("rowClickIntent", () => {
  const cases = [
    [{ button: 0 }, "open"],
    [{ button: 0, metaKey: true }, "new-tab"],
    [{ button: 0, ctrlKey: true }, "new-tab"],
    [{ button: 0, metaKey: true, shiftKey: true }, "new-tab"],
    [{ button: 0, ctrlKey: true, altKey: true }, "new-tab"],
    [{ button: 0, shiftKey: true }, "ignore"],
    [{ button: 0, altKey: true }, "ignore"],
    [{ button: 0, shiftKey: true, altKey: true }, "ignore"],
    [{ button: 1 }, "new-tab"],
    [{ button: 1, shiftKey: true }, "new-tab"],
    [{ button: 1, metaKey: true }, "new-tab"],
    [{ button: 2 }, "ignore"],
    [{ button: 2, metaKey: true }, "ignore"],
    [{ button: 2, ctrlKey: true }, "ignore"],
    [{ button: 3 }, "ignore"],
    [{ button: 4 }, "ignore"],
  ];
  for (const [e, want] of cases) {
    test(`${JSON.stringify(e)} → ${want}`, () => {
      assert.equal(rowClickIntent(e), want);
    });
  }
});

describe("trimSelections", () => {
  const flat = [{ name: "1" }, { name: "2" }, { name: "3" }];
  const grouped = [
    { group: { label: "Draft" }, rows: [{ name: "1" }, { name: "2" }] },
    { group: { label: "Published" }, rows: [{ name: "3" }] },
    { group: { label: "Archived" }, rows: [] },
  ];

  for (const [label, rows] of [
    ["flat", flat],
    ["grouped", grouped],
  ]) {
    test(`${label}: names no longer in the rows`, () => {
      assert.deepEqual(trimSelections(new Set(["2", "5", "4"]), rows), [
        "5",
        "4",
      ]);
    });
    test(`${label}: nothing when every selection is shown`, () => {
      assert.deepEqual(trimSelections(new Set(["1", "3"]), rows), []);
    });
    test(`${label}: empty selection`, () => {
      assert.deepEqual(trimSelections(new Set(), rows), []);
    });
  }

  test("no rows: every selection", () => {
    assert.deepEqual(trimSelections(new Set(["1", "2"]), []), ["1", "2"]);
  });

  test("an array selection works too", () => {
    assert.deepEqual(trimSelections(["1", "9"], flat), ["9"]);
  });

  test("a custom row key", () => {
    const rows = [{ id: "a" }, { id: "b" }];
    assert.deepEqual(trimSelections(new Set(["a", "c"]), rows, "id"), ["c"]);
    assert.deepEqual(
      trimSelections(new Set(["a", "c"]), [{ group: "g", rows }], "id"),
      ["c"]
    );
  });

  test("names are compared exactly", () => {
    assert.deepEqual(trimSelections(new Set(["1"]), [{ name: 1 }]), ["1"]);
  });
});

describe("gridTemplateColumns", () => {
  // frappe-ui 1.0.0-beta.24 src/components/ListView/utils.js, verbatim.
  function getGridTemplateColumns(columns, withCheckbox = true) {
    let checkBoxWidth = withCheckbox ? "14px " : "";
    let columnsWidth = columns
      .map((col) => {
        let width = col.width || 1;
        if (typeof width === "number") {
          return width + "fr";
        }
        return width;
      })
      .join(" ");
    return checkBoxWidth + columnsWidth;
  }

  const cases = [
    [],
    [{}],
    [{ width: 2 }],
    [{ width: 0.5 }],
    [{ width: 0 }],
    [{ width: "10rem" }],
    [{ width: "120px" }],
    [{ width: "" }],
    [{ width: null }],
    [{ width: 3 }, { width: "8rem" }, {}, { width: 1.5 }, { width: "auto" }],
  ];
  for (const columns of cases) {
    for (const withCheckbox of [true, false]) {
      test(`${JSON.stringify(columns)}, checkbox ${withCheckbox}`, () => {
        assert.equal(
          gridTemplateColumns(columns, withCheckbox),
          getGridTemplateColumns(columns, withCheckbox)
        );
      });
    }
  }

  test("the checkbox column is on by default", () => {
    assert.equal(gridTemplateColumns([{ width: 2 }]), "14px 2fr");
    assert.equal(
      gridTemplateColumns([{ width: 2 }, { width: "8rem" }, {}], false),
      "2fr 8rem 1fr"
    );
  });
});
