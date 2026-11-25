<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from "vue";
import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NInput,
  NModal,
  NProgress,
  NSelect,
  NSpace,
  NSpin,
  useMessage,
  type DataTableColumns,
} from "naive-ui";
import { useRouter } from "vue-router";
import EmptyState from "@/components/EmptyState.vue";
import {
  createMetric,
  deleteMetric,
  downloadVaultFile,
  fetchImportJob,
  fetchVaultCatalog,
  fetchVaultFilePreview,
  fetchVaultHealth,
  fetchVaultStatus,
  importVaultBatch,
  importVaultFromRaw,
  listImportJobs,
  listMetrics,
  rebuildVaultIndex,
  rebuildWiki,
  seedMetrics,
  updateMetric,
  vaultFileDownloadHref,
} from "@/api/realai";
import type {
  KnowledgeCatalogItem,
  KnowledgeCatalogResponse,
  KnowledgeQualityStatus,
  KnowledgeSourceStatus,
  KnowledgeType,
  Metric,
  VaultFilePreview,
  VaultImportJob,
} from "@/api/types";
import { useWorkbenchStore } from "@/stores/workbench";
import { formatBytes, formatTime } from "@/utils/format";
import { KNOWLEDGE_TYPE_DEFINITIONS } from "@/utils/knowledgeTypes";

type PageSection = "home" | "browse" | "governance";
type CatalogLayout = "grid" | "list";

const TYPE_DEFINITIONS = KNOWLEDGE_TYPE_DEFINITIONS;

const SOURCE_OPTIONS: Array<{
  label: string;
  value: KnowledgeSourceStatus | "";
}> = [
  { label: "全部来源状态", value: "" },
  { label: "原始资料", value: "raw" },
  { label: "已整理", value: "curated" },
  { label: "知识加工", value: "derived" },
  { label: "生成成果", value: "generated" },
];

const QUALITY_OPTIONS: Array<{
  label: string;
  value: KnowledgeQualityStatus | "";
}> = [
  { label: "全部质量状态", value: "" },
  { label: "可用", value: "ready" },
  { label: "待完善", value: "needs_attention" },
];

const message = useMessage();
const router = useRouter();
const workbench = useWorkbenchStore();

const section = ref<PageSection>("home");
const layout = ref<CatalogLayout>("grid");
const loading = ref(false);
const errorMsg = ref("");
const q = ref("");
const selectedType = ref<KnowledgeType | "all">("all");
const sourceFilter = ref<KnowledgeSourceStatus | "">("");
const qualityFilter = ref<KnowledgeQualityStatus | "">("");
const businessFilter = ref("");
const catalog = ref<KnowledgeCatalogResponse | null>(null);
const health = ref<Record<string, unknown> | null>(null);
const metrics = ref<Metric[]>([]);
const vaultPath = ref("");

const selectedItem = ref<KnowledgeCatalogItem | null>(null);
const preview = ref<VaultFilePreview | null>(null);
const previewOpen = ref(false);
const previewLoading = ref(false);
const previewPath = ref("");
const previewSheetIndex = ref(0);

const importing = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const batchInput = ref<HTMLInputElement | null>(null);
const dragOver = ref(false);
const batchPct = ref(0);
const batchStatus = ref("");
const activeImportJob = ref<VaultImportJob | null>(null);
const importPanelVisible = ref(false);
let importPollGeneration = 0;

const metricOpen = ref(false);
const seedingMetrics = ref(false);
const metricForm = ref({
  id: "",
  name: "",
  aliases: "",
  formula: "",
  unit: "",
});

const allItems = computed(() => catalog.value?.items || []);
const typeDefinition = computed(
  () =>
    TYPE_DEFINITIONS.find((item) => item.key === selectedType.value) || null,
);
const businessOptions = computed(() => [
  { label: "全部业务标签", value: "" },
  ...Object.entries(catalog.value?.business_tag_counts || {})
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => ({ label: `${label} ${count}`, value: label })),
]);

const filteredItems = computed(() => {
  const needle = q.value.trim().toLowerCase();
  return allItems.value.filter((item) => {
    if (
      selectedType.value !== "all" &&
      item.knowledge_type !== selectedType.value
    ) {
      return false;
    }
    if (sourceFilter.value && item.source_status !== sourceFilter.value) {
      return false;
    }
    if (qualityFilter.value && item.quality_status !== qualityFilter.value) {
      return false;
    }
    if (
      businessFilter.value &&
      !item.business_tags.includes(businessFilter.value)
    ) {
      return false;
    }
    if (!needle) return true;
    return [
      item.title,
      item.summary,
      item.path,
      item.knowledge_type_label,
      ...item.business_tags,
    ]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });
});

const recentItems = computed(() =>
  allItems.value
    .filter((item) => item.quality_status === "ready")
    .slice(0, 6),
);

const readyCount = computed(
  () => catalog.value?.quality_counts.ready || 0,
);
const attentionCount = computed(
  () => catalog.value?.quality_counts.needs_attention || 0,
);
const previewFile = computed(() =>
  selectedItem.value?.files.find((file) => file.path === previewPath.value),
);
const activeSheet = computed(
  () => preview.value?.sheets?.[previewSheetIndex.value] || null,
);

function typeDef(key: KnowledgeType) {
  return (
    TYPE_DEFINITIONS.find((item) => item.key === key) || TYPE_DEFINITIONS[0]
  );
}

function typeCount(key: KnowledgeType) {
  return catalog.value?.type_counts[key] || 0;
}

function healthLine(key: string) {
  if (!health.value || health.value[key] == null) return "—";
  const value = health.value[key];
  if (key === "checked_at" && typeof value === "number") {
    return formatTime(value);
  }
  if (key === "eval_pass_rate" && typeof value === "number") {
    return `${Math.round(value * 100)}%`;
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function showBrowse(type: KnowledgeType | "all" = "all") {
  selectedType.value = type;
  section.value = "browse";
}

function clearFilters() {
  q.value = "";
  sourceFilter.value = "";
  qualityFilter.value = "";
  businessFilter.value = "";
}

async function load(force = false) {
  loading.value = true;
  errorMsg.value = "";
  try {
    const [catalogData, status, healthData, metricData] = await Promise.all([
      fetchVaultCatalog({ limit: 500, refresh: force }),
      fetchVaultStatus(),
      fetchVaultHealth(),
      listMetrics(),
    ]);
    catalog.value = catalogData;
    vaultPath.value = status.vault_path;
    health.value = healthData;
    metrics.value = metricData.metrics;
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : String(error);
  } finally {
    loading.value = false;
  }
}

async function openPreview(item: KnowledgeCatalogItem) {
  selectedItem.value = item;
  preview.value = null;
  previewOpen.value = true;
  const original = item.files.find((file) => file.role === "original");
  await openFilePreview(original?.path || item.original_path || item.path);
}

async function openFilePreview(path: string) {
  previewPath.value = path;
  previewSheetIndex.value = 0;
  preview.value = null;
  previewLoading.value = true;
  try {
    preview.value = await fetchVaultFilePreview(path);
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error));
  } finally {
    previewLoading.value = false;
  }
}

