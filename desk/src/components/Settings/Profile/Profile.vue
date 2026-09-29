<template>
  <SettingsLayoutBase
    :title="__('Profile')"
    :description="__('Manage your profile information.')"
  >
    <template #content>
      <div class="flex items-center justify-between gap-2 pt-1.5 pb-8">
        <FileUploader
          :fileTypes="['image/*']"
          @success="
            (file) => {
              updateImage(file.file_url);
            }
          "
        >
          <template #default="{ openFileSelector, error: _error, uploading }">
            <div class="flex items-center justify-center gap-4">
              <div class="group relative flex-shrink-0 size-16">
                <Avatar
                  class="!size-16"
                  :image="user.doc?.user_image"
                  :label="fullName"
                />
                <div
                  v-if="agentStatusStore.myStatus"
                  class="absolute bottom-0.5 right-0.5 rounded-full bg-surface-elevation-2 p-1"
                >
                  <div
                    class="size-3.5 rounded-full"
                    :class="
                      agentStatusStore.statusColor(agentStatusStore.myStatus)
                    "
                  />
                </div>
                <Tooltip
                  :hoverDelay="0"
                  placement="bottom"
                  :text="profileTooltipText"
                >
                  <div
                    class="z-1 absolute top-0 left-0 flex h-9 cursor-pointer items-center justify-center rounded-full !size-16"
                    @click.stop="openFileSelector"
                  />
                  <div
                    v-if="user.doc?.user_image"
                    class="z-1 size-4 absolute -top-1 -right-1 flex cursor-pointer items-center justify-center rounded-full bg-surface-base opacity-0 duration-300 ease-in-out group-hover:opacity-100 hover:bg-surface-gray-2 outline outline-black-overlay-50"
                    @click.stop="updateImage()"
                    @mouseenter="isHoveringRemove = true"
                    @mouseleave="isHoveringRemove = false"
                  >
                    <FeatherIcon
                      name="x"
                      class="size-3.5 cursor-pointer text-ink-gray-4"
                    />
                  </div>
                </Tooltip>
                <div
                  v-if="uploading"
                  class="w-full h-full top-0 left-0 absolute bg-surface-gray-10 bg-opacity-20 rounded-full flex items-center justify-center"
                >
                  <LoadingIndicator class="size-4" />
                </div>
              </div>
              <div class="flex flex-col gap-0.5 min-w-0">
                <div v-if="!editName" class="flex items-center gap-1 min-w-0">
                  <span class="text-lg font-semibold text-ink-gray-9 truncate">
                    {{ user?.doc?.full_name }}
                  </span>
                  <Button
                    class="!px-1 !h-5"
                    variant="ghost"
                    :label="__('Edit name')"
                    @click="editFullName"
                  >
                    <EditIcon class="size-3.5" />
                  </Button>
                </div>
                <div v-else class="flex items-center gap-1">
                  <TextInput
                    ref="fullNameRef"
                    v-model="nameDraft"
                    :aria-label="__('Full name')"
                    @keydown.enter="saveName"
                    @keydown.esc.stop="editName = false"
                  />
                  <Button
                    variant="outline"
                    icon="lucide-check"
                    :label="__('Save name')"
                    :loading="user?.save?.loading"
                    :disabled="user?.save?.loading"
                    @click="saveName"
                  />
                </div>
                <span class="text-p-sm text-ink-gray-6 truncate">
                  {{ user?.doc?.email }}
                </span>
              </div>
            </div>
          </template>
        </FileUploader>
      </div>
      <div>
        <div class="flex items-center justify-between h-7">
          <div class="flex gap-2 items-center">
            <span class="text-base-semibold text-ink-gray-9">
              {{ __("Account Info & Security") }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="hasAgentRecord" class="flex items-center justify-between mt-6">
        <div class="flex flex-col gap-1">
          <span class="text-base-medium text-ink-gray-8">
            {{ __("Availability") }}
          </span>
          <span class="text-p-sm text-ink-gray-6">
            {{
              __(
                "Set your availability so your team knows when you're reachable."
              )
            }}
          </span>
        </div>
        <AvailabilityMenu />
      </div>
      <div class="flex items-center justify-between mt-6">
        <div class="flex flex-col gap-1">
          <span class="text-base-medium text-ink-gray-8">
            {{ __("Emails & Signature") }}
          </span>
          <span class="text-p-sm text-ink-gray-6">
            {{
              __(
                "Manage your account emails and email signature for communication."
              )
            }}
          </span>
        </div>
        <Button
          :label="__('Configure')"
          @click="emit('updateStep', 'user-email-settings')"
        />
      </div>
      <div
        v-if="passwordLoginEnabled"
        class="flex items-center justify-between mt-6"
      >
        <div class="flex flex-col gap-1">
          <span class="text-base-medium text-ink-gray-8">
            {{ __("Password") }}
          </span>
          <span class="text-p-sm text-ink-gray-6">{{
            __("Change your account password for security.")
          }}</span>
        </div>
        <Button
          icon-left="lucide-lock"
          :label="__('Change Password')"
          @click="showChangePasswordModal = true"
        />
      </div>
    </template>
  </SettingsLayoutBase>
  <ChangePasswordModal
    v-if="passwordLoginEnabled && showChangePasswordModal"
    v-model="showChangePasswordModal"
  />
</template>

<script setup lang="ts">
import {
  Avatar,
  Button,
  createDocumentResource,
  FileUploader,
  LoadingIndicator,
  toast,
} from "frappe-ui";
import { computed, nextTick, ref, useTemplateRef } from "vue";

import { useAuthStore } from "@/stores/auth";
import { __ } from "@/translation";
import EditIcon from "~icons/lucide/edit";
const emit = defineEmits(["updateStep"]);

import AvailabilityMenu from "@/components/AvailabilityMenu.vue";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { useAvailability } from "@/composables/useAvailability";
import { useAgentStatusStore } from "@/stores/agentStatus";
import ChangePasswordModal from "./components/ChangePasswordModal.vue";

const agentStatusStore = useAgentStatusStore();
const showChangePasswordModal = ref(false);
// Sites that sign in by email link only have no password to change.
const passwordLoginEnabled = !window.disable_user_pass_login;

const { userId, hasAgentRecord, reloadUser } = useAuthStore();
const user = createDocumentResource({ doctype: "User", name: userId });

const isHoveringRemove = ref(false);
const editName = ref(false);

const profileTooltipText = computed(() => {
  if (isHoveringRemove.value) return __("Remove Photo");
  return user.doc?.user_image ? __("Change Photo") : __("Upload Photo");
});

const fullNameRef = useTemplateRef("fullNameRef");
const fullName = computed(() => user.doc?.full_name ?? "");
// The name being typed stays out of user.doc until it is saved, so an
// abandoned edit is never sent with the next photo change.
const nameDraft = ref("");

function editFullName() {
  nameDraft.value = fullName.value;
  editName.value = true;
  nextTick(() => fullNameRef.value?.el?.focus());
}

function saveName() {
  const name = nameDraft.value.trim().replace(/\s+/g, " ");
  if (!user.doc || !name) return;
  if (name === fullName.value) {
    editName.value = false;
    return;
  }
  const [firstName, ...rest] = name.split(" ");
  user.doc.first_name = firstName;
  // The draft started from the full name, so it already holds any middle name.
  user.doc.middle_name = "";
  user.doc.last_name = rest.join(" ");
  save();
}

function save() {
  user.save.submit(null, {
    onSuccess: () => {
      editName.value = false;
      // The sidebar and other views read the name from the auth store.
      reloadUser();
      toast.success(__("Profile updated successfully."));
    },
    onError: (err: { message: string; messages: string[] }) => {
      // Drop the rejected values so a later save doesn't send them again.
      user.reload();
      toast.error(err.message + ": " + err.messages[0]);
    },
  });
}

function updateImage(fileUrl = "") {
  isHoveringRemove.value = false;
  user.doc.user_image = fileUrl;
  save();
}
</script>
