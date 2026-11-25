<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { NAlert, NButton, NSpace } from "naive-ui";
import { useHealthStore } from "@/stores/health";

const health = useHealthStore();
const router = useRouter();

const issues = computed(() => health.issues);

function go(path: string) {
  router.push(path);
}
</script>

<template>
  <div v-if="issues.length" class="banner ra-fade-in">
    <NAlert
      v-for="item in issues"
      :key="item.id"
      :type="item.level"
      :title="item.title"
      :bordered="false"
      class="alert"
    >
      <div class="row">
        <span>{{ item.message }}</span>
        <NSpace v-if="item.actionPath">
          <NButton size="tiny" type="primary" secondary @click="go(item.actionPath)">
            {{ item.actionLabel || "去处理" }}
          </NButton>
        </NSpace>
      </div>
    </NAlert>
  </div>
</template>

<style scoped>
.banner {
  margin-bottom: 10px;
  flex-shrink: 0;
}
.alert {
  border-radius: 12px;
  margin-bottom: 8px;
}
.alert:last-child {
  margin-bottom: 0;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
