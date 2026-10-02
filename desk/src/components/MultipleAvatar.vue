<template>
  <!--
    `filterable` (list rows): each avatar is a button that emits
    `filter` with that user's name. The root sits above the row's stretched
    link (relative z-[2]), since `isolate` would otherwise trap the buttons'
    z-index below it; w-fit keeps the blank rest of the cell on the link.
  -->
  <div
    v-if="_avatars?.length"
    class="isolate me-1.5 flex min-w-0 items-center"
    :class="filterable ? 'relative z-[2] w-fit max-w-full' : 'cursor-pointer'"
  >
    <template v-if="_avatars?.length == 1">
      <Tooltip v-if="filterable" :text="filterName(_avatars[0])">
        <button
          type="button"
          data-row-control
          :class="FILTER_BUTTON_CLASS"
          class="gap-2 text-base"
          :data-name="_avatars[0].name"
          :aria-label="filterName(_avatars[0])"
          @mousedown.middle.prevent
          @click="(e) => emit('filter', _avatars[0].name, e)"
          @auxclick="
            (e) => e.button === 1 && emit('filter', _avatars[0].name, e)
          "
        >
          <Avatar
            class="user-avatar"
            shape="circle"
            :image="_avatars[0].image"
            :label="_avatars[0].label"
            size="sm"
            :data-name="_avatars[0].name"
          />
          <span class="min-w-0 truncate" v-if="!hideName">
            {{ _avatars[0].label }}
          </span>
        </button>
      </Tooltip>
      <div
        v-else
        class="flex min-w-0 items-center gap-2 text-base line-clamp-1"
      >
        <Tooltip :text="_avatars[0].name">
          <Avatar
            class="user-avatar"
            shape="circle"
            :image="_avatars[0].image"
            :label="_avatars[0].label"
            size="sm"
            :data-name="_avatars[0].name"
          />
          <div class="min-w-0 truncate" v-if="!hideName">
            {{ _avatars[0].label }}
          </div>
        </Tooltip>
      </div>
    </template>
    <template v-else>
      <template v-if="filterable">
        <Tooltip
          v-for="avatar in visibleAvatars"
          :key="avatar.name"
          :text="filterName(avatar)"
        >
          <button
            type="button"
            data-row-control
            class="user-avatar relative -me-1.5 shrink-0 rounded-full transition hover:z-20 hover:scale-110 focus-visible:z-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-5"
            :data-name="avatar.name"
            :aria-label="filterName(avatar)"
            @mousedown.middle.prevent
            @click="(e) => emit('filter', avatar.name, e)"
            @auxclick="(e) => e.button === 1 && emit('filter', avatar.name, e)"
          >
            <Avatar
              class="ring-2 ring-[var(--surface-base)]"
              shape="circle"
              :image="avatar.image"
              :label="avatar.label"
              :size="size"
            />
          </button>
        </Tooltip>
      </template>
      <template v-else>
        <Tooltip
          v-for="avatar in visibleAvatars"
          :key="avatar.name"
          :text="avatar.name"
        >
          <Avatar
            class="user-avatar -me-1.5 ring-2 ring-[var(--surface-base)] transition hover:z-20 hover:scale-110"
            shape="circle"
            :image="avatar.image"
            :label="avatar.label"
            :size="size"
            :data-name="avatar.name"
          />
        </Tooltip>
      </template>
      <Tooltip v-if="overflowCount" :text="overflowNames">
        <div
          :data-row-peek="filterable ? '' : undefined"
          class="relative z-10 -me-1.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-gray-3 text-xs text-ink-gray-7 ring-2 ring-[var(--surface-base)]"
        >
          +{{ overflowCount }}
        </div>
      </Tooltip>
    </template>
  </div>
</template>
<script setup lang="ts">
import { useUserStore } from "@/stores/user";
import { __ } from "@/translation";
import { Avatar, Tooltip } from "frappe-ui";
import { computed } from "vue";

// The list's value-filter button look (ListViewBuilder), for the one-avatar
// button that also shows the name.
const FILTER_BUTTON_CLASS =
  "inline-flex min-w-0 max-w-full items-center rounded px-1 text-start hover:bg-surface-gray-3 hover:text-ink-gray-9 active:bg-surface-gray-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-outline-gray-5";

const props = defineProps({
  avatars: {
    type: String,
  },
  size: {
    type: String,
    default: "sm",
  },
  hideName: {
    type: Boolean,
    default: false,
  },
  // Cap the number of avatars shown; the rest collapse into a "+n" chip.
  // 0 (default) shows all, so existing callers are unaffected.
  max: {
    type: Number,
    default: 0,
  },
  // Each avatar becomes a button that emits `filter`. Off by default, so
  // other callers are unchanged.
  filterable: {
    type: Boolean,
    default: false,
  },
  // The translated label of what a click filters by, e.g. "Assigned To".
  filterLabel: {
    type: String,
    default: "",
  },
});

const emit = defineEmits<{
  (event: "filter", name: string, e: MouseEvent): void;
}>();

const { getUser } = useUserStore();
const _avatars = computed(() => {
  let result: any;
  try {
    result = JSON.parse(props.avatars);
  } catch (error) {
    result = props.avatars;
  }
  if (!result) return;
  if (result[0]?.hasOwnProperty("name")) {
    return result;
  }
  result = result.map((a: string) => {
    let _user = getUser(a);
    return {
      name: _user.name,
      label: _user.full_name,
      image: _user.user_image,
    };
  });
  return result;
});

/** "Filter by Assigned To: Jane Doe", with the full name. */
function filterName(avatar: { name: string; label?: string }) {
  return __("Filter by {0}: {1}", [
    props.filterLabel,
    avatar.label || avatar.name,
  ]);
}

const capped = computed(
  () => props.max > 0 && (_avatars.value?.length || 0) > props.max
);

const visibleAvatars = computed(() =>
  capped.value ? _avatars.value.slice(0, props.max) : _avatars.value
);

const overflowCount = computed(() =>
  capped.value ? _avatars.value.length - props.max : 0
);

const overflowNames = computed(() =>
  capped.value
    ? _avatars.value
        .slice(props.max)
        .map((a: { name: string }) => a.name)
        .join(", ")
    : ""
);
</script>