function scopeForItem(item: KnowledgeCatalogItem) {
  const supported = [
    "pipelines",
    "new_energy",
    "dataqa",
    "entities",
    "05_Metrics",
    "wiki",
    "raw",
  ];
  return supported.find((scope) => item.path.split("/").includes(scope)) || "";
}

async function useInWorkbench(item: KnowledgeCatalogItem) {
  const scope = scopeForItem(item);
  workbench.scopePaths = scope ? [scope] : [];
  workbench.setIntent(item.knowledge_type === "dataset" ? "data" : "ask");
  workbench.draft = `请基于知识库中的《${item.title}》进行分析`;
  previewOpen.value = false;
  await router.push({ name: "workbench" });
}

async function useInWriting(item: KnowledgeCatalogItem) {
  previewOpen.value = false;
  await router.push({ name: "writing", query: { source: item.path } });
}

async function importOne(file: File) {
  await importMany([file]);
}

function importStageLabel(stage?: string) {
  const labels: Record<string, string> = {
    queued: "等待处理",
    preparing: "准备导入",
    validating: "校验文件",
    classifying: "识别分类",
    preserving: "保存原件",
    extracting: "提取内容",
    converting: "转换文档",
    structuring: "生成问数表",
    storing: "写入知识库",
    knowledge_processing: "加工知识",
    indexing: "刷新索引",
    completed: "导入完成",
    failed: "导入失败",
  };
  return labels[stage || ""] || stage || "处理中";
}

async function pollImportJob(jobId: string, generation: number) {
  while (generation === importPollGeneration) {
    const job = await fetchImportJob(jobId);
    if (generation !== importPollGeneration) return;
    activeImportJob.value = job;
    batchPct.value = Math.max(batchPct.value, job.progress || 0);
    batchStatus.value = job.message || importStageLabel(job.stage);
    if (!["queued", "running"].includes(job.status)) {
      importing.value = false;
      batchPct.value = 100;
      if (job.status === "completed" && !job.failed) {
        message.success(`知识导入完成，共 ${job.done} 个文件`);
      } else if (job.done) {
        message.warning(`导入完成：成功 ${job.done} 个，失败 ${job.failed} 个`);
      } else {
        message.error(job.error || job.message || "导入失败");
      }
      await load(true);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

async function restoreImportJob() {
  try {
    const { jobs } = await listImportJobs(10);
    const running = jobs.find((job) => ["queued", "running"].includes(job.status));
    if (!running) return;
    activeImportJob.value = running;
    importPanelVisible.value = true;
    importing.value = true;
    batchPct.value = running.progress || 0;
    batchStatus.value = running.message || importStageLabel(running.stage);
    const generation = ++importPollGeneration;
    await pollImportJob(running.id, generation);
  } catch {
    importing.value = false;
    batchStatus.value = "无法恢复上次导入任务，请重新上传";
  }
}

async function importMany(files: File[]) {
  if (!files.length) return;
  const generation = ++importPollGeneration;
  importing.value = true;
  importPanelVisible.value = true;
  activeImportJob.value = null;
  batchPct.value = 0;
  batchStatus.value = "正在上传文件";
  try {
    const job = await importVaultBatch(files, (percentage) => {
      if (generation !== importPollGeneration) return;
      batchPct.value = Math.round(percentage * 0.12);
      batchStatus.value = `正在上传文件 ${percentage}%`;
    });
    if (generation !== importPollGeneration) return;
    activeImportJob.value = job;
    batchPct.value = Math.max(batchPct.value, job.progress || 0);
    batchStatus.value = job.message || "文件上传完成，等待解析";
    await pollImportJob(job.id, generation);
  } catch (error) {
    importing.value = false;
    message.error(error instanceof Error ? error.message : String(error));
  }
}

async function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (file) await importOne(file);
}

async function onBatchPicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  input.value = "";
  await importMany(files);
}

function onDrop(event: DragEvent) {
  event.preventDefault();
  dragOver.value = false;
  const files = Array.from(event.dataTransfer?.files || []);
  if (files.length === 1 && files[0]) void importOne(files[0]);
  else if (files.length > 1) void importMany(files);
}

async function onFromRaw() {
  importing.value = true;
  try {
    const result = await importVaultFromRaw();
    message.success(result.message || `完成 ${result.ok}/${result.total}`);
    await load(true);
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error));
  } finally {
    importing.value = false;
  }
}

async function onRebuildWiki() {
  try {
    const result = await rebuildWiki();
    message.success(`知识加工完成：实体 ${result.entities_written ?? 0}`);
    await load(true);
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error));
  }
}

async function onRebuildIndex() {
  try {
    const result = await rebuildVaultIndex();
    message.success(result.message || "检索索引已重建");
    await load(true);
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error));
  }
}

function openNewMetric() {
  metricForm.value = {
    id: "",
    name: "",
    aliases: "",
    formula: "",
    unit: "",
  };
  metricOpen.value = true;
}

async function saveMetric() {
  const body = {
    name: metricForm.value.name.trim(),
    aliases: metricForm.value.aliases
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean),
    formula: metricForm.value.formula || null,
    unit: metricForm.value.unit || null,
  };
  if (!body.name) return;
  if (metricForm.value.id) await updateMetric(metricForm.value.id, body);
  else await createMetric(body);
  metricOpen.value = false;
  await load(true);
}

async function onSeedMetrics() {
  seedingMetrics.value = true;
  try {
    const result = await seedMetrics();
    message.success(`口径种子完成，新增 ${result.created} 条`);
    await load(true);
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error));
  } finally {
    seedingMetrics.value = false;
  }
}

const metricColumns: DataTableColumns<Metric> = [
  { title: "指标名称", key: "name", width: 150 },
  {
    title: "别名",
    key: "aliases",
    render: (row) => (row.aliases || []).join("、") || "—",
  },
  {
    title: "公式或权威来源",
    key: "formula",
    ellipsis: { tooltip: true },
    render: (row) => row.formula || "—",
  },
  {
    title: "单位",
    key: "unit",
    width: 90,
    render: (row) => row.unit || "—",
  },
  {
    title: "",
    key: "actions",
    width: 130,
    render: (row) =>
      h(
        NSpace,
        { size: 4 },
        {
          default: () => [
            h(
              NButton,
              {
                size: "tiny",
                quaternary: true,
                onClick: () => {
                  metricForm.value = {
                    id: row.id,
                    name: row.name,
                    aliases: (row.aliases || []).join(","),
                    formula: row.formula || "",
                    unit: row.unit || "",
                  };
                  metricOpen.value = true;
                },
              },
              { default: () => "编辑" },
            ),
            h(
              NButton,
              {
                size: "tiny",
                quaternary: true,
                onClick: async () => {
                  await deleteMetric(row.id);
                  await load(true);
                },
              },
              { default: () => "删除" },
            ),
          ],
        },
      ),
  },
];

