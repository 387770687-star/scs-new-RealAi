<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NButton, NInput, NSelect, NSpace } from "naive-ui";
import type { FilterDraft, FilterOp } from "@/api/types";

const props = defineProps<{
  draft: FilterDraft;
  status: "pending" | "confirmed" | "cancelled";
  loading?: boolean;
}>();

const emit = defineEmits<{
  confirm: [draft: FilterDraft];
  cancel: [];
}>();

const opOptions = [
  { label: "等于", value: "eq" },
  { label: "不等于", value: "ne" },
  { label: "大于", value: "gt" },
  { label: "大于等于", value: "gte" },
  { label: "小于", value: "lt" },
  { label: "小于等于", value: "lte" },
  { label: "包含", value: "contains" },
];

const local = ref<FilterDraft>(cloneDraft(props.draft));

watch(
  () => props.draft,
  (d) => {
    local.value = cloneDraft(d);
  },
  { deep: true },
);

// Keep editors usable while request runs; only lock after confirmed/cancelled
const readonly = computed(() => props.status !== "pending");

function cloneDraft(d: FilterDraft): FilterDraft {
  return {
    logic: "and",
    title_hint: d.title_hint,
    conditions: (d.conditions || []).map((c) => ({ ...c })),
  };
}

function onConfirm() {
  emit("confirm", cloneDraft(local.value));
}

function opLabel(op: FilterOp) {
  return opOptions.find((o) => o.value === op)?.label || op;
}
</script>

<template>
  <div class="fcc" :class="status">
    <div class="fcc-head">
      <div class="fcc-title">
        请确认筛选条件
        <span class="badge">{{ status === "pending" ? "待确认" : status === "confirmed" ? "已确认" : "已取消" }}</span>
      </div>
      <div class="fcc-sub">
        将在知识库表格中按下列条件查找，并合并为一张结果表
        <span v-if="draft.title_hint" class="hint">（{{ draft.title_hint }}）</span>
      </div>
    </div>

    <div class="fcc-rows">
      <div v-for="c in local.conditions" :key="c.id" class="fcc-row">
        <div class="field">
          <div class="label">{{ c.field_label }}</div>
          <div class="key">{{ c.field_key }}</div>
        </div>
        <template v-if="!readonly">
          <NSelect
            v-model:value="c.op"
            :options="opOptions"
            size="small"
            style="width: 110px"
          />
          <NInput v-model:value="c.value" size="small" style="width: 120px" />
        </template>
        <template v-else>
          <span class="ro-op">{{ opLabel(c.op) }}</span>
          <span class="ro-val">{{ c.value }}</span>
        </template>
        <span v-if="c.unit" class="unit">{{ c.unit }}</span>
      </div>
    </div>

    <NSpace v-if="status === 'pending'" class="fcc-actions" :size="8">
      <NButton type="primary" size="small" :loading="loading" @click="onConfirm">确认查询</NButton>
      <NButton size="small" quaternary :disabled="loading" @click="emit('cancel')">取消</NButton>
    </NSpace>
  </div>
</template>

<style scoped>
.fcc {
  margin: 8px 0 10px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(57, 126, 236, 0.3);
  background: linear-gradient(180deg, #f2f7ff 0%, #fff 70%);
}
.fcc.confirmed {
  border-color: #bbf7d0;
  background: linear-gradient(180deg, #f0fdf4 0%, #fff 70%);
}
.fcc.cancelled {
  border-color: #e2e8f0;
  background: #f8fafc;
  opacity: 0.85;
}
.fcc-title {
  font-size: 13px;
  font-weight: 650;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 8px;
}
.badge {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--ra-accent-soft);
  color: var(--ra-accent);
}
.fcc.confirmed .badge {
  background: #dcfce7;
  color: #15803d;
}
.fcc.cancelled .badge {
  background: #e2e8f0;
  color: #64748b;
}
.fcc-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
}
.fcc-sub .hint {
  color: #94a3b8;
}
.fcc-rows {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.fcc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.field {
  min-width: 120px;
}
.field .label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}
.field .key {
  font-size: 10px;
  color: #94a3b8;
}
.unit {
  font-size: 11px;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 2px 6px;
}
.ro-op,
.ro-val {
  font-size: 12px;
  color: #0f172a;
}
.ro-op {
  font-weight: 600;
}
.fcc-actions {
  margin-top: 12px;
}
</style>
