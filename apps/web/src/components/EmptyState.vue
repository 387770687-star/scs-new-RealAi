<script setup lang="ts">
import { NEmpty, NButton } from "naive-ui";

withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    /** 极简空态短句（优先于 description） */
    text?: string;
    kind?: "empty" | "not_ready" | "network" | "error";
    actionLabel?: string;
  }>(),
  {
    title: "暂无内容",
    description: "",
    text: "",
    kind: "empty",
  },
);

const emit = defineEmits<{ action: [] }>();

const short: Record<string, string> = {
  empty: "暂无数据",
  not_ready: "接口未就绪",
  network: "无法连接",
  error: "加载失败",
};
</script>

<template>
  <div class="empty-wrap">
    <NEmpty :description="text || description || short[kind]">
      <template #extra>
        <div v-if="!text" class="empty-title">{{ title }}</div>
        <NButton v-if="actionLabel" size="small" type="primary" secondary style="margin-top: 10px" @click="emit('action')">
          {{ actionLabel }}
        </NButton>
      </template>
    </NEmpty>
  </div>
</template>

<style scoped>
.empty-wrap {
  padding: 28px 12px;
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.empty-title {
  text-align: center;
  font-weight: 600;
  font-size: 13px;
}
</style>
