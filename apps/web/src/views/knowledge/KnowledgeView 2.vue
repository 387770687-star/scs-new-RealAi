<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import {
  NButton,
  NInput,
  NSpace,
  NSelect,
  NDataTable,
  NSpin,
  NDrawer,
  NDrawerContent,
  NProgress,
  NModal,
  useMessage,
  type DataTableColumns,
} from "naive-ui";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import { useRouter } from "vue-router";
import {
  createMetric,
  deleteMetric,
  downloadVaultFile,
  fetchImportJob,
  fetchVaultFilePreview,
  fetchVaultFiles,
  fetchVaultHealth,
  fetchVaultStatus,
  importVaultBatch,
  importVaultFile,
  importVaultFromRaw,
  listMetrics,
  rebuildVaultIndex,
  rebuildWiki,
  seedMetrics,
  updateMetric,
} from "@/api/realai";
import { ApiError, type Metric, type VaultFileInfo, type VaultFilePreview } from "@/api/types";
import { formatBytes, formatTime } from "@/utils/format";

const message = useMessage();
const router = useRouter();
const loading = ref(false);
const categoryOverride = ref("");
const categoryOptions = [
  { label: "智能分类", value: "" },
  { label: "pipelines", value: "pipelines" },
  { label: "new_energy", value: "new_energy" },
  { label: "dataqa", value: "dataqa" },
];
const errorKind = ref<"empty" | "not_ready" | "network" | "error" | null>(null);
const errorMsg = ref("");
const files = ref<VaultFileInfo[]>([]);
const total = ref(0);
const q = ref("");
const vaultPath = ref("");
const preview = ref<VaultFilePreview | null>(null);
const previewOpen = ref(false);
const importing = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const batchInput = ref<HTMLInputElement | null>(null);
const dragOver = ref(false);
const extFilter = ref("all");
const health = ref<Record<string, unknown> | null>(null);
const metrics = ref<Metric[]>([]);
const batchPct = ref(0);
const batchStatus = ref("");
const metricOpen = ref(false);
const seedingMetrics = ref(false);
const metricForm = ref({ id: "", name: "", aliases: "", formula: "", unit: "" });

const extOptions = computed(() => {
  const set = new Set(files.value.map((f) => (f.extension || "").toLowerCase() || "其他"));
  return ["all", ...Array.from(set).sort()];
});

const displayFiles = computed(() => {
  if (extFilter.value === "all") return files.value;
  return files.value.filter(
    (f) =>
      (f.extension || "").toLowerCase() === extFilter.value ||
      (!f.extension && extFilter.value === "其他"),
  );
});

async function openPreview(row: VaultFileInfo) {
  try {
    preview.value = await fetchVaultFilePreview(row.path);
    previewOpen.value = true;
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

const columns: DataTableColumns<VaultFileInfo> = [
  { title: "名称", key: "name", ellipsis: { tooltip: true } },
  { title: "路径", key: "path", ellipsis: { tooltip: true } },
  {
    title: "大小",
    key: "size",
    width: 100,
    render: (row) => formatBytes(row.size),
  },
  {
    title: "更新",
    key: "mtime",
    width: 160,
    render: (row) => formatTime(row.mtime),
  },
  {
    title: "",
    key: "actions",
    width: 140,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(
            NButton,
            { size: "tiny", secondary: true, onClick: () => void openPreview(row) },
            { default: () => "预览" },
          ),
          h(
            NButton,
            {
              size: "tiny",
              quaternary: true,
              onClick: () => void downloadVaultFile(row.path, row.name),
            },
            { default: () => "下载" },
          ),
        ],
      }),
  },
];