onMounted(async () => {
  await load();
  void restoreImportJob();
});

onUnmounted(() => {
  importPollGeneration += 1;
});
</script>

<template>
  <div class="ra-page ra-fade-in knowledge-page">
    <header class="knowledge-header">
      <div>
        <h1>知识库</h1>
        <p>统一管理文档、数据、实体、指标和分析成果</p>
      </div>
      <div class="header-actions">
        <NInput
          v-model:value="q"
          clearable
          placeholder="搜索标题、摘要、标签或路径"
          class="header-search"
          @keyup.enter="showBrowse(selectedType)"
        />
        <NButton secondary @click="load(true)">刷新</NButton>
        <NButton type="primary" :loading="importing" @click="fileInput?.click()">
          导入知识
        </NButton>
      </div>
    </header>

    <nav class="section-tabs" aria-label="知识库页面">
      <button
        type="button"
        :class="{ active: section === 'home' }"
        @click="section = 'home'"
      >
        知识首页
      </button>
      <button
        type="button"
        :class="{ active: section === 'browse' }"
        @click="section = 'browse'"
      >
        分类浏览
      </button>
      <button
        type="button"
        :class="{ active: section === 'governance' }"
        @click="section = 'governance'"
      >
        知识治理
        <span v-if="attentionCount" class="tab-badge">{{ attentionCount }}</span>
      </button>
    </nav>

    <section v-if="importPanelVisible" class="import-progress-panel ra-surface">
      <div class="import-progress-head">
        <div>
          <strong>{{ batchStatus || "正在导入知识" }}</strong>
          <span v-if="activeImportJob?.current_file">
            当前文件：{{ activeImportJob.current_file }}
          </span>
          <span v-else-if="activeImportJob">
            已完成 {{ activeImportJob.done }}/{{ activeImportJob.total }}
            <template v-if="activeImportJob.failed">
              · 失败 {{ activeImportJob.failed }}
            </template>
          </span>
          <span v-else>文件上传完成后将自动解析、加工并建立索引</span>
        </div>
        <button
          v-if="!importing"
          type="button"
          class="import-close"
          aria-label="关闭导入进度"
          @click="importPanelVisible = false"
        >
          ×
        </button>
      </div>
      <NProgress
        type="line"
        :percentage="batchPct"
        :status="activeImportJob?.status === 'failed' ? 'error' : 'default'"
        :processing="importing"
      />
      <div v-if="activeImportJob?.items?.length" class="import-items">
        <div
          v-for="item in activeImportJob.items"
          :key="item.name"
          class="import-item"
          :class="item.status"
        >
          <span class="import-item-state">
            {{
              item.status === "completed"
                ? "✓"
                : item.status === "failed"
                  ? "!"
                  : item.status === "running"
                    ? "↻"
                    : "·"
            }}
          </span>
          <span class="import-item-copy">
            <strong>{{ item.name }}</strong>
            <small>{{ item.message || importStageLabel(item.stage) }}</small>
          </span>
          <span class="import-item-progress">{{ item.progress || 0 }}%</span>
        </div>
      </div>
    </section>

    <input ref="fileInput" type="file" hidden @change="onFilePicked" />
    <input
      ref="batchInput"
      type="file"
      multiple
      hidden
      @change="onBatchPicked"
    />

    <NSpin :show="loading" class="knowledge-spin">
      <EmptyState
        v-if="errorMsg"
        kind="network"
        :text="errorMsg"
        action-label="重试"
        @action="load(true)"
      />

      <main v-else-if="section === 'home'" class="home-view">
        <section
          class="knowledge-hero"
          :class="{ over: dragOver }"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop="onDrop"
        >
          <div class="hero-copy">
            <span class="eyebrow">知识资产中心</span>
            <h2>从资料到知识，从知识到决策</h2>
            <p>
              已汇聚 {{ catalog?.total || 0 }} 项逻辑知识，覆盖
              {{ TYPE_DEFINITIONS.length }} 类数据模型。拖入文件即可自动识别和加工。
            </p>
          </div>
          <div class="hero-search">
            <NInput
              v-model:value="q"
              size="large"
              clearable
              placeholder="搜索文档、数据集、实体、指标或报告"
              @keyup.enter="showBrowse('all')"
            />
            <NButton size="large" type="primary" @click="showBrowse('all')">
              搜索知识
            </NButton>
          </div>
          <div class="hero-drop-hint">
            将文件拖到这里，系统会自动识别数据类型和业务标签
          </div>
        </section>

        <section class="home-section">
          <div class="section-heading">
            <div>
              <h2>按数据类型浏览</h2>
              <p>分类由内容形态决定，业务领域作为可组合标签</p>
            </div>
            <button type="button" class="text-link" @click="showBrowse('all')">
              查看全部 →
            </button>
          </div>
          <div class="type-grid">
            <button
              v-for="item in TYPE_DEFINITIONS"
              :key="item.key"
              type="button"
              class="type-card"
              @click="showBrowse(item.key)"
            >
              <span
                class="type-glyph"
                :style="{ color: item.color, background: item.soft }"
              >
                {{ item.glyph }}
              </span>
              <span class="type-card-copy">
                <strong>{{ item.label }}</strong>
                <small>{{ item.description }}</small>
              </span>
              <span class="type-count">{{ typeCount(item.key) }}</span>
            </button>
          </div>
        </section>

        <section class="home-columns">
          <div class="ra-surface recent-panel">
            <div class="section-heading compact">
              <div>
                <h2>最近更新</h2>
                <p>最近进入知识库且可直接使用的内容</p>
              </div>
            </div>
            <div v-if="recentItems.length" class="recent-list">
              <button
                v-for="item in recentItems"
                :key="item.id"
                type="button"
                class="recent-item"
                @click="openPreview(item)"
              >
                <span
                  class="mini-glyph"
                  :style="{
                    color: typeDef(item.knowledge_type).color,
                    background: typeDef(item.knowledge_type).soft,
                  }"
                >
                  {{ typeDef(item.knowledge_type).glyph }}
                </span>
                <span class="recent-copy">
                  <strong>{{ item.title }}</strong>
                  <small>
                    {{ item.knowledge_type_label }} ·
                    {{ formatTime(item.mtime) }}
                  </small>
                </span>
                <span class="recent-arrow">›</span>
              </button>
            </div>
            <EmptyState v-else text="暂无知识" />
          </div>

          <div class="ra-surface overview-panel">
            <div class="section-heading compact">
              <div>
                <h2>知识资产概览</h2>
                <p>面向问答、问数和报告写作的可用状态</p>
              </div>
            </div>
            <div class="overview-numbers">
              <button type="button" @click="showBrowse('all')">
                <strong>{{ readyCount }}</strong>
                <span>可直接使用</span>
              </button>
              <button
                type="button"
                @click="
                  qualityFilter = 'needs_attention';
                  showBrowse('all');
                "
              >
                <strong>{{ attentionCount }}</strong>
                <span>需要完善</span>
              </button>
              <button type="button" @click="showBrowse('entity')">
                <strong>{{ typeCount("entity") }}</strong>
                <span>实体与关系</span>
              </button>
              <button type="button" @click="showBrowse('knowledge_card')">
                <strong>{{ typeCount("knowledge_card") }}</strong>
                <span>知识卡片</span>
              </button>
            </div>
            <div class="governance-notice">
              <div>
                <strong>知识质量提醒</strong>
                <span>
                  重复内容 {{ healthLine("content_dupes") }} · 重名冲突
                  {{ healthLine("conflict_name_dupes") }}
                </span>
              </div>
              <NButton size="small" secondary @click="section = 'governance'">
                去治理
              </NButton>
            </div>
          </div>
        </section>
      </main>

      <main v-else-if="section === 'browse'" class="browse-view">
        <aside class="catalog-sidebar ra-surface">
          <div class="sidebar-title">数据类型</div>
          <button
            type="button"
            class="catalog-nav-item"
            :class="{ active: selectedType === 'all' }"
            @click="selectedType = 'all'"
          >
            <span class="nav-glyph all">全</span>
            <span>全部知识</span>
            <small>{{ catalog?.total || 0 }}</small>
          </button>
          <button
            v-for="item in TYPE_DEFINITIONS"
            :key="item.key"
            type="button"
            class="catalog-nav-item"
            :class="{ active: selectedType === item.key }"
            @click="selectedType = item.key"
          >
            <span
              class="nav-glyph"
              :style="{ color: item.color, background: item.soft }"
            >
              {{ item.glyph }}
            </span>
            <span>{{ item.label }}</span>
            <small>{{ typeCount(item.key) }}</small>
          </button>

          <div class="sidebar-divider" />
          <div class="sidebar-title">快捷视图</div>
          <button
            type="button"
            class="catalog-nav-item text-only"
            :class="{ active: qualityFilter === 'needs_attention' }"
            @click="
              qualityFilter =
                qualityFilter === 'needs_attention' ? '' : 'needs_attention'
            "
          >
            <span>待完善知识</span>
            <small>{{ attentionCount }}</small>
          </button>
          <button
            type="button"
            class="catalog-nav-item text-only"
            :class="{ active: sourceFilter === 'raw' }"
            @click="sourceFilter = sourceFilter === 'raw' ? '' : 'raw'"
          >
            <span>原始资料</span>
            <small>{{ catalog?.source_counts.raw || 0 }}</small>
          </button>
        </aside>

        <section class="catalog-main">
          <div class="catalog-toolbar ra-surface">
            <div class="catalog-title">
              <h2>{{ typeDefinition?.label || "全部知识" }}</h2>
              <p>
                {{
                  typeDefinition?.description ||
                  "跨数据类型浏览和检索全部知识资产"
                }}
              </p>
            </div>
            <div class="catalog-layout-toggle">
              <button
                type="button"
                :class="{ active: layout === 'grid' }"
                @click="layout = 'grid'"
              >
                卡片
              </button>
              <button
                type="button"
                :class="{ active: layout === 'list' }"
                @click="layout = 'list'"
              >
                列表
              </button>
            </div>
          </div>

          <div class="catalog-filters">
            <NSelect
              v-model:value="businessFilter"
              size="small"
              :options="businessOptions"
              class="filter-select"
            />
            <NSelect
              v-model:value="sourceFilter"
              size="small"
              :options="SOURCE_OPTIONS"
              class="filter-select"
            />
            <NSelect
              v-model:value="qualityFilter"
              size="small"
              :options="QUALITY_OPTIONS"
              class="filter-select"
            />
            <span class="result-count">{{ filteredItems.length }} 项知识</span>
            <button
              v-if="q || sourceFilter || qualityFilter || businessFilter"
              type="button"
              class="clear-filter"
              @click="clearFilters"
            >
              清除筛选
            </button>
          </div>

          <EmptyState
            v-if="!filteredItems.length"
            text="当前分类下暂无匹配知识"
          />

          <div v-else-if="layout === 'grid'" class="catalog-grid">
            <button
              v-for="item in filteredItems"
              :key="item.id"
              type="button"
              class="knowledge-card"
              @click="openPreview(item)"
            >
              <div class="knowledge-card-top">
                <span
                  class="type-glyph small"
                  :style="{
                    color: typeDef(item.knowledge_type).color,
                    background: typeDef(item.knowledge_type).soft,
                  }"
                >
                  {{ typeDef(item.knowledge_type).glyph }}
                </span>
                <span class="source-pill">{{ item.source_status_label }}</span>
                <span
                  v-if="item.quality_status === 'needs_attention'"
                  class="quality-pill"
                >
                  待完善
                </span>
              </div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.summary }}</p>
              <div class="tag-row">
                <span v-for="tag in item.business_tags.slice(0, 3)" :key="tag">
                  {{ tag }}
                </span>
                <span v-if="!item.business_tags.length">未设置业务标签</span>
              </div>
              <div class="knowledge-card-meta">
                <span>{{ item.knowledge_type_label }}</span>
                <span>{{ formatTime(item.mtime) }}</span>
              </div>
            </button>
          </div>

          <div v-else class="catalog-list ra-surface">
            <button
              v-for="item in filteredItems"
              :key="item.id"
              type="button"
              class="knowledge-row"
              @click="openPreview(item)"
            >
              <span
                class="mini-glyph"
                :style="{
                  color: typeDef(item.knowledge_type).color,
                  background: typeDef(item.knowledge_type).soft,
                }"
              >
                {{ typeDef(item.knowledge_type).glyph }}
              </span>
              <span class="row-main">
                <strong>{{ item.title }}</strong>
                <small>{{ item.summary }}</small>
              </span>
              <span class="row-tags">
                <small>{{ item.knowledge_type_label }}</small>
                <small>{{ item.source_status_label }}</small>
              </span>
              <span class="row-time">{{ formatTime(item.mtime) }}</span>
              <span class="recent-arrow">›</span>
            </button>
          </div>
        </section>
      </main>

      <main v-else class="governance-view">
        <section class="governance-header">
          <div>
            <span class="eyebrow">知识治理</span>
            <h2>让知识始终可检索、可理解、可引用</h2>
            <p>导入、加工、去重、索引和指标口径维护集中在这里。</p>
          </div>
          <div class="governance-actions">
            <NButton secondary :loading="importing" @click="batchInput?.click()">
              批量导入
            </NButton>
            <NButton secondary :loading="importing" @click="onFromRaw">
              处理原始资料
            </NButton>
            <NButton secondary @click="onRebuildWiki">重新加工知识</NButton>
            <NButton type="primary" secondary @click="onRebuildIndex">
              重建检索索引
            </NButton>
          </div>
        </section>

        <section class="health-cards">
          <div class="health-card ready">
            <span>可用知识</span>
            <strong>{{ readyCount }}</strong>
            <small>可进入问答、问数和报告写作</small>
          </div>
          <div class="health-card warning">
            <span>待完善</span>
            <strong>{{ attentionCount }}</strong>
            <small>内容过短或信息不完整</small>
          </div>
          <div class="health-card">
            <span>内容重复</span>
            <strong>{{ healthLine("content_dupes") }}</strong>
            <small>建议检查重复源资料</small>
          </div>
          <div class="health-card">
            <span>重名冲突</span>
            <strong>{{ healthLine("conflict_name_dupes") }}</strong>
            <small>同名知识可能来自不同来源</small>
          </div>
          <div class="health-card">
            <span>知识卡片</span>
            <strong>{{ healthLine("wiki_doc_cards") }}</strong>
            <small>由源资料加工形成</small>
          </div>
          <div class="health-card">
            <span>实体质量问题</span>
            <strong>{{ healthLine("entity_low_quality") }}</strong>
            <small>低质量或不完整实体</small>
          </div>
        </section>

        <section class="governance-columns">
          <div class="ra-surface governance-panel">
            <div class="section-heading compact">
              <div>
                <h2>系统就绪状态</h2>
                <p>用于判断当前知识是否满足智能能力调用</p>
              </div>
            </div>
            <div class="readiness-grid">
              <div>
                <span>问答就绪</span>
                <strong
                  :class="{ positive: healthLine('qa_ready') === '是' }"
                >
                  {{ healthLine("qa_ready") }}
                </strong>
              </div>
              <div>
                <span>写作就绪</span>
                <strong
                  :class="{ positive: healthLine('writing_ready') === '是' }"
                >
                  {{ healthLine("writing_ready") }}
                </strong>
              </div>
              <div>
                <span>原始资料</span>
                <strong>{{ healthLine("raw_source_files") }}</strong>
              </div>
              <div>
                <span>可扫描内容</span>
                <strong>{{ healthLine("parse_ok_estimate") }}</strong>
              </div>
              <div>
                <span>评测通过率</span>
                <strong>{{ healthLine("eval_pass_rate") }}</strong>
              </div>
              <div>
                <span>最近检查</span>
                <strong class="small-value">
                  {{ healthLine("checked_at") }}
                </strong>
              </div>
            </div>
            <div class="vault-path" :title="vaultPath">{{ vaultPath }}</div>
          </div>

          <div class="ra-surface governance-panel process-panel">
            <div class="section-heading compact">
              <div>
                <h2>知识加工流程</h2>
                <p>从源文件到可被智能系统直接使用的知识资产</p>
              </div>
            </div>
            <div class="process-flow">
              <div><b>1</b><span>识别数据类型</span></div>
              <i>→</i>
              <div><b>2</b><span>提取内容与实体</span></div>
              <i>→</i>
              <div><b>3</b><span>生成知识卡片</span></div>
              <i>→</i>
              <div><b>4</b><span>建立检索与关系</span></div>
            </div>
            <p class="process-note">
              物理文件继续保存在 Vault 中，目录层只提供逻辑分类，不影响
              Obsidian、工作台检索和战略写作。
            </p>
          </div>
        </section>

        <section class="ra-surface metrics-panel">
          <div class="section-heading compact">
            <div>
              <h2>指标与规则</h2>
              <p>维护指标名称、别名、公式、单位和权威数据来源</p>
            </div>
            <NSpace>
              <NButton
                size="small"
                secondary
                :loading="seedingMetrics"
                @click="onSeedMetrics"
              >
                补充种子口径
              </NButton>
              <NButton size="small" type="primary" @click="openNewMetric">
                新建指标
              </NButton>
            </NSpace>
          </div>
          <NDataTable
            v-if="metrics.length"
            :columns="metricColumns"
            :data="metrics"
            :bordered="false"
            size="small"
          />
          <EmptyState v-else text="暂无指标口径" />
        </section>
      </main>
    </NSpin>

    <NDrawer v-model:show="previewOpen" :width="860">
      <NDrawerContent :title="selectedItem?.title || '知识详情'" closable>
        <NSpin :show="previewLoading">
          <template v-if="selectedItem">
            <div class="detail-type-row">
              <span
                class="type-glyph"
                :style="{
                  color: typeDef(selectedItem.knowledge_type).color,
                  background: typeDef(selectedItem.knowledge_type).soft,
                }"
              >
                {{ typeDef(selectedItem.knowledge_type).glyph }}
              </span>
              <div>
                <strong>{{ selectedItem.knowledge_type_label }}</strong>
                <span>
                  {{ selectedItem.source_status_label }} ·
                  {{ selectedItem.quality_status_label }}
                </span>
              </div>
            </div>

            <p class="detail-summary">{{ selectedItem.summary }}</p>

            <div class="detail-tags">
              <span v-for="tag in selectedItem.business_tags" :key="tag">
                {{ tag }}
              </span>
              <span v-if="!selectedItem.business_tags.length">未设置业务标签</span>
            </div>

            <div class="detail-actions">
              <NButton
                type="primary"
                @click="useInWorkbench(selectedItem)"
              >
                在工作台使用
              </NButton>
              <NButton secondary @click="useInWriting(selectedItem)">
                用于战略写作
              </NButton>
              <NButton
                secondary
                @click="
                  previewOpen = false;
                  router.push({ name: 'knowledge-graph' });
                "
              >
                查看关系
              </NButton>
            </div>

            <dl class="detail-meta">
              <div>
                <dt>数据类型</dt>
                <dd>{{ selectedItem.knowledge_type_label }}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>{{ formatTime(selectedItem.mtime) }}</dd>
              </div>
              <div>
                <dt>文件大小</dt>
                <dd>{{ formatBytes(selectedItem.size) }}</dd>
              </div>
              <div>
                <dt>可用格式</dt>
                <dd>
                  {{ selectedItem.formats.map((item) => item || "其他").join("、") }}
                </dd>
              </div>
            </dl>

            <div class="detail-section">
              <div class="detail-section-title">
                <div>
                  <h3>原文预览</h3>
                  <span v-if="previewFile">
                    {{ previewFile.role_label || "知识文件" }} ·
                    {{ previewFile.name }}
                  </span>
                </div>
                <span v-if="preview?.truncated" class="preview-notice">
                  内容较长，当前显示预览范围
                </span>
              </div>
              <pre
                v-if="
                  preview?.preview_mode === 'text' ||
                  preview?.preview_mode === 'document'
                "
                class="detail-preview"
              >{{ preview.content }}</pre>
              <iframe
                v-else-if="preview?.preview_mode === 'pdf'"
                :src="vaultFileDownloadHref(previewPath)"
                :title="previewFile?.name || selectedItem.title"
                class="detail-pdf"
              />
              <div
                v-else-if="preview?.preview_mode === 'spreadsheet'"
                class="spreadsheet-preview"
              >
                <div
                  v-if="(preview.sheets?.length || 0) > 1"
                  class="sheet-tabs"
                >
                  <button
                    v-for="(sheet, index) in preview.sheets"
                    :key="sheet.name"
                    type="button"
                    :class="{ active: previewSheetIndex === index }"
                    @click="previewSheetIndex = index"
                  >
                    {{ sheet.name }}
                  </button>
                </div>
                <div v-if="activeSheet" class="sheet-meta">
                  {{ activeSheet.name }} · 共 {{ activeSheet.total_rows }} 行
                  <span v-if="activeSheet.truncated">
                    · 显示前 {{ activeSheet.rows.length }} 行
                  </span>
                </div>
                <div class="sheet-table-wrap">
                  <table v-if="activeSheet" class="sheet-table">
                    <thead>
                      <tr>
                        <th class="row-number">#</th>
                        <th
                          v-for="column in activeSheet.columns"
                          :key="column"
                        >
                          {{ column }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(row, rowIndex) in activeSheet.rows"
                        :key="rowIndex"
                      >
                        <td class="row-number">{{ rowIndex + 1 }}</td>
                        <td
                          v-for="(cell, cellIndex) in row"
                          :key="cellIndex"
                        >
                          {{ cell ?? "" }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <img
                v-else-if="preview?.preview_mode === 'image'"
                :src="vaultFileDownloadHref(previewPath)"
                :alt="selectedItem.title"
                class="detail-image"
              />
              <EmptyState
                v-else
                :text="
                  preview?.message ||
                  '此格式暂不支持在线预览，请下载后查看'
                "
              />
            </div>

            <div class="detail-section">
              <h3>源文件</h3>
              <div class="source-files">
                <div
                  v-for="file in selectedItem.files"
                  :key="file.path"
                  class="source-file"
                  :class="{ active: previewPath === file.path }"
                >
                  <div>
                    <strong>
                      <span class="file-role">
                        {{ file.role_label || "知识文件" }}
                      </span>
                      {{ file.name }}
                    </strong>
                    <span>{{ file.path }} · {{ formatBytes(file.size) }}</span>
                  </div>
                  <NSpace :size="5">
                    <NButton
                      size="tiny"
                      :type="previewPath === file.path ? 'primary' : 'default'"
                      secondary
                      @click="openFilePreview(file.path)"
                    >
                      预览
                    </NButton>
                    <NButton
                      size="tiny"
                      secondary
                      @click="downloadVaultFile(file.path, file.name)"
                    >
                      下载
                    </NButton>
                  </NSpace>
                </div>
              </div>
            </div>
          </template>
        </NSpin>
      </NDrawerContent>
    </NDrawer>

    <NModal
      v-model:show="metricOpen"
      preset="card"
      title="指标与规则"
      style="width: 460px"
    >
      <NSpace vertical>
        <NInput v-model:value="metricForm.name" placeholder="指标名称" />
        <NInput
          v-model:value="metricForm.aliases"
          placeholder="别名，使用逗号分隔"
        />
        <NInput
          v-model:value="metricForm.formula"
          type="textarea"
          placeholder="公式或权威数据来源"
        />
        <NInput v-model:value="metricForm.unit" placeholder="单位" />
        <NButton type="primary" block @click="saveMetric">保存</NButton>
      </NSpace>
    </NModal>
  </div>
</template>

<style scoped>
.knowledge-page {
  gap: 0;
  overflow: hidden;
}

.knowledge-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex: 0 0 auto;
  padding: 2px 2px 14px;
}

.knowledge-header h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: -0.04em;
}

