<script setup lang="ts">
import { computed, ref } from "vue";
import { NDrawer, NDrawerContent, NEmpty, NTag } from "naive-ui";
import type { KnowledgeCard } from "@/api/types";
import DataTableCard from "@/components/DataTableCard.vue";

const props = defineProps<{
  cards: KnowledgeCard[];
}>();

const active = ref<KnowledgeCard | null>(null);
const showDrawer = ref(false);

const kindLabel: Record<string, string> = {
  retrieve: "检索",
  kb: "检索",
  data: "问数",
  web: "联网",
};

const list = computed(() => props.cards || []);

function open(card: KnowledgeCard) {
  active.value = card;
  showDrawer.value = true;
}

function tableRows(card: KnowledgeCard): Record<string, unknown>[] {
  const t = card.table;
  if (Array.isArray(t)) return t as Record<string, unknown>[];
  return [];
}

function tableColumns(card: KnowledgeCard): string[] {
  if (Array.isArray(card.columns)) return card.columns.map(String);
  const rows = tableRows(card);
  if (rows[0]) return Object.keys(rows[0]);
  return [];
}
</script>

<template>
  <aside class="cards-panel">
    <div class="cards-top">
      <div class="head">知识卡片</div>
      <p class="hint">
        写作检索 / 问数 / 联网命中会出现在这里；正文里的 kb:/data: 引用也会自动补齐，可点开查看。
      </p>
    </div>
    <div class="cards-list">
      <NEmpty v-if="!list.length" description="暂无卡片" size="small" />
      <button
        v-for="(c, i) in list"
        :key="`${c.id}-${i}`"
        type="button"
        class="card"
        @click="open(c)"
      >
        <div class="row">
          <NTag size="tiny" :bordered="false">{{ kindLabel[c.kind] || kindLabel[c.type || ""] || c.kind }}</NTag>
          <span class="title">{{ c.title || c.source }}</span>
        </div>
        <div class="excerpt">{{ c.excerpt }}</div>
      </button>
    </div>
  </aside>

  <NDrawer
    v-model:show="showDrawer"
    :width="480"
    placement="right"
    @after-leave="active = null"
  >
    <NDrawerContent v-if="active" :title="active.title || active.source" closable>
      <p class="meta">{{ active.id }} · {{ active.source }}</p>
      <p class="body">{{ active.excerpt }}</p>
      <DataTableCard
        v-if="tableRows(active).length"
        title="问数结果"
        :columns="tableColumns(active)"
        :rows="tableRows(active)"
      />
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.cards-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.cards-top {
  flex: 0 0 auto;
}
.head {
  font-weight: 650;
  font-size: 14px;
}
.hint {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--ra-muted);
  line-height: 1.4;
}
.cards-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card {
  text-align: left;
  border: 1px solid var(--ra-border);
  background: #f8fafc;
  border-radius: 12px;
  padding: 10px;
  cursor: pointer;
  flex: 0 0 auto;
}
.card:hover {
  border-color: var(--ra-accent);
}
.row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.title {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.excerpt {
  margin-top: 6px;
  font-size: 11px;
  color: var(--ra-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  font-size: 12px;
  color: var(--ra-muted);
}
.body {
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
