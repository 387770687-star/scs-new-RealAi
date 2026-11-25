import {
  ApiError,
  type AgentProgressStep,
  type Artifact,
  type EvalCase,
  type EvalRun,
  type EvalSuite,
  type LightAskResponse,
  type KnowledgeCatalogResponse,
  type KnowledgeQualityStatus,
  type KnowledgeSourceStatus,
  type KnowledgeType,
  type Metric,
  type RealAiConfigResponse,
  type RealAiSettings,
  type ReportRunResponse,
  type SkillDetail,
  type SkillFileContent,
  type SkillDraft,
  type SkillExecuteResponse,
  type SkillOptimizeResponse,
  type SkillSummary,
  type VaultFileInfo,
  type VaultFilePreview,
  type VaultImportJob,
  type WorkbenchIntent,
  type WritingTask,
} from "./types";

const FETCH_TIMEOUT_MS = 60_000;

function apiRoot(): string {
  // Electron loadFile（file://）时无 Vite 代理，直连 Gateway
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    return "http://127.0.0.1:8401/api/realai";
  }
  return "/api/realai";
}

function skillsRoot(): string {
  return `${apiRoot()}/skills`;
}

function errorDetail(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as {
      detail?:
        | string
        | Array<{ loc?: Array<string | number>; msg?: string; type?: string }>;
    };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((item) => {
          const field = (item.loc || [])
            .filter((part) => part !== "body")
            .join(".");
          return `${field ? `${field}：` : ""}${item.msg || item.type || "参数不正确"}`;
        })
        .join("；");
    }
  } catch {
    /* keep raw response */
  }
  return raw;
}