const metricColumns: DataTableColumns<Metric> = [
  { title: "名称", key: "name", width: 120 },
  {
    title: "别名",
    key: "aliases",
    render: (r) => (r.aliases || []).join(", "),
  },
  { title: "公式", key: "formula", ellipsis: { tooltip: true } },
  { title: "单位", key: "unit", width: 80 },
  {
    title: "",
    key: "a",
    width: 120,
    render: (r) =>
      h(NSpace, { size: 4 }, {
        default: () => [
          h(
            NButton,
            {
              size: "tiny",
              quaternary: true,
              onClick: () => {
                metricForm.value = {
                  id: r.id,
                  name: r.name,
                  aliases: (r.aliases || []).join(","),
                  formula: r.formula || "",
                  unit: r.unit || "",
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
                await deleteMetric(r.id);
                await loadMetrics();
              },
            },
            { default: () => "删" },
          ),
        ],
      }),
  },
];

async function loadMetrics() {
  try {
    const res = await listMetrics();
    metrics.value = res.metrics;
  } catch {
    metrics.value = [];
  }
}

async function onSeedMetrics() {
  seedingMetrics.value = true;
  try {
    const res = await seedMetrics();
    message.success(`口径种子完成，新增 ${res.created} 条`);
    await loadMetrics();
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : "种子口径失败");
  } finally {
    seedingMetrics.value = false;
  }
}

async function loadHealth() {
  try {
    health.value = await fetchVaultHealth();
  } catch {
    health.value = null;
  }
}

async function load() {
  loading.value = true;
  errorKind.value = null;
  errorMsg.value = "";
  try {
    const [list, status] = await Promise.all([
      fetchVaultFiles(100, 0, q.value),
      fetchVaultStatus(),
      loadMetrics(),
      loadHealth(),
    ]);
    files.value = list.files;
    total.value = list.total;
    vaultPath.value = status.vault_path;
    if (!list.files.length) errorKind.value = "empty";
  } catch (err) {
    files.value = [];
    if (err instanceof ApiError) {
      errorKind.value =
        err.kind === "network" ? "network" : err.kind === "not_ready" ? "not_ready" : "error";
      errorMsg.value = err.message;
    } else {
      errorKind.value = "error";
      errorMsg.value = String(err);
    }
  } finally {
    loading.value = false;
  }
}

async function importOne(file: File) {
  importing.value = true;
  try {
    const res = await importVaultFile(file, categoryOverride.value ? categoryOverride.value : undefined);
    if (res.success) {
      const cat = res.category ? ` → ${res.category}` : "";
      message.success((res.message || "已导入") + cat);
      await load();
    } else {
      message.error(res.message || "导入失败");
    }
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    importing.value = false;
  }
}

async function onFromRaw() {
  importing.value = true;
  try {
    const res = await importVaultFromRaw();
    message.success(res.message || `完成 ${res.ok}/${res.total}`);
    await load();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    importing.value = false;
  }
}

