<template>
  <div class="flex border-b h-12 items-center">
    <div class="z-20 -me-4 ms-1 flex items-center justify-center">
      <Button variant="ghosted" @click="sidebarOpened = !sidebarOpened">
        <FeatherIcon name="menu" class="size-4" />
      </Button>
    </div>
    <header id="app-header" class="w-full"></header>
  </div>
  <CallUI v-if="callingWasEnabled" class="me-3 mt-2" :userEmail="user" />
</template>

<script setup>
import { mobileSidebarOpened as sidebarOpened } from "@/composables/mobile";
import { useAuthStore } from "@/stores/auth";
import { useTelephonyStore } from "@/stores/telephony";
import { defineAsyncComponent, onMounted, ref, watch } from "vue";

const CallUI = defineAsyncComponent(() => import("../telephony/CallUI.vue"));

const { user } = useAuthStore();

const telephonyStore = useTelephonyStore();

// The call UI pulls in the telephony SDKs, so it loads only once calling is
// enabled, and stays mounted if a refetch turns it off, so a call in
// progress isn't cut off.
const callingWasEnabled = ref(false);
watch(
  () => telephonyStore.isCallingEnabled,
  (enabled) => {
    if (enabled) callingWasEnabled.value = true;
  },
  { immediate: true }
);

onMounted(() => {
  telephonyStore.fetchCallIntegrationStatus();
});
</script>