async function readJson<T>(input: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(input, {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new ApiError(`无法连接后端服务：${msg}`, 0, "network");
  }

  if (!res.ok) {
    const detail = errorDetail(await res.text());
    const kind = res.status === 404 || res.status === 501 ? "not_ready" : "business";
    throw new ApiError(detail || `请求失败 (${res.status})`, res.status, kind);
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
  }>(`${apiRoot()}/vault/files?${params.toString()}`);
}

export async function fetchVaultCatalog(params?: {
  limit?: number;
  offset?: number;
  q?: string;
  knowledge_type?: KnowledgeType | "";
  source_status?: KnowledgeSourceStatus | "";
  quality_status?: KnowledgeQualityStatus | "";
  business_tag?: string;
  refresh?: boolean;
}) {
  const search = new URLSearchParams({
    limit: String(params?.limit ?? 500),
    offset: String(params?.offset ?? 0),
  });
  if (params?.q?.trim()) search.set("q", params.q.trim());
  if (params?.knowledge_type) search.set("knowledge_type", params.knowledge_type);
  if (params?.source_status) search.set("source_status", params.source_status);
  if (params?.quality_status) search.set("quality_status", params.quality_status);
  if (params?.business_tag) search.set("business_tag", params.business_tag);
  if (params?.refresh) search.set("refresh", "true");
  return readJson<KnowledgeCatalogResponse>(
    `${apiRoot()}/vault/catalog?${search.toString()}`,
  );
}

export async function fetchOnboardingStatus() {
  return readJson<{
    needed: boolean;
    health: Record<string, unknown>;
  }>(`${apiRoot()}/onboarding/status`);
}

export async function completeOnboarding(body: {
  api_key: string;
  web_search_enabled?: boolean;
  web_search_mode?: "off" | "auto" | "force";
  import_demo?: boolean;
}) {
  return readJson<{ ok: boolean; settings: RealAiSettings }>(`${apiRoot()}/onboarding/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchRealAiHealth() {
  return readJson<Record<string, unknown>>(`${apiRoot()}/health`);
}

export async function fetchVaultFilePreview(path: string) {
  return readJson<VaultFilePreview>(
    `${apiRoot()}/vault/file?path=${encodeURIComponent(path)}`,
  );
}

export function vaultFileDownloadHref(path: string) {
  return `${apiRoot()}/vault/file/download?path=${encodeURIComponent(path)}`;
}

export async function downloadVaultFile(path: string, filename?: string) {
  const res = await fetch(vaultFileDownloadHref(path));
  if (!res.ok) throw new ApiError(`下载失败 (${res.status})`, res.status);
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

export async function fetchVaultStatus() {
  return readJson<{ vault_mtime: number; vault_path: string }>(`${apiRoot()}/vault/status`);
}

export async function importVaultFile(file: File, targetDir?: string) {
  const form = new FormData();
  form.append("file", file);
  const q = targetDir ? `?target_dir=${encodeURIComponent(targetDir)}` : "";
  return readJson<{
    success: boolean;
    vault_path?: string;
    markdown_path?: string;
    table_path?: string;
    category?: string;
    category_source?: string;
    dropped_columns?: string[];
    vision_preanalyze?: Record<string, unknown>;
    message: string;
  }>(`${apiRoot()}/vault/import${q}`, {
    method: "POST",
    body: form,
  });
}

export async function uploadWorkbenchImage(file: File, sessionId?: string | null) {
  const form = new FormData();
  form.append("file", file);
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return readJson<{ ok: boolean; path: string; size: number }>(
    `${apiRoot()}/vault/upload-image${q}`,
    { method: "POST", body: form },
  );
}

export async function importVaultFromRaw() {
  return readJson<{
    success: boolean;
    message: string;
    total?: number;
    ok?: number;
    items?: unknown[];
  }>(`${apiRoot()}/vault/import/from-raw`, { method: "POST" });
}

export async function rebuildVaultIndex() {
  return readJson<{ ok: boolean; message?: string }>(`${apiRoot()}/vault/index/rebuild`, {
    method: "POST",
  });
}

export async function rebuildWiki() {
  return readJson<{ success: boolean; entities_written?: number; graph?: { nodes: number; edges: number } }>(
    `${apiRoot()}/vault/wiki/rebuild`,
    { method: "POST" },
  );
}

export async function fetchVaultGraph(params?: {
  seed?: string;
  depth?: number;
  types?: string;
  limit?: number;
}) {
  const sp = new URLSearchParams();
  if (params?.seed) sp.set("seed", params.seed);
  if (params?.depth != null) sp.set("depth", String(params.depth));
  if (params?.types) sp.set("types", params.types);
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const q = sp.toString();
  return readJson<{
    nodes: Array<{
      id: string;
      kind: string;
      title: string;
      path: string | null;
      type: string;
      props?: Record<string, unknown>;
    }>;
    edges: Array<{ source: string; target: string; rel: string; weight: number }>;
  }>(`${apiRoot()}/vault/graph${q ? `?${q}` : ""}`);
}

export async function listChatSessions(limit = 100) {
  return readJson<{
    sessions: Array<{
      id: string;
      title: string;
      created_at: number;
      updated_at: number;
      intent?: string | null;
    }>;
  }>(`${apiRoot()}/chat/sessions?limit=${limit}`);
}

export async function createChatSession(title = "新对话", intent?: string) {
  return readJson<{
    id: string;
    title: string;
    messages?: Array<{
      id: string;
      role: string;
      content: Record<string, unknown>;
      created_at: number;
    }>;
  }>(`${apiRoot()}/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, intent }),
  });
}

export async function getChatSession(sessionId: string) {
  return readJson<{
    id: string;
    title: string;
    messages: Array<{
      id: string;
      role: string;
      content: Record<string, unknown>;
      created_at: number;
    }>;
  }>(`${apiRoot()}/chat/sessions/${encodeURIComponent(sessionId)}`);
}

export async function deleteChatSession(sessionId: string) {
  return readJson<{ ok: boolean }>(`${apiRoot()}/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function lightAsk(
  query: string,
  webSearchMode: "off" | "auto" | "force" | boolean,
  intent: WorkbenchIntent = "ask",
  scopePaths: string[] = [],
  sessionId?: string | null,
  visionMode: "off" | "auto" | "force" = "auto",
  imagePaths: string[] = [],
  skillId?: string | null,
) {
  const mode =
    typeof webSearchMode === "boolean"
      ? webSearchMode
        ? "force"
        : "off"
      : webSearchMode;
  return readJson<LightAskResponse & { session_id?: string }>(`${apiRoot()}/light/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      web_search_mode: mode,
      web_search_enabled: mode !== "off",
      vision_mode: visionMode,
      image_paths: imagePaths,
      intent,
      scope_paths: scopePaths,
      session_id: sessionId || undefined,
      skill_id: skillId || undefined,
    }),
  });
}

