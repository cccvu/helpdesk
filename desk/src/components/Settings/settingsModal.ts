import { computed, defineAsyncComponent, h, markRaw, ref } from "vue";
import LucideMail from "~icons/lucide/mail";
import LucideMailOpen from "~icons/lucide/mail-open";
import LucideUser from "~icons/lucide/user";
import LucideUserPlus from "~icons/lucide/user-plus";
import LucideUsers from "~icons/lucide/users";
import ShieldCheck from "~icons/lucide/shield-check";
import Briefcase from "~icons/lucide/briefcase";
import Settings from "~icons/lucide/settings-2";
import {
  ERPNextSettingsIcon,
  FieldDependencyIcon,
  PhoneIcon,
} from "@/components/icons";
import { FieldDependencyIcon, PhoneIcon, SlidersIcon } from "@/components/icons";
import { __ } from "@/translation";
import { Avatar } from "frappe-ui";
import { useAuthStore } from "@/stores/auth";
import SettingsGear from "~icons/lucide/settings";
import ZapIcon from "~icons/lucide/zap";

// Each page loads when its tab is first opened; labels and icons stay eager
// for the sidebar and the command palette.
const Agents = defineAsyncComponent(() => import("./Agents.vue"));
const EmailConfig = defineAsyncComponent(() => import("./EmailConfig.vue"));
const TeamsConfig = defineAsyncComponent(
  () => import("./Teams/TeamsConfig.vue")
);
const Sla = defineAsyncComponent(() => import("./Sla/Sla.vue"));
const HolidayList = defineAsyncComponent(() => import("./Holiday/Holiday.vue"));
const FieldDependencyConfig = defineAsyncComponent(
  () => import("./FieldDependency/FieldDependencyConfig.vue")
);
const InviteAgents = defineAsyncComponent(() => import("./InviteAgents.vue"));
const AssignmentRules = defineAsyncComponent(
  () => import("./Assignment Rules/AssignmentRules.vue")
);
const ERPNextIntegrationSettings = defineAsyncComponent(
  () =>
    import("@/components/erpnext-integration/ERPNextIntegrationSettings.vue")
);
const TelephonyPage = defineAsyncComponent(
  () => import("./Telephony/TelephonyPage.vue")
);
const EmailNotifications = defineAsyncComponent(
  () => import("./EmailNotifications/EmailNotifications.vue")
);
const SavedReplies = defineAsyncComponent(
  () => import("./SavedReplies/SavedReplies.vue")
);
const General = defineAsyncComponent(() => import("./General/General.vue"));
const ProfilePage = defineAsyncComponent(
  () => import("./Profile/ProfilePage.vue")
);
const Preferences = defineAsyncComponent(
  () => import("./Preferences/Preferences.vue")
);

export const showSettingsModal = ref(false);

const auth = useAuthStore();

export const tabs = computed(() => {
  const _tabs = [
    {
      label: __("My settings"),
      hideLabel: true,
      noborder: true,
      items: [
        {
          label: __("Profile"),
          icon: h(Avatar, {
            image: auth.userImage,
            label: auth.userName,
            size: "xs",
          }),
          component: markRaw(ProfilePage),
        },
        {
          label: __("Preferences"),
          icon: markRaw(SlidersIcon),
          component: markRaw(Preferences),
        },
      ],
    },
    {
      label: __("Email Settings"),
      condition: () => auth.isAdmin || auth.isManager,
      items: [
        {
          label: __("Email Accounts"),
          icon: markRaw(LucideMail),
          component: markRaw(EmailConfig),
        },
        {
          label: __("Email Notifications"),
          icon: markRaw(LucideMailOpen),
          component: markRaw(EmailNotifications),
        },
      ],
    },
    {
      label: __("App Settings"),
      items: [
        {
          label: __("General"),
          icon: markRaw(SettingsGear),
          component: markRaw(General),
          condition: () => auth.isAdmin,
        },
        {
          label: __("Agents"),
          icon: markRaw(LucideUser),
          component: markRaw(Agents),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("Invite Agents"),
          icon: markRaw(LucideUserPlus),
          component: markRaw(InviteAgents),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("Teams"),
          icon: markRaw(LucideUsers),
          component: markRaw(TeamsConfig),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("SLA Policies"),
          icon: markRaw(ShieldCheck),
          component: markRaw(Sla),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("Business Holidays"),
          icon: markRaw(Briefcase),
          component: markRaw(HolidayList),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("Assignment Rules"),
          icon: markRaw(h(Settings, { class: "rotate-90" })),
          component: markRaw(AssignmentRules),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("Field Dependencies"),
          icon: markRaw(FieldDependencyIcon),
          component: markRaw(FieldDependencyConfig),
          condition: () => auth.isAdmin || auth.isManager,
        },
        {
          label: __("Saved Replies"),
          icon: markRaw(ZapIcon),
          component: markRaw(SavedReplies),
        },
      ],
    },
    {
      label: __("Integrations"),
      items: [
        {
          label: __("Telephony"),
          icon: markRaw(PhoneIcon),
          component: markRaw(TelephonyPage),
        },
        {
          label: __("ERPNext"),
          icon: markRaw(ERPNextSettingsIcon),
          component: markRaw(ERPNextIntegrationSettings),
          condition: () => auth.isAdmin || auth.isManager,
        },
      ],
    },
  ];

  return _tabs.filter((tab) => {
    if (tab.condition && !tab.condition()) return false;
    if (tab.items) {
      tab.items = tab.items.filter((item) => {
        if (item.condition && !item.condition()) return false;
        return true;
      });
    }
    return true;
  });
});

export const activeTab = ref(tabs.value[0].items[0]);

export const nextActiveTab = ref(null);

export const disableSettingModalOutsideClick = ref(false);

type TabName =
  | "Profile"
  | "Preferences"
  | "Email Accounts"
  | "Email Notifications"
  | "General"
  | "Agents"
  | "Invite Agents"
  | "Teams"
  | "SLA Policies"
  | "Business Holidays"
  | "Assignment Rules"
  | "Field Dependencies"
  | "Telephony"
  | "ERPNext"
  | "Saved Replies";

export const setActiveSettingsTab = (tabName: TabName) => {
  activeTab.value =
    (tabName &&
      tabs.value
        .map((tab) => tab.items)
        .flat()
        .find((tab) => tab.label == __(tabName))) ||
    tabs.value[0].items[0];
};
