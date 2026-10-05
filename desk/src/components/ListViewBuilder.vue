<template>
  <!-- View Controls -->
  <div
    :class="[
      'flex items-center justify-between gap-2 px-5 pb-4 pt-3 ',
      list?.data?.data?.length > 0 ? 'relative' : 'absolute w-[stretch]',
    ]"
    v-if="showViewControls"
  >
    <QuickFilters v-if="!isMobileView" />
    <div v-if="!isMobileView" class="-ms-2 h-5 border-s"></div>
    <div
      class="flex items-start gap-2 justify-end h-full py-1 ps-0.5"
      v-if="!isMobileView"
    >
      <Button
        :label="__('Save Changes')"
        v-if="
          viewReady && (isViewUpdated || route.query.filters) && canSaveView
        "
        @click="saveChanges"
      />
      <Reload @click="handleReload" :loading="list.loading" />
      <div data-list-filter-trigger class="contents"><Filter /></div>
      <SortBy :hide-label="isMobileView" />
      <ColumnSettings
        :hide-label="isMobileView"
        v-if="!options.hideColumnSetting"
      />
    </div>
    <div v-else class="flex justify-between items-center w-full">
      <div data-list-filter-trigger class="contents"><Filter /></div>
      <div class="flex items-center gap-2">
        <Reload @click="handleReload" :loading="list.loading" />
        <SortBy :hide-label="isMobileView" />
      </div>
    </div>
  </div>

  <!-- Loading State -->
  <div
    v-if="list.loading && !list.data?.data?.length"
    class="flex items-center justify-center h-full w-full absolute top-0 z-100"
  >
    <LoadingIndicator :scale="8" />
  </div>
  <!-- List View -->
  <!--
    Rows are not links: the title cell holds the row's one link,
    stretched over the row; a value that filters is its own button above it.
  -->
  <ListView
    v-else-if="list.data?.data.length > 0"
    ref="listViewEl"
    class="flex-1"
    :columns="columns"
    :rows="rows"
    row-key="name"
    :options="{
      selectable: options.selectable,
      showTooltip: false,
      resizeColumn: true,
      rowHeight: '2.5rem',
      emptyState,
    }"
  >
    <ListViewHeader class="sm:mx-5 mx-3">
      <ListHeaderItem
        v-for="column in columns"
        :key="column.key"
        :item="column"
        @columnWidthUpdated="handleColumnResize"
      />
    </ListViewHeader>
    <ListRows
      :rows="rows"
      v-slot="{ idx, column, item, row }"
      :group-by-actions="options.groupByActions"
      :title-label="(r) => String(r[titleKey] || r.name)"
      @scrollend="handleListScroll"
      class="list-rows"
    >
      <ListRowItem :item="item" :column="column" :row="row">
        <template v-if="cellActionOf(column, item) === 'title'">
          <RouterLink
            v-if="options.rowRoute?.name"
            data-row-link
            :to="rowRoute(row)"
            :class="TITLE_LINK_CLASS"
          >
            <component :is="listCell(column, row, item, idx)" />
          </RouterLink>
          <button
            v-else
            type="button"
            data-row-link
            :class="TITLE_LINK_CLASS"
            @click="emit('rowClick', row.name)"
          >
            <component :is="listCell(column, row, item, idx)" />
          </button>
        </template>
        <MultipleAvatar
          v-else-if="
            cellActionOf(column, item) === 'filter' &&
            column.type === 'MultipleAvatar'
          "
          filterable
          :avatars="item"
          :filter-label="__(column.label)"
          class="min-w-0"
          @pointerdown.capture="onValuePointerDown"
          @filter="(name, e) => onValueClick(e, column, row, item, name)"
        />
        <Tooltip
          v-else-if="cellActionOf(column, item) === 'filter'"
          :text="__('Filter by {0}', [__(column.label)])"
        >
          <button
            type="button"
            data-row-control
            data-list-filter
            :class="FILTER_BUTTON_CLASS"
            @pointerdown="onValuePointerDown"
            @mousedown.middle.prevent
            @click="(e) => onValueClick(e, column, row, item)"
            @auxclick="
              (e) => e.button === 1 && onValueClick(e, column, row, item)
            "
          >
            <span class="sr-only">
              {{ __("Filter by {0}:", [__(column.label)]) }}
            </span>
            <span data-value class="flex min-w-0 truncate">
              <component :is="listCell(column, row, item, idx)" />
            </span>
          </button>
        </Tooltip>
        <component v-else :is="listCell(column, row, item, idx)" />
      </ListRowItem>
    </ListRows>
    <ListSelectBanner v-if="options.showSelectBanner">
      <template #actions="{ selections, unselectAll }">
        <div class="flex items-center gap-1">
          <Button
            v-for="action in selectBannerOptions(selections, unselectAll, true)"
            :key="action.label"
            :label="action.label"
            :icon-left="action.icon"
            variant="ghost"
            @click="action.onClick"
          />
          <Dropdown :options="selectBannerOptions(selections, unselectAll)">
            <Button
              icon="lucide-more-horizontal"
              variant="ghost"
              :label="__('More actions')"
            />
          </Dropdown>
        </div>
      </template>
    </ListSelectBanner>
  </ListView>

  <!-- List Footer -->
  <div
    class="p-20 border-t sm:px-5 px-3 py-2"
    v-if="list.data?.data.length > 0"
  >
    <ListFooter
      :options="{
        rowCount: list?.data?.row_count,
        totalCount: list?.data?.total_count,
      }"
      :pageLengthCount="defaultParams.page_length_count"
      @loadMore="handlePageLength(defaultParams.page_length_count, true)"
      v-model="defaultParams.page_length_count"
      @update:modelValue="
        (count) => {
          handlePageLength(count);
        }
      "
    />
  </div>
  <!-- Empty State -->
  <EmptyState
    v-else-if="!list.loading"
    :title="emptyState.title"
    :icon="emptyState.icon"
    :description="emptyState.description"
  />