/** SSE light ask: progress with growing trajectory, then full result (answer not token-streamed). */
export async function lightAskStream(
  query: string,
  webSearchMode: "off" | "auto" | "force" | boolean,
  intent: WorkbenchIntent = "ask",
  scopePaths: string[] = [],
  sessionId: string | null | undefined,
  onProgress: (trajectory: string[]) => void,
  visionMode: "off" | "auto" | "force" = "auto",
  imagePaths: string[] = [],
  skillId?: string | null,
): Promise<LightAskResponse & { session_id?: string }> {
  const mode =
    typeof webSearchMode === "boolean"
      ? webSearchMode
        ? "force"
        : "off"
      : webSearchMode;
  let res: Response;
  try {
    res = await fetch(`${apiRoot()}/light/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        web_search_mode: mode,
        web_search_enabled: mode !== "off",
        vision_mode: visionMode,
        image_paths: imagePaths,
        intent,
        scope_paths: scopePaths,
        session_id: sessionId || undefined,
        skill_id: skillId || undefined,
      }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new ApiError(`无法连接后端服务：${msg}`, 0, "network");
  }

  if (!res.ok || !res.body) {
    const detail = errorDetail(await res.text());
    const kind = res.status === 404 || res.status === 501 ? "not_ready" : "business";
    throw new ApiError(detail || `请求失败 (${res.status})`, res.status, kind);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: (LightAskResponse & { session_id?: string }) | null = null;

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
        trajectory?: string[];
        result?: LightAskResponse & { session_id?: string };
        message?: string;
      };
      if (payload.type === "progress" && payload.trajectory) {
        onProgress(payload.trajectory);
      } else if (payload.type === "result" && payload.result) {
        if (payload.result.trajectory) onProgress(payload.result.trajectory);
        finalResult = payload.result;
      } else if (payload.type === "error") {
        throw new ApiError(payload.message || "问答流式处理失败");
      }
    }
  }

  if (!finalResult) {
    throw new ApiError("问答流未返回结果");
  }
  return finalResult;
}

export async function confirmLightAskFilter(body: {
  query: string;
  filter: import("./types").FilterDraft;
  webSearchEnabled?: boolean;
  webSearchMode?: "off" | "auto" | "force";
  intent: WorkbenchIntent;
  scopePaths: string[];
  sessionId?: string | null;
  messageId?: string | null;
  skillId?: string | null;
}) {
  const mode =
    body.webSearchMode ||
    (body.webSearchEnabled === true ? "force" : body.webSearchEnabled === false ? "off" : "auto");
  return readJson<LightAskResponse & { session_id?: string; message_id?: string }>(
    `${apiRoot()}/light/ask/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: body.query,
        confirm_kind: "filter",
        filter: body.filter,
        web_search_mode: mode,
        web_search_enabled: mode !== "off",
        intent: body.intent,
        scope_paths: body.scopePaths,
        session_id: body.sessionId || undefined,
        message_id: body.messageId || undefined,
        skill_id: body.skillId || undefined,
      }),
    },
  );
}

export async function fetchRealAiConfig() {
  return readJson<RealAiConfigResponse>(`${apiRoot()}/config`);
}

export async function saveRealAiConfig(
  body: Partial<RealAiSettings> & { llm?: Record<string, unknown> },
) {
  return readJson<RealAiConfigResponse & { ok: boolean }>(`${apiRoot()}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function syncRealAiConfig() {
  return readJson<{ ok: boolean; deerflow: Record<string, unknown> }>(`${apiRoot()}/config/sync`, {
    method: "POST",
  });
}

export async function runReport(goal: string, stepConfirm?: boolean, confirmed = false) {
  return readJson<ReportRunResponse>(`${apiRoot()}/report/run`, {
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
  let res: Response;
  try {
    res = await fetch(`${apiRoot()}/report/run/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, step_confirm: stepConfirm, confirmed }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new ApiError(`无法连接后端服务：${msg}`, 0, "network");
  }

  if (!res.ok || !res.body) {
    const detail = errorDetail(await res.text());
    const kind = res.status === 404 || res.status === 501 ? "not_ready" : "business";
    throw new ApiError(detail || `请求失败 (${res.status})`, res.status, kind);
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
        throw new ApiError(payload.message || "报告流式生成失败");
      }
    }
  }

  if (!finalResult) {
    throw new ApiError("报告流未返回结果");
  }
  return finalResult;
}

