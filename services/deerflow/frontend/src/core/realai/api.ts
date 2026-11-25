import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { gatewayBaseUrl } from "@/core/config/ports";

import type {
  AgentProgressStep,
  LightAskResponse,
  RealAiConfigResponse,
  RealAiSettings,
  ReportRunResponse,
  SkillDetail,
  SkillExecuteResponse,
  SkillSummary,
  VaultFileInfo,
  VaultFilePreview,
} from "./types";

/** Browser: Next rewrite `/api/realai/*`. SSR: talk to gateway directly. */
function realaiApiRoot(): string {
  if (typeof window !== "undefined") {
    const pub = getBackendBaseURL();
    return pub ? `${pub}/api/realai` : "/api/realai";
  }
  const internal =
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.replace(/\/+$/, "") ||
    gatewayBaseUrl("127.0.0.1");
  return `${internal}/api/realai`;
}

const base = () => realaiApiRoot();
const skillsBase = () => `${realaiApiRoot()}/skills`;

const FETCH_TIMEOUT_MS = 20_000;

async function readJson<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithAuth(input, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      detail = parsed.detail ?? detail;
    } catch {
      /* keep raw text */
    }
    throw new Error(detail || `请求失败 (${res.status})`);
  }
  return (await res.json()) as T;
}

export async function fetchVaultFiles(limit = 50, offset = 0, q = "") {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (q.trim()) params.set("q", q.trim());
  return readJson<{
    files: VaultFileInfo[];
    count: number;
    total: number;
    offset: number;
    limit: number;
    vault_mtime: number;
  }>(`${base()}/vault/files?${params.toString()}`);
}

export async function fetchOnboardingStatus() {
  return readJson<{
    needed: boolean;
    health: Record<string, unknown>;
  }>(`${base()}/onboarding/status`);
}

export async function completeOnboarding(body: {
  api_key: string;
  web_search_enabled?: boolean;
  import_demo?: boolean;
}) {
  return readJson<{ ok: boolean; settings: RealAiSettings }>(`${base()}/onboarding/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchRealAiHealth() {
  return readJson<Record<string, unknown>>(`${base()}/health`);
}

export async function fetchVaultFilePreview(path: string) {
  return readJson<VaultFilePreview>(
    `${base()}/vault/file?path=${encodeURIComponent(path)}`,
  );
}

export function vaultFileDownloadHref(path: string) {
  return `${base()}/vault/file/download?path=${encodeURIComponent(path)}`;
}

export async function downloadVaultFile(path: string, filename?: string) {
  const res = await fetchWithAuth(vaultFileDownloadHref(path));
  if (!res.ok) {
    throw new Error(`下载失败 (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || path.split("/").pop() || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function fetchVaultFileBlob(path: string) {
  const res = await fetchWithAuth(vaultFileDownloadHref(path));
  if (!res.ok) {
    throw new Error(`读取文件失败 (${res.status})`);
  }
  return res.blob();
}

export async function fetchVaultStatus() {
  return readJson<{ vault_mtime: number; vault_path: string }>(`${base()}/vault/status`);
}

export async function importVaultFile(file: File) {
  const form = new FormData();
  form.append("file", file);
  return readJson<{
    success: boolean;
    vault_path?: string;
    markdown_path?: string;
    message: string;
  }>(`${base()}/vault/import`, {
    method: "POST",
    body: form,
  });
}

export async function lightAsk(query: string, webSearchEnabled: boolean) {
  return readJson<LightAskResponse>(`${base()}/light/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, web_search_enabled: webSearchEnabled }),
  });
}

export async function fetchRealAiConfig() {
  return readJson<RealAiConfigResponse>(`${base()}/config`);
}

export async function saveRealAiConfig(body: Partial<RealAiSettings> & { llm?: Record<string, unknown> }) {
  return readJson<RealAiConfigResponse & { ok: boolean }>(`${base()}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function syncRealAiConfig() {
  return readJson<{ ok: boolean; deerflow: Record<string, unknown> }>(`${base()}/config/sync`, {
    method: "POST",
  });
}

export async function runReport(goal: string, stepConfirm?: boolean, confirmed = false) {
  return readJson<ReportRunResponse>(`${base()}/report/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, step_confirm: stepConfirm, confirmed }),
  });
}

export async function runReportStream(
  goal: string,
  stepConfirm: boolean | undefined,
  confirmed: boolean,
  onProgress: (steps: AgentProgressStep[]) => void,
): Promise<ReportRunResponse> {
  const res = await fetchWithAuth(`${base()}/report/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, step_confirm: stepConfirm, confirmed }),
  });
  if (!res.ok || !res.body) {
    let detail = await res.text();
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      detail = parsed.detail ?? detail;
    } catch {
      /* keep */
    }
    throw new Error(detail || `请求失败 (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ReportRunResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = JSON.parse(line.slice(5).trim()) as {
        type: string;
        agent_progress?: AgentProgressStep[];
        result?: ReportRunResponse;
        message?: string;
      };
      if (payload.type === "progress" && payload.agent_progress) {
        onProgress(payload.agent_progress);
      } else if (payload.type === "result" && payload.result) {
        if (payload.result.agent_progress) onProgress(payload.result.agent_progress);
        finalResult = payload.result;
      } else if (payload.type === "error") {
        throw new Error(payload.message || "报告流式生成失败");
      }
    }
  }

  if (!finalResult) {
    throw new Error("报告流未返回结果");
  }
  return finalResult;
}

export async function fetchSkills(includeDeerflow = false) {
  return readJson<{ skills: SkillSummary[]; count: number }>(
    `${skillsBase()}?include_deerflow=${includeDeerflow ? "true" : "false"}`,
  );
}

export async function fetchSkillsWorkshop() {
  return readJson<{
    skills: SkillSummary[];
    count: number;
    realai_count: number;
    deerflow_count: number;
    note?: string;
  }>(`${skillsBase()}/workshop`);
}

export async function fetchSkill(id: string) {
  return readJson<SkillDetail>(`${skillsBase()}/${encodeURIComponent(id)}`);
}

export async function saveSkill(
  id: string,
  body: { name: string; description: string; body: string },
  isUpdate = false,
) {
  return readJson<{ ok: boolean }>(`${skillsBase()}/${encodeURIComponent(id)}`, {
    method: isUpdate ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteSkill(id: string) {
  return readJson<{ ok: boolean }>(`${skillsBase()}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function importSkillZip(file: File) {
  const form = new FormData();
  form.append("file", file);
  return readJson<{ ok: boolean; imported: string[] }>(`${skillsBase()}/import`, {
    method: "POST",
    body: form,
  });
}

export async function executeSkill(id: string, input: string) {
  return readJson<SkillExecuteResponse>(`${skillsBase()}/${encodeURIComponent(id)}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
}

export async function setSkillEnabled(id: string, enabled: boolean) {
  return readJson<{ ok: boolean; id: string; enabled: boolean }>(
    `${skillsBase()}/${encodeURIComponent(id)}/enabled`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}

export async function fetchSkillHistory(id: string) {
  return readJson<{ skill_id: string; history: Record<string, unknown>[] }>(
    `${skillsBase()}/${encodeURIComponent(id)}/history`,
  );
}
