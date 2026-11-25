<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <div class="ra-page-header">
    <h1 class="ra-page-title">{{ title }}</h1>
    <div v-if="$slots.actions" class="actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
}
/* Naive NUpload 默认 block/100% 宽，会把按钮挤成竖排 */
.actions :deep(.n-upload),
.actions :deep(.n-upload-trigger) {
  display: inline-flex !important;
  width: auto !important;
}
</style>
