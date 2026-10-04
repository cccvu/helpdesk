<template>
  <div class="flex flex-col gap-6">
    <ThemeSwitcher
      :name="config.brandName || 'Helpdesk'"
      :logo="config.brandLogo || HDLogo"
    />
    <!-- Keep these controls' text, focus outlines and switch edge readable. -->
    <div
      class="flex flex-col gap-6 [--ink-gray-5:var(--ink-gray-7)] [--focus-outline-default:2px_solid_var(--outline-gray-6)] [&_[role=switch][data-state=unchecked]]:border-outline-gray-5"
    >
      <fieldset :aria-describedby="`${id}-text-size-description`">
        <legend class="text-base-medium text-ink-gray-8">
          {{ __("Text size") }}
        </legend>
        <p
          :id="`${id}-text-size-description`"
          class="mt-1 text-p-sm text-ink-gray-7"
        >
          {{ __("Make text smaller or larger. M is the default.") }}
        </p>
        <div class="mt-3 flex flex-wrap gap-x-5 gap-y-2">
          <label
            v-for="option in textSizeOptions"
            :key="option.value"
            class="flex cursor-pointer items-center gap-2 text-base text-ink-gray-8"
          >
            <input
              v-model="appearance.textSize"
              type="radio"
              :name="`${id}-text-size`"
              :value="option.value"
              :class="radioClasses"
            />
            {{ __(option.label) }}
            <span class="sr-only">({{ __(option.name) }})</span>
          </label>
        </div>
      </fieldset>
      <fieldset :aria-describedby="`${id}-font-description`">
        <legend class="text-base-medium text-ink-gray-8">
          {{ __("Font") }}
        </legend>
        <p
          :id="`${id}-font-description`"
          class="mt-1 text-p-sm text-ink-gray-7"
        >
          {{ __("Choose the typeface used across the app.") }}
        </p>
        <div class="mt-3 flex flex-col gap-3">
          <div
            v-for="option in fontOptions"
            :key="option.value"
            class="flex items-start gap-2"
          >
            <input
              :id="`${id}-font-${option.value}`"
              v-model="appearance.font"
              type="radio"
              :name="`${id}-font`"
              :value="option.value"
              :aria-describedby="`${id}-font-${option.value}-description`"
              class="mt-0.5"
              :class="radioClasses"
            />
            <div class="flex flex-col gap-0.5">
              <label
                :for="`${id}-font-${option.value}`"
                class="cursor-pointer text-base text-ink-gray-8"
              >
                {{ __(option.label) }}
              </label>
              <span
                :id="`${id}-font-${option.value}-description`"
                class="text-p-sm text-ink-gray-7"
              >
                {{ __(option.description) }}
              </span>
            </div>
          </div>
        </div>
      </fieldset>
      <Switch
        v-model="appearance.increaseContrast"
        size="md"
        :description="contrastDescription"
      >
        <template #label>
          <span class="text-base-medium text-ink-gray-8">
            {{ __("Increase contrast") }}
          </span>
        </template>
      </Switch>
      <div class="flex items-center justify-between gap-2">
        <Button
          variant="subtle"
          :label="__('Reset to defaults')"
          @click="appearance.reset()"
        />
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useId } from "vue";
import { Button, Switch } from "frappe-ui";
import HDLogo from "@/assets/logos/HDLogo.vue";
import {
  useAppearanceStore,
  type Font,
  type TextSize,
} from "@/stores/appearance";
import { useConfigStore } from "@/stores/config";
import { __ } from "@/translation";
import ThemeSwitcher from "./ThemeSwitcher.vue";

const appearance = useAppearanceStore();
const config = useConfigStore();
const id = useId();

const textSizeOptions: { value: TextSize; label: string; name: string }[] = [
  { value: "s", label: "S", name: "Small" },
  { value: "m", label: "M", name: "Medium" },
  { value: "l", label: "L", name: "Large" },
  { value: "xl", label: "XL", name: "Extra large" },
  { value: "xxl", label: "XXL", name: "Extra extra large" },
];

const contrastDescription = __(
  "Stronger text, borders and focus outlines. Follows your device's setting until you change it."
);

const fontOptions: { value: Font; label: string; description: string }[] = [
  {
    value: "inter",
    label: "Inter (default)",
    description: "Compact and neutral",
  },
  {
    value: "atkinson",
    label: "Atkinson Hyperlegible",
    description: "Easier to tell similar letters and numbers apart",
  },
  {
    value: "system",
    label: "System",
    description: "Your device's own typeface",
  },
];

// @tailwindcss/forms hides the outline on focused inputs and adds a ring;
// give the radios the same visible outline as the other controls instead.
const radioClasses =
  "bg-transparent text-ink-gray-9 border-outline-gray-5 focus:ring-0 focus:ring-offset-0 focus-visible:[outline:2px_solid_var(--outline-gray-6)] focus-visible:[outline-offset:2px]";
</script>
