<script setup lang="ts">
import { computed, ref } from "vue";
import { NButton, NModal, NSpace, NTooltip, useMessage } from "naive-ui";
import {
  copyText,
  downloadCsv,
  downloadXlsx,
  safeFilename,
  toMarkdownTable,
  toTsv,
  type TableMatrix,
} from "@/utils/tableExport";

const props = withDefaults(
  defineProps<{
    title?: string;
    columns: string[];
    rows: Record<string, unknown>[];
    columnLabels?: Record<string, string> | ((key: string) => string);
    sourceHint?: string;
    /** Compact card in chat; fullscreen lifts max-height */
    maxBodyHeight?: string;
  }>(),
  {
    title: "表格",
    maxBodyHeight: "320px",
  },
);

const message = useMessage();
const wrap = ref(false);
const fullscreen = ref(false);
const busy = ref(false);

const matrix = computed<TableMatrix>(() => ({
  columns: props.columns,
  rows: props.rows,
  labels: props.columnLabels,
}));

const meta = computed(
  () => `${props.rows.length} 行 × ${props.columns.length} 列`,
);

function cellText(row: Record<string, unknown>, key: string) {
  const v = row[key];
  return v == null ? "" : String(v);
}

function labelFor(key: string) {
  const labels = props.columnLabels;
  if (!labels) return key;
  if (typeof labels === "function") return labels(key);
  return labels[key] || key;
}

async function onCopyTsv() {
  try {
    await copyText(toTsv(matrix.value));
    message.success("已复制（可贴到 Excel）");
  } catch {
    message.error("复制失败");
  }
}

async function onCopyMd() {
  try {
    await copyText(toMarkdownTable(matrix.value));
    message.success("已复制 Markdown 表");
  } catch {
    message.error("复制失败");
  }
}

function onDownloadCsv() {
  try {
    downloadCsv(matrix.value, safeFilename(props.title));
    message.success("已下载 CSV");
  } catch {
    message.error("下载失败");
  }
}

async function onDownloadXlsx() {
  busy.value = true;
  try {
    await downloadXlsx(matrix.value, safeFilename(props.title));
    message.success("已下载 Excel");
  } catch {
    message.error("下载失败");
  } finally {
    busy.value = false;
  }
}

function toggleWrap() {
  wrap.value = !wrap.value;
}
</script>

<template>
  <div class="dtc" :class="{ wrap }">
    <div class="dtc-head">
      <div class="dtc-titles">
        <div class="dtc-title" :title="title">{{ title }}</div>
        <div class="dtc-meta">
          <span>{{ meta }}</span>
          <span v-if="sourceHint" class="hint" :title="sourceHint">{{ sourceHint }}</span>
        </div>
      </div>
      <NSpace :size="4" class="dtc-actions" wrap>
        <NTooltip>
          <template #trigger>
            <NButton size="tiny" secondary @click="onCopyTsv">复制</NButton>
          </template>
          复制为制表符文本，可贴到 Excel / WPS
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="tiny" quaternary @click="onCopyMd">MD</NButton>
          </template>
          复制为 Markdown 表格
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="tiny" quaternary @click="onDownloadCsv">CSV</NButton>
          </template>
          下载 CSV（Excel 可直接打开）
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="tiny" quaternary :loading="busy" @click="onDownloadXlsx">Excel</NButton>
          </template>
          下载 .xlsx
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="tiny" quaternary :type="wrap ? 'primary' : 'default'" @click="toggleWrap">
              {{ wrap ? "不换行" : "换行" }}
            </NButton>
          </template>
          {{ wrap ? "切回单行 + 横滑" : "允许单元格内换行" }}
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="tiny" quaternary @click="fullscreen = true">全屏</NButton>
          </template>
          放大查看整表
        </NTooltip>
      </NSpace>
    </div>

    <div
      class="dtc-scroll"
      :style="{ maxHeight: maxBodyHeight }"
    >
      <table class="dtc-table">
        <thead>
          <tr>
            <th v-for="c in columns" :key="c">{{ labelFor(c) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in rows" :key="ri">
            <td v-for="c in columns" :key="c">{{ cellText(row, c) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <NModal
      v-model:show="fullscreen"
      preset="card"
      :title="title"
      :bordered="false"
      style="width: min(1100px, 96vw)"
      :segmented="{ content: true }"
    >
      <template #header-extra>
        <span class="dtc-meta">{{ meta }}</span>
      </template>
      <div class="dtc fs" :class="{ wrap }">
        <NSpace :size="6" style="margin-bottom: 10px">
          <NButton size="small" secondary @click="onCopyTsv">复制</NButton>
          <NButton size="small" quaternary @click="onCopyMd">复制 MD</NButton>
          <NButton size="small" quaternary @click="onDownloadCsv">CSV</NButton>
          <NButton size="small" quaternary :loading="busy" @click="onDownloadXlsx">Excel</NButton>
          <NButton size="small" quaternary :type="wrap ? 'primary' : 'default'" @click="toggleWrap">
            {{ wrap ? "不换行" : "允许换行" }}
          </NButton>
        </NSpace>
        <div class="dtc-scroll fs-scroll">
          <table class="dtc-table">
            <thead>
              <tr>
                <th v-for="c in columns" :key="'fs-' + c">{{ labelFor(c) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in rows" :key="'fs-r-' + ri">
                <td v-for="c in columns" :key="'fs-' + c + ri">{{ cellText(row, c) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.dtc {
  border: 1px solid var(--ra-border, #e2e8f0);
  border-radius: 10px;
  background: #fff;
  padding: 8px 10px 10px;
  margin: 8px 0 12px;
}
.dtc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.dtc-titles {
  min-width: 0;
  flex: 1;
}
.dtc-title {
  font-size: 12px;
  font-weight: 650;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dtc-meta {
  font-size: 11px;
  color: var(--ra-muted, #64748b);
  margin-top: 2px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dtc-meta .hint {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dtc-actions {
  flex-shrink: 0;
}
.dtc-scroll {
  overflow: auto;
  border: 1px solid #eef2f7;
  border-radius: 8px;
  background: #fafbfc;
}
.fs-scroll {
  max-height: min(70vh, 640px);
}
.dtc-table {
  border-collapse: collapse;
  font-size: 12px;
  line-height: 1.4;
  width: max-content;
  min-width: 100%;
}
.dtc-table th,
.dtc-table td {
  padding: 6px 10px;
  text-align: left;
  border-bottom: 1px solid #eef2f7;
  vertical-align: top;
  min-width: 96px;
  max-width: 280px;
}
.dtc-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f1f5f9;
  font-weight: 650;
  color: #334155;
  white-space: nowrap;
}
.dtc:not(.wrap) .dtc-table td {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dtc.wrap .dtc-table td {
  white-space: normal;
  word-break: break-word;
  max-width: 320px;
}
.dtc-table tbody tr:hover td {
  background: #f8fafc;
}
.dtc-table tr:last-child td {
  border-bottom: none;
}
.dtc.fs {
  border: none;
  padding: 0;
  margin: 0;
}
</style>
