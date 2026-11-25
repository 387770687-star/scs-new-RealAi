import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { fetchOnboardingStatus, fetchRealAiConfig, fetchRealAiHealth } from "@/api/realai";
import { ApiError } from "@/api/types";

export interface HealthIssue {
  id: string;
  level: "warning" | "error" | "info";
  title: string;
  message: string;
  actionPath?: string;
  actionLabel?: string;
}

export const useHealthStore = defineStore("health", () => {
  const online = ref(false);
  const loading = ref(false);
  const health = ref<Record<string, unknown> | null>(null);
  const hasApiKey = ref(false);
  const vaultPath = ref("");
  const onboardingNeeded = ref(false);
  const lastError = ref("");

  const issues = computed<HealthIssue[]>(() => {
    const list: HealthIssue[] = [];
    if (!online.value) {
      list.push({
        id: "offline",
        level: "error",
        title: "后端未就绪",
        message: lastError.value || "无法访问 Gateway。请先启动后端服务。",
        actionPath: "/system",
        actionLabel: "打开系统管理",
      });
      return list;
    }
    if (!hasApiKey.value) {
      list.push({
        id: "no-key",
        level: "warning",
        title: "尚未配置 API Key",
        message: "请在系统管理或模型中心填写 MiniMax Key，否则无法问答与写报告。",
        actionPath: "/system",
        actionLabel: "去配置",
      });
    }
    if (onboardingNeeded.value) {
      list.push({
        id: "onboarding",
        level: "info",
        title: "建议完成首次向导",
        message: "可一键导入示例资料并完成基础配置。",
        actionPath: "/system",
        actionLabel: "去向导",
      });
    }
    return list;
  });

  async function refresh() {
    loading.value = true;
    lastError.value = "";
    try {
      health.value = await fetchRealAiHealth();
      online.value = true;
      const [cfg, onboarding] = await Promise.all([
        fetchRealAiConfig(),
        fetchOnboardingStatus(),
      ]);
      hasApiKey.value = Boolean(cfg.settings?.llm?.hasApiKey || cfg.deerflow?.has_api_key);
      vaultPath.value = cfg.vault_path || "";
      onboardingNeeded.value = Boolean(onboarding.needed);
    } catch (err) {
      online.value = false;
      health.value = null;
      lastError.value = err instanceof ApiError ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  return {
    online,
    loading,
    health,
    hasApiKey,
    vaultPath,
    onboardingNeeded,
    lastError,
    issues,
    refresh,
  };
});
