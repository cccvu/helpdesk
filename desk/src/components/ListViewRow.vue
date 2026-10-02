<template>
  <!--
    The row is not a link (contract C1). Its title cell holds the row's one
    link ([data-row-link]); that link's ::after stretches over the whole row
    (z-[1]), so the row surface is a real link. Controls ([data-row-control])
    and hover-only info ([data-row-peek]) sit above it (relative z-[2]).
  -->
  <div
    ref="rowEl"
    data-list-row
    class="relative flex flex-col transition-colors duration-100 motion-reduce:transition-none [&:hover:not(:has([data-row-control]:hover))_[data-row-link]]:underline"
    :class="[
      roundedClass,
      isSelected ? 'bg-surface-gray-2' : '',
      row.disabled
        ? 'pointer-events-none'
        : isSelected
        ? 'cursor-pointer hover:bg-surface-gray-3'
        : 'cursor-pointer hover:bg-surface-sidebar',
    ]"
    :aria-disabled="row.disabled ? 'true' : undefined"
    @click="rowFallback"
    @auxclick="rowFallbackAux"
    @mousedown="preventPeekAutoscroll"
  >
    <div
      class="grid items-center gap-4 px-2"
      :class="{
        'cursor-not-allowed': row.disabled,
        'opacity-50': row.disabled,
      }"
      :style="{
        height: rowHeight,
        gridTemplateColumns: gridTemplateColumns(
          list.columns,
          list.options.selectable
        ),
      }"
    >
      <label
        v-if="list.options.selectable"
        data-row-control
        class="relative z-[2] flex h-full w-fit cursor-pointer items-center pe-2"
        @click="onCheckboxLabelClick"
        @dblclick.stop
      >
        <Checkbox
          :modelValue="isSelected"
          :disabled="row.disabled"
          class="cursor-pointer"
        />
        <span class="sr-only">{{ __("Select {0}", [titleLabel]) }}</span>
      </label>

      <div
        v-for="(column, i) in list.columns"
        :key="column.key"
        :class="[
          alignmentMap[column.align],
          i == 0 ? 'text-ink-gray-9' : 'text-ink-gray-7',
          'overflow-x-hidden',
        ]"
      >
        <slot v-bind="{ idx: i, column, item: row[column.key], row }" />
      </div>
    </div>

    <div
      v-if="!isLastRow"
      class="h-px border-t"
      :class="
        roundedClass === 'rounded' || roundedClass?.includes?.('rounded-b')
          ? 'mx-2 border-outline-gray-1'
          : 'border-t-[--surface-gray-2]'
      "
    />
  </div>
</template>

<script setup lang="ts">
import { __ } from "@/translation";
import { Checkbox } from "frappe-ui";
import { computed, inject, ref } from "vue";

import { gridTemplateColumns, rowClickIntent } from "./listRowActions.js";

const alignmentMap: Record<string, string> = {
  left: "justify-start",
  start: "justify-start",
  center: "justify-center",
  middle: "justify-center",
  right: "justify-end",
  end: "justify-end",
};

const props = defineProps({
  row: {
    type: Object,
    required: true,
  },
  titleLabel: {
    type: String,
    default: "",
  },
});

// frappe-ui ListView provides it (a computed).
const list = inject<any>("list");
const rowEl = ref<HTMLElement | null>(null);

const IGNORE =
  "[data-row-link], [data-row-control], a, button, input, label, select, textarea";

/** Clicks that land on the row but not on its link (peek elements) open it. */
function rowFallback(e: MouseEvent) {
  if (props.row.disabled) return;
  const target = e.target;
  if (!(target instanceof Element) || target.closest(IGNORE)) return;
  const selection = window.getSelection?.();
  if (
    selection &&
    !selection.isCollapsed &&
    rowEl.value?.contains(selection.anchorNode)
  )
    return;
  const link = rowEl.value?.querySelector<HTMLElement>("[data-row-link]");
  if (!link) return;
  const intent = rowClickIntent(e);
  if (intent === "open") link.click();
  else if (intent === "new-tab" && link instanceof HTMLAnchorElement)
    window.open(link.href, "_blank", "noopener");
}

function rowFallbackAux(e: MouseEvent) {
  if (e.button === 1) rowFallback(e);
}

/** Middle-button press on a peek element: no autoscroll, the click opens. */
function preventPeekAutoscroll(e: MouseEvent) {
  if (e.button !== 1) return;
  if (e.target instanceof Element && e.target.closest("[data-row-peek]"))
    e.preventDefault();
}

const isLastRow = computed(() => {
  if (!list.value.rows?.length) return false;
  return (
    list.value.rows[list.value.rows.length - 1][list.value.rowKey] ===
    props.row[list.value.rowKey]
  );
});

const isSelected = computed(() => {
  return list.value.selections.has(props.row[list.value.rowKey]);
});

const rowHeight = computed(() => {
  if (typeof list.value.options.rowHeight === "number") {
    return `${list.value.options.rowHeight}px`;
  }
  return list.value.options.rowHeight;
});

const roundedClass = computed(() => {
  if (!isSelected.value) return "rounded";

  const selections = [...list.value.selections];
  let groups = list.value.rows[0]?.group
    ? list.value.rows.map((k) => k.rows)
    : [list.value.rows];

  for (let rows of groups) {
    let currentIndex = rows.findIndex((k) => k == props.row);
    if (currentIndex === -1) continue;

    let atBottom = !selections.includes(rows[currentIndex + 1]?.name);
    let atTop = !selections.includes(rows[currentIndex - 1]?.name);

    return (atBottom ? "rounded-b " : "") + (atTop ? "rounded-t" : "");
  }
});

/**
 * Every click on the checkbox or the label around it toggles here, once, with
 * the click's own modifiers. A click beside the input cancels the label's
 * activation: Firefox does not activate a label on Shift-click, which would
 * break Shift range selection from the label's padding. A click on the input
 * itself is never cancelled: that would revert its checked state after Vue
 * has rendered it.
 */
function onCheckboxLabelClick(e: MouseEvent) {
  if (!(e.target instanceof HTMLInputElement)) e.preventDefault();
  handleCheckboxClick(e);
}

const handleCheckboxClick = (event: MouseEvent) => {
  if (props.row.disabled) return;

  const value = props.row[list.value.rowKey];

  if (event.shiftKey && !list.value.selections.has(value)) {
    const lastSelected = Array.from(list.value.selections).pop();

    const rows = list.value.rows.find((k) => k.group)
      ? list.value.rows.reduce((acc, curr) => acc.concat(curr.rows), [])
      : list.value.rows;

    const lastIndex = rows.findIndex(
      (k) => lastSelected === k[list.value.rowKey]
    );
    const curIndex = rows.findIndex((k) => value === k[list.value.rowKey]);

    const start = Math.min(lastIndex, curIndex);
    const end = Math.max(lastIndex, curIndex);

    for (let i = start; i <= end; i++) {
      if (rows[i].disabled) continue;
      list.value.selections.add(rows[i][list.value.rowKey]);
    }
  } else {
    list.value.toggleRow(value);
  }
};
</script>
