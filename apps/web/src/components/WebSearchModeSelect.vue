<script setup lang="ts">
import { NSelect, NSpace } from "naive-ui";
import { useConfigStore } from "@/stores/config";
import { WEB_SEARCH_MODE_OPTIONS, type WebSearchMode } from "@/utils/webSearchMode";

withDefaults(
  defineProps<{
    /** 是否显示左侧「联网」文字 */
    showLabel?: boolean;
  }>(),
  { showLabel: true },
);

const config = useConfigStore();
</script>

<template>
  <NSpace align="center" :size="10" class="web-search-mode">
    <span v-if="showLabel" class="muted">联网</span>
    <NSelect
      :value="config.webSearchMode"
      :options="WEB_SEARCH_MODE_OPTIONS"
      size="small"
      style="width: 88px"
      :consistent-menu-width="false"
      @update:value="(v) => config.setWebSearchMode(v as WebSearchMode)"
    />
  </NSpace>
</template>

<style scoped>
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
</style>
