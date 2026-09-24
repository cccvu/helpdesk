<template>
  <!-- Avatar falls back to the brand initial if the logo fails to load -->
  <Avatar
    v-if="config.brandLogo"
    :image="config.brandLogo"
    :label="config.brandName || 'Helpdesk'"
    size="xl"
    shape="square"
  />
  <HDLogo v-else class="h-8 w-8 shrink-0 rounded" />
</template>

<script setup lang="ts">
import HDLogo from "@/assets/logos/HDLogo.vue";
import { Avatar } from "frappe-ui";

import { useConfigStore } from "@/stores/config";
const config = useConfigStore();
</script>

<style scoped></style>