async function onRebuildWiki() {
  try {
    const res = await rebuildWiki();
    message.success(`Wiki 重建：实体 ${res.entities_written ?? 0}`);
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

async function onBatch(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const list = Array.from(input.files || []);
  input.value = "";
  if (!list.length) return;
  importing.value = true;
  batchPct.value = 0;
  batchStatus.value = "导入中";
  try {
    const job = await importVaultBatch(list);
    let cur = job;
    while (cur.status === "running" || cur.status === "pending") {
      await new Promise((r) => setTimeout(r, 600));
      cur = await fetchImportJob(cur.id);
      batchPct.value = cur.total ? Math.round((cur.done / cur.total) * 100) : 0;
    }
    batchStatus.value = cur.status;
    batchPct.value = 100;
    message.success(`完成 ${cur.done}/${cur.total}，失败 ${cur.failed}`);
    await load();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    importing.value = false;
  }
}

async function onFilePicked(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  await importOne(file);
  input.value = "";
}

function onDrop(ev: DragEvent) {
  ev.preventDefault();
  dragOver.value = false;
  const file = ev.dataTransfer?.files?.[0];
  if (file) void importOne(file);
}

async function onRebuild() {
  try {
    const res = await rebuildVaultIndex();
    message.success(res.message || "已触发");
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

async function saveMetric() {
  const body = {
    name: metricForm.value.name.trim(),
    aliases: metricForm.value.aliases
      .split(/[,，]/)
      .map((x) => x.trim())
      .filter(Boolean),
    formula: metricForm.value.formula || null,
    unit: metricForm.value.unit || null,
  };
  if (!body.name) return;
  if (metricForm.value.id) await updateMetric(metricForm.value.id, body);
  else await createMetric(body);
  metricOpen.value = false;
  await loadMetrics();
}

function healthLine(key: string) {
  if (!health.value || health.value[key] == null) return "—";
  const v = health.value[key];
  if (key === "checked_at" && typeof v === "number") return formatTime(v);
  if (key === "eval_pass_rate" && typeof v === "number") return `${Math.round(v * 100)}%`;
  if (typeof v === "boolean") return v ? "是" : "否";
  return String(v);
}

onMounted(load);
</script>

<template>
  <div class="ra-page ra-fade-in knowledge-page">
    <div class="page-sticky">
      <PageHeader title="知识库">
        <template #actions>
          <NInput
            v-model:value="q"
            clearable
            placeholder="搜索"
            style="width: 160px"
            @keyup.enter="load"
          />
          <NButton secondary @click="load">刷新</NButton>
          <NSelect
            v-model:value="categoryOverride"
            size="small"
            :options="categoryOptions"
            style="width: 130px"
          />
          <NButton secondary :loading="importing" @click="fileInput?.click()">导入</NButton>
          <NButton secondary :loading="importing" @click="batchInput?.click()">批量</NButton>
          <NButton secondary :loading="importing" @click="onFromRaw">导入 raw</NButton>
          <input ref="fileInput" type="file" hidden @change="onFilePicked" />
          <input ref="batchInput" type="file" multiple hidden @change="onBatch" />
          <NButton secondary @click="router.push({ name: 'knowledge-graph' })">图谱</NButton>
          <NButton secondary @click="onRebuildWiki">重建 Wiki</NButton>
          <NButton type="primary" secondary @click="onRebuild">重建索引</NButton>
        </template>
      </PageHeader>

      <div
        class="dropzone"
        :class="{ over: dragOver }"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop="onDrop"
      >
        拖入导入
      </div>

      <div v-if="batchStatus" class="batch">
        <NProgress type="line" :percentage="batchPct" />
        <span class="muted">{{ batchStatus }}</span>
      </div>

      <div class="gap-row">
        <div class="ra-surface soft">
          <div class="m-head">
            <div class="m-label">指标口径</div>
            <NButton
              size="tiny"
              secondary
              @click="
                metricForm = { id: '', name: '', aliases: '', formula: '', unit: '' };
                metricOpen = true;
              "
            >
              新建
            </NButton>
            <NButton size="tiny" secondary :loading="seedingMetrics" @click="onSeedMetrics">
              种子口径
            </NButton>
          </div>
          <NDataTable
            v-if="metrics.length"
            :columns="metricColumns"
            :data="metrics"
            size="small"
            :bordered="false"
            :max-height="160"
          />
          <EmptyState v-else text="暂无口径" />
        </div>
        <div class="ra-surface soft">
          <div class="m-label">健康度</div>
          <div class="health-grid">
            <div><span>文件</span>{{ healthLine("file_total") }}</div>
            <div><span>可扫样本</span>{{ healthLine("parse_ok_estimate") }}</div>
            <div><span>wiki 要点卡</span>{{ healthLine("wiki_doc_cards") }}</div>
            <div><span>raw 源文件</span>{{ healthLine("raw_source_files") }}</div>
            <div><span>过短文档</span>{{ healthLine("thin_docs") }}</div>
            <div><span>脏实体</span>{{ healthLine("entity_low_quality") }}</div>
            <div><span>内容重复</span>{{ healthLine("content_dupes") }}</div>
            <div><span>重名冲突</span>{{ healthLine("conflict_name_dupes") }}</div>
            <div><span>问答就绪</span>{{ healthLine("qa_ready") }}</div>
            <div><span>写作就绪</span>{{ healthLine("writing_ready") }}</div>
            <div><span>检查时间</span>{{ healthLine("checked_at") }}</div>
            <div><span>评测通过率</span>{{ healthLine("eval_pass_rate") }}</div>
          </div>
          <div class="muted path">{{ vaultPath }} · {{ total }}</div>
        </div>
      </div>

      <div class="filters">
        <button
          v-for="ext in extOptions"
          :key="ext"
          type="button"
          class="ra-chip"
          :class="{ active: extFilter === ext }"
          @click="extFilter = ext"
        >
          {{ ext === "all" ? "全部" : ext }}
        </button>
      </div>
    </div>

    <div class="ra-surface table-wrap">
      <NSpin :show="loading" class="table-spin">
        <EmptyState
          v-if="errorKind === 'network' || errorKind === 'not_ready' || errorKind === 'error'"
          :kind="errorKind"
          :text="errorMsg || undefined"
          action-label="重试"
          @action="load"
        />
        <EmptyState v-else-if="errorKind === 'empty'" text="知识库为空" />
        <NDataTable
          v-else
          :columns="columns"
          :data="displayFiles"
          :bordered="false"
          size="small"
          flex-height
          class="files-table"
        />
      </NSpin>
    </div>

    <NDrawer v-model:show="previewOpen" :width="520">
      <NDrawerContent :title="preview?.name || '预览'" closable>
        <pre v-if="preview?.preview_mode === 'text'" class="preview">{{ preview.content }}</pre>
        <img
          v-else-if="preview?.preview_mode === 'image' && preview.content"
          :src="preview.content"
          alt="preview"
          style="max-width: 100%"
        />
        <EmptyState v-else text="无法预览" />
      </NDrawerContent>
    </NDrawer>

    <NModal v-model:show="metricOpen" preset="card" title="口径" style="width: 420px">
      <NSpace vertical>
        <NInput v-model:value="metricForm.name" placeholder="名称" />
        <NInput v-model:value="metricForm.aliases" placeholder="别名，逗号分隔" />
        <NInput v-model:value="metricForm.formula" placeholder="公式" />
        <NInput v-model:value="metricForm.unit" placeholder="单位" />
        <NButton type="primary" @click="saveMetric">保存</NButton>
      </NSpace>
    </NModal>
  </div>
</template>

<style scoped>
.knowledge-page {
  overflow: hidden;
}
.page-sticky {
  flex-shrink: 0;
  background: transparent;
  padding-bottom: 2px;
}
.dropzone {
  border: 1.5px dashed #cbd5e1;
  border-radius: 14px;
  padding: 14px;
  text-align: center;
  background: rgba(255, 255, 255, 0.65);
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--ra-muted);
}
.dropzone.over {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
  color: var(--ra-accent);
}
.batch {
  margin-bottom: 10px;
}
.gap-row {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 10px;
  margin-bottom: 12px;
}
.ra-surface {
  background: var(--ra-surface);
  border: 1px solid var(--ra-border);
  border-radius: var(--ra-radius);
  box-shadow: var(--ra-shadow);
}
.soft {
  padding: 14px 16px;
}
.m-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.m-label {
  font-weight: 650;
  font-size: 13px;
}
.health-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  font-size: 13px;
  margin-top: 8px;
}
.health-grid span {
  display: block;
  color: var(--ra-muted);
  font-size: 11px;
}
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
.path {
  margin-top: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.table-wrap {
  padding: 12px;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.table-spin {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.table-wrap :deep(.n-spin-container),
.table-wrap :deep(.n-spin-content) {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.files-table {
  flex: 1;
  min-height: 0;
}
.preview {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.55;
  margin: 0;
}
</style>
