<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NSwitch,
  NSelect,
  NSpin,
  NDivider,
  NDynamicInput,
  useMessage,
} from "naive-ui";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import {
  completeOnboarding,
  fetchRealAiConfig,
  fetchRealAiHealth,
  saveRealAiConfig,
  syncRealAiConfig,
} from "@/api/realai";
import { ApiError, type RealAiSettings } from "@/api/types";
import { useHealthStore } from "@/stores/health";
import { useConfigStore } from "@/stores/config";
import {
  WEB_SEARCH_MODE_OPTIONS,
  normalizeWebSearchMode,
  type WebSearchMode,
} from "@/utils/webSearchMode";
import {
  VISION_MODE_OPTIONS,
  normalizeVisionMode,
  type VisionMode,
} from "@/utils/visionMode";

const message = useMessage();
const router = useRouter();
const healthStore = useHealthStore();
const configStore = useConfigStore();

const loading = ref(false);
const saving = ref(false);
const loadKind = ref<"network" | "not_ready" | "error" | null>(null);
const loadError = ref("");
const healthJson = ref("");
const modelSummary = ref("未配置");

const form = ref({
  obsidianVaultPath: "",
  webSearchMode: "auto" as WebSearchMode,
  visionMode: "auto" as VisionMode,
  webSearchSkillId: "web-search",
  reportOutputDir: "",
  stepConfirm: false,
  intakeSkillId: "strategic-planning-intake",
  researcherSkillId: "strategic-planning-researcher",
  architectSkillId: "strategic-planning-architect",
  writerSkillId: "strategic-planning-writer",
  citerSkillId: "strategic-planning-citer",
  reviewSkillId: "strategic-planning-reviewer",
  optimizerSkillId: "strategic-planning-optimizer",
  excelRoots: [] as string[],
});

const onboardingKey = ref("");
const onboardingWebMode = ref<WebSearchMode>("auto");
const onboardingDemo = ref(true);

async function load() {
  loading.value = true;
  loadKind.value = null;
  try {
    const [cfg, health] = await Promise.all([fetchRealAiConfig(), fetchRealAiHealth()]);
    healthJson.value = JSON.stringify(health, null, 2);
    const s = cfg.settings || {};
    const llm = s.llm || {};
    const primary = llm.roles?.primary || llm.modelId || llm.model || "—";
    const proto = llm.protocol === "anthropic" ? "Anthropic" : "OpenAI 兼容";
    modelSummary.value = llm.hasApiKey
      ? `${proto} · ${llm.provider || "—"} · 主模型 ${primary}`
      : `${proto} · 尚未配置 Key（请到「模型」页）`;
    form.value = {
      obsidianVaultPath: s.obsidianVaultPath || cfg.vault_path || "",
      webSearchMode: normalizeWebSearchMode(
        s.search?.webSearchMode,
        s.search?.webSearchEnabled,
      ),
      visionMode: normalizeVisionMode(s.search?.visionMode),
      webSearchSkillId: s.search?.webSearchSkillId || "web-search",
      reportOutputDir: s.report?.outputDir || "",
      stepConfirm: Boolean(s.report?.stepConfirm),
      intakeSkillId: s.report?.intakeSkillId || "strategic-planning-intake",
      researcherSkillId: s.report?.researcherSkillId || "strategic-planning-researcher",
      architectSkillId: s.report?.architectSkillId || "strategic-planning-architect",
      writerSkillId: s.report?.writerSkillId || "strategic-planning-writer",
      citerSkillId: s.report?.citerSkillId || "strategic-planning-citer",
      reviewSkillId: s.report?.reviewSkillId || "strategic-planning-reviewer",
      optimizerSkillId: s.report?.optimizerSkillId || "strategic-planning-optimizer",
      excelRoots: [...(s.data?.excelRoots || [])],
    };
    await healthStore.refresh();
    await configStore.load();
  } catch (err) {
    if (err instanceof ApiError) {
      loadKind.value = err.kind === "network" ? "network" : err.kind === "not_ready" ? "not_ready" : "error";
      loadError.value = err.message;
    } else {
      loadKind.value = "error";
      loadError.value = String(err);
    }
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const body: Partial<RealAiSettings> = {
      obsidianVaultPath: form.value.obsidianVaultPath,
      search: {
        webSearchMode: form.value.webSearchMode,
        webSearchEnabled: form.value.webSearchMode !== "off",
        webSearchSkillId: form.value.webSearchSkillId || "web-search",
        visionMode: form.value.visionMode,
      },
      report: {
        outputDir: form.value.reportOutputDir,
        stepConfirm: form.value.stepConfirm,
        intakeSkillId: form.value.intakeSkillId,
        researcherSkillId: form.value.researcherSkillId,
        architectSkillId: form.value.architectSkillId,
        writerSkillId: form.value.writerSkillId,
        citerSkillId: form.value.citerSkillId,
        reviewSkillId: form.value.reviewSkillId,
        optimizerSkillId: form.value.optimizerSkillId,
      },
      data: { excelRoots: form.value.excelRoots.filter(Boolean) },
    };
    await saveRealAiConfig(body);
    message.success("配置已保存");
    await load();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    saving.value = false;
  }
}

