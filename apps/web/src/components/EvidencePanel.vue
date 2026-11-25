<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  NTag,
  NTabs,
  NTabPane,
  NButton,
  NModal,
  NSpin,
  useMessage,
} from "naive-ui";
import type { EvidenceItem, EvidencePack, VaultFilePreview } from "@/api/types";
import { downloadVaultFile, fetchVaultFilePreview } from "@/api/realai";
import { buildCitationIndex } from "@/utils/citations";

const props = defineProps<{
  evidence?: EvidencePack | null;
  trajectory?: string[];
}>();

const emit = defineEmits<{
  select: [item: EvidenceItem];
}>();

const message = useMessage();
const tab = ref("all");
const previewOpen = ref(false);
const previewLoading = ref(false);
const preview = ref<VaultFilePreview | null>(null);
const previewPath = ref("");
/** ids with excerpt fully expanded */
const expandedIds = ref<Set<string>>(new Set());
const EXCERPT_COLLAPSE_AT = 180;

const citation = computed(() => buildCitationIndex(props.evidence?.items ?? []));
const orderedItems = computed(() => citation.value.ordered);
const idToNum = computed(() => citation.value.idToNum);

watch(
  () => props.evidence,
  () => {
    expandedIds.value = new Set();
  },
);

function isExpanded(id: string) {
  return expandedIds.value.has(id);
}

