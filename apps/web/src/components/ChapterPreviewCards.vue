<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NButton, NInput, NTag } from "naive-ui";
import type { ChapterCard } from "@/utils/chapters";
import { countChineseChars } from "@/utils/chapters";
import { splitMarkdownBlocks, type MarkdownBlock } from "@/utils/format";
import DataTableCard from "@/components/DataTableCard.vue";
import EmptyState from "@/components/EmptyState.vue";

const props = defineProps<{
  chapters: ChapterCard[];
  editable?: boolean;
}>();

const emit = defineEmits<{
  save: [chapters: ChapterCard[]];
}>();

const local = ref<ChapterCard[]>([]);
const editingId = ref<string | null>(null);
const draftBody = ref("");
const expanded = ref<Record<string, boolean>>({});

watch(
  () => props.chapters,
  (list) => {
    local.value = list.map((c) => ({ ...c }));
    for (const c of list) {
      if (c.status === "ready" && expanded.value[c.id] === undefined) {
        expanded.value[c.id] = true;
      }
    }
  },
  { immediate: true, deep: true },
);

const hasAny = computed(() => local.value.length > 0);

function statusLabel(c: ChapterCard): string {
  if (c.status === "ready") return "已写";
  if (c.status === "writing") return "写作中";
  return "待写";
}

function toggle(id: string) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] };
}

function startEdit(c: ChapterCard) {
  editingId.value = c.id;
  draftBody.value = c.body;
  expanded.value = { ...expanded.value, [c.id]: true };
}

function cancelEdit() {
  editingId.value = null;
  draftBody.value = "";
}

function commitEdit(c: ChapterCard) {
  const body = draftBody.value;
  local.value = local.value.map((x) =>
    x.id === c.id
      ? {
          ...x,
          body,
          chinese_chars: countChineseChars(body),
          status: body.trim() ? "ready" : "pending",
        }
      : x,
  );
  editingId.value = null;
  draftBody.value = "";
  emit("save", local.value.map((x) => ({ ...x })));
}

function blocksFor(body: string): MarkdownBlock[] {
  return body ? splitMarkdownBlocks(body) : [];
}
</script>

<template>
  <div v-if="hasAny" class="chapter-cards">
    <article
      v-for="(c, idx) in local"
      :key="c.id"
      class="chapter-card"
      :class="c.status"
    >
      <header class="card-head" @click="toggle(c.id)">
        <span class="idx">{{ idx + 1 }}</span>
        <div class="titles">
          <div class="heading">{{ c.heading }}</div>
          <div class="meta">
            <NTag size="tiny" :bordered="false" :type="c.status === 'ready' ? 'success' : 'default'">
              {{ statusLabel(c) }}
            </NTag>
            <span v-if="c.chinese_chars" class="muted">约 {{ c.chinese_chars }} 字</span>
            <span v-if="c.word_budget" class="muted">预算 {{ c.word_budget }}</span>
          </div>
        </div>
        <span class="chev">{{ expanded[c.id] ? "收起" : "展开" }}</span>
      </header>

      <div v-if="expanded[c.id]" class="card-body">
        <div v-if="editable" class="card-actions">
          <template v-if="editingId === c.id">
            <NButton size="tiny" type="primary" @click.stop="commitEdit(c)">保存本章</NButton>
            <NButton size="tiny" quaternary @click.stop="cancelEdit">取消</NButton>
          </template>
          <NButton v-else size="tiny" secondary @click.stop="startEdit(c)">编辑</NButton>
        </div>

        <NInput
          v-if="editingId === c.id"
          v-model:value="draftBody"
          type="textarea"
          class="chapter-editor"
          :autosize="{ minRows: 8, maxRows: 24 }"
          placeholder="本章 Markdown 正文…"
          @click.stop
        />
        <template v-else-if="c.body.trim()">
          <div class="md-blocks">
            <template v-for="(block, bi) in blocksFor(c.body)" :key="bi">
              <div v-if="block.type === 'html'" class="md" v-html="block.html" />
              <DataTableCard
                v-else
                :title="block.title || '表格'"
                :columns="block.columns"
                :rows="block.rows"
              />
            </template>
          </div>
        </template>
        <EmptyState v-else text="本章尚未生成" />
      </div>
    </article>
  </div>
  <EmptyState v-else text="运行后在此按章预览正文" />
</template>

<style scoped>
.chapter-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chapter-card {
  border: 1px solid var(--ra-border, #e2e8f0);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
.chapter-card.pending {
  opacity: 0.85;
}
.card-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  user-select: none;
}
.card-head:hover {
  background: #f8fafc;
}
.idx {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: #f1f5f9;
  font-size: 12px;
  font-weight: 650;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #475569;
}
.titles {
  flex: 1;
  min-width: 0;
}
.heading {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.35;
  color: #0f172a;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 4px;
  font-size: 11px;
}
.muted {
  color: var(--ra-muted, #64748b);
}
.chev {
  flex: 0 0 auto;
  font-size: 11px;
  color: var(--ra-muted, #64748b);
  padding-top: 2px;
}
.card-body {
  padding: 0 12px 12px;
  border-top: 1px solid #f1f5f9;
}
.card-actions {
  display: flex;
  gap: 8px;
  padding: 8px 0;
}
.chapter-editor {
  width: 100%;
}
.chapter-editor :deep(textarea.n-input__textarea-el) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
}
.md-blocks {
  padding-top: 8px;
}
.md :deep(p) {
  margin: 0 0 0.65em;
  line-height: 1.65;
  font-size: 13px;
}
.md :deep(h1),
.md :deep(h2),
.md :deep(h3) {
  margin: 0.8em 0 0.4em;
  font-size: 14px;
}
.md :deep(ul) {
  margin: 0 0 0.65em;
  padding-left: 1.2em;
}
</style>
