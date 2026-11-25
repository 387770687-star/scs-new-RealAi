<script setup lang="ts">
import { NSelect, NSpace } from "naive-ui";
import { useConfigStore } from "@/stores/config";
import { VISION_MODE_OPTIONS, type VisionMode } from "@/utils/visionMode";

withDefaults(
  defineProps<{
    showLabel?: boolean;
  }>(),
  { showLabel: true },
);

const config = useConfigStore();
</script>

<template>
  <NSpace align="center" :size="10" class="vision-mode">
    <span v-if="showLabel" class="muted">看图</span>
    <NSelect
      :value="config.visionMode"
      :options="VISION_MODE_OPTIONS"
      size="small"
      style="width: 88px"
      :consistent-menu-width="false"
      @update:value="(v) => config.setVisionMode(v as VisionMode)"
    />
  </NSpace>
</template>

<style scoped>
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
</style>
