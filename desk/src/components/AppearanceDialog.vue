<template>
  <Dialog
    v-model:open="appearance.dialogOpen"
    :title="__('Appearance')"
    size="md"
    :show-close-button="false"
  >
    <AppearanceSettings>
      <template #actions>
        <Button
          variant="solid"
          :label="__('Done')"
          @click="appearance.dialogOpen = false"
        />
      </template>
    </AppearanceSettings>
  </Dialog>
</template>

<script setup lang="ts">
import { Button, Dialog } from "frappe-ui";
import AppearanceSettings from "@/components/Settings/Preferences/components/AppearanceSettings.vue";
import { useAppearanceStore } from "@/stores/appearance";
import { __ } from "@/translation";

const appearance = useAppearanceStore();
</script>
