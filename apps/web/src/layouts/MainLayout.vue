<script setup lang="ts">
import { computed, h, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter, RouterLink } from "vue-router";
import {
  NLayout,
  NLayoutSider,
  NLayoutContent,
  NMenu,
  NIcon,
  type MenuOption,
} from "naive-ui";
import {
  ChatboxEllipsesOutline,
  FolderOpenOutline,
  GitNetworkOutline,
  DocumentTextOutline,
  ExtensionPuzzleOutline,
  HardwareChipOutline,
  SpeedometerOutline,
  SettingsOutline,
} from "@vicons/ionicons5";
import HealthBanner from "@/components/HealthBanner.vue";
import { useHealthStore } from "@/stores/health";
import { useConfigStore } from "@/stores/config";
import { useWorkbenchStore } from "@/stores/workbench";

const route = useRoute();
const router = useRouter();
const health = useHealthStore();
const config = useConfigStore();
const workbench = useWorkbenchStore();

function icon(comp: unknown) {
  return () => h(NIcon, { size: 18 }, { default: () => h(comp as object) });
}

const menuOptions = computed<MenuOption[]>(() => [
  {
    type: "group",
    label: "研究",
    key: "g-research",
    children: [
      { label: "工作台", key: "workbench", icon: icon(ChatboxEllipsesOutline) },
      { label: "战略规划生成", key: "writing", icon: icon(DocumentTextOutline) },
    ],
  },
  {
    type: "group",
    label: "资产",
    key: "g-assets",
    children: [
      { label: "知识库", key: "knowledge", icon: icon(FolderOpenOutline) },
      { label: "知识图谱", key: "knowledge-graph", icon: icon(GitNetworkOutline) },
      { label: "Skill", key: "skills", icon: icon(ExtensionPuzzleOutline) },
    ],
  },
  {
    type: "group",
    label: "系统",
    key: "g-system",
    children: [
      { label: "模型", key: "models", icon: icon(HardwareChipOutline) },
      { label: "评测", key: "evaluation", icon: icon(SpeedometerOutline) },
      { label: "设置", key: "system", icon: icon(SettingsOutline) },
    ],
  },
]);

const activeKey = computed(() => String(route.name || "workbench"));
const isWorkbench = computed(() => route.name === "workbench");

function onMenuUpdate(key: string) {
  router.push({ name: key });
}

let offMenu: (() => void) | undefined;

onMounted(async () => {
  await Promise.all([health.refresh(), config.load()]);
  offMenu = window.realai?.onMenuAction?.((action, payload) => {
    if (action === "navigate" && typeof payload === "string") router.push(payload);
    else if (action === "toggle-evidence") workbench.toggleEvidence();
    else if (action === "new-ask") {
      router.push({ name: "workbench" });
      workbench.newAskFocus();
    } else if (action === "new-report") router.push({ name: "writing" });
    else if (action === "toggle-web-search") void config.cycleWebSearch();
    else if (action === "reload") window.location.reload();
  });
});

onUnmounted(() => offMenu?.());
</script>

<template>
  <NLayout has-sider class="shell">
    <NLayoutSider
      bordered
      collapse-mode="width"
      :collapsed-width="68"
      :width="260"
      show-trigger
      class="sider"
      :native-scrollbar="false"
    >
      <RouterLink
        :to="{ name: 'workbench' }"
        class="brand"
        aria-label="战略规划域多源多模态知识大脑"
      >
        <div class="logo">R</div>
        <div class="brand-text">
          <div class="name">战略规划域多源</div>
          <div class="tagline">多模态知识大脑</div>
        </div>
      </RouterLink>
      <NMenu
        :value="activeKey"
        :options="menuOptions"
        :collapsed-width="68"
        :collapsed-icon-size="20"
        @update:value="onMenuUpdate"
      />
    </NLayoutSider>
    <NLayoutContent class="content" :class="{ flush: isWorkbench }">
      <div class="content-inner">
        <HealthBanner />
        <div class="view-slot">
          <router-view />
        </div>
      </div>
    </NLayoutContent>
  </NLayout>
</template>

<style scoped>
.shell {
  width: 100%;
  height: 100%;
  max-height: 100%;
  overflow: hidden;
}
.shell :deep(.n-layout),
.shell :deep(.n-layout-scroll-container) {
  height: 100% !important;
  max-height: 100%;
}
.sider {
  background: var(--ra-sider) !important;
  border-right: 1px solid var(--ra-border) !important;
  height: 100% !important;
}
.sider :deep(.n-layout-sider-scroll-container) {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: auto;
}
.sider :deep(.n-menu) {
  flex: 1;
  padding: 0 8px 12px;
  min-height: 0;
  overflow: auto;
}
.sider :deep(.n-menu-item-group-title) {
  font-size: 11px;
  letter-spacing: 0.08em;
  color: #94a3b8 !important;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 14px 14px;
  color: var(--ra-text);
  flex-shrink: 0;
}
.logo {
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  border-radius: 14px;
  background: linear-gradient(145deg, var(--ra-secondary-blue), var(--ra-accent));
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 700;
  box-shadow: 0 10px 22px rgba(57, 126, 236, 0.3);
}
.brand-text {
  min-width: 0;
  line-height: 1.25;
}
.name {
  font-weight: 700;
  font-size: 14px;
  letter-spacing: -0.01em;
  white-space: nowrap;
}
.tagline {
  margin-top: 3px;
  color: var(--ra-muted);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.content {
  height: 100% !important;
  max-height: 100%;
  overflow: hidden !important;
  background: var(--ra-bg);
  background-image: var(--ra-bg-glow);
}
.content :deep(.n-layout-scroll-container) {
  height: 100% !important;
  max-height: 100%;
  overflow: hidden !important;
}
.content-inner {
  padding: 16px 20px 20px;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.content.flush .content-inner {
  padding: 10px 12px 12px;
}
.content-inner > :deep(.banner) {
  flex-shrink: 0;
}
.view-slot {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: auto; /* 普通页：高度充满窗口，超出滚动 */
}
.content.flush .view-slot {
  overflow: hidden; /* 工作台：内部列自己滚 */
}
.view-slot > :deep(*) {
  flex: 1 1 auto;
  min-height: 0;
  max-height: 100%;
}
</style>