.knowledge-header p,
.section-heading p,
.catalog-title p,
.governance-header p {
  margin: 4px 0 0;
  color: var(--ra-muted);
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-search {
  width: min(360px, 32vw);
}

.section-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 4px;
  margin-bottom: 14px;
  width: fit-content;
  border: 1px solid var(--ra-border);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.75);
}

.section-tabs button {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ra-muted);
  cursor: pointer;
}

.section-tabs button.active {
  color: var(--ra-accent);
  background: #fff;
  box-shadow: 0 4px 14px rgba(57, 126, 236, 0.1);
  font-weight: 600;
}

.tab-badge {
  min-width: 18px;
  padding: 1px 5px;
  border-radius: 999px;
  color: #b45309;
  background: #fff2d8;
  font-size: 10px;
}

.knowledge-spin {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.knowledge-spin :deep(.n-spin-container),
.knowledge-spin :deep(.n-spin-content) {
  height: 100%;
  min-height: 0;
}

.home-view,
.governance-view {
  height: 100%;
  overflow: auto;
  padding: 0 2px 20px;
}

.knowledge-hero {
  position: relative;
  overflow: hidden;
  padding: 28px 32px 22px;
  border: 1px solid rgba(57, 126, 236, 0.16);
  border-radius: 20px;
  background:
    radial-gradient(
      circle at 90% 15%,
      rgba(50, 207, 252, 0.18),
      transparent 30%
    ),
    linear-gradient(130deg, #f8fbff 0%, #edf4ff 55%, #f3f8ff 100%);
  transition: 0.2s ease;
}

.knowledge-hero::after {
  content: "K";
  position: absolute;
  right: 48px;
  top: -38px;
  color: rgba(57, 126, 236, 0.05);
  font-size: 210px;
  font-weight: 700;
  pointer-events: none;
}

.knowledge-hero.over {
  border-color: var(--ra-accent);
  box-shadow: inset 0 0 0 2px rgba(57, 126, 236, 0.12);
}

.hero-copy {
  position: relative;
  z-index: 1;
  max-width: 720px;
}

.eyebrow {
  color: var(--ra-accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.hero-copy h2,
.governance-header h2 {
  margin: 7px 0 8px;
  font-size: 28px;
  letter-spacing: -0.04em;
}

.hero-copy p {
  margin: 0;
  color: #526177;
  font-size: 13px;
  line-height: 1.7;
}

.hero-search {
  position: relative;
  z-index: 1;
  display: flex;
  gap: 10px;
  max-width: 720px;
  margin-top: 22px;
}

.hero-search :deep(.n-input) {
  box-shadow: 0 8px 24px rgba(57, 126, 236, 0.09);
}

.hero-drop-hint {
  position: relative;
  z-index: 1;
  margin-top: 13px;
  color: #7b8798;
  font-size: 11px;
}

.home-section {
  margin-top: 22px;
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.section-heading.compact {
  align-items: center;
}

.section-heading h2,
.catalog-title h2 {
  margin: 0;
  font-size: 17px;
  letter-spacing: -0.02em;
}

.text-link,
.clear-filter {
  border: 0;
  background: transparent;
  color: var(--ra-accent);
  font-size: 12px;
  cursor: pointer;
}

.type-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.type-card {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  align-items: center;
  gap: 11px;
  min-height: 84px;
  padding: 14px;
  border: 1px solid var(--ra-border);
  border-radius: 15px;
  background: #fff;
  color: var(--ra-text);
  text-align: left;
  cursor: pointer;
  transition: 0.18s ease;
}

.type-card:hover {
  border-color: rgba(57, 126, 236, 0.35);
  box-shadow: 0 12px 30px rgba(57, 126, 236, 0.1);
  transform: translateY(-2px);
}

.type-glyph,
.mini-glyph,
.nav-glyph {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border-radius: 13px;
  font-weight: 700;
}

.type-glyph.small {
  width: 36px;
  height: 36px;
  border-radius: 11px;
}

.type-card-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.type-card-copy strong {
  font-size: 14px;
}

.type-card-copy small {
  margin-top: 4px;
  overflow: hidden;
  color: var(--ra-muted);
  font-size: 11px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.type-count {
  color: #94a3b8;
  font-size: 20px;
  font-weight: 600;
}

.home-columns,
.governance-columns {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 12px;
  margin-top: 20px;
}

.recent-panel,
.overview-panel,
.governance-panel,
.metrics-panel {
  padding: 18px;
}

.recent-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: #f8faff;
  color: var(--ra-text);
  text-align: left;
  cursor: pointer;
}

.recent-item:hover {
  border-color: var(--ra-border);
  background: #fff;
}

.mini-glyph {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  font-size: 12px;
}

.recent-copy {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.recent-copy strong {
  overflow: hidden;
  font-size: 12px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.recent-copy small {
  margin-top: 3px;
  color: var(--ra-muted);
  font-size: 10px;
}

.recent-arrow {
  color: #94a3b8;
  font-size: 20px;
}

.overview-numbers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.overview-numbers button {
  display: flex;
  flex-direction: column;
  padding: 14px;
  border: 1px solid #eef2f8;
  border-radius: 12px;
  background: #fafcff;
  text-align: left;
  cursor: pointer;
}

.overview-numbers strong {
  color: var(--ra-text);
  font-size: 24px;
}

.overview-numbers span {
  color: var(--ra-muted);
  font-size: 11px;
}

.governance-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  padding: 12px;
  border-radius: 12px;
  background: #fff8eb;
}

.governance-notice div {
  display: flex;
  flex-direction: column;
}

.governance-notice strong {
  font-size: 12px;
}

.governance-notice span {
  margin-top: 2px;
  color: #9a650c;
  font-size: 10px;
}

.browse-view {
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr);
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.catalog-sidebar {
  overflow: auto;
  padding: 14px 10px;
}

.sidebar-title {
  padding: 3px 10px 9px;
  color: #94a3b8;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.catalog-nav-item {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  width: 100%;
  margin-bottom: 3px;
  padding: 8px 9px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #475569;
  text-align: left;
  cursor: pointer;
}

.catalog-nav-item:hover,
.catalog-nav-item.active {
  color: var(--ra-accent);
  background: var(--ra-accent-soft);
}

.catalog-nav-item.active {
  font-weight: 600;
}

.catalog-nav-item small {
  color: #94a3b8;
}

.nav-glyph {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-size: 10px;
}

.nav-glyph.all {
  color: #fff;
  background: var(--ra-accent);
}

.catalog-nav-item.text-only {
  grid-template-columns: 1fr auto;
  padding-left: 12px;
}

.sidebar-divider {
  height: 1px;
  margin: 12px 8px;
  background: #edf1f7;
}

.catalog-main {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.catalog-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 17px;
}

.catalog-layout-toggle {
  display: flex;
  padding: 3px;
  border-radius: 9px;
  background: #f1f5f9;
}

.catalog-layout-toggle button {
  padding: 5px 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--ra-muted);
  font-size: 11px;
  cursor: pointer;
}

.catalog-layout-toggle button.active {
  color: var(--ra-accent);
  background: #fff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.catalog-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 2px;
}

.filter-select {
  width: 160px;
}

.result-count {
  margin-left: auto;
  color: var(--ra-muted);
  font-size: 11px;
}

.catalog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding-bottom: 18px;
}

.knowledge-card {
  display: flex;
  flex-direction: column;
  min-height: 230px;
  padding: 16px;
  border: 1px solid var(--ra-border);
  border-radius: 15px;
  background: #fff;
  color: var(--ra-text);
  text-align: left;
  cursor: pointer;
  transition: 0.18s ease;
}

.knowledge-card:hover {
  border-color: rgba(57, 126, 236, 0.35);
  box-shadow: 0 12px 28px rgba(57, 126, 236, 0.09);
  transform: translateY(-2px);
}

.knowledge-card-top {
  display: flex;
  align-items: center;
  gap: 7px;
}

.source-pill,
.quality-pill {
  padding: 3px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 9px;
}

.quality-pill {
  color: #a16207;
  background: #fff5d9;
}

.knowledge-card h3 {
  display: -webkit-box;
  overflow: hidden;
  margin: 13px 0 7px;
  font-size: 14px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.knowledge-card > p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: #64748b;
  font-size: 11px;
  line-height: 1.65;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: auto;
  padding-top: 12px;
}

.tag-row span,
.detail-tags span {
  padding: 3px 7px;
  border-radius: 999px;
  color: #52719c;
  background: #f1f6fd;
  font-size: 9px;
}

.knowledge-card-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 11px;
  padding-top: 9px;
  border-top: 1px solid #f0f3f8;
  color: #94a3b8;
  font-size: 9px;
}

.catalog-list {
  padding: 6px 12px;
}

.knowledge-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) 180px 120px 18px;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 11px 5px;
  border: 0;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  color: var(--ra-text);
  text-align: left;
  cursor: pointer;
}

.knowledge-row:last-child {
  border-bottom: 0;
}

.knowledge-row:hover {
  background: #f8fbff;
}

.row-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.row-main strong,
.row-main small {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.row-main strong {
  font-size: 12px;
}

.row-main small,
.row-time,
.row-tags small {
  color: var(--ra-muted);
  font-size: 10px;
}

.row-tags {
  display: flex;
  gap: 7px;
}

.governance-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 22px;
  border: 1px solid var(--ra-border);
  border-radius: 18px;
  background:
    radial-gradient(
      circle at 90% 10%,
      rgba(168, 108, 255, 0.09),
      transparent 35%
    ),
    #fff;
}

.governance-header h2 {
  font-size: 23px;
}

.governance-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 7px;
}