function toggleExcerpt(id: string) {
  const next = new Set(expandedIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedIds.value = next;
}

function displayExcerpt(item: EvidenceItem) {
  const text = item.excerpt || "（无原文片段）";
  if (isExpanded(item.id) || text.length <= EXCERPT_COLLAPSE_AT) return text;
  return text.slice(0, EXCERPT_COLLAPSE_AT) + "…";
}

function canExpandExcerpt(item: EvidenceItem) {
  return (item.excerpt || "").length > EXCERPT_COLLAPSE_AT;
}

function citeNum(item: EvidenceItem) {
  return idToNum.value.get(item.id) ?? 0;
}

const grouped = computed(() => {
  const map: Record<string, EvidenceItem[]> = {
    kb: [],
    data: [],
    viz: [],
    web: [],
    inference: [],
  };
  for (const item of orderedItems.value) {
    const key = map[item.type] ? item.type : "inference";
    map[key].push(item);
  }
  return map;
});

const filtered = computed(() => {
  if (tab.value === "all") return orderedItems.value;
  return grouped.value[tab.value] || [];
});

const items = orderedItems;

const typeLabel: Record<string, string> = {
  kb: "知识库",
  data: "问数",
  viz: "图片依据",
  web: "联网",
  inference: "推测",
};

const typeType: Record<string, "default" | "success" | "warning" | "info" | "error"> = {
  kb: "success",
  data: "info",
  viz: "warning",
  web: "default",
  inference: "error",
};

async function openItem(item: EvidenceItem) {
  emit("select", item);
  const path = String(item.meta?.path || item.source || "").trim();
  if (item.type !== "kb" || !path || path.startsWith("http")) return;

  previewPath.value = path;
  preview.value = null;
  previewOpen.value = true;
  previewLoading.value = true;
  try {
    preview.value = await fetchVaultFilePreview(path);
  } catch (err) {
    previewOpen.value = false;
    message.error(err instanceof Error ? err.message : "无法打开来源文件");
  } finally {
    previewLoading.value = false;
  }
}

async function downloadCurrent() {
  const path = preview.value?.path || previewPath.value;
  if (!path) return;
  try {
    await downloadVaultFile(path, preview.value?.name);
  } catch (err) {
    message.error(err instanceof Error ? err.message : "下载失败");
  }
}
</script>

<template>
  <div class="ev">
    <div class="ev-sticky">
      <div class="ev-head">
        <div>
          <div class="title">证据溯源</div>
          <div class="muted">查看回答依据与执行轨迹</div>
        </div>
        <span class="count">{{ items.length }}</span>
      </div>

      <NTabs v-model:value="tab" type="segment" size="small" animated class="ev-tabs">
        <NTabPane name="all" :tab="`全部 ${items.length}`" />
        <NTabPane name="kb" :tab="`知识库 ${grouped.kb.length}`" />
        <NTabPane name="data" :tab="`问数 ${grouped.data.length}`" />
        <NTabPane name="web" :tab="`联网 ${grouped.web.length}`" />
        <NTabPane name="inference" :tab="`推测 ${grouped.inference.length}`" />
      </NTabs>
    </div>

    <div class="list ra-scroll">
      <div v-if="!filtered.length" class="empty-evidence">
        <div class="empty-visual" aria-hidden="true">
          <span class="empty-ring ring-a" />
          <span class="empty-ring ring-b" />
          <svg viewBox="0 0 48 48">
            <path
              d="M14 9.5h16l6 6V37a3 3 0 0 1-3 3H14a3 3 0 0 1-3-3V12.5a3 3 0 0 1 3-3Z"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linejoin="round"
            />
            <path
              d="M29.5 9.5V16H36M17 23h13M17 29h10"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <circle cx="34" cy="34" r="6" fill="#fff" stroke="currentColor" stroke-width="2.4" />
            <path d="m38.4 38.4 3.4 3.4" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
          </svg>
        </div>
        <strong>等待可追溯证据</strong>
        <p>提问后，知识库原文、问数结果和联网来源会自动汇集到这里。</p>
        <div class="empty-pills">
          <span>原文定位</span>
          <span>数据口径</span>
          <span>执行轨迹</span>
        </div>
      </div>
      <article v-for="item in filtered" :key="item.id" class="card ra-fade-in">
        <div class="card-body">
          <div class="card-top">
            <span class="cite-badge" :title="item.id">[{{ citeNum(item) }}]</span>
            <NTag size="small" :type="typeType[item.type] || 'default'" round>
              {{ typeLabel[item.type] || item.type }}
            </NTag>
            <code class="id">{{ item.id }}</code>
          </div>
          <div class="source-row">
            <NButton
              v-if="item.type === 'kb'"
              size="tiny"
              type="primary"
              secondary
              class="source-btn"
              @click="openItem(item)"
            >
              打开来源
            </NButton>
            <div class="source" :title="item.source || ''">{{ item.source || "—" }}</div>
          </div>
          <p class="excerpt">{{ displayExcerpt(item) }}</p>
          <button
            v-if="canExpandExcerpt(item)"
            type="button"
            class="excerpt-toggle"
            @click="toggleExcerpt(item.id)"
          >
            {{ isExpanded(item.id) ? "收起" : "展开全部" }}
          </button>
        </div>
        <div v-if="item.type !== 'kb'" class="card-actions">
          <span class="muted tiny locator">
            {{ item.meta?.locator ? `定位：${item.meta.locator}` : "暂无更细定位" }}
          </span>
          <NTag v-if="item.type === 'inference'" size="tiny" type="warning">须单独标注为推测</NTag>
        </div>
      </article>
    </div>

    <div v-if="trajectory?.length" class="traj">
      <div class="title sm">本轮轨迹</div>
      <ol>
        <li v-for="(step, i) in trajectory" :key="i">{{ step }}</li>
      </ol>
    </div>

    <NModal
      v-model:show="previewOpen"
      preset="card"
      :title="preview?.name || '来源预览'"
      style="width: min(720px, 92vw)"
      :bordered="false"
      segmented
    >
      <template #header-extra>
        <NButton
          v-if="previewPath"
          size="tiny"
          quaternary
          :disabled="previewLoading"
          @click="downloadCurrent"
        >
          下载
        </NButton>
      </template>
      <NSpin :show="previewLoading">
        <div class="preview-body">
          <div v-if="preview?.path" class="preview-path muted">{{ preview.path }}</div>
          <pre v-if="preview?.preview_mode === 'text'" class="preview-text">{{
            preview.content || "（无文本内容）"
          }}</pre>
          <img
            v-else-if="preview?.preview_mode === 'image' && preview.content"
            class="preview-img"
            :src="preview.content"
            :alt="preview.name"
          />
          <div v-else-if="!previewLoading" class="preview-fallback">
            <p>{{ preview?.message || "该文件类型暂不支持在线预览。" }}</p>
            <NButton size="small" secondary @click="downloadCurrent">下载查看</NButton>
          </div>
          <div v-if="preview?.truncated" class="muted tiny trunc-hint">内容已截断，完整文件可下载查看</div>
        </div>
      </NSpin>
    </NModal>
  </div>
</template>

<style scoped>
.ev {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}
.ev-sticky {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: transparent;
  z-index: 1;
}
.ev-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  padding: 2px 2px 0;
}
.ev-tabs {
  width: 100%;
}
.ev-tabs :deep(.n-tabs-rail) {
  padding: 3px;
  border-radius: 12px;
  background: #f0f4f9;
}
.ev-tabs :deep(.n-tabs-tab) {
  min-width: 0;
  padding: 6px 8px;
  border-radius: 9px;
  font-size: 10px;
}
.ev-tabs :deep(.n-tabs-tab--active) {
  box-shadow: 0 5px 14px rgba(46, 78, 123, 0.08);
}
.title {
  color: #1e2b40;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.02em;
}
.title.sm {
  font-size: 12px;
  margin-bottom: 6px;
}
.muted {
  color: #929eb0;
  font-size: 11px;
  margin-top: 2px;
}
.tiny {
  font-size: 11px;
}
.count {
  min-width: 30px;
  height: 30px;
  border-radius: 999px;
  border: 1px solid rgba(57, 126, 236, 0.11);
  background: linear-gradient(145deg, #edf5ff, #f7faff);
  color: var(--ra-accent);
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 650;
}
.list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 2px;
}
.empty-evidence {
  flex: 1;
  min-height: 320px;
  padding: 42px 12px 30px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.empty-visual {
  position: relative;
  width: 74px;
  height: 74px;
  margin-bottom: 24px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(57, 126, 236, 0.11);
  border-radius: 24px;
  color: #72a1e7;
  background: linear-gradient(145deg, #f7faff, #ebf4ff);
  box-shadow: 0 14px 34px rgba(57, 126, 236, 0.09);
}
.empty-visual svg {
  position: relative;
  z-index: 2;
  width: 44px;
  height: 44px;
}
.empty-ring {
  position: absolute;
  border: 1px solid rgba(57, 126, 236, 0.1);
  border-radius: 50%;
}
.ring-a {
  width: 106px;
  height: 106px;
}
.ring-b {
  width: 142px;
  height: 142px;
  border-style: dashed;
  opacity: 0.6;
}
.empty-evidence strong {
  color: #34445c;
  font-size: 13px;
  font-weight: 700;
}
.empty-evidence p {
  max-width: 230px;
  margin: 8px 0 0;
  color: #97a3b3;
  font-size: 11px;
  line-height: 1.65;
}
.empty-pills {
  margin-top: 17px;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 5px;
}
.empty-pills span {
  padding: 4px 7px;
  border: 1px solid rgba(57, 126, 236, 0.08);
  border-radius: 999px;
  background: rgba(247, 250, 254, 0.9);
  color: #9aa7b8;
  font-size: 9px;
}
.card {
  border: 1px solid rgba(57, 126, 236, 0.11);
  border-radius: 15px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.86);
  min-width: 0;
  max-width: 100%;
  overflow: visible;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 8px 22px rgba(45, 75, 116, 0.04);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.card:hover {
  transform: translateY(-1px);
  border-color: rgba(57, 126, 236, 0.22);
  box-shadow: 0 12px 28px rgba(57, 126, 236, 0.075);
}
.card-body {
  min-width: 0;
  max-width: 100%;
}
.card-top {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
  min-width: 0;
  flex-wrap: wrap;
}
.cite-badge {
  flex-shrink: 0;
  min-width: 28px;
  height: 22px;
  padding: 0 6px;
  border-radius: 999px;
  background: linear-gradient(145deg, #eaf3ff, #f5f9ff);
  color: var(--ra-accent, #397eec);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}
.id {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: var(--ra-muted);
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-all;
}
.source-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  margin-bottom: 6px;
}
.source-btn {
  flex-shrink: 0;
}
.source {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #334158;
  font-weight: 600;
  margin-bottom: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.excerpt {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #526176;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  min-width: 0;
  max-width: 100%;
}
.excerpt-toggle {
  margin-top: 4px;
  padding: 0;
  border: none;
  background: none;
  color: var(--ra-accent, #397eec);
  font-size: 12px;
  cursor: pointer;
}
.excerpt-toggle:hover {
  text-decoration: underline;
}
.card-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
  padding-top: 2px;
}
.locator {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.traj {
  flex-shrink: 0;
  max-height: 28%;
  overflow: auto;
  border-top: 1px solid rgba(57, 126, 236, 0.09);
  padding: 11px 2px 0;
}
.traj ol {
  margin: 0;
  padding-left: 18px;
  color: var(--ra-muted);
  font-size: 12px;
  line-height: 1.6;
}
.preview-body {
  min-height: 120px;
  max-height: min(70vh, 560px);
  overflow: auto;
}
.preview-path {
  margin-bottom: 8px;
  word-break: break-all;
  font-size: 11px;
}
.preview-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  font-family: ui-monospace, "Cascadia Mono", "Segoe UI Mono", Consolas, monospace;
  color: #1e293b;
}
.preview-img {
  display: block;
  max-width: 100%;
  height: auto;
  border-radius: 8px;
}
.preview-fallback {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 0;
  color: var(--ra-muted);
  font-size: 13px;
}
.trunc-hint {
  margin-top: 10px;
}
</style>