export async function fetchSkills(includeDeerflow = false) {
  return readJson<{ skills: SkillSummary[]; count: number }>(
    `${skillsRoot()}?include_deerflow=${includeDeerflow ? "true" : "false"}`,
  );
}

export async function fetchSkillsWorkshop() {
  return readJson<{
    skills: SkillSummary[];
    count: number;
    realai_count: number;
    deerflow_count: number;
    note?: string;
  }>(`${skillsRoot()}/workshop`);
}

export async function fetchSkill(id: string) {
  return readJson<SkillDetail>(`${skillsRoot()}/${encodeURIComponent(id)}`);
}

export async function fetchSkillFile(id: string, path: string) {
  const q = new URLSearchParams({ path });
  return readJson<SkillFileContent>(
    `${skillsRoot()}/${encodeURIComponent(id)}/file?${q.toString()}`,
  );
}

export async function saveSkill(
  id: string,
  body: { name: string; description: string; body: string },
  isUpdate = false,
) {
  return readJson<{ ok: boolean }>(`${skillsRoot()}/${encodeURIComponent(id)}`, {
    method: isUpdate ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteSkill(id: string) {
  return readJson<{ ok: boolean }>(`${skillsRoot()}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function importSkillZip(file: File) {
  const form = new FormData();
  form.append("file", file);
  return readJson<{ ok: boolean; imported: string[] }>(`${skillsRoot()}/import`, {
    method: "POST",
    body: form,
  });
}

export async function executeSkill(id: string, input: string) {
  return readJson<SkillExecuteResponse>(`${skillsRoot()}/${encodeURIComponent(id)}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
}

export async function previewSkillDraft(body: {
  name: string;
  description: string;
  body: string;
  input: string;
}) {
  return readJson<SkillExecuteResponse>(`${skillsRoot()}/preview-execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function setSkillEnabled(id: string, enabled: boolean) {
  return readJson<{ ok: boolean; id: string; enabled: boolean }>(
    `${skillsRoot()}/${encodeURIComponent(id)}/enabled`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}

export async function fetchSkillHistory(id: string) {
  return readJson<{ skill_id: string; history: Record<string, unknown>[] }>(
    `${skillsRoot()}/${encodeURIComponent(id)}/history`,
  );
}

export async function optimizeSkill(body: {
  skill_id: string;
  message: string;
  history?: Array<{ role: string; content: string }>;
  current_draft?: Partial<SkillDraft> | null;
}) {
  return readJson<SkillOptimizeResponse>(`${skillsRoot()}/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchSkillOptimizeSession(skillId: string) {
  return readJson<{
    session: {
      id: string;
      title?: string;
      messages?: Array<{
        id: string;
        role: string;
        content: Record<string, unknown>;
        created_at?: number;
      }>;
    };
    latest_draft?: SkillDraft | null;
  }>(`${skillsRoot()}/${encodeURIComponent(skillId)}/optimize/session`);
}

export async function postSkillOptimizeTurn(
  skillId: string,
  body: { message: string; current_draft?: Partial<SkillDraft> | null },
) {
  return readJson<
    SkillOptimizeResponse & {
      session?: {
        id: string;
        messages?: Array<{
          id: string;
          role: string;
          content: Record<string, unknown>;
          created_at?: number;
        }>;
      };
      session_id?: string;
    }
  >(`${skillsRoot()}/${encodeURIComponent(skillId)}/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteSkillOptimizeMessage(skillId: string, messageId: string) {
  return readJson<{
    ok: boolean;
    session?: {
      id: string;
      messages?: Array<{
        id: string;
        role: string;
        content: Record<string, unknown>;
        created_at?: number;
      }>;
    };
  }>(
    `${skillsRoot()}/${encodeURIComponent(skillId)}/optimize/messages/${encodeURIComponent(messageId)}`,
    { method: "DELETE" },
  );
}

export async function clearSkillOptimizeSession(skillId: string) {
  return readJson<{
    ok: boolean;
    session?: {
      id: string;
      messages?: Array<{
        id: string;
        role: string;
        content: Record<string, unknown>;
        created_at?: number;
      }>;
    };
  }>(`${skillsRoot()}/${encodeURIComponent(skillId)}/optimize/session`, {
    method: "DELETE",
  });
}

export async function publishOptimizedSkill(body: {
  publish_id: string;
  name: string;
  description: string;
  body: string;
  source_skill_id?: string;
}) {
  return readJson<{ ok: boolean; skill: SkillSummary; message?: string }>(
    `${skillsRoot()}/optimize/publish`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function fetchModelsRouting(limit = 50) {
  return readJson<{ calls: Record<string, unknown>[]; count: number }>(
    `${apiRoot()}/models/routing?limit=${limit}`,
  );
}

export async function fetchModelsConfig() {
  return readJson<{ models: Record<string, unknown>[]; settings: Record<string, unknown> }>(
    `${apiRoot()}/models`,
  );
}

export async function listWritingTasks(limit = 50) {
  return readJson<{ tasks: WritingTask[] }>(`${apiRoot()}/writing/tasks?limit=${limit}`);
}

export async function listWritingReportTypes() {
  return readJson<{ types: Array<{ id: string; label: string; min_chars: number }> }>(
    `${apiRoot()}/writing/report-types`,
  );
}

export async function createWritingTask(
  goal: string,
  opts?: {
    stepConfirm?: boolean;
    reportType?: string | null;
    audience?: string;
    scopePaths?: string[];
    skillProfileId?: string | null;
  },
) {
  return readJson<WritingTask>(`${apiRoot()}/writing/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      goal,
      step_confirm: Boolean(opts?.stepConfirm),
      // null = 不使用模板，由架构阶段动态生成大纲。
      report_type: opts?.reportType || null,
      audience: opts?.audience || "",
      scope_paths: opts?.scopePaths || [],
      skill_profile_id: opts?.skillProfileId || null,
    }),
  });
}

export async function startWritingIntake(id: string) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/intake/start`,
    { method: "POST" },
  );
}

export async function patchWritingIntakeAnswers(
  id: string,
  answers: Array<{ id: string; answer?: string; skipped?: boolean }>,
) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/intake/answers`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    },
  );
}