</template>

<script setup lang="ts">
import { MultipleAvatar, StarRating } from "@/components";
import {
  ColumnSettings,
  QuickFilters,
  Reload,
  SortBy,
} from "@/components/view-controls";
import { Filter, normalizeFilters } from "@/components/view-controls/filter";
import { useScreenSize } from "@/composables/screen";
import {
  currentView as headerView,
  useView,
  views,
} from "@/composables/useView";
import { useAuthStore } from "@/stores/auth";
import { globalStore } from "@/stores/globalStore";
import { useUserStore } from "@/stores/user";
import { capture } from "@/telemetry";
import { View, ViewType } from "@/types";
import { formatTimeShort, getIcon } from "@/utils";
import { useMediaQuery, useStorage } from "@vueuse/core";
import { useTicketStatusStore } from "@/stores/ticketStatus";
import { __ } from "@/translation";
import {
  createResource,
  Dropdown,
  FeatherIcon,
  frappeRequest,
  ListFooter,
  ListHeaderItem,
  ListRowItem,
  ListSelectBanner,
  ListView,
  LoadingIndicator,
  Tooltip,
  dayjs,
  toast,
} from "frappe-ui";
import {
  computed,
  h,
  nextTick,
  onMounted,
  onUnmounted,
  provide,
  reactive,
  ref,
  VNode,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "./EmptyState.vue";
import {
  cellAction,
  cellCondition,
  resolveTitleKey,
  trimSelections,
  valueClickIntent,
} from "./listRowActions.js";
import { listFilters } from "./listViewFilters";
import ListRows from "./ListRows.vue";
import ListViewHeader from "./ListViewHeader.vue";

interface P {
  options: {
    doctype: string;
    defaultFilters?: Record<string, any>;
    columnConfig?: Record<string, any>;
    emptyState?: {
      // type of a h componnt
      icon?: string | VNode;
      title: string;
      description?: string;
    };
    hideViewControls?: boolean;
    hideColumnSetting?: boolean;
    selectable?: boolean;
    view?: ViewType;
    groupByActions?: Array<any>;
    showSelectBanner?: boolean;
    selectBannerActions?: Record<string, any>;
    default_page_length?: number;
    isCustomerPortal?: boolean;
    rowRoute?: Record<string, string>;
    /** Column whose cell holds the row's link; defaults to the first column. */
    titleField?: string;
  };
}

interface E {
  (event: "rowClick", row: any): void;
}
const props = defineProps<P>();
const emit = defineEmits<E>();
const route = useRoute();
const router = useRouter();
const { isManager } = useAuthStore();
const { getUser } = useUserStore();
const { $dialog, $socket } = globalStore();
const { getStatus } = useTicketStatusStore();

const listSelections = ref(new Set());
const defaultOptions = reactive({
  doctype: "",
  hideViewControls: false,
  selectable: false,
  view: {
    view_type: "list",
    group_by_field: "owner",
    name: route.query.view,
  },
  groupByActions: [],
  default_page_length: 20,
  isCustomerPortal: false,
  hideColumnSetting: true,
  rowRoute: {
    name: "",
    prop: "",
  },
  selectBannerActions: [
    {
      label: __("Delete"),
      icon: "lucide-trash-2",
      onClick: (selections: Set<string>) => {
        $dialog({
          title: __("Delete"),
          message: __("Are you sure you want to delete {0} item(s)?", [
            selections.size,
          ]),
          actions: [
            {
              label: __("Delete"),
              variant: "solid",
              theme: "red",
              iconLeft: "trash-2",
              onClick({ close }) {
                handleBulkDelete(close, selections);
              },
            },
          ],
        });
      },
      condition: () => !options.value.isCustomerPortal && isManager,
    },
  ],
});

function handleBulkDelete(hide: Function, selections: Set<string>) {
  capture("bulk_delete" + props.options.doctype);
  const requested = Array.from(selections);
  const requestedCount = requested.length;

  const failureMessages: string[] = [];
  let successMessage = "";
  let failedCount = 0;

  const onBulkResult = (data: { message: string; title: string }) => {
    const isFailure =
      data.title === __("Bulk Operation Failed") ||
      data.title === "Bulk Operation Failed";
    const isSuccess =
      data.title === __("Bulk Operation Successful") ||
      data.title === "Bulk Operation Successful";
    if (!isFailure && !isSuccess) return;

    if (isFailure) {
      // Parse how many items failed from the message (Frappe includes the count)
      const match = data.message.match(/Failed to delete (\d+) documents?/);
      if (match) {
        failedCount = parseInt(match[1], 10);
      }
      failureMessages.push(data.message);
    } else {
      successMessage = data.message;
    }
  };

  $socket.on("msgprint", onBulkResult);

  // Use frappeRequest (not `call`) so per-item delete errors surfaced in
  // `_server_messages` get routed through the app's serverMessagesHandler.
  // `call` silently drops them on 200 responses.
  frappeRequest({
    url: "frappe.desk.reportview.delete_items",
    params: {
      items: JSON.stringify(requested),
      doctype: props.options.doctype,
    },
  }).finally(() => {
    $socket.off("msgprint", onBulkResult);

    const deletedCount = requestedCount - failedCount;

    if (failureMessages.length > 0 && deletedCount > 0) {
      // Partial success: some deleted, some failed — show both toasts
      toast.success(__("{0} item(s) deleted successfully", [deletedCount]));
      for (const msg of failureMessages) {
        toast.error(msg);
      }
    } else if (failureMessages.length > 0) {
      // All failed
      for (const msg of failureMessages) {
        toast.error(msg);
      }
    } else if (successMessage) {
      // All succeeded
      toast.success(successMessage);
    } else {
      // Fallback: no socket messages received (e.g. enqueued for >10 items)
      toast.success(__("{0} item(s) queued for deletion", [requestedCount]));
    }

    hide();
    reset();
  });
}

function reset() {
  exposeFunctions.reload();
  exposeFunctions.unselectAll();
}

const options = computed(() => {
  return {
    ...defaultOptions,
    ...props.options,
  };
});

const { isMobileView } = useScreenSize();

const defaultEmptyState = {
  icon: "",
  title: __("No Data Found"),
};

const pageLengthCount = useStorage(
  `list_page_length_count+${props.options.doctype}`,
  options.value.default_page_length
);

const defaultParams = reactive({
  doctype: options.value.doctype,
  filters: {},
  default_filters: options.value.defaultFilters,
  order_by: "modified desc",
  page_length: pageLengthCount.value,
  page_length_count: pageLengthCount.value,
  view: options.value.view,
  columns: [],
  rows: [],
  show_customer_portal_fields: options.value.isCustomerPortal,
  is_default: false,
});

const emptyState = computed(() => {
  return options.value?.emptyState || defaultEmptyState;
});

const isViewUpdated = ref(false);
/** The saved view has been applied: saving before then would save empties. */
const viewReady = ref(false);

const list = createResource({
  url: "helpdesk.api.doc.get_list_data",
  params: defaultParams,
  transform: (data) => {
    data.columns.forEach((column) => {
      handleFetchFromField(column);
      handleColumnConfig(column);
    });
    return data;
  },
  onSuccess: (data) => {
    list.params = defaultParams;
    columns.value = data.columns;
    // Bulk actions must never act on rows a filter (or any reload) just hid.
    const selections = listViewEl.value?.selections;
    if (selections) {
      for (const name of trimSelections(selections, data.data || [])) {
        selections.delete(name);
      }
    }
    restoreFocusAfterReload();
  },
});

/** frappe-ui ListView: exposes `selections`. */
const listViewEl = ref(null);

const exposeFunctions = {
  list,
  reload,
  unselectAll: () => {},
};

/** Banner actions. `inline` picks the ones shown as buttons; the rest fill the "..." menu. */
function selectBannerOptions(
  selections: Set<string>,
  unselectAll = () => {},
  inline = false
) {
  exposeFunctions["unselectAll"] = unselectAll;

  // Get the user-provided actions
  const userActions = options.value.selectBannerActions.map((action) => ({
    ...action,
    onClick: () => action.onClick?.(selections),
  }));

  // Get the default actions
  // overwrite the default actions if user provided actions with same label
  const defaultActions = defaultOptions.selectBannerActions
    .filter(
      (action) =>
        !userActions.some(
          (defaultAction) => defaultAction.label === action.label
        )
    )
    .map((action) => ({
      ...action,
      onClick: () => action.onClick?.(selections),
    }));

  return [...userActions, ...defaultActions].filter(
    (action) =>
      Boolean(action.inline) === inline && (action.condition?.() ?? true)
  );
}

const rows = computed(() => {
  if (!list.data?.data) return [];
  if (list.data.view_type === "group_by") {
    if (!list.data?.group_by_field?.name) return [];
    return getGroupedByRows(list.data.data, list.data.group_by_field);
  }
  return list.data?.data;
});
const columns = ref([]);

function getGroupedByRows(listRows, groupByField) {
  let groupedRows = [];
  groupByField.options?.forEach((option) => {
    let filteredRows = [];

    if (!option.value) {
      filteredRows = listRows.filter((row) => !row[groupByField.name]);
    } else {
      filteredRows = listRows.filter(
        (row) => row[groupByField.name] == option.value
      );
    }

    let groupDetail = {
      group: option || " ",
      collapsed: false,
      rows: filteredRows,
      icon: h(FeatherIcon, {
        name: "folder",
        class: "h-4 w-4 flex-shrink-0 text-ink-gray-6",
      }),
    };
    groupedRows.push(groupDetail);
  });
  return groupedRows || listRows;
}

function handleFetchFromField(column) {
  if (!column.hasOwnProperty("key")) return column;
  const regex = /([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)/;
  const isFetchFromField = column.key.match(regex);
  column.key = isFetchFromField ? isFetchFromField[2] : column.key;
}

function handleColumnConfig(column) {
  if (!options.value?.columnConfig) return column;
  const columnConfig = options.value.columnConfig;
  if (!columnConfig.hasOwnProperty(column.key)) return column;
  column.prefix = columnConfig[column.key]?.prefix;

  return column;
}

const filterableFields = createResource({
  url: "helpdesk.api.doc.get_filterable_fields",
  cache: ["DocField", options.value.doctype],
  auto: !options.value.hideViewControls,
  params: {
    doctype: options.value.doctype,
    append_assign: true,
    show_customer_portal_fields: defaultParams.show_customer_portal_fields,
  },
  transform: (data) => {
    data = data.map((field) => {
      return {
        label: field.label,
        value: field.fieldname,
        ...field,
      };
    });
    return data;
  },
});

const sortableFields = createResource({
  url: "helpdesk.api.doc.sort_options",
  auto: !options.value.hideViewControls,
  params: {
    doctype: options.value.doctype,
    show_customer_portal_fields: defaultParams.show_customer_portal_fields,
  },
});

const quickFilters = createResource({
  url: "helpdesk.api.doc.get_quick_filters",
  auto: !options.value.hideViewControls,
  params: {
    doctype: options.value.doctype,
    show_customer_portal_fields: defaultParams.show_customer_portal_fields,
  },
  transform: (data) => {
    if (Boolean(data.length)) return;
    data = [{ name: "name", label: "Name", fieldtype: "Data" }];
    return data;
  },
});

function listCell(column: any, row: any, item: any, idx: number) {
  const columnConfig = options.value.columnConfig;
  if (columnConfig && columnConfig[column.key]?.custom) {
    return columnConfig[column.key]?.custom({ column, row, item, idx });
  }
  if (idx === 0) {
    return h("span", {
      class: "truncate text-base text-ink-gray-6",
      textContent: item,
    });
  }
  if (column.type === "Datetime") {
    return h("span", {
      class: "text-p-xs",
      textContent: formatTimeShort(item),
    });
  }
  if (column.type === "MultipleAvatar") {
    // data-row-peek: above the row link, so the names' tooltips open on hover;
    // a click still opens the row (row fallback).
    return h(
      "span",
      { "data-row-peek": "", class: "relative z-[2] flex min-w-0" },
      h(MultipleAvatar, {
        avatars: item,
        hideName: false,
        class: "flex items-center flex-1 min-w-0",
      })
    );
  }
  if (column.type === "Rating") {
    return h(StarRating, {
      rating: item || 0,
      class: "truncate",
    });
  }
  return h("span", {
    class: "truncate flex-1",
    textContent: item,
  });
}

// --- Row link and value filters ---

const TITLE_LINK_CLASS =
  "min-w-0 truncate text-start after:absolute after:inset-0 after:z-[1] after:rounded after:content-[''] after:ring-inset after:ring-outline-gray-5 focus-visible:outline-none focus-visible:after:ring-2";
const FILTER_BUTTON_CLASS =
  "relative z-[2] inline-flex min-w-0 max-w-full items-center rounded px-1 text-start hover:bg-surface-gray-3 hover:text-ink-gray-9 active:bg-surface-gray-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-outline-gray-5";
const CELL_FILTER_TOAST = "list-cell-filter";

const titleKey = computed(() =>
  resolveTitleKey(columns.value, options.value.titleField)
);
// Values filter only where a pointer can hover; a tap anywhere opens the row.
const inlineFilters = useMediaQuery("(hover: hover) and (pointer: fine)");

function cellActionOf(column, item) {
  return cellAction(column, item, {
    titleKey: titleKey.value,
    inlineFilters: inlineFilters.value,
  });
}

function rowRoute(row) {
  return {
    name: options.value.rowRoute?.name,
    params: { [options.value.rowRoute?.prop]: row.name },
    query: { view: route.query?.view },
  };
}

/** The value button's last pointerdown: a click's own pointerType is unreliable. */
let lastPointerType = "";
function onValuePointerDown(e: PointerEvent) {
  lastPointerType = e.pointerType;
}

/**
 * A click on a value button (or an assignee avatar, with `assignee` its
 * name): filters on a plain click, opens the row in a new tab on Ctrl/Cmd or
 * middle click, and opens it on a touch tap.
 */
function onValueClick(e: MouseEvent, column, row, item, assignee?: string) {
  e.preventDefault();
  e.stopPropagation();
  // A keyboard-activated click (detail 0) had no pointer: a stale pointerdown,
  // such as a touch scroll that started on a value, must not decide it.
  const intent = valueClickIntent(e, e.detail === 0 ? "" : lastPointerType);
  lastPointerType = "";
  const button = e.currentTarget as HTMLElement | null;
  const link = button
    ?.closest("[data-list-row]")
    ?.querySelector<HTMLElement>("[data-row-link]");
  if (intent === "open") {
    link?.click();
    return;
  }
  if (intent === "new-tab") {
    if (link instanceof HTMLAnchorElement) {
      window.open(link.href, "_blank", "noopener");
    }
    return;
  }
  if (intent !== "filter") return;

  if (column.label == "Status" && options.value.doctype === "HD Ticket") {
    item = getStatus(item)?.label_agent;
  }
  const condition = cellCondition(column, item, { assignee });
  if (!condition) return;
  const text =
    column.type === "MultipleAvatar"
      ? getUser(assignee)?.full_name || assignee
      : button?.querySelector("[data-value]")?.textContent?.trim() ||
        String(condition[2]);
  applyCellFilter(condition, __(column.label), text, button);
}

/**
 * The clicked value button, set while its filter reloads: if it still has
 * focus (as after a keyboard activation), focus stays in the list.
 */
let focusAfterReload: HTMLElement | null = null;

/** The list's own route: a navigation that lands elsewhere isn't a filter. */
const listRouteName = route.name;
/** The `?filters` the last cell filter navigated to. */
let cellFilterPushed: string | null = null;

/**
 * Applies one cell's filter in place of any on the same field, as navigation:
 * it goes into the URL (`?filters`), so Back undoes it and a reload keeps it.
 * Nothing is saved; Save Changes does that on purpose. The toast's Undo is
 * Back.
 */
async function applyCellFilter(
  condition: [string, string, unknown],
  label: string,
  text: string,
  button: HTMLElement | null
) {
  const previous = normalizeFilters(defaultParams.filters);
  // Already filtered by exactly this (or a double-click's second click).
  const wanted = JSON.stringify(condition);
  if (previous.some((c) => JSON.stringify(c) === wanted)) return;
  const next = [
    ...previous.filter(([field]) => field !== condition[0]),
    condition,
  ];
  const pushed = JSON.stringify(next);
  focusAfterReload = button;
  if (pushed === route.query.filters) {
    // The URL already holds it, but a named view's popover edit moved the list
    // off it in place, and the router refuses a duplicate navigation.
    applyUrlFilters();
    list.submit({ ...defaultParams });
    return;
  }
  cellFilterPushed = pushed;
  // The route watch applies the URL's filters and reloads the list.
  const failure = await router.push({
    query: { ...route.query, filters: pushed },
  });
  const ours = () =>
    route.name === listRouteName && route.query.filters === pushed;
  if (failure || !ours()) {
    focusAfterReload = null;
    return;
  }

  toast(() => h("span", __("Filtered by {0}: {1}", [label, text])), {
    id: CELL_FILTER_TOAST,
    duration: 8000,
    action: {
      label: __("Undo"),
      onClick: () => {
        // Only the change this toast offered to undo.
        if (ours()) router.back();
      },
    },
  });
}

/**
 * After a filter reload, focus stays on the same value button: rows are
 * keyed, so it survives when its row does. When its row is gone, focus moves
 * to the Filter button rather than falling back to the page.
 */
function restoreFocusAfterReload() {
  const button = focusAfterReload;
  focusAfterReload = null;
  if (!button || document.activeElement !== button) return;
  nextTick(() => {
    if (button.isConnected) return;
    document
      .querySelector<HTMLElement>("[data-list-filter-trigger] button")
      ?.focus();
  });
}

const showViewControls = computed(() => {
  return (
    !options.value.hideViewControls &&
    filterableFields.data &&
    sortableFields.data &&
    quickFilters.data
  );
});

const listViewData = reactive({
  list,
  filterableFields,
  quickFilters,
  sortableFields,
});

provide("listViewData", listViewData);

provide("listViewActions", {
  applyFilters,
  applySort,
  updateColumns,
  reload,
});

// Also published module-scope, for the command palette: it renders in the
// sidebar, outside this provide chain.
listFilters.value = {
  current: () => normalizeFilters(list?.params?.filters),
  apply: applyFilters,
};
onUnmounted(() => {
  listFilters.value = null;
  toast.dismiss(CELL_FILTER_TOAST);
});

/**
 * The filter popover, quick filters and the command palette. Any of them ends
 * the chance to undo a cell filter. On a default view the change is saved at
 * once, with everything the list shows: a cell filter in the URL is saved too,
 * so it leaves the URL.
 */
function applyFilters(filters) {
  toast.dismiss(CELL_FILTER_TOAST);
  isViewUpdated.value = true;
  defaultParams.filters = normalizeFilters(filters);

  // automatically update filters for default view
  if (!defaultParams.is_default) {
    list.submit({ ...defaultParams });
    return;
  }
  handleViewUpdate(defaultParams.filters);
  viewFilters = defaultParams.filters;
  isViewUpdated.value = false;
  if (route.query.filters == null) {
    list.submit({ ...defaultParams });
  } else {
    // the route watch reloads the list
    router.replace({ query: { ...route.query, filters: undefined } });
  }
}

function applySort(order_by: string) {
  isViewUpdated.value = true;
  defaultParams.order_by = order_by;
  list.submit({ ...defaultParams, order_by });
  if (!defaultParams.is_default) return;
  // The view's own filters: a cell filter is saved only by Save Changes.
  handleViewUpdate(viewFilters);
  isViewUpdated.value = false;
}

function updateColumns(obj) {
  isViewUpdated.value = true;
  const { columns: _columns, isDefault, rows } = obj;
  _columns?.forEach((column) => {
    handleFetchFromField(column);
    handleColumnConfig(column);
  });
  columns.value = defaultParams.columns = isDefault ? "" : _columns;
  defaultParams.rows = isDefault ? "" : rows;
  list.reload({ ...defaultParams });
}

function reload(reset: boolean = false) {
  if (reset) {
    defaultParams.filters = normalizeFilters(options.value.defaultFilters);
    defaultParams.order_by = "modified desc";
    defaultParams.page_length = options.value.default_page_length;
    pageLengthCount.value = options.value.default_page_length;
    defaultParams.page_length_count = pageLengthCount.value;
    defaultParams.columns = [];
    defaultParams.rows = [];
    defaultParams.is_default = true;
  }
  list.reload({ ...defaultParams });
}

function handlePageLength(count: number, loadMore: boolean = false) {
  pageLengthCount.value = count;
  defaultParams.page_length_count = pageLengthCount.value;
  if (loadMore) {
    defaultParams.page_length += count;
  } else {
    if (
      count === defaultParams.page_length &&
      count === defaultParams.page_length_count
    ) {
      return;
    }
    defaultParams.page_length = count;
    defaultParams.page_length_count = count;
  }
  list.reload();
}

/** Saves `filters` with the list's sort, columns and rows to the current view. */
function handleViewUpdate(filters, onSaved: () => void = () => {}) {
  const saved = () => {
    isViewUpdated.value = false;
    onSaved();
  };
  const view = {
    filters: JSON.stringify(filters),
    columns: JSON.stringify(defaultParams.columns),
    rows: JSON.stringify(defaultParams.rows),
    order_by: defaultParams.order_by,
    name: (route.query.view as string) || "default",
    dt: options.value.doctype,
    route_name: route.name,
    is_customer_portal: options.value.isCustomerPortal,
  };
  const currentView = findView(route.query.view as string).value;
  if (currentView && currentView.public) {
    $dialog({
      title: __("Confirm Changes"),
      message: __(
        "This view is public. Changes made will be visible to everyone."
      ),
      actions: [
        {
          label: __("Save"),
          variant: "solid",
          onClick({ close }) {
            updateView(view, saved);
            close();
          },
        },
        {
          label: __("Cancel"),
          variant: "outline",
          onClick({ close }) {
            close();
          },
        },
      ],
    });
  } else {
    updateView(view, saved);
  }
}

/**
 * Save Changes: the filters as shown, a cell filter in the URL included. Once
 * saved, the view holds them, so they leave the URL, unless the list moved on
 * while a named view's save was on its way.
 */
function saveChanges() {
  const filters = defaultParams.filters;
  const view = route.query.view;
  const urlFilters = route.query.filters;
  handleViewUpdate(filters, () => {
    if (route.query.view !== view) return;
    viewFilters = filters;
    if (urlFilters != null && route.query.filters === urlFilters) {
      router.replace({ query: { ...route.query, filters: undefined } });
    }
  });
}

const { findView, updateView, defaultView } = useView(options.value.doctype);

const canSaveView = computed(() => {
  let currentView: View = findView(route.query.view as string).value;
  if (currentView?.is_standard) return false;
  if (!currentView || !currentView.public) return true;
  if (currentView.public && isManager) {
    return true;
  }
  return false;
});

function handleReload() {
  handleViewChanges();
  isViewUpdated.value = false;
}

function handleViewChanges() {
  toast.dismiss(CELL_FILTER_TOAST);
  if (!switchToView(route.query.view as string)) return;
  applyUrlFilters();
  list.submit({ ...defaultParams });
}

/** Base for URL filters, so repeated pushes layer on the view, not each other. */
let viewFilters = [];

/** Owns sort, columns and rows. False means a redirect is in flight. */
function switchToView(view: string): boolean {
  defaultParams.view.name = view;
  const currentView: View = findCurrentView();
  if (currentView) {
    // normalize so legacy dict-format saved views become list conditions
    viewFilters = normalizeFilters(currentView.filters);
    defaultParams.order_by = currentView.order_by || "modified desc";
    defaultParams.columns = currentView.columns;
    defaultParams.rows = currentView.rows;
    return true;
  }
  if (view) {
    // Stale ?view: drop it but keep the filters, unlike a push to the bare route.
    router.replace({
      name: route.name,
      query: { ...route.query, view: undefined },
    });
    return false;
  }
  viewFilters = normalizeFilters(options.value.defaultFilters);
  defaultParams.order_by = "modified desc";
  defaultParams.columns = [];
  defaultParams.rows = [];
  defaultParams.is_default = true;
  headerView.value.label = __("List");
  headerView.value.icon = LucideAlignJustify;
  return true;
}

/** Touches `filters` only, so filtering never resets the user's sort. */
function applyUrlFilters() {
  viewReady.value = true;
  const urlFilters = parseUrlFilters();
  if (!urlFilters) {
    defaultParams.filters = viewFilters;
    return;
  }
  const overriddenFields = new Set(urlFilters.map((c) => c[0]));
  defaultParams.filters = urlFilters.length
    ? [...viewFilters.filter((c) => !overriddenFields.has(c[0])), ...urlFilters]
    : [];
}

/** null when the URL carries no filters; [] means "clear them". */
function parseUrlFilters() {
  if (!route.query.filters) return null;
  try {
    return normalizeFilters(JSON.parse(route.query.filters as string));
  } catch (e) {
    console.error("Failed to parse filters from URL", e);
    return null;
  }
}

function findCurrentView() {
  let currentView: View;
  if (route.query.view) {
    currentView = findView(route.query.view as string).value;
    defaultParams.is_default = false;
  } else if (defaultView.value) {
    currentView = defaultView.value;
    defaultParams.is_default = true;
  }
  return currentView;
}

// The view is re-read only when it changes; re-reading it on every filter
// change is what let a filter silently reset the sort.
watch(
  [() => route.query.view as string, () => route.query.filters as string],
  ([view, filters], [previousView]) => {
    // vue-sonner dismisses a frame later, so a cell filter's own navigation
    // would close the toast it is about to show.
    if (filters !== cellFilterPushed) toast.dismiss(CELL_FILTER_TOAST);
    if (view !== previousView && !switchToView(view)) return;
    applyUrlFilters();
    list.submit({ ...defaultParams });
  }
);

const listScrollPosition = useStorage(
  `list_position+${props.options.doctype}`,
  0
);
function handleListScroll(e) {
  listScrollPosition.value = e.target.scrollTop;
}
function handleScrollPosition() {
  setTimeout(() => {
    const listContainer = document.querySelector(".list-rows");
    if (!listContainer) return;
    listContainer.scrollTop = listScrollPosition.value;
  }, 200);
}

function handleColumnResize({ key, width, save } = {}) {
  const column = columns.value.find((c) => c.key === key);
  if (column) column.width = width;
  if (!save) return;
  isViewUpdated.value = true;
  defaultParams.columns = columns.value;
  if (!defaultParams.is_default) return;
  handleViewUpdate(viewFilters);
  isViewUpdated.value = false;
}

onMounted(async () => {
  handleScrollPosition();

  if (views.data?.length > 0 && views.filters?.dt === options.value.doctype) {
    handleViewChanges();
  } else {
    await views.list.promise;
    handleViewChanges();
  }
  if (route.query.view || defaultView.value) {
    if (route.query.view) {
      const currentView = findCurrentView();
      if (!currentView) return;
      headerView.value.label = currentView.label || __("List");
      headerView.value.icon = getIcon(currentView.icon);
    }
    return;
  }
});

defineExpose(exposeFunctions);
</script>
