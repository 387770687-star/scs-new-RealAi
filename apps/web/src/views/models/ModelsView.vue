<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NDataTable,
  NDynamicInput,
  useMessage,
  type DataTableColumns,
  type SelectOption,
} from "naive-ui";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import {
  fetchModelsRouting,
  fetchRealAiConfig,
  saveRealAiConfig,
} from "@/api/realai";
import { ApiError } from "@/api/types";
import { formatTime } from "@/utils/format";

interface CatalogModel {
  id: string;
  label: string;
  apiModel: string;
}

const message = useMessage();
const loading = ref(false);
const saving = ref(false);
const loadKind = ref<"network" | "not_ready" | "error" | null>(null);
const loadError = ref("");

const form = ref({
  protocol: "openai_compatible" as "openai_compatible" | "anthropic",
  provider: "minimax",
  baseUrl: "https://api.minimaxi.com/v1",
  apiKey: "",
  hasApiKey: false,
  apiKeyPreview: "",
  models: [{ id: "minimax-m3", label: "MiniMax M3", apiModel: "MiniMax-M3" }] as CatalogModel[],
  roles: {
    primary: "minimax-m3",
    fast: "",
    vision: "",
    fallback: "",
  },
});

const protocolOptions: SelectOption[] = [
  { label: "OpenAI 兼容（MiniMax / DeepSeek 等）", value: "openai_compatible" },
  { label: "Anthropic", value: "anthropic" },
];

const calls = ref<Record<string, unknown>[]>([]);

const modelOptions = computed<SelectOption[]>(() =>
  form.value.models
    .filter((m) => m.id?.trim())
    .map((m) => ({
      label: `${m.label || m.apiModel || m.id}（${m.apiModel || m.id}）`,
      value: m.id,
    })),
);

const roleEmptyOptions = computed<SelectOption[]>(() => [
  { label: "未启用（用主模型）", value: "" },
  ...modelOptions.value,
]);

const callColumns: DataTableColumns<Record<string, unknown>> = [
  {
    title: "时间",
    key: "created_at",
    width: 160,
    render: (r) => formatTime(Number(r.created_at || 0)),
  },
  { title: "模型", key: "model", width: 140, ellipsis: { tooltip: true } },
  {
    title: "用途",
    key: "purpose",
    width: 120,
    ellipsis: { tooltip: true },
    render: (r) => String(r.purpose || "—"),
  },
  { title: "任务", key: "task_id", ellipsis: { tooltip: true } },
  {
    title: "耗时",
    key: "latency_ms",
    width: 90,
    render: (r) => (r.latency_ms != null ? `${Math.round(Number(r.latency_ms))}ms` : "—"),
  },
  {
    title: "降级",
    key: "degraded",
    width: 70,
    render: (r) => (r.degraded ? "是" : "否"),
  },
  {
    title: "错误",
    key: "error",
    ellipsis: { tooltip: true },
    render: (r) => String(r.error || "—"),
  },
];

function slugId(raw: string): string {
  return (
    raw
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, "-")
      .replace(/^-+|-+$/g, "") || `model-${Date.now().toString(36)}`
  );
}

function onProtocolChange(v: string) {
  form.value.protocol = v as "openai_compatible" | "anthropic";
  if (v === "anthropic") {
    if (!form.value.baseUrl || form.value.baseUrl.includes("minimax")) {
      form.value.baseUrl = "https://api.anthropic.com";
    }
    if (form.value.provider === "minimax") form.value.provider = "anthropic";
  } else if (v === "openai_compatible") {
    if (!form.value.baseUrl || form.value.baseUrl.includes("anthropic")) {
      form.value.baseUrl = "https://api.minimaxi.com/v1";
    }
    if (form.value.provider === "anthropic") form.value.provider = "minimax";
  }
}

function createModelRow(): CatalogModel {
  const n = form.value.models.length + 1;
  return { id: `model-${n}`, label: "", apiModel: "" };
}