export async function confirmWritingIntake(id: string) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/intake/confirm`,
    { method: "POST" },
  );
}

export async function skipWritingIntake(id: string) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/intake/skip`,
    { method: "POST" },
  );
}

export async function getWritingTask(id: string) {
  return readJson<WritingTask>(`${apiRoot()}/writing/tasks/${encodeURIComponent(id)}`);
}

export async function patchWritingTask(
  id: string,
  body: {
    goal?: string;
    step_confirm?: boolean;
    outline?: Record<string, unknown>;
    status?: string;
    report_type?: string;
    audience?: string;
    scope_paths?: string[];
    preview_markdown?: string;
    rewrite_exports?: boolean;
  },
) {
  return readJson<WritingTask>(`${apiRoot()}/writing/tasks/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function exportWritingTask(
  id: string,
  format: "md" | "docx" | "pdf",
  markdown?: string,
) {
  const res = await fetch(`${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, markdown }),
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) {
    let detail = `导出失败 (${res.status})`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j.detail) detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="?([^"]+)"?/i.exec(cd);
  const filename = m?.[1] || `report.${format === "docx" ? "docx" : format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function deleteWritingTask(id: string) {
  return readJson<{ ok: boolean }>(`${apiRoot()}/writing/tasks/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export type WritingStreamHandlers = {
  onProgress?: (steps: AgentProgressStep[]) => void;
  onCard?: (cards: import("./types").KnowledgeCard[]) => void;
  onChapter?: (payload: { chapter?: unknown; preview_markdown?: string }) => void;
  onChapterDelta?: (payload: {
    chapter_id?: string;
    chapter_index?: number;
    heading?: string;
    delta?: string;
    body?: string;
    replace?: boolean;
    attempt?: number;
  }) => void;
  onScorecard?: (scorecard: import("./types").Scorecard) => void;
  onOutline?: (outline: Record<string, unknown>) => void;
};