.import-progress-panel {
  flex: 0 0 auto;
  margin: 0 2px 12px;
  padding: 13px 16px;
  border-color: rgba(57, 126, 236, 0.22);
  background: linear-gradient(135deg, #fff 0%, #f4f8ff 100%);
}

.import-progress-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 9px;
}

.import-progress-head > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.import-progress-head strong {
  font-size: 12px;
}

.import-progress-head span {
  color: var(--ra-muted);
  font-size: 10px;
}

.import-close {
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 18px;
  cursor: pointer;
}

.import-items {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  max-height: 116px;
  margin-top: 10px;
  overflow: auto;
}

.import-item {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  padding: 7px 9px;
  border: 1px solid #e8eef7;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.78);
}

.import-item-state {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  color: #64748b;
  background: #edf2f7;
  font-size: 10px;
}

.import-item.running .import-item-state {
  color: #2563eb;
  background: #e7f0ff;
}

.import-item.completed .import-item-state {
  color: #047857;
  background: #dcfce7;
}

.import-item.failed .import-item-state {
  color: #b91c1c;
  background: #fee2e2;
}

.import-item-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.import-item-copy strong,
.import-item-copy small {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.import-item-copy strong {
  font-size: 10px;
}

.import-item-copy small,
.import-item-progress {
  color: var(--ra-muted);
  font-size: 9px;
}

.health-cards {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 9px;
  margin-top: 12px;
}

.health-card {
  display: flex;
  flex-direction: column;
  padding: 14px;
  border: 1px solid var(--ra-border);
  border-radius: 13px;
  background: #fff;
}

.health-card > span {
  color: var(--ra-muted);
  font-size: 10px;
}

.health-card strong {
  margin: 4px 0 2px;
  font-size: 22px;
}

.health-card small {
  color: #94a3b8;
  font-size: 9px;
  line-height: 1.4;
}

.health-card.ready strong {
  color: #0f766e;
}

.health-card.warning strong {
  color: #b45309;
}

.readiness-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.readiness-grid div {
  display: flex;
  flex-direction: column;
  padding: 12px;
  border-radius: 11px;
  background: #f8faff;
}

.readiness-grid span {
  color: var(--ra-muted);
  font-size: 10px;
}

.readiness-grid strong {
  margin-top: 3px;
  font-size: 14px;
}

.readiness-grid strong.positive {
  color: #0f766e;
}

.readiness-grid .small-value {
  font-size: 10px;
}

.vault-path {
  overflow: hidden;
  margin-top: 10px;
  color: #94a3b8;
  font-size: 9px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.process-panel {
  display: flex;
  flex-direction: column;
}

.process-flow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: 8px;
}

.process-flow div {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  text-align: center;
}

.process-flow b {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  color: var(--ra-accent);
  background: var(--ra-accent-soft);
  font-size: 11px;
}

.process-flow span {
  color: #526177;
  font-size: 10px;
}

.process-flow i {
  color: #cbd5e1;
  font-style: normal;
}

.process-note {
  margin: auto 0 0;
  padding-top: 14px;
  color: #94a3b8;
  font-size: 9px;
  line-height: 1.6;
}

.metrics-panel {
  margin-top: 12px;
}

.detail-type-row {
  display: flex;
  align-items: center;
  gap: 11px;
}

.detail-type-row div {
  display: flex;
  flex-direction: column;
}

.detail-type-row strong {
  font-size: 14px;
}

.detail-type-row span {
  margin-top: 3px;
  color: var(--ra-muted);
  font-size: 10px;
}

.detail-summary {
  margin: 16px 0;
  padding: 13px 15px;
  border-left: 3px solid var(--ra-accent);
  background: #f5f8fe;
  color: #4b5d75;
  font-size: 12px;
  line-height: 1.75;
}

.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.detail-actions {
  display: flex;
  gap: 7px;
  margin: 16px 0;
}

.detail-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 0;
}

