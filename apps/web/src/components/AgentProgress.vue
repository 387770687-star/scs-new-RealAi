<script setup lang="ts">
import { NTimeline, NTimelineItem, NTag } from "naive-ui";
import type { AgentProgressStep } from "@/api/types";
import EmptyState from "./EmptyState.vue";

defineProps<{
  steps?: AgentProgressStep[];
}>();

function statusType(s: string): "default" | "success" | "warning" | "info" | "error" {
  if (s === "completed") return "success";
  if (s === "running") return "info";
  if (s === "failed") return "error";
  if (s === "skipped") return "warning";
  return "default";
}

function statusText(s: string) {
  const map: Record<string, string> = {
    pending: "等待",
    running: "进行中",
    completed: "完成",
    skipped: "跳过",
    failed: "失败",
  };
  return map[s] || s;
}
</script>

<template>
  <div>
    <EmptyState v-if="!steps?.length" title="尚无 Agent 进度" description="开始生成报告后，这里会显示各子 Agent 状态。" />
    <NTimeline v-else>
      <NTimelineItem
        v-for="step in steps"
        :key="step.id"
        :type="step.status === 'failed' ? 'error' : step.status === 'completed' ? 'success' : 'info'"
        :title="step.label"
      >
        <template #header>
          <div class="row">
            <span>{{ step.label }}</span>
            <NTag size="tiny" :type="statusType(step.status)">{{ statusText(step.status) }}</NTag>
          </div>
        </template>
        <div class="msg">{{ step.message || step.id }}</div>
      </NTimelineItem>
    </NTimeline>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.msg {
  color: var(--ra-muted);
  font-size: 12px;
}
</style>