export async function runWritingTaskStream(
  id: string,
  body: {
    confirmed?: boolean;
    confirmed_chapter?: boolean;
    resume_chapter_index?: number;
    outline?: Record<string, unknown>;
    scope_paths?: string[];
    report_type?: string;
    audience?: string;
    web_search_mode?: "off" | "auto" | "force";
    resume?: boolean;
  },
  onProgressOrHandlers: ((steps: AgentProgressStep[]) => void) | WritingStreamHandlers,
): Promise<WritingTask> {
  const handlers: WritingStreamHandlers =
    typeof onProgressOrHandlers === "function"
      ? { onProgress: onProgressOrHandlers }
      : onProgressOrHandlers;
  const res = await fetch(`${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const detail = await res.text();
    throw new ApiError(detail || `请求失败 (${res.status})`, res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
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
        message?: string;
        result?: ReportRunResponse;
        cards?: import("./types").KnowledgeCard[];
        chapter?: unknown;
        chapter_id?: string;
        chapter_index?: number;
        heading?: string;
        delta?: string;
        body?: string;
        replace?: boolean;
        attempt?: number;
        preview_markdown?: string;
        scorecard?: import("./types").Scorecard;
        outline?: Record<string, unknown>;
      };
      if (payload.type === "progress" && payload.agent_progress) {
        handlers.onProgress?.(payload.agent_progress);
      }
      if (payload.type === "outline" && payload.outline) {
        handlers.onOutline?.(payload.outline);
      }
      if (payload.type === "card" && payload.cards) handlers.onCard?.(payload.cards);
      if (payload.type === "chapter") {
        handlers.onChapter?.({
          chapter: payload.chapter,
          preview_markdown: payload.preview_markdown,
        });
      }
      if (payload.type === "chapter_delta") {
        handlers.onChapterDelta?.({
          chapter_id: payload.chapter_id,
          chapter_index: payload.chapter_index,
          heading: payload.heading,
          delta: payload.delta,
          body: payload.body,
          replace: payload.replace,
          attempt: payload.attempt,
        });
      }
      if (payload.type === "scorecard" && payload.scorecard) {
        handlers.onScorecard?.(payload.scorecard);
      }
      if (payload.type === "error") throw new ApiError(payload.message || "失败");
    }
  }
  return getWritingTask(id);
}

export async function pauseWritingTask(id: string) {
  return readJson<{ ok: boolean; action: string; message?: string }>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/pause`,
    { method: "POST" },
  );
}

export async function cancelWritingTask(id: string) {
  return readJson<{ ok: boolean; action: string; message?: string }>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/cancel`,
    { method: "POST" },
  );
}

export async function confirmWritingOutline(
  id: string,
  outline?: Record<string, unknown> | null,
  webSearchMode?: "off" | "auto" | "force",
) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/confirm-outline`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed: true,
        outline: outline || undefined,
        web_search_mode: webSearchMode,
      }),
    },
  );
}

export async function confirmWritingChapter(
  id: string,
  body?: {
    resume_chapter_index?: number;
    outline?: Record<string, unknown>;
    web_search_mode?: "off" | "auto" | "force";
  },
) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(id)}/confirm-chapter`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed: true,
        confirmed_chapter: true,
        resume_chapter_index: body?.resume_chapter_index,
        outline: body?.outline,
        web_search_mode: body?.web_search_mode,
      }),
    },
  );
}

export async function createArtifact(body: {
  kind: string;
  title: string;
  content: Record<string, unknown>;
  evidence_ids?: string[];
}) {
  return readJson<Artifact>(`${apiRoot()}/artifacts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function insertArtifactToTask(taskId: string, artifactId: string) {
  return readJson<WritingTask>(
    `${apiRoot()}/writing/tasks/${encodeURIComponent(taskId)}/insert-artifact`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artifact_id: artifactId }),
    },
  );
}

export async function listMetrics() {
  return readJson<{ metrics: Metric[] }>(`${apiRoot()}/metrics`);
}

export async function seedMetrics() {
  return readJson<{ ok: boolean; created: number; metrics: Metric[] }>(`${apiRoot()}/metrics/seed`, {
    method: "POST",
  });
}