.detail-meta div {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
}

.detail-meta dt {
  color: #94a3b8;
  font-size: 9px;
}

.detail-meta dd {
  margin: 3px 0 0;
  font-size: 11px;
}

.detail-section {
  margin-top: 20px;
}

.detail-section h3 {
  margin: 0 0 9px;
  font-size: 13px;
}

.detail-section-title {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 9px;
}

.detail-section-title h3 {
  margin: 0;
}

.detail-section-title > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.detail-section-title span,
.preview-notice {
  color: #94a3b8;
  font-size: 9px;
}

.detail-preview {
  max-height: 420px;
  overflow: auto;
  padding: 16px;
  border: 1px solid #e7edf6;
  border-radius: 12px;
  background: #fbfcfe;
  font: 12px/1.75 var(--ra-font);
  white-space: pre-wrap;
  word-break: break-word;
}

.detail-image {
  display: block;
  max-width: 100%;
  max-height: 440px;
  margin: 0 auto;
  border-radius: 12px;
}

.detail-pdf {
  display: block;
  width: 100%;
  height: min(70vh, 760px);
  border: 1px solid #e7edf6;
  border-radius: 12px;
  background: #f8fafc;
}

.spreadsheet-preview {
  overflow: hidden;
  border: 1px solid #e7edf6;
  border-radius: 12px;
  background: #fff;
}