async function load() {
  loading.value = true;
  loadError.value = "";
  loadKind.value = null;
  try {
    const cfg = await fetchRealAiConfig();
    const llm = cfg.settings?.llm || {};
    const catalog = (llm.models || []) as CatalogModel[];
    const roles = llm.roles || {};
    form.value = {
      protocol: (llm.protocol as "openai_compatible" | "anthropic") || "openai_compatible",
      provider: llm.provider || "minimax",
      baseUrl: llm.baseUrl || "",
      apiKey: "",
      hasApiKey: Boolean(llm.hasApiKey),
      apiKeyPreview: llm.apiKeyPreview || "",
      models:
        catalog.length > 0
          ? catalog.map((m) => ({
              id: m.id || slugId(m.apiModel || "model"),
              label: m.label || m.apiModel || "",
              apiModel: m.apiModel || "",
            }))
          : [
              {
                id: llm.modelId || "minimax-m3",
                label: llm.model || "MiniMax M3",
                apiModel: (llm.model || "MiniMax-M3").replace(/\s+/g, "-"),
              },
            ],
      roles: {
        primary: roles.primary || llm.modelId || catalog[0]?.id || "minimax-m3",
        fast: roles.fast || "",
        vision: roles.vision || "",
        fallback: roles.fallback || "",
      },
    };
    try {
      const routing = await fetchModelsRouting(80);
      calls.value = routing.calls || [];
    } catch {
      calls.value = [];
    }
  } catch (err) {
    if (err instanceof ApiError) {
      loadKind.value =
        err.kind === "network" ? "network" : err.kind === "not_ready" ? "not_ready" : "error";
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
  const cleaned = form.value.models
    .map((m, i) => {
      const apiModel = (m.apiModel || "").trim();
      if (!apiModel) return null;
      const id = (m.id || "").trim() || slugId(apiModel || `model-${i + 1}`);
      return {
        id,
        label: (m.label || "").trim() || apiModel,
        apiModel,
      };
    })
    .filter(Boolean) as CatalogModel[];

  if (!cleaned.length) {
    message.warning("请至少登记一个模型");
    return;
  }
  const ids = new Set(cleaned.map((m) => m.id));
  let primary = form.value.roles.primary;
  if (!primary || !ids.has(primary)) primary = cleaned[0].id;

  const roleOrEmpty = (v: string) => (v && ids.has(v) ? v : "");

  saving.value = true;
  try {
    const llm: Record<string, unknown> = {
      protocol: form.value.protocol,
      provider: form.value.provider,
      baseUrl: form.value.baseUrl,
      models: cleaned,
      roles: {
        primary,
        fast: roleOrEmpty(form.value.roles.fast),
        vision: roleOrEmpty(form.value.roles.vision),
        fallback: roleOrEmpty(form.value.roles.fallback),
      },
    };
    if (form.value.apiKey.trim()) llm.apiKey = form.value.apiKey.trim();
    await saveRealAiConfig({ llm });
    message.success("已保存并同步到 DeerFlow");
    form.value.apiKey = "";
    await load();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="ra-page ra-fade-in">
    <PageHeader title="模型">
      <template #actions>
        <NButton secondary @click="load">刷新</NButton>
        <NButton type="primary" :loading="saving" @click="save">保存</NButton>
      </template>
    </PageHeader>

    <NSpin :show="loading">
      <EmptyState
        v-if="loadKind"
        :kind="loadKind"
        :text="loadError || undefined"
        action-label="重试"
        @action="load"
      />
      <div v-else class="grid">
        <div class="left">
          <section class="ra-panel">
            <h3>连接</h3>
            <p class="hint">一套连接（协议 / 地址 / Key），可登记多个模型名并分配用途。</p>
            <NForm label-placement="top">
              <NFormItem label="协议">
                <NSelect
                  :value="form.protocol"
                  :options="protocolOptions"
                  @update:value="onProtocolChange"
                />
              </NFormItem>
              <NFormItem label="厂商">
                <NInput v-model:value="form.provider" placeholder="如 minimax / anthropic" />
              </NFormItem>
              <NFormItem label="Base URL">
                <NInput v-model:value="form.baseUrl" placeholder="接口根地址" />
              </NFormItem>
              <NFormItem :label="form.hasApiKey ? `Key（${form.apiKeyPreview || '已配置'}）` : 'Key'">
                <NInput
                  v-model:value="form.apiKey"
                  type="password"
                  show-password-on="click"
                  placeholder="留空不改"
                />
              </NFormItem>
            </NForm>
          </section>

          <section class="ra-panel">
            <h3>模型清单</h3>
            <p class="hint">每行：内部 id、显示名、厂商真实模型名（apiModel）。</p>
            <NDynamicInput v-model:value="form.models" :on-create="createModelRow">
              <template #default="{ value }">
                <div class="model-row">
                  <NInput v-model:value="value.id" placeholder="id" />
                  <NInput v-model:value="value.label" placeholder="显示名" />
                  <NInput v-model:value="value.apiModel" placeholder="apiModel" />
                </div>
              </template>
            </NDynamicInput>
          </section>

          <section class="ra-panel">
            <h3>角色选用</h3>
            <p class="hint">从清单里选哪个做主/高速/视觉/备用。高速未选则问数也用主模型。</p>
            <NForm label-placement="top">
              <NFormItem label="主模型（问答 / 写作默认）">
                <NSelect v-model:value="form.roles.primary" :options="modelOptions" />
              </NFormItem>
              <NFormItem label="高速（问数等）">
                <NSelect v-model:value="form.roles.fast" :options="roleEmptyOptions" clearable />
              </NFormItem>
              <NFormItem label="视觉（预留）">
                <NSelect v-model:value="form.roles.vision" :options="roleEmptyOptions" clearable />
              </NFormItem>
              <NFormItem label="备用（失败时降级）">
                <NSelect v-model:value="form.roles.fallback" :options="roleEmptyOptions" clearable />
              </NFormItem>
            </NForm>
            <NSpace>
              <NButton type="primary" :loading="saving" @click="save">保存</NButton>
            </NSpace>
          </section>
        </div>

        <section class="ra-panel">
          <h3>调用记录</h3>
          <NDataTable
            v-if="calls.length"
            :columns="callColumns"
            :data="calls"
            size="small"
            :bordered="false"
            :max-height="560"
          />
          <EmptyState v-else text="暂无记录" />
        </section>
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: minmax(360px, 420px) minmax(0, 1fr);
  gap: 12px;
}
.left {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ra-panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--ra-border);
  border-radius: 18px;
  padding: 16px;
}
h3 {
  margin: 0 0 8px;
  font-size: 15px;
}
.hint {
  margin: 0 0 12px;
  color: var(--ra-muted);
  font-size: 12px;
  line-height: 1.5;
}
.model-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1.2fr;
  gap: 8px;
  width: 100%;
}
</style>