export async function createMetric(body: Partial<Metric> & { name: string }) {
  return readJson<Metric>(`${apiRoot()}/metrics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateMetric(id: string, body: Partial<Metric> & { name: string }) {
  return readJson<Metric>(`${apiRoot()}/metrics/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteMetric(id: string) {
  return readJson<{ ok: boolean }>(`${apiRoot()}/metrics/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function fetchVaultHealth() {
  return readJson<Record<string, unknown>>(`${apiRoot()}/vault/health`);
}

export async function importVaultBatch(
  files: File[],
  onUploadProgress?: (percentage: number) => void,
) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (!onUploadProgress) {
    return readJson<VaultImportJob>(`${apiRoot()}/vault/import/batch`, {
      method: "POST",
      body: form,
    });
  }
  return new Promise<VaultImportJob>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${apiRoot()}/vault/import/batch`);
    request.timeout = 120_000;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onUploadProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onerror = () => reject(new ApiError("上传失败：网络连接异常", 0));
    request.ontimeout = () => reject(new ApiError("上传超时，请检查文件大小后重试", 408));
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        reject(
          new ApiError(
            errorDetail(request.responseText) || `上传失败 (${request.status})`,
            request.status,
          ),
        );
        return;
      }
      try {
        resolve(JSON.parse(request.responseText) as VaultImportJob);
      } catch {
        reject(new ApiError("上传响应格式错误", request.status));
      }
    };
    request.send(form);
  });
}

export async function fetchImportJob(id: string) {
  return readJson<VaultImportJob>(
    `${apiRoot()}/vault/import/jobs/${encodeURIComponent(id)}`,
  );
}

export async function listImportJobs(limit = 20) {
  return readJson<{ jobs: VaultImportJob[] }>(
    `${apiRoot()}/vault/import/jobs?limit=${encodeURIComponent(limit)}`,
  );
}

const EVAL_POLL_TIMEOUT_MS = 15_000;

export async function listEvalSuites() {
  return readJson<{ suites: EvalSuite[] }>(`${apiRoot()}/evaluation/suites`);
}

export async function createEvalSuite(name: string, description = "") {
  return readJson<EvalSuite>(`${apiRoot()}/evaluation/suites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
}

export async function seedEvalSuites(recreate = false) {
  return readJson<{
    ok: boolean;
    suite_ids: string[];
    suites: Array<EvalSuite | null>;
  }>(`${apiRoot()}/evaluation/suites/seed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recreate }),
  });
}

export async function getEvalSuite(id: string) {
  return readJson<EvalSuite>(`${apiRoot()}/evaluation/suites/${encodeURIComponent(id)}`);
}

export async function exportEvalSuite(id: string) {
  return readJson<{
    version: number;
    name: string;
    description?: string;
    kind?: string | null;
    cases: Array<Partial<EvalCase> & { question: string }>;
  }>(`${apiRoot()}/evaluation/suites/${encodeURIComponent(id)}/export`);
}