.sheet-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 9px 0;
  overflow-x: auto;
  background: #f8fafc;
}

.sheet-tabs button {
  flex: 0 0 auto;
  padding: 6px 10px;
  border: 0;
  border-radius: 7px 7px 0 0;
  background: transparent;
  color: #64748b;
  font-size: 10px;
  cursor: pointer;
}

.sheet-tabs button.active {
  color: var(--ra-accent);
  background: #fff;
  font-weight: 600;
}

.sheet-meta {
  padding: 8px 11px;
  border-bottom: 1px solid #edf1f7;
  color: #64748b;
  font-size: 9px;
}

.sheet-table-wrap {
  max-height: 520px;
  overflow: auto;
}

.sheet-table {
  width: max-content;
  min-width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 10px;
}

.sheet-table th,
.sheet-table td {
  min-width: 110px;
  max-width: 260px;
  padding: 7px 9px;
  overflow: hidden;
  border-right: 1px solid #edf1f7;
  border-bottom: 1px solid #edf1f7;
  background: #fff;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.sheet-table th {
  position: sticky;
  z-index: 2;
  top: 0;
  color: #475569;
  background: #f8fafc;
  font-weight: 600;
}

.sheet-table .row-number {
  position: sticky;
  z-index: 1;
  left: 0;
  min-width: 44px;
  width: 44px;
  color: #94a3b8;
  background: #f8fafc;
  text-align: right;
}

