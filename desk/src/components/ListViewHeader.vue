<template>
  <!--
    frappe-ui's ListHeader, with a named select-all that shows when only some
    rows are selected (indeterminate). Uses the same grid as ListViewRow, so
    header and row columns line up.
  -->
  <div
    class="mb-2 grid items-center gap-4 rounded bg-surface-gray-2 p-2"
    :style="{
      gridTemplateColumns: gridTemplateColumns(
        list.columns,
        list.options.selectable
      ),
    }"
  >
    <label
      v-if="list.options.selectable"
      class="flex w-fit cursor-pointer items-center"
      @click="onSelectAllClick"
    >
      <Checkbox
        :modelValue="list.allRowsSelected"
        :indeterminate="list.selections.size > 0 && !list.allRowsSelected"
        class="cursor-pointer"
      />
      <span class="sr-only">{{ __("Select all rows on this page") }}</span>
    </label>
    <slot>
      <ListHeaderItem
        v-for="column in list.columns"
        :key="column.key"
        :item="column"
        @columnWidthUpdated="(payload) => emit('columnWidthUpdated', payload)"
      />
    </slot>
  </div>
</template>

<script setup lang="ts">
import { __ } from "@/translation";
import { Checkbox, ListHeaderItem } from "frappe-ui";
import { inject } from "vue";

import { gridTemplateColumns } from "./listRowActions.js";

const emit = defineEmits<{
  (event: "columnWidthUpdated", payload: unknown): void;
}>();

// frappe-ui ListView provides it (a computed).
const list = inject<any>("list");

/** Selects every loaded row, or clears them all when all are selected. */
function onSelectAllClick(e: MouseEvent) {
  // A click beside the input would also activate the label: toggle once.
  if (!(e.target instanceof HTMLInputElement)) e.preventDefault();
  list.value.toggleAllRows(true);
}
</script>