export async function importEvalSuite(payload: {
  name: string;
  description?: string;
  kind?: string | null;
  cases: Array<Partial<EvalCase> & { question: string }>;
}) {
  return readJson<EvalSuite>(`${apiRoot()}/evaluation/suites/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version: 1, ...payload }),
  });
}

export async function deleteEvalSuite(id: string) {
  return readJson<{ ok: boolean }>(`${apiRoot()}/evaluation/suites/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function addEvalCase(suiteId: string, body: Partial<EvalCase> & { question: string }) {
  return readJson<EvalCase>(
    `${apiRoot()}/evaluation/suites/${encodeURIComponent(suiteId)}/cases`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function updateEvalCase(caseId: string, body: Partial<EvalCase>) {
  return readJson<EvalCase>(`${apiRoot()}/evaluation/cases/${encodeURIComponent(caseId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function duplicateEvalCase(caseId: string) {
  return readJson<EvalCase>(
    `${apiRoot()}/evaluation/cases/${encodeURIComponent(caseId)}/duplicate`,
    { method: "POST" },
  );
}

export async function validateEvalSuite(suiteId: string) {
  return readJson<{
    suite_id: string;
    case_count: number;
    ready: boolean;
    errors: number;
    warnings: number;
    issues: Array<{ case_id: string; level: "error" | "warning"; message: string }>;
  }>(`${apiRoot()}/evaluation/suites/${encodeURIComponent(suiteId)}/validate`);
}

export async function deleteEvalCase(caseId: string) {
  return readJson<{ ok: boolean }>(
    `${apiRoot()}/evaluation/cases/${encodeURIComponent(caseId)}`,
    { method: "DELETE" },
  );
}

export type EvalRunOptions = {
  webSearchEnabled?: boolean;
  modelOverride?: string | null;
  skillOverrides?: Record<string, string>;
  compareBaseRunId?: string | null;
  caseIds?: string[];
  concurrency?: number;
  lightTimeoutSeconds?: number;
  reportTimeoutSeconds?: number;
  judgeEnabled?: boolean;
  judgeModelOverride?: string | null;
};

export async function startEvalRun(suiteId: string, opts: EvalRunOptions = {}) {
  return readJson<EvalRun>(`${apiRoot()}/evaluation/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      suite_id: suiteId,
      web_search_enabled: opts.webSearchEnabled ?? false,
      model_override: opts.modelOverride || null,
      skill_overrides: opts.skillOverrides || {},
      compare_base_run_id: opts.compareBaseRunId || null,
      case_ids: opts.caseIds || [],
      concurrency: opts.concurrency ?? 3,
      light_timeout_seconds: opts.lightTimeoutSeconds ?? 180,
      report_timeout_seconds: opts.reportTimeoutSeconds ?? 900,
      judge_enabled: opts.judgeEnabled ?? false,
      judge_model_override: opts.judgeModelOverride || null,
      wait: false,
    }),
  });
}

/** @deprecated use startEvalRun + pollEvalRun */
export async function runEvalSuite(suiteId: string, webSearchEnabled = false) {
  return startEvalRun(suiteId, { webSearchEnabled });
}

export async function getEvalRun(runId: string) {
  return readJson<EvalRun>(`${apiRoot()}/evaluation/runs/${encodeURIComponent(runId)}`, {
    signal: AbortSignal.timeout(EVAL_POLL_TIMEOUT_MS),
  });
}

export async function pollEvalRun(
  runId: string,
  onTick?: (run: EvalRun) => void,
  maxMs = 600_000,
): Promise<EvalRun> {
  const started = Date.now();
  while (Date.now() - started < maxMs) {
    const run = await getEvalRun(runId);
    onTick?.(run);
    if (
      run.status === "completed" ||
      run.status === "failed" ||
      run.status === "empty" ||
      run.status === "cancelled"
    ) {
      return run;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error("跑批超时，请稍后在结果列表中查看");
}

export async function listEvalRuns(suiteId?: string) {
  const q = suiteId ? `?suite_id=${encodeURIComponent(suiteId)}` : "";
  return readJson<{ runs: EvalRun[] }>(`${apiRoot()}/evaluation/runs${q}`);
}

export async function fetchEvalOverview(suiteId?: string) {
  const q = suiteId ? `?suite_id=${encodeURIComponent(suiteId)}` : "";
  return readJson<{
    latest?: EvalRun | null;
    trend: Array<{
      id: string;
      created_at: number;
      status: string;
      pass_rate?: number | null;
      avg_score?: number | null;
      avg_latency_ms?: number | null;
      prompt_tokens?: number;
      completion_tokens?: number;
    }>;
    failure_stages: Record<string, number>;
    running: number;
    completed_count: number;
  }>(`${apiRoot()}/evaluation/overview${q}`);
}

export async function cancelEvalRun(runId: string) {
  return readJson<EvalRun>(
    `${apiRoot()}/evaluation/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
}

export async function retryFailedEvalRun(runId: string) {
  return readJson<EvalRun>(
    `${apiRoot()}/evaluation/runs/${encodeURIComponent(runId)}/retry-failed`,
    { method: "POST" },
  );
}

export async function compareEvalRuns(runId: string, baseRunId: string) {
  return readJson<Record<string, unknown>>(
    `${apiRoot()}/evaluation/runs/${encodeURIComponent(runId)}/compare/${encodeURIComponent(baseRunId)}`,
  );
}

/** 探测可选能力接口是否存在（无假数据） */
export async function probeCapability(path: string): Promise<"ok" | "not_ready" | "network"> {
  try {
    const res = await fetch(`${apiRoot()}${path}`, {
      method: "GET",
      signal: AbortSignal.timeout(8000),
    });
    if (res.status === 404 || res.status === 501) return "not_ready";
    if (res.ok || res.status === 405 || res.status === 422) return "ok";
    return "not_ready";
  } catch {
    return "network";
  }
}