.sheet-table th.row-number {
  z-index: 3;
}

.source-files {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.source-file {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #edf1f7;
  border-radius: 10px;
}

.source-file.active {
  border-color: rgba(57, 126, 236, 0.36);
  background: #f6f9ff;
}

.source-file div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.source-file strong,
.source-file span {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.source-file strong {
  font-size: 11px;
}

.source-file .file-role {
  display: inline-block;
  margin: 0 6px 0 0;
  padding: 2px 5px;
  border-radius: 5px;
  color: #356fcb;
  background: #eaf2ff;
  font-size: 8px;
  vertical-align: 1px;
}

.source-file span {
  margin-top: 2px;
  color: #94a3b8;
  font-size: 9px;
}

.source-file strong .file-role {
  display: inline-block;
  margin: 0 6px 0 0;
  color: #356fcb;
  font-size: 8px;
}

@media (max-width: 1300px) {
  .type-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .catalog-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .health-cards {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .knowledge-header,
  .governance-header {
    align-items: stretch;
    flex-direction: column;
  }

  .header-search {
    flex: 1;
    width: auto;
  }

  .type-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .browse-view {
    grid-template-columns: 190px minmax(0, 1fr);
  }

  .home-columns,
  .governance-columns {
    grid-template-columns: 1fr;
  }
}
</style>
