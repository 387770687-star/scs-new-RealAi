<script setup lang="ts">
withDefaults(
  defineProps<{
    online?: boolean;
    label?: string;
  }>(),
  { online: false },
);
</script>

<template>
  <span class="dot-wrap" :class="{ online }">
    <span class="dot" />
    <span>{{ label || (online ? "服务在线" : "服务离线") }}</span>
  </span>
</template>

<style scoped>
.dot-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ra-muted);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
}
.dot-wrap.online .dot {
  background: var(--ra-success);
  box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.18);
}
.dot-wrap.online {
  color: #047857;
}
</style>
