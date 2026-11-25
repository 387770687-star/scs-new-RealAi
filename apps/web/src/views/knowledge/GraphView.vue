<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { NButton, NInput, NSelect, NSpace, useMessage } from "naive-ui";
import * as echarts from "echarts";
import PageHeader from "@/components/PageHeader.vue";
import {
  fetchVaultFilePreview,
  fetchVaultGraph,
  rebuildWiki,
} from "@/api/realai";
import type { VaultFilePreview } from "@/api/types";

const message = useMessage();
const seed = ref("");
const typeFilter = ref("");
const chartEl = ref<HTMLDivElement | null>(null);
const loading = ref(false);
let chart: echarts.ECharts | null = null;
const preview = ref<VaultFilePreview | null>(null);

async function openPreview(path: string) {
  try {
    preview.value = await fetchVaultFilePreview(path);
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e));
  }
}

const typeOptions = [
  { label: "全部", value: "" },
  { label: "管段", value: "pipe_section" },
  { label: "站场", value: "station" },
  { label: "管线", value: "pipeline" },
  { label: "文档", value: "document" },
  { label: "指标", value: "metric" },
  { label: "组织", value: "org" },
  { label: "LNG", value: "lng" },
  { label: "储气库", value: "storage" },
];

async function load() {
  loading.value = true;
  try {
    const data = await fetchVaultGraph({
      seed: seed.value.trim() || undefined,
      depth: seed.value.trim() ? 2 : 1,
      types: typeFilter.value ? typeFilter.value : undefined,
      limit: 180,
    });
    await nextTick();
    if (!chartEl.value) return;
    if (!chart) chart = echarts.init(chartEl.value);
    const cats = Array.from(new Set(data.nodes.map((n) => n.type || "other")));
    chart.setOption({
      color: ["#397EEC", "#025BFE", "#A86CFF", "#32CFFC", "#CCCBCC"],
      tooltip: {
        formatter: (p: { data?: { name?: string; path?: string; category?: number } }) => {
          const d = p.data;
          if (!d) return "";
          return `${d.name || ""}<br/>${d.path || ""}`;
        },
      },
      legend: [{ data: cats }],
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          categories: cats.map((c) => ({ name: c })),
          force: { repulsion: 120, edgeLength: [40, 120] },
          label: { show: true, position: "right", fontSize: 11 },
          data: data.nodes.map((n) => ({
            id: n.id,
            name: n.title,
            path: n.path,
            category: Math.max(0, cats.indexOf(n.type || "other")),
            symbolSize: n.kind === "entity" ? 28 : 18,
          })),
          links: data.edges
            .filter((e) => e.rel === "wikilink")
            .map((e) => ({ source: e.source, target: e.target })),
          lineStyle: { color: "#94a3b8", curveness: 0.1 },
        },
      ],
    });
    chart.off("click");
    chart.on("click", (params) => {
      const path = (params.data as { path?: string } | undefined)?.path;
      if (!path) return;
      void openPreview(path);
    });
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e));
  } finally {
    loading.value = false;
  }
}

async function onRebuild() {
  try {
    const res = await rebuildWiki();
    message.success(
      `图谱已重建：实体 ${res.entities_written ?? 0}，节点 ${res.graph?.nodes ?? 0}`,
    );
    await load();
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e));
  }
}

function onResize() {
  chart?.resize();
}

onMounted(() => {
  void load();
  window.addEventListener("resize", onResize);
});
onUnmounted(() => {
  window.removeEventListener("resize", onResize);
  chart?.dispose();
  chart = null;
});

watch(typeFilter, () => void load());
</script>

<template>
  <div class="graph-page ra-fade-in">
    <PageHeader title="知识图谱">
      <template #actions>
        <NSpace>
          <NInput v-model:value="seed" size="small" placeholder="种子：站名/管段" style="width: 200px" @keyup.enter="load" />
          <NSelect
            v-model:value="typeFilter"
            size="small"
            :options="typeOptions"
            style="width: 120px"
            clearable
          />
          <NButton size="small" :loading="loading" @click="load">刷新</NButton>
          <NButton size="small" type="primary" @click="onRebuild">重建 Wiki</NButton>
        </NSpace>
      </template>
    </PageHeader>
    <p class="hint">与 Obsidian 共用 Vault 中的 [[双向链接]]；点击节点可预览笔记。</p>
    <div ref="chartEl" class="chart" />
    <aside v-if="preview" class="preview">
      <div class="pt">{{ preview.name }}</div>
      <pre>{{ preview.content?.slice(0, 4000) || "（无文本预览）" }}</pre>
      <NButton size="tiny" quaternary @click="preview = null">关闭</NButton>
    </aside>
  </div>
</template>

<style scoped>
.graph-page {
  flex: 1;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0 4px 8px;
  position: relative;
  overflow: hidden;
}
.hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--ra-muted, #64748b);
  flex-shrink: 0;
}
.chart {
  flex: 1;
  min-height: 0;
  border: 1px solid var(--ra-border, #e2e8f0);
  border-radius: 8px;
  background: #fafbfc;
}
.preview {
  position: absolute;
  right: 16px;
  top: 100px;
  width: 320px;
  max-height: 60%;
  overflow: auto;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 8px 24px rgb(15 23 42 / 8%);
}
.pt {
  font-weight: 600;
  margin-bottom: 8px;
}
.preview pre {
  white-space: pre-wrap;
  font-size: 12px;
  margin: 0 0 8px;
}
</style>
