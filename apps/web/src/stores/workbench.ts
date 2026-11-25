import { defineStore } from "pinia";
import { ref } from "vue";
import {
  confirmLightAskFilter,
  createArtifact,
  createChatSession,
  deleteChatSession,
  getChatSession,
  lightAskStream,
  listChatSessions,
  uploadWorkbenchImage,
} from "@/api/realai";
import type {
  ChartSpec,
  DataTable,
  EntityProfile,
  EvidencePack,
  FilterDraft,
  SkillRuntimeUse,
  WorkbenchIntent,
} from "@/api/types";
import { useConfigStore } from "./config";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  conclusion?: string;
  tables?: DataTable[];
  chartSpec?: ChartSpec | null;
  entityProfile?: EntityProfile | null;
  evidence?: EvidencePack;
  trajectory?: string[];
  /** True while light-ask SSE is in progress for this placeholder bubble. */
  pending?: boolean;
  awaitingConfirm?: boolean;
  confirmKind?: string;
  filterDraft?: FilterDraft | null;
  filterStatus?: "pending" | "confirmed" | "cancelled";
  serverMessageId?: string;
  /** Original user query for confirm round-trip */
  sourceQuery?: string;
  /** Attached image vault paths for this user turn */
  imagePaths?: string[];
  skillUsed?: SkillRuntimeUse | null;
  sourceSkillId?: string | null;
  createdAt: number;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  updated_at: number;
}

