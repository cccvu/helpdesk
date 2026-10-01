<template>
  <div class="flex border-b pe-5 rtl:pe-6">
    <div id="app-header" class="flex-1 w-full"></div>
    <div class="flex items-start justify-center">
      <CallUI v-if="callingWasEnabled" :userEmail="user" />
    </div>
  </div>
</template>

<script setup>
import { useAuthStore } from "@/stores/auth";
import { useTelephonyStore } from "@/stores/telephony";
import { defineAsyncComponent, onMounted, ref, watch } from "vue";

const CallUI = defineAsyncComponent(() =>
  import("@/components/telephony/CallUI.vue")
);

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
