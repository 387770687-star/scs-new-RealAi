<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { NButton, NInput, NTag } from "naive-ui";
import type { CitationLedgerEntry } from "@/api/types";
import type { ChapterCard } from "@/utils/chapters";
import { countChineseChars, stripChapterReferenceSection } from "@/utils/chapters";
import { splitMarkdownBlocks, type MarkdownBlock } from "@/utils/format";
import DataTableCard from "@/components/DataTableCard.vue";
import EmptyState from "@/components/EmptyState.vue";

const props = withDefaults(
  defineProps<{
    title: string;
    mainLine?: string;
    chapters: ChapterCard[];
    references?: CitationLedgerEntry[];
    editable?: boolean;
    fontScale?: number;
  }>(),
  {
    mainLine: "",
    references: () => [],
    editable: false,
    fontScale: 100,
  },
);

const emit = defineEmits<{
  save: [chapters: ChapterCard[]];
  activeChange: [chapterId: string];
}>();

const scrollRoot = ref<HTMLElement | null>(null);
const local = ref<ChapterCard[]>([]);
const editingId = ref<string | null>(null);
const draftBody = ref("");
const chapterEls = new Map<string, HTMLElement>();

watch(
  () => props.chapters,
  (list) => {
    local.value = list.map((chapter) => ({ ...chapter }));
  },
  { immediate: true, deep: true },
);

const documentStyle = computed(() => ({
  "--document-font-size": `${(17 * props.fontScale) / 100}px`,
  "--document-scale": String(props.fontScale / 100),
}));

function blocksFor(body: string): MarkdownBlock[] {
  return body ? splitMarkdownBlocks(body) : [];
}

function displayBody(body: string): string {
  return stripChapterReferenceSection(body);
}

function referenceNumber(entry: CitationLedgerEntry, index: number): number {
  return entry.n || index + 1;
}

function referenceLabel(entry: CitationLedgerEntry, index: number): string {
  return String(entry.label || entry.id || `来源 ${index + 1}`).replace(/^【\d+】\s*/, "");
}

function statusLabel(chapter: ChapterCard): string {
  if (chapter.status === "ready") return "已完成";
  if (chapter.status === "writing") return "生成中";
  return "待生成";
}

function statusType(chapter: ChapterCard): "success" | "info" | "default" {
  if (chapter.status === "ready") return "success";
  if (chapter.status === "writing") return "info";
  return "default";
}

function setChapterEl(id: string, el: unknown) {
  if (el instanceof HTMLElement) chapterEls.set(id, el);
  else chapterEls.delete(id);
}

function updateActiveChapter() {
  const root = scrollRoot.value;
  if (!root || !local.value.length) return;
  const rootTop = root.getBoundingClientRect().top;
  let active = local.value[0]?.id || "";
  let closest = Number.NEGATIVE_INFINITY;
  for (const chapter of local.value) {
    const el = chapterEls.get(chapter.id);
    if (!el) continue;
    const offset = el.getBoundingClientRect().top - rootTop;
    if (offset <= 150 && offset > closest) {
      active = chapter.id;
      closest = offset;
    }
  }
  if (active) emit("activeChange", active);
}