export const useWorkbenchStore = defineStore("workbench", () => {
  const messages = ref<ChatMessage[]>([]);
  const asking = ref(false);
  const error = ref("");
  const evidenceOpen = ref(true);
  const lastEvidence = ref<EvidencePack | null>(null);
  const lastTrajectory = ref<string[]>([]);
  const draft = ref("");
  const intent = ref<WorkbenchIntent>("ask");
  const selectedSkillId = ref<string | null>(null);
  const scopePaths = ref<string[]>([
    "wiki",
    "raw",
    "pipelines",
    "new_energy",
    "dataqa",
    "entities",
    "05_Metrics",
  ]);
  const processHint = ref("");

  const sessions = ref<ChatSessionSummary[]>([]);
  const sessionId = ref<string | null>(null);
  /** Pending workbench image uploads (vault-relative paths), cleared after send. */
  const pendingImages = ref<{ path: string; name: string }[]>([]);
  const uploadingImage = ref(false);

  function clearChat() {
    messages.value = [];
    lastEvidence.value = null;
    lastTrajectory.value = [];
    error.value = "";
    processHint.value = "";
    pendingImages.value = [];
  }

  function removePendingImage(path: string) {
    pendingImages.value = pendingImages.value.filter((p) => p.path !== path);
  }

  async function attachImage(file: File) {
    uploadingImage.value = true;
    error.value = "";
    try {
      const sid = await ensureSession();
      const res = await uploadWorkbenchImage(file, sid);
      if (res.path) {
        pendingImages.value = [
          ...pendingImages.value.filter((p) => p.path !== res.path),
          { path: res.path, name: file.name },
        ].slice(-2);
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      uploadingImage.value = false;
    }
  }

  function newAskFocus() {
    draft.value = "";
    intent.value = "ask";
  }

  function setIntent(next: WorkbenchIntent) {
    intent.value = next;
  }

  function useSuggestion(text: string) {
    draft.value = text;
  }

  async function loadSessions() {
    try {
      const res = await listChatSessions(100);
      sessions.value = res.sessions.map((s) => ({
        id: s.id,
        title: s.title,
        updated_at: s.updated_at,
      }));
    } catch {
      sessions.value = [];
    }
  }

  async function ensureSession() {
    if (sessionId.value) return sessionId.value;
    const s = await createChatSession("新对话", intent.value);
    sessionId.value = s.id;
    await loadSessions();
    return s.id;
  }

  async function newSession() {
    const s = await createChatSession("新对话", intent.value);
    sessionId.value = s.id;
    clearChat();
    await loadSessions();
  }

  async function openSession(id: string) {
    const s = await getChatSession(id);
    sessionId.value = s.id;
    const mapped = (s.messages || []).map((m) => {
      const c = m.content || {};
      const text = String(c.text || c.answer || c.query || "");
      return {
        id: m.id,
        role: (m.role === "assistant" || m.role === "user" ? m.role : "system") as ChatMessage["role"],
        content: text,
        conclusion: c.conclusion as string | undefined,
        tables: c.tables as DataTable[] | undefined,
        chartSpec: (c.chart_spec as ChartSpec | null) ?? null,
        entityProfile: (c.entity_profile as EntityProfile | null) ?? null,
        evidence: c.evidence as EvidencePack | undefined,
        trajectory: c.trajectory as string[] | undefined,
        awaitingConfirm: !!c.awaiting_confirm,
        confirmKind: c.confirm_kind as string | undefined,
        filterDraft: (c.filter_draft as FilterDraft | null) ?? null,
        filterStatus: c.awaiting_confirm
          ? "pending"
          : c.filter_status === "confirmed"
            ? "confirmed"
            : c.filter_draft
              ? "confirmed"
              : undefined,
        serverMessageId: m.id,
        skillUsed: (c.skill_used as SkillRuntimeUse | null) ?? null,
        sourceSkillId:
          String((c.skill_used as SkillRuntimeUse | undefined)?.id || "") || null,
        createdAt: Math.round((m.created_at || 0) * 1000),
      } as ChatMessage;
    });
    // Attach sourceQuery for awaiting filter confirms from prior user message
    for (let i = 0; i < mapped.length; i += 1) {
      if (mapped[i].role === "assistant" && mapped[i].filterStatus === "pending") {
        for (let j = i - 1; j >= 0; j -= 1) {
          if (mapped[j].role === "user" && mapped[j].content?.trim()) {
            mapped[i].sourceQuery = mapped[j].content.trim();
            break;
          }
        }
      }
    }
    messages.value = mapped;
    const last = [...messages.value].reverse().find((m) => m.role === "assistant");
    lastEvidence.value = last?.evidence || null;
    lastTrajectory.value = last?.trajectory || [];
  }

  async function removeSession(id: string) {
    await deleteChatSession(id);
    if (sessionId.value === id) {
      sessionId.value = null;
      clearChat();
    }
    await loadSessions();
  }

  async function ask(query?: string) {
    const q = (query ?? draft.value).trim();
    if (!q || asking.value) return;

    const config = useConfigStore();
    asking.value = true;
    error.value = "";
    processHint.value = "处理中";
    const now = Date.now();
    const imagesForTurn = pendingImages.value.map((p) => p.path);
    const skillIdForTurn = selectedSkillId.value;
    messages.value.push({
      id: `u-${now}`,
      role: "user",
      content: q,
      imagePaths: imagesForTurn.length ? [...imagesForTurn] : undefined,
      createdAt: now,
    });
    const assistantId = `a-${now}`;
    messages.value.push({
      id: assistantId,
      role: "assistant",
      content: "",
      trajectory: [],
      pending: true,
      sourceSkillId: skillIdForTurn,
      createdAt: now,
    });
    draft.value = "";
    pendingImages.value = [];

    const patchAssistant = (patch: Partial<ChatMessage>) => {
      const idx = messages.value.findIndex((m) => m.id === assistantId);
      if (idx < 0) return;
      messages.value[idx] = { ...messages.value[idx], ...patch };
    };

    /** 前端节奏：后端步骤可能瞬间到齐，这里按约 50ms 逐步露出 */
    const STEP_GAP_MS = 50;
    let latestTrajectory: string[] = [];
    let queuedLen = 0;
    let revealChain: Promise<void> = Promise.resolve();

    const enqueueTrajectoryReveal = (traj: string[]) => {
      latestTrajectory = traj;
      while (queuedLen < traj.length) {
        queuedLen += 1;
        const revealUpTo = queuedLen;
        revealChain = revealChain.then(
          () =>
            new Promise<void>((resolve) => {
              window.setTimeout(() => {
                const shown = latestTrajectory.slice(0, revealUpTo);
                lastTrajectory.value = shown;
                patchAssistant({ trajectory: [...shown] });
                resolve();
              }, STEP_GAP_MS);
            }),
        );
      }
    };

    try {
      const sid = await ensureSession();
      const res = await lightAskStream(
        q,
        config.webSearchMode,
        intent.value,
        scopePaths.value,
        sid,
        (trajectory) => {
          enqueueTrajectoryReveal(trajectory);
        },
        config.visionMode,
        imagesForTurn,
        skillIdForTurn,
      );
      if (res.trajectory?.length) {
        enqueueTrajectoryReveal(res.trajectory);
      }
      await revealChain;
      if (res.session_id) sessionId.value = res.session_id;
      lastEvidence.value = res.evidence;
      lastTrajectory.value = res.trajectory || latestTrajectory;
      evidenceOpen.value = true;
      processHint.value = "";
      const awaiting = !!res.awaiting_confirm;
      patchAssistant({
        content: res.answer,
        conclusion: res.conclusion,
        tables: res.tables,
        chartSpec: res.chart_spec,
        entityProfile: res.entity_profile ?? null,
        evidence: res.evidence,
        trajectory: res.trajectory || latestTrajectory,
        pending: false,
        awaitingConfirm: awaiting,
        confirmKind: res.confirm_kind,
        filterDraft: res.filter_draft ?? null,
        filterStatus: awaiting ? "pending" : undefined,
        serverMessageId: res.message_id,
        sourceQuery: q,
        skillUsed: res.skill_used ?? null,
        sourceSkillId: res.skill_used?.id || skillIdForTurn,
      });
      await loadSessions();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      processHint.value = "";
      patchAssistant({
        content: error.value,
        pending: false,
      });
      messages.value.push({
        id: `s-${Date.now()}`,
        role: "system",
        content: error.value,
        createdAt: Date.now(),
      });
    } finally {
      asking.value = false;
    }
  }

  function toggleEvidence() {
    evidenceOpen.value = !evidenceOpen.value;
  }

  function showEvidence(pack?: EvidencePack | null, trajectory?: string[]) {
    if (pack) lastEvidence.value = pack;
    if (trajectory) lastTrajectory.value = trajectory;
    evidenceOpen.value = true;
  }

  async function saveLastAsArtifact() {
    const last = [...messages.value].reverse().find((m) => m.role === "assistant");
    if (!last) return null;
    return createArtifact({
      kind: "conclusion",
      title: (last.conclusion || last.content).slice(0, 80),
      content: {
        answer: last.content,
        conclusion: last.conclusion,
        tables: last.tables,
        chart_spec: last.chartSpec,
      },
      evidence_ids: (last.evidence?.items || []).map((i) => i.id),
    });
  }

  function resolveSourceQuery(assistantIdx: number, msg: ChatMessage): string {
    if (msg.sourceQuery?.trim()) return msg.sourceQuery.trim();
    // Fallback: nearest previous user bubble (session reload / missing sourceQuery)
    for (let i = assistantIdx - 1; i >= 0; i -= 1) {
      const prev = messages.value[i];
      if (prev.role === "user" && prev.content?.trim()) return prev.content.trim();
    }
    return "";
  }

  async function confirmFilter(messageId: string, draft: FilterDraft) {
    const idx = messages.value.findIndex((m) => m.id === messageId);
    if (idx < 0) return;
    const msg = messages.value[idx];
    const q = resolveSourceQuery(idx, msg);
    if (!q) {
      error.value = "找不到对应的提问内容，请重新提问后再确认筛选。";
      messages.value[idx] = {
        ...msg,
        content: error.value,
      };
      return;
    }
    const config = useConfigStore();
    asking.value = true;
    error.value = "";
    const baseTraj = [...(msg.trajectory || [])].filter(
      (t) => t !== "等待确认筛选条件",
    );
    if (!baseTraj.includes("已确认筛选条件")) {
      baseTraj.push("已确认筛选条件");
    }
    messages.value[idx] = {
      ...msg,
      sourceQuery: q,
      filterStatus: "pending",
      trajectory: [...baseTraj],
      awaitingConfirm: true,
    };
    lastTrajectory.value = baseTraj;
    try {
      const res = await confirmLightAskFilter({
        query: q,
        filter: draft,
        webSearchMode: config.webSearchMode,
        intent: intent.value as WorkbenchIntent,
        scopePaths: scopePaths.value,
        sessionId: sessionId.value,
        messageId: msg.serverMessageId,
        skillId: msg.sourceSkillId || msg.skillUsed?.id || null,
      });
      const mergedTraj = [
        ...baseTraj,
        ...(res.trajectory || []).filter((t) => t !== "已确认筛选条件"),
      ];
      messages.value[idx] = {
        ...messages.value[idx],
        content: res.answer,
        conclusion: res.conclusion,
        tables: res.tables,
        chartSpec: res.chart_spec,
        evidence: res.evidence,
        trajectory: mergedTraj,
        filterDraft: res.filter_draft ?? draft,
        filterStatus: "confirmed",
        awaitingConfirm: false,
        pending: false,
        sourceQuery: q,
        skillUsed: res.skill_used ?? msg.skillUsed ?? null,
        sourceSkillId: res.skill_used?.id || msg.sourceSkillId || null,
      };
      lastEvidence.value = res.evidence;
      lastTrajectory.value = mergedTraj;
      evidenceOpen.value = true;
      if (res.session_id) sessionId.value = res.session_id;
      await loadSessions();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      messages.value[idx] = {
        ...messages.value[idx],
        content: error.value,
        filterStatus: "pending",
      };
    } finally {
      asking.value = false;
    }
  }

  function cancelFilter(messageId: string) {
    const idx = messages.value.findIndex((m) => m.id === messageId);
    if (idx < 0) return;
    const msg = messages.value[idx];
    const traj = [...(msg.trajectory || [])];
    if (!traj.includes("用户取消条件确认")) traj.push("用户取消条件确认");
    messages.value[idx] = {
      ...msg,
      filterStatus: "cancelled",
      awaitingConfirm: false,
      content: "已取消本次条件筛选。",
      trajectory: traj,
    };
    lastTrajectory.value = traj;
  }

  return {
    messages,
    asking,
    error,
    evidenceOpen,
    lastEvidence,
    lastTrajectory,
    draft,
    intent,
    selectedSkillId,
    scopePaths,
    processHint,
    sessions,
    sessionId,
    pendingImages,
    uploadingImage,
    clearChat,
    newAskFocus,
    setIntent,
    useSuggestion,
    loadSessions,
    newSession,
    openSession,
    removeSession,
    ask,
    attachImage,
    removePendingImage,
    confirmFilter,
    cancelFilter,
    toggleEvidence,
    showEvidence,
    saveLastAsArtifact,
  };
});
