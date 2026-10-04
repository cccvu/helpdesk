import { computed, ref, watch, watchEffect } from "vue";
import { defineStore } from "pinia";
import { usePreferredContrast, useStorage } from "@vueuse/core";

export type TextSize = "s" | "m" | "l" | "xl" | "xxl";
export type Font = "inter" | "atkinson" | "system";

// Display preferences, stored per browser. Each one is applied as a data
// attribute on <html> that index.css styles; at its default the attribute is
// absent, so the default look is unchanged.
export const useAppearanceStore = defineStore("appearance", () => {
  const textSize = useStorage<TextSize>("appearance_text_size", "m", undefined, {
    writeDefaults: false,
  });
  const font = useStorage<Font>("appearance_font", "inter", undefined, {
    writeDefaults: false,
  });
  // null follows the device's "increase contrast" setting.
  const contrast = useStorage<"more" | "standard" | null>(
    "appearance_contrast",
    null
  );
  const preferredContrast = usePreferredContrast();

  const increaseContrast = computed({
    get() {
      const value =
        contrast.value ??
        (preferredContrast.value === "more" ? "more" : "standard");
      return value === "more";
    },
    set(value: boolean) {
      contrast.value = value ? "more" : "standard";
    },
  });

  const htmlAttributes = computed<Record<string, string | null>>(() => ({
    "data-text-size": textSize.value !== "m" ? textSize.value : null,
    "data-font": font.value !== "inter" ? font.value : null,
    "data-contrast": increaseContrast.value ? "more" : null,
  }));

  function applyAttributes(element: Element) {
    for (const [name, value] of Object.entries(htmlAttributes.value)) {
      if (value) element.setAttribute(name, value);
      else element.removeAttribute(name);
    }
  }

  watchEffect(() => applyAttributes(document.documentElement));

  function reset() {
    textSize.value = "m";
    font.value = "inter";
    contrast.value = null;
  }

  // The Appearance dialog has no trigger element, so focus would land on
  // <body> when it closes. Remember where focus was and return it there.
  // dialogRequested mounts it on first use, so its chunks aren't loaded before.
  const dialogOpen = ref(false);
  const dialogRequested = ref(false);
  let returnFocusTo: HTMLElement | null = null;

  function openDialog(returnTo?: HTMLElement | null) {
    returnFocusTo =
      returnTo ??
      document.querySelector<HTMLElement>(
        '[aria-haspopup="menu"][aria-expanded="true"]'
      ) ??
      (document.activeElement as HTMLElement | null);
    dialogRequested.value = true;
    dialogOpen.value = true;
  }

  watch(dialogOpen, (open) => {
    if (open) return;
    const element = returnFocusTo;
    returnFocusTo = null;
    setTimeout(() => {
      if (element?.isConnected) element.focus();
    });
  });

  return {
    applyAttributes,
    dialogOpen,
    dialogRequested,
    font,
    htmlAttributes,
    increaseContrast,
    openDialog,
    reset,
    textSize,
  };
});