async function scrollToChapter(id: string) {
  await nextTick();
  const el = chapterEls.get(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  emit("activeChange", id);
}

function scrollToWriting() {
  const chapter = local.value.find((item) => item.status === "writing") ||
    [...local.value].reverse().find((item) => item.status === "ready");
  if (chapter) scrollToChapter(chapter.id);
}

function startEdit(chapter: ChapterCard) {
  editingId.value = chapter.id;
  draftBody.value = displayBody(chapter.body);
}

function cancelEdit() {
  editingId.value = null;
  draftBody.value = "";
}

function saveChapter(chapter: ChapterCard) {
  const body = draftBody.value;
  local.value = local.value.map((item) =>
    item.id === chapter.id
      ? {
          ...item,
          body,
          chinese_chars: countChineseChars(body),
          status: body.trim() ? "ready" : "pending",
        }
      : item,
  );
  editingId.value = null;
  draftBody.value = "";
  emit("save", local.value.map((item) => ({ ...item })));
}

onMounted(updateActiveChapter);

defineExpose({ scrollToChapter, scrollToWriting });
</script>

<template>
  <div ref="scrollRoot" class="document-scroll" @scroll.passive="updateActiveChapter">
    <main class="document-canvas" :style="documentStyle">
      <header class="document-title-block">
        <div class="document-kicker">战略规划报告</div>
        <h1>{{ title || "未命名报告" }}</h1>
        <p v-if="mainLine" class="document-main-line">{{ mainLine }}</p>
      </header>

      <div v-if="local.length" class="document-chapters">
        <article
          v-for="(chapter, index) in local"
          :key="chapter.id"
          :ref="(el) => setChapterEl(chapter.id, el)"
          class="document-chapter"
          :class="chapter.status"
          :data-chapter-id="chapter.id"
        >
          <div class="chapter-title-row">
            <div>
              <div class="chapter-eyebrow">第 {{ index + 1 }} 章</div>
              <h2>{{ chapter.heading }}</h2>
            </div>
            <div class="chapter-actions">
              <NTag size="small" :bordered="false" :type="statusType(chapter)">
                {{ statusLabel(chapter) }}
              </NTag>
              <span v-if="chapter.chinese_chars" class="chapter-count">
                约 {{ chapter.chinese_chars }} 字
              </span>
              <NButton
                v-if="editable && editingId !== chapter.id && displayBody(chapter.body).trim()"
                size="tiny"
                quaternary
                @click="startEdit(chapter)"
              >
                编辑本章
              </NButton>
            </div>
          </div>

          <div v-if="editingId === chapter.id" class="chapter-editor-wrap">
            <NInput
              v-model:value="draftBody"
              type="textarea"
              class="chapter-editor"
              :autosize="{ minRows: 12, maxRows: 36 }"
              placeholder="本章 Markdown 正文…"
            />
            <div class="chapter-editor-actions">
              <NButton size="small" type="primary" @click="saveChapter(chapter)">保存本章</NButton>
              <NButton size="small" quaternary @click="cancelEdit">取消</NButton>
            </div>
          </div>

          <div v-else-if="displayBody(chapter.body).trim()" class="chapter-content">
            <template v-for="(block, blockIndex) in blocksFor(displayBody(chapter.body))" :key="blockIndex">
              <div v-if="block.type === 'html'" class="document-markdown" v-html="block.html" />
              <DataTableCard
                v-else
                :title="block.title || '表格'"
                :columns="block.columns"
                :rows="block.rows"
              />
            </template>
          </div>

          <div v-else class="chapter-placeholder" :class="chapter.status">
            <span class="placeholder-dot" />
            {{ chapter.status === "writing" ? "正在生成本章内容…" : "本章等待生成" }}
          </div>
        </article>

        <article v-if="references.length" class="global-references">
          <div class="chapter-eyebrow">全文统一引用</div>
          <h2>参考文献</h2>
          <div class="reference-list">
            <div v-for="(entry, index) in references" :key="entry.id || index" class="reference-item">
              <span class="reference-number">【{{ referenceNumber(entry, index) }}】</span>
              <div>
                <div class="reference-label">{{ referenceLabel(entry, index) }}</div>
                <p v-if="entry.excerpt" class="reference-excerpt">{{ entry.excerpt }}</p>
                <div class="reference-meta">
                  <span>{{ entry.source_type || "知识库" }}</span>
                  <a v-if="entry.url" :href="entry.url" target="_blank" rel="noreferrer">查看原文</a>
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>
      <EmptyState v-else text="正文生成后将在这里连续展示" />
    </main>
  </div>
</template>

<style scoped>
.document-scroll {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: auto;
  scroll-behavior: smooth;
  background: #f3f6fa;
  padding: 28px clamp(18px, 4vw, 54px) 80px;
  box-sizing: border-box;
}
.document-canvas {
  width: min(920px, 100%);
  min-height: calc(100% - 24px);
  margin: 0 auto;
  padding: clamp(44px, 6vw, 72px) clamp(38px, 7vw, 86px) 90px;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid #e7ebf1;
  border-radius: 6px;
  box-shadow: 0 18px 50px rgba(40, 57, 86, 0.08);
  color: #202735;
  font-size: var(--document-font-size);
}
.document-title-block {
  padding-bottom: 32px;
  margin-bottom: 42px;
  border-bottom: 1px solid #e8edf4;
}
.document-kicker {
  font-size: 0.72em;
  letter-spacing: 0.12em;
  color: var(--ra-accent, #397eec);
  font-weight: 700;
}
.chapter-eyebrow {
  font-size: max(18px, 1em);
  line-height: 1.4;
  letter-spacing: 0.04em;
  color: var(--ra-accent, #397eec);
  font-weight: 800;
}
.document-title-block h1 {
  margin: 10px 0 0;
  font-size: 2em;
  line-height: 1.3;
  letter-spacing: -0.02em;
}
.document-main-line {
  margin: 20px 0 0;
  padding: 14px 18px;
  border-left: 3px solid var(--ra-accent, #397eec);
  background: #f5f8ff;
  color: #4a5568;
  font-size: 0.92em;
  line-height: 1.75;
  white-space: pre-wrap;
}
.document-chapters {
  display: flex;
  flex-direction: column;
  gap: 54px;
}
.document-chapter {
  scroll-margin-top: 28px;
}
.document-chapter.pending {
  opacity: 0.82;
}
.chapter-title-row {
  display: flex;
  justify-content: space-between;
  gap: 22px;
  align-items: flex-start;
  margin-bottom: 24px;
}
.chapter-title-row h2 {
  margin: 5px 0 0;
  font-size: 1.55em;
  line-height: 1.4;
  letter-spacing: -0.01em;
}
.chapter-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 7px;
  padding-top: 4px;
  flex-shrink: 0;
}
.chapter-count {
  font-size: 12px;
  color: var(--ra-muted, #64748b);
  white-space: nowrap;
}
.chapter-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.document-markdown :deep(p) {
  margin: 0 0 1.05em;
  font-size: 1em;
  line-height: 1.88;
  text-align: justify;
  text-justify: inter-ideograph;
  overflow-wrap: anywhere;
}
.document-markdown :deep(h3),
.document-markdown :deep(h4),
.document-markdown :deep(h5) {
  margin: 1.7em 0 0.7em;
  color: #202735;
  line-height: 1.45;
}
.document-markdown :deep(h3) {
  font-size: 1.28em;
}
.document-markdown :deep(h4) {
  font-size: 1.15em;
}
.document-markdown :deep(h5) {
  font-size: 1.05em;
}
.document-markdown :deep(ul) {
  margin: 0 0 1em;
  padding-left: 1.45em;
  line-height: 1.85;
}
.document-markdown :deep(code) {
  font-size: 0.88em;
  padding: 2px 5px;
  background: #f2f5f9;
  border-radius: 4px;
}
.chapter-placeholder {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 88px;
  padding: 20px;
  border: 1px dashed #d7dee8;
  border-radius: 10px;
  background: #fafbfd;
  color: #7a8799;
  font-size: 0.88em;
}
.placeholder-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c3ccd8;
}
.chapter-placeholder.writing .placeholder-dot {
  background: var(--ra-accent, #397eec);
  box-shadow: 0 0 0 5px rgba(57, 126, 236, 0.12);
  animation: documentPulse 1.2s ease-in-out infinite;
}
.chapter-editor-wrap {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chapter-editor :deep(textarea.n-input__textarea-el) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: max(14px, calc(var(--document-font-size) * 0.9));
  line-height: 1.72;
}
.chapter-editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.global-references {
  padding-top: 8px;
  scroll-margin-top: 28px;
}
.global-references h2 {
  margin: 6px 0 24px;
  font-size: 1.55em;
  line-height: 1.4;
}
.reference-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.reference-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  padding-bottom: 18px;
  border-bottom: 1px solid #edf0f5;
  font-size: 0.88em;
  line-height: 1.65;
}
.reference-number {
  font-weight: 700;
  color: #334155;
}
.reference-label {
  color: #273244;
}
.reference-excerpt {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.9em;
}
.reference-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 5px;
  color: #8a96a8;
  font-size: 12px;
}
.reference-meta a {
  color: var(--ra-accent, #397eec);
  text-decoration: none;
}
@keyframes documentPulse {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
@media (max-width: 760px) {
  .document-scroll {
    padding: 0 0 48px;
  }
  .document-canvas {
    border: none;
    border-radius: 0;
    box-shadow: none;
    padding: 36px 24px 64px;
  }
  .chapter-title-row {
    flex-direction: column;
    gap: 10px;
  }
  .chapter-actions {
    justify-content: flex-start;
  }
}
</style>