async function sync() {
  try {
    await syncRealAiConfig();
    message.success("已同步到 DeerFlow");
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

async function runOnboarding() {
  if (!onboardingKey.value.trim()) {
    message.warning("请填写 API Key");
    return;
  }
  try {
    await completeOnboarding({
      api_key: onboardingKey.value.trim(),
      web_search_mode: onboardingWebMode.value,
      web_search_enabled: onboardingWebMode.value !== "off",
      import_demo: onboardingDemo.value,
    });
    message.success("向导已完成");
    onboardingKey.value = "";
    await load();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

onMounted(load);
</script>

<template>
  <div class="ra-page ra-fade-in">
    <PageHeader title="设置">
      <template #actions>
        <NButton secondary @click="load">刷新</NButton>
        <NButton secondary @click="sync">同步 DeerFlow</NButton>
        <NButton type="primary" :loading="saving" @click="save">保存配置</NButton>
      </template>
    </PageHeader>

    <NSpin :show="loading">
      <EmptyState
        v-if="loadKind"
        :kind="loadKind"
        :description="loadError"
        action-label="重试"
        @action="load"
      />
      <div v-else class="grid">
        <section class="ra-panel">
          <h3>配置 · 规划人员常用</h3>
          <NForm label-placement="top">
            <NFormItem label="Obsidian Vault 路径">
              <NInput v-model:value="form.obsidianVaultPath" />
            </NFormItem>
            <NFormItem label="默认联网（关闭 / 智能 / 强制）">
              <NSelect
                v-model:value="form.webSearchMode"
                :options="WEB_SEARCH_MODE_OPTIONS"
                style="width: 160px"
              />
            </NFormItem>
            <NFormItem label="默认看图（关闭 / 智能 / 强制）">
              <NSelect
                v-model:value="form.visionMode"
                :options="VISION_MODE_OPTIONS"
                style="width: 160px"
              />
            </NFormItem>
            <NFormItem label="报告输出目录（Vault 相对路径）">
              <NInput v-model:value="form.reportOutputDir" />
            </NFormItem>
            <NFormItem label="报告逐步确认">
              <NSwitch v-model:value="form.stepConfirm" />
            </NFormItem>
            <NFormItem label="摸底问答 Skill ID">
              <NInput v-model:value="form.intakeSkillId" />
            </NFormItem>
            <NFormItem label="研究 Skill ID">
              <NInput v-model:value="form.researcherSkillId" />
            </NFormItem>
            <NFormItem label="架构 Skill ID">
              <NInput v-model:value="form.architectSkillId" />
            </NFormItem>
            <NFormItem label="写作 Skill ID">
              <NInput v-model:value="form.writerSkillId" />
            </NFormItem>
            <NFormItem label="引用 Skill ID">
              <NInput v-model:value="form.citerSkillId" />
            </NFormItem>
            <NFormItem label="评审 Skill ID">
              <NInput v-model:value="form.reviewSkillId" />
            </NFormItem>
            <NFormItem label="优化 Skill ID">
              <NInput v-model:value="form.optimizerSkillId" />
            </NFormItem>
          </NForm>
        </section>

        <section class="ra-panel">
          <h3>配置 · 系统管理员</h3>
          <NForm label-placement="top">
            <NFormItem label="模型">
              <div class="model-jump">
                <p class="muted">{{ modelSummary }}</p>
                <NButton secondary @click="router.push({ name: 'models' })">打开模型中心</NButton>
              </div>
            </NFormItem>
            <NFormItem label="Excel 根目录">
              <NDynamicInput v-model:value="form.excelRoots" />
            </NFormItem>
          </NForm>
        </section>

        <section class="ra-panel">
          <h3>运维 · 健康检查</h3>
          <pre class="health">{{ healthJson || "（无数据）" }}</pre>
        </section>

        <section class="ra-panel">
          <h3>首次向导</h3>
          <p class="muted">适合首次安装：填写 Key，可选导入油气管道示例资料。</p>
          <NForm label-placement="top">
            <NFormItem label="API Key">
              <NInput v-model:value="onboardingKey" type="password" show-password-on="click" />
            </NFormItem>
            <NFormItem label="默认联网模式">
              <NSelect
                v-model:value="onboardingWebMode"
                :options="WEB_SEARCH_MODE_OPTIONS"
                style="width: 160px"
              />
            </NFormItem>
            <NFormItem label="导入示例资料">
              <NSwitch v-model:value="onboardingDemo" />
            </NFormItem>
            <NButton type="primary" secondary @click="runOnboarding">完成向导</NButton>
          </NForm>
          <NDivider />
          <p class="muted">桌面菜单「帮助 → 健康检查」会刷新本页状态。模型协议与多模型请到「模型」页配置。</p>
        </section>
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.muted {
  color: var(--ra-muted);
  font-size: 12px;
  line-height: 1.5;
}
.model-jump {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}
.health {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  background: #f8fafc;
  border-radius: 10px;
  padding: 12px;
  font-size: 12px;
}
</style>
