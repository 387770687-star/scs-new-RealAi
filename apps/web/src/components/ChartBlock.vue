<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import * as echarts from "echarts";
import type { ChartSpec } from "@/api/types";

const props = defineProps<{ spec: ChartSpec }>();
const el = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;

function hasPlottableSeries(): boolean {
  const series = props.spec?.series || [];
  return series.some((s) => (s.data || []).some((v) => typeof v === "number" && v !== 0 && !Number.isNaN(v)));
}

function render() {
  if (!el.value || !props.spec || !hasPlottableSeries()) return;
  if (!chart) chart = echarts.init(el.value);
  const cats = props.spec.categories || [];
  const series = (props.spec.series || []).map((s) => ({
    name: s.name,
    type: props.spec.type === "line" ? "line" : "bar",
    data: s.data,
  }));
  chart.setOption({
    title: { text: props.spec.title || "", left: "center", textStyle: { fontSize: 13 } },
    tooltip: { trigger: "axis" },
    grid: { left: 40, right: 16, top: 40, bottom: 32 },
    xAxis: { type: "category", data: cats },
    yAxis: { type: "value" },
    series,
  });
}

onMounted(render);
watch(() => props.spec, render, { deep: true });
onUnmounted(() => {
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div ref="el" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 220px;
  margin-top: 8px;
}
</style>
