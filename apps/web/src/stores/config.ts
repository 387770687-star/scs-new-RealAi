import { defineStore } from "pinia";
import { ref } from "vue";
import {
  fetchRealAiConfig,
  saveRealAiConfig,
  syncRealAiConfig,
} from "@/api/realai";
import type { RealAiConfigResponse, RealAiSettings } from "@/api/types";
import {
  cycleWebSearchMode,
  normalizeWebSearchMode,
  type WebSearchMode,
} from "@/utils/webSearchMode";
import {
  cycleVisionMode,
  normalizeVisionMode,
  type VisionMode,
} from "@/utils/visionMode";

export const useConfigStore = defineStore("config", () => {
  const config = ref<RealAiConfigResponse | null>(null);
  const loading = ref(false);
  const saving = ref(false);
  const error = ref("");

  /** @deprecated prefer webSearchMode */
  const webSearchEnabled = ref(false);
  const webSearchMode = ref<WebSearchMode>("auto");
  const visionMode = ref<VisionMode>("auto");

  function applySearchFromSettings(settings?: RealAiSettings) {
    const mode = normalizeWebSearchMode(
      settings?.search?.webSearchMode,
      settings?.search?.webSearchEnabled,
    );
    webSearchMode.value = mode;
    webSearchEnabled.value = mode !== "off";
    visionMode.value = normalizeVisionMode(settings?.search?.visionMode);
  }

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      config.value = await fetchRealAiConfig();
      applySearchFromSettings(config.value.settings);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      config.value = null;
    } finally {
      loading.value = false;
    }
  }

  async function save(partial: Partial<RealAiSettings> & { llm?: Record<string, unknown> }) {
    saving.value = true;
    error.value = "";
    try {
      const res = await saveRealAiConfig(partial);
      config.value = res;
      applySearchFromSettings(res.settings);
      return res;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      saving.value = false;
    }
  }

  async function setWebSearchMode(mode: WebSearchMode) {
    webSearchMode.value = mode;
    webSearchEnabled.value = mode !== "off";
    await save({
      search: {
        webSearchMode: mode,
        webSearchEnabled: mode !== "off",
        visionMode: visionMode.value,
      },
    });
  }

  async function setVisionMode(mode: VisionMode) {
    visionMode.value = mode;
    await save({
      search: {
        webSearchMode: webSearchMode.value,
        webSearchEnabled: webSearchMode.value !== "off",
        visionMode: mode,
      },
    });
  }

  /** Legacy boolean toggle → maps true to force, false to off. */
  async function setWebSearch(enabled: boolean) {
    await setWebSearchMode(enabled ? "force" : "off");
  }

  async function cycleWebSearch() {
    await setWebSearchMode(cycleWebSearchMode(webSearchMode.value));
  }

  async function cycleVision() {
    await setVisionMode(cycleVisionMode(visionMode.value));
  }

  async function sync() {
    return syncRealAiConfig();
  }

  return {
    config,
    loading,
    saving,
    error,
    webSearchEnabled,
    webSearchMode,
    visionMode,
    load,
    save,
    setWebSearch,
    setWebSearchMode,
    setVisionMode,
    cycleWebSearch,
    cycleVision,
    sync,
  };
});
