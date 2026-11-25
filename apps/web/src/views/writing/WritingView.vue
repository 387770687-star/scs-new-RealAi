<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NProgress,
  NTag,
  useMessage,
} from "naive-ui";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import KnowledgeCardsPanel from "@/components/KnowledgeCardsPanel.vue";
import ChapterPreviewCards from "@/components/ChapterPreviewCards.vue";
import ContinuousDocumentPreview from "@/components/ContinuousDocumentPreview.vue";
import StatusDot from "@/components/StatusDot.vue";
import WebSearchModeSelect from "@/components/WebSearchModeSelect.vue";
import { useWritingStore } from "@/stores/writing";
import { useHealthStore } from "@/stores/health";
import { exportWritingTask, fetchSkills, listWritingReportTypes } from "@/api/realai";
import type { AgentProgressStep, StepTraceItem, WritingTask } from "@/api/types";
import type { ChapterCard } from "@/utils/chapters";
import { countChineseChars } from "@/utils/chapters";
import { KNOWLEDGE_TYPE_DEFINITIONS } from "@/utils/knowledgeTypes";
import { formatStrategicMainLine } from "@/utils/llmText";

const writing = useWritingStore();
const health = useHealthStore();
const message = useMessage();
let backgroundSyncTimer: ReturnType<typeof setInterval> | null = null;
let backgroundSyncBusy = false;

function stopBackgroundSync() {
  if (backgroundSyncTimer) {
    clearInterval(backgroundSyncTimer);
    backgroundSyncTimer = null;
  }
}

watch(
  () => [writing.current?.id, writing.current?.status, writing.running] as const,
  ([id, status, locallyRunning]) => {
    stopBackgroundSync();
    if (!id || status !== "running" || locallyRunning) return;
    backgroundSyncTimer = setInterval(async () => {
      if (backgroundSyncBusy) return;
      backgroundSyncBusy = true;
      try {
        const updated = await writing.syncCurrent();
        if (!updated || updated.status !== "running") stopBackgroundSync();
      } catch {
        // 后端短暂忙碌时保持现有页面，下一轮继续同步。
      } finally {
        backgroundSyncBusy = false;
      }
    }, 1500);
  },
  { immediate: true },
);

onUnmounted(stopBackgroundSync);

const goal = ref("");
const audience = ref("");
const stepConfirm = ref(false);
const reportType = ref<string | null>(null);
const skillProfileId = ref<string | null>(null);
const scopeOptions = KNOWLEDGE_TYPE_DEFINITIONS.map((definition) => ({
  ...definition,
  value: `type:${definition.key}`,
}));
const allScopeValues = scopeOptions.map((option) => option.value);
const scopePaths = ref<string[]>([...allScopeValues]);
const reportTypeOptions = ref<Array<{ label: string; value: string }>>([]);
const skillProfileOptions = ref<Array<{ label: string; value: string }>>([]);
const exportOptions = [
  { label: "导出 Word", key: "docx" },
  { label: "导出 PDF", key: "pdf" },
  { label: "导出 Markdown", key: "md" },
];
const editingPreview = ref(false);
const editMarkdown = ref("");
const savingPreview = ref(false);
const exporting = ref(false);
const showOutlineRaw = ref(false);
const outlineRawText = ref("");
const previewFontScale = ref(100);
const progressExpanded = ref(false);
const outlineCollapsed = ref(false);
const sourcesCollapsed = ref(false);
const workspaceTaskDrawer = ref(false);
const activeChapterId = ref("");
const continuousPreview = ref<InstanceType<typeof ContinuousDocumentPreview> | null>(null);

type OutlineSectionForm = {
  id: string;
  heading: string;
  purpose: string;
  word_budget: number | null;
};

type OutlineForm = {
  title: string;
  report_type: string;
  report_type_label: string;
  min_chars: number | null;
  strategic_main_line: string;
  sections: OutlineSectionForm[];
  /** 保留后端其它字段（如 pipeline_agents） */
  extras: Record<string, unknown>;
};

const emptyOutlineForm = (): OutlineForm => ({
  title: "",
  report_type: "",
  report_type_label: "",
  min_chars: null,
  strategic_main_line: "",
  sections: [],
  extras: {},
});

const outlineForm = ref<OutlineForm>(emptyOutlineForm());
const outlineEditable = computed(() => {
  const s = writing.current?.status || "";
  return ["draft", "outline", "await_confirm", "failed"].includes(s) || !writing.current?.result;
});

const currentMarkdown = computed(
  () => writing.assembledPreview || writing.livePreview || writing.current?.result?.preview_markdown || "",
);

const reportBodyCharCount = computed(() =>
  writing.liveChapters.reduce(
    (total, chapter) => total + (chapter.chinese_chars || countChineseChars(chapter.body || "")),
    0,
  ),
);

const allKnowledgeScopesSelected = computed(
  () => scopePaths.value.length === allScopeValues.length,
);

function toggleKnowledgeScope(value: string) {
  if (scopePaths.value.includes(value) && scopePaths.value.length === 1) {
    message.warning("请至少保留一种知识类型");
    return;
  }
  scopePaths.value = scopePaths.value.includes(value)
    ? scopePaths.value.filter((item) => item !== value)
    : [...scopePaths.value, value];
}

function toggleAllKnowledgeScopes() {
  scopePaths.value = [...allScopeValues];
}

watch(
  () => writing.current?.id,
  () => {
    editingPreview.value = false;
    editMarkdown.value = "";
    progressExpanded.value = false;
    activeChapterId.value = writing.liveChapters[0]?.id || "";
  },
);

const statusOptions = [
  { label: "全部", value: "all" },
  { label: "草稿", value: "draft" },
  { label: "待智能补缺", value: "await_intake" },
  { label: "大纲", value: "outline" },
  { label: "写作中", value: "writing" },
  { label: "运行中", value: "running" },
  { label: "已暂停", value: "paused" },
  { label: "已终止", value: "cancelled" },
  { label: "完成", value: "completed" },
  { label: "待确认大纲", value: "await_confirm" },
  { label: "待确认章节", value: "await_chapter" },
  { label: "失败", value: "failed" },
];

const LEGACY_STEP_IDS = new Set([
  "lead",
  "retrieve",
  "data",
  "vision",
  "evidence_audit",
  "arch",
  "review",
]);

const NEW_STEP_SKILL_KEYS: Record<string, string> = {
  intake: "intake",
  researcher: "researcher",
  architect: "architect",
  writer: "writer",
  citer: "citer",
  reviewer: "review",
  optimizer: "optimizer",
};

const PIPELINE_STEP_DEFINITIONS = [
  { id: "intake", label: "智能补缺" },
  { id: "researcher", label: "战略研究" },
  { id: "architect", label: "报告架构" },
  { id: "writer", label: "逐章写作" },
  { id: "citer", label: "引用审核" },
  { id: "reviewer", label: "质量评审" },
  { id: "optimizer", label: "迭代优化" },
] as const;

const isLegacyProgress = computed(() => {
  const steps = writing.current?.progress || [];
  if (!steps.length) return false;
  return steps.some(
    (s) =>
      LEGACY_STEP_IDS.has(s.id) ||
      s.label === "战略主 Agent" ||
      s.label === "知识检索" ||
      s.label === "管网评审",
  );
});

const agentSteps = computed<AgentProgressStep[]>(() => {
  const rawSteps = writing.current?.progress || [];
  const skills = writing.current?.result?.skills || {};
  const enrichSkill = (s: AgentProgressStep): AgentProgressStep => {
    if (s.skill_id) return s;
    const key = NEW_STEP_SKILL_KEYS[s.id];
    if (!key) return s;
    const sid = skills[key];
    if (typeof sid !== "string" || !sid) return s;
    return {
      ...s,
      skill_id: sid,
      skill_name: sid,
      skill_valid: skills[`${key}_valid`] !== false,
    };
  };
  if (isLegacyProgress.value) return rawSteps.map(enrichSkill);

  const byId = new Map(rawSteps.map((step) => [step.id, step]));
  const steps = PIPELINE_STEP_DEFINITIONS.map(({ id, label }) =>
    enrichSkill(
      byId.get(id) || {
        id,
        label,
        status: "pending",
        message: "",
      },
    ),
  );

  // Between the synchronous “start run” response and the first backend
  // progress event, old UI treated the single completed intake row as 1/1
  // and displayed 99%. Show the real seven-stage pipeline and optimistically
  // advance to the next pending stage while the worker is starting.
  const active = writing.running || writing.current?.status === "running";
  if (active && !steps.some((step) => step.status === "running")) {
    const nextIndex = steps.findIndex((step) => step.status === "pending");
    if (nextIndex >= 0) {
      steps[nextIndex] = {
        ...steps[nextIndex],
        status: "running",
        message:
          steps[nextIndex].id === "researcher"
            ? "正在启动资料研究并核验可用来源"
            : "正在进入下一阶段",
      };
    }
  }
  return steps;
});

function stepSkillLine(s: AgentProgressStep): string {
  if (!s.skill_id && !s.skill_name) return "";
  const name = s.skill_name || s.skill_id || "";
  const id = s.skill_id && s.skill_id !== name ? `（${s.skill_id}）` : "";
  const bad = s.skill_valid === false ? " · 无效" : "";
  return `Skill：${name}${id}${bad}`;
}

function stepToolLine(s: AgentProgressStep): string {
  return s.tools?.length ? `工具：${s.tools.join("、")}` : "";
}

function stepRefLine(s: AgentProgressStep): string {
  if (!s.references?.length) return "";
  const names = s.references.map((p) => p.split("/").pop() || p);
  return `参考：${names.join("、")}`;
}

function stepScriptLine(s: AgentProgressStep): string {
  if (s.scripts?.length) {
    const names = s.scripts.map((p) => p.split("/").pop() || p);
    return `脚本文件：${names.join("、")}（随包列出，默认不执行）`;
  }
  if (s.skill_id) return "脚本：无";
  return "";
}

function stepDetailLines(s: AgentProgressStep): string[] {
  return [stepSkillLine(s), stepToolLine(s), stepRefLine(s), stepScriptLine(s)].filter(Boolean);
}

function displayStepMessage(s: AgentProgressStep): string {
  const msg = (s.message || "").trim();
  if (!msg) return "";
  // 下方已展示 Skill 明细时，隐藏重复的「Skill：xxx」进度文案
  if (s.skill_id && /^Skill[:：]/.test(msg)) return "";
  if (s.skill_id && /^加载\s*Skill[:：]/.test(msg)) return "";
  return msg;
}

const traceModalOpen = ref(false);
const traceStepId = ref<string | null>(null);
/** Expanded keys: `${index}:${field}` */
const expandedTrace = ref<Record<string, boolean>>({});

/** Live-bound step from current progress (refreshes while modal is open). */
const traceStep = computed(() => {
  if (!traceStepId.value) return null;
  return agentSteps.value.find((s) => s.id === traceStepId.value) || null;
});

function openStepTrace(s: AgentProgressStep) {
  traceStepId.value = s.id;
  expandedTrace.value = {};
  traceModalOpen.value = true;
}

function closeStepTrace() {
  traceModalOpen.value = false;
}

function hasStepTrace(s: AgentProgressStep | null): boolean {
  return Boolean(s?.trace && s.trace.length > 0);
}

function isStepRunning(s: AgentProgressStep | null): boolean {
  return s?.status === "running";
}

function previewText(text: string, max = 180): string {
  const t = (text || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

function isExpanded(idx: number, field: string): boolean {
  return Boolean(expandedTrace.value[`${idx}:${field}`]);
}

function toggleExpand(idx: number, field: string) {
  const key = `${idx}:${field}`;
  expandedTrace.value = { ...expandedTrace.value, [key]: !expandedTrace.value[key] };
}

function formatTraceTime(at?: number): string {
  if (!at) return "";
  try {
    return new Date(at * 1000).toLocaleTimeString();
  } catch {
    return "";
  }
}

function traceItemKindLabel(item: StepTraceItem): string {
  if (item.kind === "llm") return "模型对话";
  if (item.kind === "llm_pending") return "生成中";
  return "动作";
}

function stepTraceHint(s: AgentProgressStep): string {
  if (s.status === "running") {
    return hasStepTrace(s) ? "点击查看实时过程" : "点击查看实时过程";
  }
  return hasStepTrace(s) ? "点击查看过程" : "点击查看（可能无记录）";
}

onMounted(async () => {
  const savedScale = Number(window.localStorage.getItem("realai-writing-font-scale"));
  if (Number.isFinite(savedScale) && savedScale >= 80 && savedScale <= 160) {
    previewFontScale.value = savedScale;
  }
  if (window.innerWidth < 1300) sourcesCollapsed.value = true;
  if (window.innerWidth < 980) outlineCollapsed.value = true;
  await writing.refresh();
  // 从导航进入写作页时始终从新任务开始，历史草稿和运行任务由用户在列表中主动恢复。
  writing.beginCreate();
  try {
    const res = await listWritingReportTypes();
    reportTypeOptions.value = res.types.map((t) => ({
      label: t.label,
      value: t.id,
    }));
  } catch {
    reportTypeOptions.value = [
      { label: "区域油气基础设施规划", value: "regional" },
      { label: "集团总体战略规划", value: "group" },
      { label: "业务专项规划", value: "business" },
      { label: "新能源/战新产业规划", value: "emerging" },
      { label: "省级政府汇报备参", value: "gov_brief" },
    ];
  }
  try {
    const res = await fetchSkills(false);
    skillProfileOptions.value = res.skills
      .filter(
        (skill) =>
          skill.valid &&
          skill.enabled !== false &&
          skill.source !== "deerflow" &&
          !skill.read_only,
      )
      .map((skill) => ({
        label: `${skill.name} · ${skill.id}`,
        value: skill.id,
      }));
  } catch {
    skillProfileOptions.value = [];
  }
});

watch(previewFontScale, (value) => {
  window.localStorage.setItem("realai-writing-font-scale", String(value));
});

function parseOutline(o: Record<string, unknown> | null | undefined): OutlineForm {
  if (!o || !Object.keys(o).length) return emptyOutlineForm();
  const sectionsRaw = Array.isArray(o.sections) ? o.sections : [];
  const known = new Set([
    "title",
    "report_type",
    "report_type_label",
    "min_chars",
    "strategic_main_line",
    "sections",
    "chapter_drafts",
  ]);
  const extras: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (!known.has(k)) extras[k] = v;
  }
  if (o.chapter_drafts !== undefined) extras.chapter_drafts = o.chapter_drafts;
  return {
    title: String(o.title || ""),
    report_type: String(o.report_type || ""),
    report_type_label: String(o.report_type_label || ""),
    min_chars: typeof o.min_chars === "number" ? o.min_chars : null,
    strategic_main_line: formatStrategicMainLine(String(o.strategic_main_line || "")),
    sections: sectionsRaw.map((s, i) => {
      const row = (s && typeof s === "object" ? s : {}) as Record<string, unknown>;
      return {
        id: String(row.id || `sec-${i + 1}`),
        heading: String(row.heading || `第 ${i + 1} 章`),
        purpose: String(row.purpose || ""),
        word_budget:
          typeof row.word_budget === "number"
            ? row.word_budget
            : Number(row.word_budget) || null,
      };
    }),
    extras,
  };
}

function buildOutlinePayload(): Record<string, unknown> | undefined {
  const f = outlineForm.value;
  if (!f.sections.length && !f.title) return undefined;
  return {
    ...f.extras,
    title: f.title,
    report_type: f.report_type || undefined,
    report_type_label: f.report_type_label || undefined,
    min_chars: f.min_chars ?? undefined,
    strategic_main_line: f.strategic_main_line,
    sections: f.sections.map((s) => ({
      id: s.id,
      heading: s.heading.trim() || s.id,
      purpose: s.purpose.trim(),
      word_budget: s.word_budget ?? undefined,
    })),
  };
}

watch(
  () => writing.current?.outline,
  (o) => {
    outlineForm.value = parseOutline(o as Record<string, unknown> | undefined);
    const cleaned = o && typeof o === "object" ? { ...o } : o;
    // min_chars 是内部质量阈值，不属于用户大纲。
    if (cleaned && typeof cleaned === "object") {
      delete (cleaned as Record<string, unknown>).min_chars;
    }
    if (cleaned && typeof cleaned === "object" && "strategic_main_line" in cleaned) {
      (cleaned as Record<string, unknown>).strategic_main_line = formatStrategicMainLine(
        String((cleaned as Record<string, unknown>).strategic_main_line || ""),
      );
    }
    outlineRawText.value =
      cleaned && Object.keys(cleaned).length
        ? JSON.stringify(cleaned, null, 2)
        : "";
    showOutlineRaw.value = false;
  },
  { immediate: true, deep: true },
);

const creating = ref(false);
const confirmingIntake = ref(false);
const skippingIntake = ref(false);
/** local drafts so we don't PATCH on every keystroke */
const answerDrafts = ref<Record<string, string>>({});

const showCreateForm = computed(
  () => writing.creatingMode || (!writing.current && !writing.loading),
);

const showIntakePanel = computed(() => {
  const t = writing.current;
  if (!t) return false;
  if (t.status === "await_intake") return true;
  const st = t.intake?.status;
  return st === "await_answers" || st === "running" || st === "pending";
});

/** 创建完成后立即进入写作工作台，正文为空时也保持同一页面。 */
const previewWorkspace = computed(
  () =>
    Boolean(writing.current) &&
    !showCreateForm.value &&
    !showIntakePanel.value,
);

const completedStepCount = computed(
  () =>
    agentSteps.value.filter((step) => step.status === "completed" || step.status === "skipped")
      .length,
);

const currentAgentStep = computed(
  () =>
    agentSteps.value.find((step) => step.status === "running") ||
    [...agentSteps.value].reverse().find((step) => step.status === "completed") ||
    agentSteps.value[0] ||
    null,
);

type GenerationPhase = {
  id: string;
  label: string;
  detail: string;
  stepIds: string[];
  status: "pending" | "running" | "completed" | "failed";
};

const generationPhases = computed<GenerationPhase[]>(() => {
  const definitions = [
    {
      id: "intake",
      label: "需求确认",
      detail: "确认写作目标与边界",
      stepIds: ["intake"],
    },
    {
      id: "research",
      label: "资料研究",
      detail: "检索知识库、问数与联网核验",
      stepIds: ["researcher"],
    },
    {
      id: "outline",
      label: "生成大纲",
      detail: "组织战略主线与章节结构",
      stepIds: ["architect"],
    },
    {
      id: "writing",
      label: "逐章写作",
      detail: "正文将按章节实时出现",
      stepIds: ["writer"],
    },
    {
      id: "review",
      label: "审核优化",
      detail: "统一引用、评审并迭代",
      stepIds: ["citer", "reviewer", "optimizer"],
    },
  ];
  return definitions.map((phase) => {
    const steps = agentSteps.value.filter((step) => phase.stepIds.includes(step.id));
    let status: GenerationPhase["status"] = "pending";
    if (steps.some((step) => step.status === "failed")) status = "failed";
    else if (steps.some((step) => step.status === "running")) status = "running";
    else if (
      steps.length > 0 &&
      steps.every((step) => step.status === "completed" || step.status === "skipped")
    ) {
      status = "completed";
    }
    return { ...phase, status };
  });
});

const pipelineProgressPct = computed(() => {
  if (!agentSteps.value.length) return 0;
  const runningWeight = agentSteps.value.some((step) => step.status === "running") ? 0.35 : 0;
  return Math.min(
    99,
    Math.round(((completedStepCount.value + runningWeight) / agentSteps.value.length) * 100),
  );
});

const isTaskActivelyRunning = computed(
  () => writing.running || writing.current?.status === "running",
);

const showGenerationStage = computed(
  () => isTaskActivelyRunning.value && writing.liveChapters.length === 0,
);

const workspaceTrackPct = computed(() =>
  reportBodyCharCount.value > 0
    ? writing.progressPct(writing.current)
    : pipelineProgressPct.value,
);

const generationStageTitle = computed(() => {
  const id = currentAgentStep.value?.id;
  if (id === "researcher") return "正在研究与核验资料";
  if (id === "architect") return "正在搭建报告大纲";
  if (id === "writer") return "正在准备首章正文";
  if (id === "citer") return "正在统一全文引用";
  if (id === "reviewer") return "正在进行质量评审";
  if (id === "optimizer") return "正在优化报告内容";
  return "正在准备写作任务";
});

const generationStageDescription = computed(() => {
  const id = currentAgentStep.value?.id;
  if (id === "researcher") {
    return "系统正在检索知识库、结构化数据和外部资料，并核对可用于正文的事实。";
  }
  if (id === "architect") {
    return "资料已经汇集，正在形成战略主线、章节结构和每章写作目标。";
  }
  if (id === "writer") {
    return "大纲已经就绪，首章生成后会立即切换为正文流式预览。";
  }
  return "页面会自动更新，无需刷新。大纲和正文生成后将在这里直接出现。";
});

const activePendingTrace = computed<StepTraceItem | null>(() => {
  const trace = currentAgentStep.value?.trace || [];
  return [...trace].reverse().find((item) => item.kind === "llm_pending") || null;
});

const liveThinkingText = computed(() => {
  const pendingTitle = String(activePendingTrace.value?.title || "").trim();
  const id = currentAgentStep.value?.id;
  if (id === "optimizer" && pendingTitle) {
    return `正在后台生成并校验${pendingTitle.replace(/^正在/, "")}`;
  }
  if (pendingTitle) {
    return pendingTitle.startsWith("正在") ? pendingTitle : `正在${pendingTitle}`;
  }
  if (id === "intake") return "正在确认写作目标与边界";
  if (id === "researcher") return "正在检索并核验资料";
  if (id === "architect") return "正在撰写报告大纲";
  if (id === "writer") {
    const chapter = writing.liveChapters.find((item) => item.status === "writing");
    if (chapter) {
      const index = writing.liveChapters.findIndex((item) => item.id === chapter.id);
      return `正在撰写第 ${index + 1} 章「${chapter.heading}」`;
    }
    return "正在组织章节内容";
  }
  if (id === "citer") return "正在统一全文引用";
  if (id === "reviewer") return "正在检查报告质量";
  if (id === "optimizer") return "正在后台校验优化稿";
  return "正在思考并组织内容";
});

const liveThinkingDetail = computed(() => {
  const id = currentAgentStep.value?.id;
  if (id === "researcher") {
    return writing.currentCards.length
      ? `已汇集 ${writing.currentCards.length} 条候选来源，继续核验相关性与可引用性`
      : "正在连接知识库、结构化数据与可信来源";
  }
  if (id === "architect") return "正在形成战略主线、章节结构和每章写作目标";
  if (id === "writer") return "正文 token 返回后会立即追加到当前章节";
  if (id === "citer") return "正在核对正文引用并生成全文统一来源清单";
  if (id === "reviewer") return "正在检查结构、事实、口径和表达质量";
  if (id === "optimizer") {
    return "当前正文保持不变；候选稿只有在章节完整、仍以正文为主且复评分数提升后才会提交";
  }
  return displayStepMessage(currentAgentStep.value) || "处理状态会在这里持续更新";
});

const generationActivities = computed<StepTraceItem[]>(() => {
  const steps = [...agentSteps.value].reverse();
  const items: StepTraceItem[] = [];
  for (const step of steps) {
    const trace = [...(step.trace || [])].reverse();
    for (const item of trace) {
      items.push(item);
      if (items.length >= 4) return items;
    }
  }
  return items;
});

const runActionLabel = computed(() => {
  const status = writing.current?.status || "";
  if (["completed", "failed", "cancelled"].includes(status)) return "重新运行";
  const hasPipelineOutput =
    Boolean(writing.current?.result) ||
    outlineForm.value.sections.length > 0 ||
    agentSteps.value.some(
      (step) => step.id !== "intake" && step.status !== "pending",
    );
  return hasPipelineOutput ? "重新运行" : "开始生成";
});

const latestScorecard = computed(
  () => writing.currentScorecards[writing.currentScorecards.length - 1] || null,
);

const progressSummary = computed(() => {
  const step = currentAgentStep.value;
  if (!step) return "等待开始生成";
  if (step.status === "running") return `正在进行：${step.label}`;
  if (writing.current?.status === "completed") return "报告生成完成";
  return `最近完成：${step.label}`;
});

function changePreviewFont(delta: number) {
  previewFontScale.value = Math.min(160, Math.max(80, previewFontScale.value + delta));
}

function resetPreviewFont() {
  previewFontScale.value = 100;
}

function selectOutlineChapter(id: string) {
  activeChapterId.value = id;
  continuousPreview.value?.scrollToChapter(id);
}

function locateCurrentWriting() {
  continuousPreview.value?.scrollToWriting();
}

async function selectWorkspaceTask(id: string) {
  await writing.select(id);
  workspaceTaskDrawer.value = false;
}

watch(
  () => writing.liveChapters.map((chapter) => chapter.id).join("|"),
  () => {
    if (!activeChapterId.value && writing.liveChapters[0]) {
      activeChapterId.value = writing.liveChapters[0].id;
    }
  },
  { immediate: true },
);

const intakeQuestions = computed(() => writing.current?.intake?.questions || []);
const intakeBrief = computed(() => writing.current?.intake?.evidence_brief || []);
const intakeDiagnostics = computed(() => writing.current?.intake?.diagnostics?.latest);

watch(
  intakeQuestions,
  (qs) => {
    const next: Record<string, string> = { ...answerDrafts.value };
    for (const q of qs) {
      if (next[q.id] === undefined) next[q.id] = q.answer || "";
    }
    answerDrafts.value = next;
  },
  { immediate: true },
);

const canRunPipeline = computed(() => {
  const t = writing.current;
  if (!t) return false;
  if (t.status === "await_intake") return false;
  const intake = t.intake;
  if (intake == null) return true; // legacy
  return intake.status === "done";
});

async function create() {
  if (!goal.value.trim()) {
    message.warning("请输入报告目标");
    return;
  }
  creating.value = true;
  try {
    const task = await writing.createTask(goal.value.trim(), {
      stepConfirm: stepConfirm.value,
      reportType: reportType.value,
      audience: audience.value.trim(),
      scopePaths: [...scopePaths.value],
      skillProfileId: skillProfileId.value,
    });
    // 先让任务页完成一次渲染，再启动智能补缺，避免创建表单停留到接口结束。
    await nextTick();
    goal.value = "";
    reportType.value = null;
    skillProfileId.value = null;
    answerDrafts.value = {};
    message.success("已创建，正在智能识别是否需要补充关键信息…");
    const updated = await writing.startIntake(task.id);
    if (updated.intake?.status === "done") {
      message.success("信息充分，已跳过补缺，正在生成大纲…");
      await nextTick();
      void run();
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : "创建失败");
  } finally {
    creating.value = false;
  }
}

async function flushIntakeAnswer(qid: string) {
  const draft = answerDrafts.value[qid] ?? "";
  const q = intakeQuestions.value.find((x) => x.id === qid);
  if (q && (q.answer || "") === draft && !q.skipped) return;
  try {
    await writing.saveIntakeAnswers([{ id: qid, answer: draft, skipped: false }]);
  } catch (e) {
    message.error(e instanceof Error ? e.message : "保存答案失败");
  }
}

async function onIntakeSkip(qid: string) {
  try {
    answerDrafts.value = { ...answerDrafts.value, [qid]: "" };
    await writing.saveIntakeAnswers([{ id: qid, answer: "", skipped: true }]);
  } catch (e) {
    message.error(e instanceof Error ? e.message : "跳过失败");
  }
}

async function confirmIntake() {
  confirmingIntake.value = true;
  try {
    // flush drafts first
    const patches = intakeQuestions.value.map((q) => ({
      id: q.id,
      answer: answerDrafts.value[q.id] ?? q.answer ?? "",
      skipped: Boolean(q.skipped) && !(answerDrafts.value[q.id] || "").trim(),
    }));
    if (patches.length) await writing.saveIntakeAnswers(patches);
    await writing.confirmIntake();
    message.success("补缺完成，正在生成报告大纲…");
    await nextTick();
    await run();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "确认失败");
  } finally {
    confirmingIntake.value = false;
  }
}

async function skipIntakeAndRun() {
  skippingIntake.value = true;
  try {
    await writing.skipIntake();
    message.success("已跳过补缺，正在生成报告大纲…");
    await nextTick();
    void run();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "跳过失败");
  } finally {
    skippingIntake.value = false;
  }
}

async function run() {
  if (!writing.current) return;
  if (!health.online) {
    message.error("服务离线");
    return;
  }
  if (!canRunPipeline.value) {
    message.warning("请先完成或跳过智能补缺");
    return;
  }
  try {
    // 首次运行必须让后端自行判断是否需要大纲确认，不预先伪造 confirmed。
    await writing.runActive(false, buildOutlinePayload(), { resume: false });
    await writing.select(writing.current.id);
    const st = writing.current?.status;
    if (st === "paused") message.info("已暂停，可点「继续」从断点接着跑");
    else if (st === "cancelled") message.info("已终止，预览与知识卡片已保留");
    else if (st === "await_confirm") message.success("大纲已生成，请确认后继续写作");
    else message.success("本轮完成");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "运行失败");
  }
}

async function resume() {
  if (!writing.current) return;
  if (!health.online) {
    message.error("服务离线");
    return;
  }
  try {
    await writing.resumeActive();
    await writing.select(writing.current.id);
    const st = writing.current?.status;
    if (st === "paused") message.info("再次暂停");
    else if (st === "cancelled") message.info("已终止，预览与知识卡片已保留");
    else message.success("已从断点跑完");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "继续失败");
  }
}

async function pause() {
  if (!writing.current) return;
  try {
    await writing.pauseActive();
    message.info("已请求暂停：当前步骤或本章写完后停下");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "暂停失败");
  }
}

async function terminate() {
  if (!writing.current) return;
  try {
    await writing.cancelActive();
    message.info("已请求终止：将保留已生成内容");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "终止失败");
  }
}

async function confirmOutline() {
  if (!writing.current) return;
  try {
    await writing.confirmOutline(buildOutlinePayload() || null);
    message.success("已确认大纲，继续写作");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "确认失败");
  }
}

async function confirmChapter() {
  if (!writing.current) return;
  try {
    await writing.confirmChapter();
    message.success("已确认，继续下一章");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "确认失败");
  }
}

async function remove(t: WritingTask) {
  if (t.status === "running") {
    message.warning("运行中的任务请先终止，再删除");
    return;
  }
  try {
    await writing.remove(t.id);
    message.success("任务已删除");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "删除失败");
  }
}

function statusLabel(s: string) {
  const m: Record<string, string> = {
    pending: "等待",
    running: "进行中",
    completed: "完成",
    skipped: "跳过",
    failed: "失败",
  };
  return m[s] || s;
}

function statusType(s: string): "default" | "success" | "warning" | "info" | "error" {
  if (s === "completed") return "success";
  if (s === "running") return "info";
  if (s === "failed") return "error";
  if (s === "skipped") return "warning";
  return "default";
}

function startEditPreview() {
  editMarkdown.value = currentMarkdown.value;
  editingPreview.value = true;
}

function cancelEditPreview() {
  editingPreview.value = false;
  editMarkdown.value = "";
}

async function saveEditPreview() {
  if (!writing.current) return;
  savingPreview.value = true;
  try {
    await writing.savePreview(editMarkdown.value, true);
    // Re-select to refresh chapter cards from saved preview
    await writing.select(writing.current.id);
    editingPreview.value = false;
    message.success("已保存，并更新 Vault 导出文件");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "保存失败");
  } finally {
    savingPreview.value = false;
  }
}

async function onSaveChapters(chapters: ChapterCard[]) {
  savingPreview.value = true;
  try {
    await writing.saveChapters(chapters, true);
    message.success("已保存本章，并更新 Vault 导出文件");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "保存失败");
  } finally {
    savingPreview.value = false;
  }
}

async function downloadFormat(format: "md" | "docx" | "pdf") {
  if (!writing.current) return;
  const md = editingPreview.value ? editMarkdown.value : currentMarkdown.value;
  if (!md.trim()) {
    message.warning("暂无正文可下载");
    return;
  }
  exporting.value = true;
  try {
    await exportWritingTask(writing.current.id, format, md);
    message.success(
      format === "md" ? "已下载 Markdown" : format === "docx" ? "已下载 Word" : "已下载 PDF",
    );
  } catch (e) {
    message.error(e instanceof Error ? e.message : "下载失败");
  } finally {
    exporting.value = false;
  }
}

function handleExportSelect(key: string | number) {
  const format = String(key);
  if (format === "md" || format === "docx" || format === "pdf") {
    downloadFormat(format);
  }
}
</script>

<template>
  <div class="page ra-fade-in">
    <PageHeader v-if="!previewWorkspace" title="战略规划生成">
      <template #actions>
        <NSpace align="center" :size="10">
          <StatusDot :online="health.online" />
          <WebSearchModeSelect />
        </NSpace>
      </template>
    </PageHeader>

    <div
      class="layout"
      :class="{
        'workspace-layout': previewWorkspace,
        'create-layout': showCreateForm,
      }"
    >
      <aside v-if="!previewWorkspace" class="list">
        <NButton type="primary" block @click="writing.beginCreate()">新建任务</NButton>
        <NSelect
          :value="writing.statusFilter"
          :options="statusOptions"
          size="small"
          style="margin-top: 8px"
          @update:value="(v) => writing.setFilter(String(v))"
        />

        <div class="tasks">
          <div
            v-for="t in writing.filtered"
            :key="t.id"
            class="task"
            :class="{ on: writing.current?.id === t.id && !writing.creatingMode }"
            role="button"
            tabindex="0"
            @click="writing.select(t.id)"
            @keydown.enter="writing.select(t.id)"
            @keydown.space.prevent="writing.select(t.id)"
          >
            <div class="t-goal">{{ writing.displayTitle(t) }}</div>
            <div class="t-meta">
              {{ t.status }} · {{ t.report_type || "regional" }} · {{ writing.progressPct(t) }}%
            </div>
            <NPopconfirm
              :positive-text="'删除'"
              :negative-text="'取消'"
              :disabled="t.status === 'running'"
              @positive-click="remove(t)"
            >
              <template #trigger>
                <button
                  type="button"
                  class="task-delete"
                  :disabled="t.status === 'running'"
                  :title="t.status === 'running' ? '请先终止运行中的任务' : '删除任务'"
                  :aria-label="`删除 ${writing.displayTitle(t)}`"
                  @click.stop
                >
                  删除
                </button>
              </template>
              确认删除“{{ writing.displayTitle(t) }}”？删除后无法恢复。
            </NPopconfirm>
          </div>
          <EmptyState v-if="!writing.filtered.length" text="暂无任务" />
        </div>
      </aside>

      <main class="detail" :class="{ 'workspace-detail': previewWorkspace }">
        <template v-if="showCreateForm">
          <div class="create-panel">
            <header class="create-hero">
              <span>新建写作任务</span>
              <h2>描述你要完成的规划任务</h2>
              <p>系统先在本地识别关键信息；信息充分时直接生成大纲，仅在确有缺口时补问 1～2 题。</p>
            </header>

            <div class="create-form">
              <section class="create-primary-field">
                <div class="create-field-heading">
                  <label>写作目标</label>
                  <span>请说明主题、范围、重点内容和输出要求</span>
                </div>
              <NInput
                v-model:value="goal"
                class="goal-input"
                type="textarea"
                  :autosize="{ minRows: 6, maxRows: 10 }"
                  placeholder="例如：以集团战略规划专家身份，编制“十五五”发展规划中的市场发展章节；重点分析业务现状、发展思路、2030年目标与重点行动，采用规范的国企公文文风。"
              />
              </section>

              <div class="create-secondary-grid">
                <section class="create-field">
                  <div class="create-field-heading">
                    <label>目标读者</label>
                    <span>可选</span>
                  </div>
                  <NInput
                    v-model:value="audience"
                    placeholder="例如：董事会、集团管理层"
                  />
                </section>
                <section class="create-field">
                  <div class="create-field-heading">
                    <label>报告模板</label>
                    <span>可选</span>
                  </div>
                  <NSelect
                    v-model:value="reportType"
                    :options="reportTypeOptions"
                    clearable
                    placeholder="不选模板，由 AI 生成大纲"
                  />
                  <p v-if="!reportType" class="template-hint">
                    未选择模板时，AI 会先生成大纲供你确认。
                  </p>
                </section>
              </div>

              <section class="create-field writing-skill-field">
                <div class="create-field-heading">
                  <label>写作方法</label>
                  <span>可选 · 使用任务创建时的版本快照</span>
                </div>
                <NSelect
                  v-model:value="skillProfileId"
                  :options="skillProfileOptions"
                  clearable
                  filterable
                  placeholder="系统默认写作方法"
                />
                <p class="template-hint">
                  选择客户 Skill 后，将用于本任务的大纲设计、逐章写作和报告评审；检索、问数与引用规则仍由系统控制。
                </p>
              </section>

              <section class="knowledge-scope-section">
              <div class="knowledge-scope-heading">
                <div>
                  <strong>知识范围</strong>
                    <span>默认使用全部类型，可按需缩小范围</span>
                </div>
                <NButton
                  size="tiny"
                  quaternary
                  type="primary"
                  :disabled="allKnowledgeScopesSelected"
                  @click="toggleAllKnowledgeScopes"
                >
                    {{
                      allKnowledgeScopesSelected
                        ? `已选 ${scopePaths.length} 类`
                        : `已选 ${scopePaths.length} / ${allScopeValues.length} 类`
                    }}
                </NButton>
              </div>
              <div class="knowledge-scope-grid">
                <button
                  v-for="option in scopeOptions"
                  :key="option.value"
                  type="button"
                  class="knowledge-scope-card"
                  :class="{ selected: scopePaths.includes(option.value) }"
                  :aria-pressed="scopePaths.includes(option.value)"
                  @click="toggleKnowledgeScope(option.value)"
                >
                  <span
                    class="knowledge-scope-glyph"
                    :style="{
                      color: option.color,
                      background: option.soft,
                    }"
                  >
                    {{ option.glyph }}
                  </span>
                  <span class="knowledge-scope-copy">
                    <strong>{{ option.label }}</strong>
                  </span>
                  <span class="knowledge-scope-check">
                    {{ scopePaths.includes(option.value) ? "✓" : "" }}
                  </span>
                  </button>
              </div>
              </section>

              <section class="create-option-row">
                <div>
                  <strong>逐步确认</strong>
                  <span>开启后，系统会在关键阶段暂停，等待你确认后继续。</span>
                </div>
                <NSwitch v-model:value="stepConfirm" size="small" />
              </section>

              <footer class="create-actions">
                <p>
                  智能补缺仅使用本地知识库；正文写作是否联网由页顶联网模式控制。
                </p>
                <NButton
                  type="primary"
                  size="large"
                  :loading="creating || writing.intakeBusy"
                  :disabled="!health.online"
                  @click="create"
                >
                  创建并智能检查
                </NButton>
              </footer>
            </div>
          </div>
        </template>

        <template v-else-if="showIntakePanel && writing.current">
          <div class="intake-panel">
            <div class="head">
              <h2>{{ writing.displayTitle(writing.current) }}</h2>
              <NTag type="info" size="small">智能补缺</NTag>
            </div>
            <p class="muted tiny">
              仅补充会改变大纲的关键信息。答完后继续，也可以跳过补缺直接生成大纲。
            </p>
            <div v-if="writing.intakeBusy && !intakeQuestions.length" class="muted">
              正在本地提取时间、区域、业务范围、目标、读者与硬约束…
            </div>
            <div v-if="intakeDiagnostics" class="intake-diagnostics">
              <span>耗时 {{ ((intakeDiagnostics.duration_ms || 0) / 1000).toFixed(1) }} 秒</span>
              <span>相关资料 {{ intakeDiagnostics.retrieved_count || 0 }} 条</span>
              <span v-if="intakeDiagnostics.model_called">快速模型</span>
              <NTag
                v-if="intakeDiagnostics.parse_error || intakeDiagnostics.model_error"
                size="small"
                type="warning"
              >
                已启用结构化兜底
              </NTag>
            </div>
            <div v-if="intakeBrief.length" class="intake-brief">
              <div class="label">相关资料摘要</div>
              <ul>
                <li v-for="b in intakeBrief.slice(0, 6)" :key="b.id || b.source">
                  <strong>{{ b.title || b.source }}</strong>
                  <span class="muted"> — {{ b.excerpt }}</span>
                </li>
              </ul>
            </div>
            <div class="intake-questions">
              <div v-for="q in intakeQuestions" :key="q.id" class="qa-card">
                <div class="qa-prompt">{{ q.prompt }}</div>
                <p v-if="q.why" class="qa-why muted tiny">{{ q.why }}</p>
                <NInput
                  :value="answerDrafts[q.id] ?? ''"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 4 }"
                  :disabled="!!q.skipped"
                  :placeholder="q.skipped ? '已跳过' : '请输入答案'"
                  @update:value="(v) => (answerDrafts[q.id] = String(v))"
                  @blur="flushIntakeAnswer(q.id)"
                />
                <div class="qa-actions">
                  <NTag v-if="q.skipped" size="small" type="warning">已跳过</NTag>
                  <NTag
                    v-else-if="(answerDrafts[q.id] || q.answer || '').trim()"
                    size="small"
                    type="success"
                  >
                    已答
                  </NTag>
                  <NButton
                    v-if="!q.skipped"
                    size="tiny"
                    quaternary
                    @click="onIntakeSkip(q.id)"
                  >
                    跳过此题
                  </NButton>
                </div>
              </div>
              <EmptyState v-if="!intakeQuestions.length && !writing.intakeBusy" text="暂无问题" />
            </div>
            <div class="intake-actions">
              <NButton
                type="primary"
                :loading="confirmingIntake"
                :disabled="!intakeQuestions.length || writing.intakeBusy"
                @click="confirmIntake"
              >
                确认并生成大纲
              </NButton>
              <NButton
                secondary
                :loading="skippingIntake"
                :disabled="confirmingIntake"
                @click="skipIntakeAndRun"
              >
                跳过补缺，直接生成大纲
              </NButton>
              <NButton secondary :disabled="isTaskActivelyRunning" @click="remove(writing.current)">
                删除任务
              </NButton>
            </div>
          </div>
        </template>

        <template v-else-if="writing.current">
          <template v-if="previewWorkspace">
            <div class="workspace-shell">
              <header class="workspace-toolbar">
                <div class="workspace-title-group">
                  <div class="workspace-nav-actions">
                    <NButton size="small" quaternary @click="workspaceTaskDrawer = true">
                      任务列表
                    </NButton>
                    <NButton size="small" type="primary" @click="writing.beginCreate()">
                      ＋ 新建任务
                    </NButton>
                  </div>
                  <div class="workspace-title-copy">
                    <strong>{{ writing.displayTitle(writing.current) }}</strong>
                    <span>
                      {{ progressSummary }} ·
                      {{
                        reportBodyCharCount > 0
                          ? `正文 ${writing.progressPct(writing.current)}%`
                          : `后台 ${completedStepCount}/${agentSteps.length}`
                      }}
                    </span>
                  </div>
                </div>

                <div class="workspace-actions">
                  <NButton
                    size="small"
                    secondary
                    :type="progressExpanded ? 'primary' : 'default'"
                    @click="progressExpanded = !progressExpanded"
                  >
                    {{ progressExpanded ? "收起进度" : "进度" }}
                  </NButton>
                  <div class="font-control" aria-label="正文缩放">
                    <button
                      type="button"
                      title="缩小正文字号"
                      :disabled="previewFontScale <= 80"
                      @click="changePreviewFont(-10)"
                    >
                      A−
                    </button>
                    <button type="button" title="恢复默认字号" @click="resetPreviewFont">
                      {{ previewFontScale }}%
                    </button>
                    <button
                      type="button"
                      title="放大正文字号"
                      :disabled="previewFontScale >= 160"
                      @click="changePreviewFont(10)"
                    >
                      A+
                    </button>
                  </div>
                  <NButton size="small" secondary @click="outlineCollapsed = !outlineCollapsed">
                    大纲
                  </NButton>
                  <NButton size="small" secondary @click="sourcesCollapsed = !sourcesCollapsed">
                    来源 {{ writing.currentCards.length }}
                  </NButton>
                  <template v-if="!editingPreview">
                    <NButton
                      size="small"
                      type="primary"
                      ghost
                      :disabled="!currentMarkdown"
                      @click="startEditPreview"
                    >
                      整篇编辑
                    </NButton>
                  </template>
                  <template v-else>
                    <NButton size="small" type="primary" :loading="savingPreview" @click="saveEditPreview">
                      保存
                    </NButton>
                    <NButton size="small" quaternary :disabled="savingPreview" @click="cancelEditPreview">
                      取消
                    </NButton>
                  </template>
                  <NDropdown :options="exportOptions" trigger="click" @select="handleExportSelect">
                    <NButton
                      size="small"
                      secondary
                      :loading="exporting"
                      :disabled="!currentMarkdown && !editMarkdown"
                    >
                      导出 ▾
                    </NButton>
                  </NDropdown>
                  <NButton
                    v-if="writing.current.status === 'await_confirm'"
                    size="small"
                    type="primary"
                    :loading="writing.running"
                    :disabled="!health.online"
                    @click="confirmOutline"
                  >
                    确认大纲并继续
                  </NButton>
                  <NButton
                    v-else-if="writing.current.status === 'paused'"
                    size="small"
                    type="primary"
                    :loading="writing.running"
                    :disabled="!health.online"
                    @click="resume"
                  >
                    继续
                  </NButton>
                  <NButton
                    v-else-if="isTaskActivelyRunning"
                    size="small"
                    secondary
                    :loading="writing.controlPending === 'pause'"
                    :disabled="!isTaskActivelyRunning || !!writing.controlPending"
                    @click="pause"
                  >
                    暂停
                  </NButton>
                  <NButton
                    v-else
                    size="small"
                    type="primary"
                    :disabled="!health.online || !canRunPipeline"
                    @click="run"
                  >
                    {{ runActionLabel }}
                  </NButton>
                  <NButton
                    v-if="writing.current.status === 'await_chapter'"
                    size="small"
                    type="primary"
                    secondary
                    @click="confirmChapter"
                  >
                    确认本章并继续
                  </NButton>
                  <NButton
                    v-if="isTaskActivelyRunning"
                    size="small"
                    secondary
                    type="error"
                    :loading="writing.controlPending === 'cancel'"
                    :disabled="!isTaskActivelyRunning || !!writing.controlPending"
                    @click="terminate"
                  >
                    终止
                  </NButton>
                </div>
              </header>

              <div class="workspace-progress-track">
                <div
                  class="workspace-progress-value"
                  :class="{ 'pipeline-stage': reportBodyCharCount === 0 && isTaskActivelyRunning }"
                  :style="{ width: `${workspaceTrackPct}%` }"
                />
              </div>

              <section v-if="progressExpanded" class="workspace-progress-panel">
                <div class="progress-panel-head">
                  <div>
                    <strong>步骤进度</strong>
                    <span>
                      正文完成度 {{ writing.progressPct(writing.current) }}% ·
                      后台步骤 {{ completedStepCount }}/{{ agentSteps.length }}
                    </span>
                  </div>
                  <NButton size="tiny" quaternary @click="progressExpanded = false">收起</NButton>
                </div>
                <div class="workspace-step-grid">
                  <button
                    v-for="step in agentSteps"
                    :key="step.id"
                    type="button"
                    class="workspace-step-card"
                    :class="[step.status, { clickable: step.status !== 'pending' }]"
                    :disabled="step.status === 'pending'"
                    @click="step.status !== 'pending' && openStepTrace(step)"
                  >
                    <NTag size="tiny" :bordered="false" :type="statusType(step.status)">
                      {{ statusLabel(step.status) }}
                    </NTag>
                    <strong>{{ step.label }}</strong>
                    <span>{{ displayStepMessage(step) || stepDetailLines(step)[0] || "等待执行" }}</span>
                  </button>
                </div>
                <div v-if="writing.currentScorecards.length" class="workspace-score-summary">
                  最近评分：
                  <strong>{{ latestScorecard?.total ?? "-" }}</strong>
                  <span>{{ latestScorecard?.verdict || "" }}</span>
                </div>
              </section>

              <div
                class="document-workspace"
                :class="{
                  'outline-hidden': outlineCollapsed,
                  'sources-hidden': sourcesCollapsed,
                }"
              >
                <aside v-if="!outlineCollapsed" class="workspace-outline">
                  <div class="workspace-panel-head">
                    <div>
                      <span>报告大纲</span>
                      <small>{{ outlineForm.sections.length }} 章</small>
                    </div>
                    <NButton size="tiny" quaternary @click="outlineCollapsed = true">收起</NButton>
                  </div>
                  <div class="outline-report-title">
                    {{ writing.displayTitle(writing.current) }}
                  </div>
                  <div v-if="outlineForm.strategic_main_line" class="outline-mainline-compact">
                    {{ outlineForm.strategic_main_line }}
                  </div>
                  <nav class="workspace-outline-nav" aria-label="报告章节">
                    <button
                      v-for="(chapter, index) in writing.liveChapters"
                      :key="chapter.id"
                      type="button"
                      :class="[
                        chapter.status,
                        { active: activeChapterId === chapter.id },
                      ]"
                      @click="selectOutlineChapter(chapter.id)"
                    >
                      <span class="outline-status-dot" />
                      <span class="outline-index">{{ index + 1 }}</span>
                      <span class="outline-label">{{ chapter.heading }}</span>
                    </button>
                  </nav>
                  <div v-if="!writing.liveChapters.length" class="outline-build-state">
                    <div class="outline-build-intro">
                      <span class="outline-build-pulse" />
                      <div>
                        <strong>{{ isTaskActivelyRunning ? "大纲准备中" : "尚未生成大纲" }}</strong>
                        <small>
                          {{ isTaskActivelyRunning ? "完成研究后自动生成" : "开始生成后显示章节" }}
                        </small>
                      </div>
                    </div>
                    <ol class="outline-phase-list">
                      <li
                        v-for="phase in generationPhases"
                        :key="phase.id"
                        :class="phase.status"
                      >
                        <span class="phase-status-mark">
                          {{ phase.status === "completed" ? "✓" : "" }}
                        </span>
                        <div>
                          <strong>{{ phase.label }}</strong>
                          <small>{{ phase.detail }}</small>
                        </div>
                      </li>
                    </ol>
                  </div>
                  <NButton
                    v-if="isTaskActivelyRunning"
                    size="small"
                    type="primary"
                    secondary
                    block
                    @click="locateCurrentWriting"
                  >
                    定位到正在生成
                  </NButton>
                </aside>

                <section class="workspace-document">
                  <div class="document-status-bar">
                    <div>
                      <span>{{ showGenerationStage ? "生成进展" : "正文预览" }}</span>
                      <span class="muted">
                        {{
                          showGenerationStage
                            ? "正文将在大纲完成后逐章出现"
                            : `约 ${reportBodyCharCount} 字`
                        }}
                      </span>
                    </div>
                    <span v-if="isTaskActivelyRunning" class="document-live-status">
                      <span class="thinking-shimmer-text">{{ liveThinkingText }}</span>
                    </span>
                  </div>

                  <div
                    v-if="isTaskActivelyRunning && !showGenerationStage"
                    class="document-thinking-strip"
                    role="status"
                    aria-live="polite"
                  >
                    <span class="thinking-breathe-dot" aria-hidden="true" />
                    <div>
                      <strong class="thinking-shimmer-text">{{ liveThinkingText }}</strong>
                      <small>{{ liveThinkingDetail }}</small>
                    </div>
                  </div>

                  <div v-if="editingPreview" class="workspace-editor-wrap">
                    <NInput
                      v-model:value="editMarkdown"
                      type="textarea"
                      class="workspace-editor"
                      :style="{ '--editor-font-size': `${(16 * previewFontScale) / 100}px` }"
                      placeholder="在此编辑 Markdown 正文…"
                    />
                  </div>
                  <div v-else-if="showGenerationStage" class="generation-stage-scroll">
                    <section class="generation-stage-card">
                      <header class="generation-stage-header">
                        <div class="generation-orbit" aria-hidden="true">
                          <span />
                          <span />
                          <strong>{{ completedStepCount + 1 }}</strong>
                        </div>
                        <div>
                          <div
                            class="generation-stage-eyebrow generation-thinking-label"
                            role="status"
                            aria-live="polite"
                          >
                            <span class="thinking-breathe-dot" aria-hidden="true" />
                            <span class="thinking-shimmer-text">{{ liveThinkingText }}</span>
                          </div>
                          <h2>{{ generationStageTitle }}</h2>
                          <p>{{ liveThinkingDetail || generationStageDescription }}</p>
                        </div>
                      </header>

                      <div class="generation-live-summary">
                        <div>
                          <span>当前阶段</span>
                          <strong>{{ currentAgentStep?.label || "准备中" }}</strong>
                          <small>{{ displayStepMessage(currentAgentStep) || "正在初始化任务" }}</small>
                        </div>
                        <div>
                          <span>可用来源</span>
                          <strong>{{ writing.currentCards.length }}</strong>
                          <small>右侧可实时查看检索结果</small>
                        </div>
                        <div>
                          <span>后台步骤</span>
                          <strong>{{ completedStepCount }}/{{ agentSteps.length }}</strong>
                          <small>完成后自动进入下一阶段</small>
                        </div>
                      </div>

                      <div class="generation-phase-rail">
                        <div
                          v-for="(phase, index) in generationPhases"
                          :key="phase.id"
                          class="generation-phase"
                          :class="phase.status"
                        >
                          <span class="generation-phase-index">
                            {{ phase.status === "completed" ? "✓" : index + 1 }}
                          </span>
                          <div>
                            <strong>{{ phase.label }}</strong>
                            <small>{{ phase.detail }}</small>
                          </div>
                        </div>
                      </div>

                      <div class="generation-detail-grid">
                        <section class="generation-activity">
                          <div class="generation-section-head">
                            <div>
                              <strong>实时处理记录</strong>
                              <span>自动更新</span>
                            </div>
                            <NButton size="tiny" quaternary @click="progressExpanded = true">
                              查看完整过程
                            </NButton>
                          </div>
                          <div v-if="generationActivities.length" class="generation-activity-list">
                            <div
                              v-for="(activity, index) in generationActivities"
                              :key="`${activity.at || index}-${activity.title}`"
                              class="generation-activity-item"
                            >
                              <span />
                              <div>
                                <strong>{{ activity.title }}</strong>
                                <p>{{ activity.summary || "正在处理…" }}</p>
                              </div>
                            </div>
                          </div>
                          <div v-else class="generation-activity-empty">
                            <span class="activity-loader" />
                            <div>
                              <strong class="thinking-shimmer-text">{{ liveThinkingText }}</strong>
                              <p>第一条处理记录产生后会立即显示在这里。</p>
                            </div>
                          </div>
                        </section>

                        <aside class="generation-next">
                          <span>接下来</span>
                          <strong>
                            {{
                              currentAgentStep?.id === "researcher"
                                ? "生成并展示报告大纲"
                                : "开始流式输出章节正文"
                            }}
                          </strong>
                          <p>你可以继续查看右侧来源，页面会在内容就绪时自动切换。</p>
                        </aside>
                      </div>
                    </section>
                  </div>
                  <ContinuousDocumentPreview
                    v-else
                    ref="continuousPreview"
                    :title="writing.displayTitle(writing.current)"
                    :main-line="outlineForm.strategic_main_line"
                    :chapters="writing.liveChapters"
                    :references="writing.current.result?.citation_ledger || []"
                    :editable="!isTaskActivelyRunning"
                    :font-scale="previewFontScale"
                    @active-change="activeChapterId = $event"
                    @save="onSaveChapters"
                  />
                </section>

                <aside v-if="!sourcesCollapsed" class="workspace-sources">
                  <div class="workspace-panel-head">
                    <div>
                      <span>参考来源</span>
                      <small>{{ writing.currentCards.length }} 条</small>
                    </div>
                    <NButton size="tiny" quaternary @click="sourcesCollapsed = true">收起</NButton>
                  </div>
                  <KnowledgeCardsPanel :cards="writing.currentCards" />
                </aside>
              </div>

              <footer v-if="isTaskActivelyRunning || writing.controlPending" class="workspace-run-footer">
                <span>{{ progressSummary }}</span>
                <span>后台步骤 {{ completedStepCount }}/{{ agentSteps.length }}</span>
                <strong>
                  {{
                    reportBodyCharCount > 0
                      ? `正文 ${writing.progressPct(writing.current)}%`
                      : `后台 ${pipelineProgressPct}%`
                  }}
                </strong>
              </footer>
            </div>
          </template>

          <template v-else>
          <div class="detail-top">
            <div class="head">
              <h2>{{ writing.displayTitle(writing.current) }}</h2>
              <NSpace>
                <NButton
                  v-if="writing.current.status !== 'paused'"
                  type="primary"
                  :loading="writing.running"
                  :disabled="!health.online || isTaskActivelyRunning || !canRunPipeline"
                  @click="run"
                >
                  运行
                </NButton>
                <NButton
                  v-if="writing.current.status === 'paused'"
                  type="primary"
                  :loading="writing.running"
                  :disabled="!health.online"
                  @click="resume"
                >
                  继续
                </NButton>
                <NButton
                  secondary
                  :loading="writing.controlPending === 'pause'"
                  :disabled="!isTaskActivelyRunning || !!writing.controlPending"
                  @click="pause"
                >
                  暂停
                </NButton>
                <NButton
                  secondary
                  type="error"
                  :loading="writing.controlPending === 'cancel'"
                  :disabled="!isTaskActivelyRunning || !!writing.controlPending"
                  @click="terminate"
                >
                  终止
                </NButton>
                <NButton
                  v-if="writing.current.status === 'await_confirm'"
                  secondary
                  :loading="writing.running"
                  @click="confirmOutline"
                >
                  确认大纲
                </NButton>
                <NButton
                  v-if="writing.current.status === 'await_chapter'"
                  secondary
                  :loading="writing.running"
                  @click="confirmChapter"
                >
                  确认本章并继续
                </NButton>
                <NButton secondary :disabled="isTaskActivelyRunning" @click="remove(writing.current)">
                  删除
                </NButton>
              </NSpace>
            </div>

            <NProgress
              type="line"
              :percentage="writing.progressPct(writing.current)"
              :show-indicator="true"
              style="margin: 12px 0"
            />
            <p v-if="writing.current.status === 'paused'" class="legacy-hint">
              已暂停。点「继续」会从断点接着生成；预览与知识卡片已保留。
            </p>
            <p v-else-if="writing.current.status === 'cancelled'" class="legacy-hint">
              已终止。预览与知识卡片已保留；再点「运行」会重新开始一整轮。
            </p>
            <p v-else-if="writing.controlPending" class="legacy-hint">
              已收到{{ writing.controlPending === "pause" ? "暂停" : "终止" }}请求，等待当前步骤或本章写完…
            </p>

            <div class="mid-split">
              <div class="mid-col mid-steps">
                <div class="label">步骤进度</div>
                <p v-if="isLegacyProgress" class="legacy-hint">
                  这是旧流水线记录，看不到 Skill/脚本明细。请新建任务并重新运行（需重启 Gateway）。
                </p>
                <div class="steps">
                  <div
                    v-for="s in agentSteps"
                    :key="s.id"
                    class="step"
                    :class="[
                      s.status,
                      {
                        rich: stepDetailLines(s).length > 0,
                        clickable: s.status !== 'pending',
                      },
                    ]"
                    :title="
                      [
                        s.status !== 'pending' ? '点击查看本步过程记录' : '',
                        ...stepDetailLines(s),
                        displayStepMessage(s),
                      ]
                        .filter(Boolean)
                        .join('\n')
                    "
                    role="button"
                    tabindex="0"
                    @click="s.status !== 'pending' && openStepTrace(s)"
                    @keydown.enter="s.status !== 'pending' && openStepTrace(s)"
                  >
                    <div class="step-main">
                      <NTag size="tiny" :bordered="false" :type="statusType(s.status)">
                        {{ statusLabel(s.status) }}
                      </NTag>
                      <span class="step-label">{{ s.label }}</span>
                      <span class="step-msg">{{ displayStepMessage(s) }}</span>
                    </div>
                    <div v-if="stepDetailLines(s).length" class="step-meta">
                      <div
                        v-for="(line, li) in stepDetailLines(s)"
                        :key="li"
                        class="step-detail"
                        :class="{ skill: li === 0 && stepSkillLine(s) }"
                      >
                        {{ line }}
                      </div>
                    </div>
                    <div v-if="s.status !== 'pending'" class="step-hint">
                      {{ stepTraceHint(s) }}
                    </div>
                  </div>
                </div>
              </div>
              <div class="mid-col mid-outline">
                <div class="outline-head">
                  <div class="label">大纲</div>
                  <button type="button" class="raw-toggle" @click="showOutlineRaw = !showOutlineRaw">
                    {{ showOutlineRaw ? "返回章节视图" : "原始数据" }}
                  </button>
                </div>
                <div v-if="showOutlineRaw" class="outline-raw-wrap">
                  <NInput
                    v-model:value="outlineRawText"
                    type="textarea"
                    class="outline-input"
                    readonly
                  />
                </div>
                <div v-else-if="outlineForm.sections.length || outlineForm.title" class="outline-view">
                  <div class="outline-title">
                    {{ writing.displayTitle(writing.current) }}
                  </div>
                  <div class="outline-meta">
                    <NTag v-if="outlineForm.report_type_label" size="tiny" :bordered="false">
                      {{ outlineForm.report_type_label }}
                    </NTag>
                    <span class="muted">共 {{ outlineForm.sections.length }} 章</span>
                  </div>
                  <div v-if="outlineForm.strategic_main_line || outlineEditable" class="outline-mainline">
                    <div class="sub-label">战略主线</div>
                    <NInput
                      v-if="outlineEditable"
                      v-model:value="outlineForm.strategic_main_line"
                      type="textarea"
                      size="small"
                      :autosize="{ minRows: 2, maxRows: 5 }"
                      placeholder="以…为统领，以…为主线…"
                    />
                    <p v-else class="mainline-text">
                      {{
                        outlineForm.strategic_main_line ||
                        "（主线生成异常，可点「原始数据」查看或重新运行）"
                      }}
                    </p>
                  </div>
                  <ol class="outline-chapters">
                    <li v-for="(sec, idx) in outlineForm.sections" :key="sec.id || idx" class="chapter">
                      <span class="chapter-idx">{{ idx + 1 }}</span>
                      <NInput
                        v-if="outlineEditable"
                        v-model:value="sec.heading"
                        size="tiny"
                        class="chapter-heading-input"
                        placeholder="标题"
                      />
                      <span v-else class="chapter-heading" :title="sec.heading">{{ sec.heading }}</span>
                      <span class="chapter-budget">
                        <template v-if="outlineEditable">
                          <NInputNumber
                            v-model:value="sec.word_budget"
                            size="tiny"
                            :min="100"
                            :step="100"
                            :show-button="false"
                            class="budget-input"
                          />
                          <span class="muted">字</span>
                        </template>
                        <template v-else-if="sec.word_budget">约 {{ sec.word_budget }} 字</template>
                      </span>
                      <NInput
                        v-if="outlineEditable"
                        v-model:value="sec.purpose"
                        size="tiny"
                        placeholder="用途"
                        class="chapter-purpose-input"
                      />
                      <span v-else-if="sec.purpose" class="chapter-purpose" :title="sec.purpose">
                        {{ sec.purpose }}
                      </span>
                    </li>
                  </ol>
                </div>
                <EmptyState v-else text="运行后显示章节大纲" />
              </div>
            </div>

            <div v-if="writing.currentScorecards.length" class="scorecards-bar">
              <div class="label">七维评分</div>
              <div class="scorecards-scroll">
                <div
                  v-for="(sc, i) in writing.currentScorecards"
                  :key="i"
                  class="scorecard"
                >
                  <div class="sc-head">
                    第 {{ i + 1 }} 轮 · 总分 {{ sc.total ?? "-" }}
                    <NTag v-if="sc.verdict" size="tiny">{{ sc.verdict }}</NTag>
                  </div>
                  <ul v-if="sc.dimensions?.length" class="dims">
                    <li v-for="d in sc.dimensions" :key="d.name">
                      {{ d.name }}：{{ d.score }}/5
                      <span v-if="d.reason" class="muted"> — {{ d.reason }}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          <div class="preview-pane">
            <div class="preview-toolbar">
              <div class="label">
                预览
                <span v-if="reportBodyCharCount" class="muted">
                  （约 {{ reportBodyCharCount }} 字）
                </span>
                <span v-if="writing.current.result?.evidence_weak" class="warn-tag">
                  证据偏弱
                </span>
                <span
                  v-if="
                    writing.current.result?.completion_note &&
                    writing.current.result.completion_note !== 'completed' &&
                    !(
                      writing.current.result.completion_note === 'completed_under_length'
                    )
                  "
                  class="warn-tag"
                >
                  {{
                    writing.current.result.completion_note === "completed_weak_evidence"
                      ? "弱证据完成"
                      : writing.current.result.completion_note === "completed_with_gaps"
                        ? "有缺口完成"
                        : "有缺口完成"
                  }}
                </span>
              </div>
              <NSpace size="small" align="center">
                <NButton
                  size="tiny"
                  secondary
                  :loading="exporting"
                  :disabled="!currentMarkdown && !editMarkdown"
                  @click="downloadFormat('docx')"
                >
                  下载 Word
                </NButton>
                <NButton
                  size="tiny"
                  secondary
                  :loading="exporting"
                  :disabled="!currentMarkdown && !editMarkdown"
                  @click="downloadFormat('pdf')"
                >
                  下载 PDF
                </NButton>
                <NButton
                  size="tiny"
                  secondary
                  :loading="exporting"
                  :disabled="!currentMarkdown && !editMarkdown"
                  @click="downloadFormat('md')"
                >
                  下载 MD
                </NButton>
                <template v-if="!editingPreview">
                  <NButton
                    size="tiny"
                    type="primary"
                    ghost
                    :disabled="!currentMarkdown && !writing.liveChapters.length"
                    @click="startEditPreview"
                  >
                    整篇编辑
                  </NButton>
                </template>
                <template v-else>
                  <NButton size="tiny" :loading="savingPreview" type="primary" @click="saveEditPreview">
                    保存整篇
                  </NButton>
                  <NButton size="tiny" quaternary :disabled="savingPreview" @click="cancelEditPreview">
                    取消
                  </NButton>
                </template>
              </NSpace>
            </div>
            <div class="preview-scroll">
              <NInput
                v-if="editingPreview"
                v-model:value="editMarkdown"
                type="textarea"
                class="preview-editor"
                placeholder="在此编辑 Markdown 正文…"
              />
              <ChapterPreviewCards
                v-else
                :chapters="writing.liveChapters"
                :editable="!isTaskActivelyRunning"
                @save="onSaveChapters"
              />
              <div v-if="writing.current.result?.vault_path" class="muted vault-path">
                Vault: {{ writing.current.result.vault_path }}
              </div>
              <div v-if="writing.current.error" class="err">{{ writing.current.error }}</div>
            </div>
            </div>
          </template>
        </template>
        <EmptyState v-else text="选择或新建写作任务" />
      </main>

      <aside v-if="!previewWorkspace && !showCreateForm" class="cards">
        <KnowledgeCardsPanel :cards="writing.currentCards" />
      </aside>
    </div>

    <NDrawer v-model:show="workspaceTaskDrawer" :width="340" placement="left">
      <NDrawerContent title="写作任务" closable>
        <NButton type="primary" block @click="writing.beginCreate(); workspaceTaskDrawer = false">
          新建任务
        </NButton>
        <NSelect
          :value="writing.statusFilter"
          :options="statusOptions"
          size="small"
          style="margin-top: 10px"
          @update:value="(v) => writing.setFilter(String(v))"
        />
        <div class="drawer-tasks">
          <div
            v-for="task in writing.filtered"
            :key="task.id"
            class="task"
            :class="{ on: writing.current?.id === task.id }"
            role="button"
            tabindex="0"
            @click="selectWorkspaceTask(task.id)"
            @keydown.enter="selectWorkspaceTask(task.id)"
            @keydown.space.prevent="selectWorkspaceTask(task.id)"
          >
            <div class="t-goal">{{ writing.displayTitle(task) }}</div>
            <div class="t-meta">
              {{ task.status }} · {{ task.report_type || "regional" }} · {{ writing.progressPct(task) }}%
            </div>
            <NPopconfirm
              positive-text="删除"
              negative-text="取消"
              :disabled="task.status === 'running'"
              @positive-click="remove(task)"
            >
              <template #trigger>
                <button
                  type="button"
                  class="task-delete"
                  :disabled="task.status === 'running'"
                  :title="task.status === 'running' ? '请先终止运行中的任务' : '删除任务'"
                  :aria-label="`删除 ${writing.displayTitle(task)}`"
                  @click.stop
                >
                  删除
                </button>
              </template>
              确认删除“{{ writing.displayTitle(task) }}”？删除后无法恢复。
            </NPopconfirm>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>

    <NModal
      v-model:show="traceModalOpen"
      preset="card"
      :title="traceStep ? `过程记录 · ${traceStep.label}` : '过程记录'"
      style="width: min(720px, 94vw)"
      :bordered="false"
      size="huge"
      @after-leave="traceStepId = null"
    >
      <div v-if="!hasStepTrace(traceStep)" class="trace-empty">
        <template v-if="isStepRunning(traceStep)">
          本步进行中，过程将陆续出现…（每次动作或模型调用完成后会自动刷新）
        </template>
        <template v-else>
          此任务运行时未记录过程（旧任务）。请新建任务并重新运行后，再点卡片查看。
        </template>
      </div>
      <div v-else class="trace-list">
        <p v-if="isStepRunning(traceStep)" class="trace-live-hint">进行中 · 列表会随新过程自动更新</p>
        <div
          v-for="(item, ti) in traceStep!.trace"
          :key="`${item.kind}-${item.title}-${item.at || ti}`"
          class="trace-item"
          :class="item.kind"
        >
          <div class="trace-item-head">
            <NTag
              size="tiny"
              :type="item.kind === 'llm' ? 'info' : item.kind === 'llm_pending' ? 'warning' : 'default'"
              :bordered="false"
            >
              {{ traceItemKindLabel(item) }}
            </NTag>
            <strong class="trace-title">{{ item.title }}</strong>
            <span v-if="formatTraceTime(item.at)" class="trace-time">{{ formatTraceTime(item.at) }}</span>
          </div>
          <p v-if="item.summary" class="trace-summary">{{ item.summary }}</p>

          <template v-if="item.kind === 'llm_pending'">
            <p class="trace-muted pending-pulse">模型生成中，请稍候…</p>
          </template>

          <template v-else-if="item.kind === 'action'">
            <div v-if="item.detail" class="trace-field">
              <div class="trace-field-label">详情</div>
              <pre class="trace-pre">{{
                isExpanded(ti, "detail") ? item.detail : previewText(item.detail)
              }}</pre>
              <button
                v-if="(item.detail || '').length > 180"
                type="button"
                class="trace-expand"
                @click="toggleExpand(ti, 'detail')"
              >
                {{ isExpanded(ti, "detail") ? "收起" : "展开全文" }}
              </button>
            </div>
          </template>

          <template v-else-if="item.kind === 'llm'">
            <div v-if="item.system" class="trace-field">
              <div class="trace-field-label">系统提示</div>
              <pre class="trace-pre">{{
                isExpanded(ti, "system") ? item.system : previewText(item.system)
              }}</pre>
              <button
                v-if="(item.system || '').length > 180"
                type="button"
                class="trace-expand"
                @click="toggleExpand(ti, 'system')"
              >
                {{ isExpanded(ti, "system") ? "收起" : "展开全文" }}
              </button>
            </div>
            <div class="trace-field">
              <div class="trace-field-label">提示词</div>
              <pre class="trace-pre">{{
                isExpanded(ti, "prompt") ? item.prompt || "" : previewText(item.prompt || "")
              }}</pre>
              <button
                v-if="(item.prompt || '').length > 180"
                type="button"
                class="trace-expand"
                @click="toggleExpand(ti, 'prompt')"
              >
                {{ isExpanded(ti, "prompt") ? "收起" : "展开全文" }}
              </button>
            </div>
            <div class="trace-field">
              <div class="trace-field-label">模型回复</div>
              <pre class="trace-pre">{{
                isExpanded(ti, "reply") ? item.reply || "" : previewText(item.reply || "")
              }}</pre>
              <button
                v-if="(item.reply || '').length > 180"
                type="button"
                class="trace-expand"
                @click="toggleExpand(ti, 'reply')"
              >
                {{ isExpanded(ti, "reply") ? "收起" : "展开全文" }}
              </button>
            </div>
            <div class="trace-field">
              <div class="trace-field-label">思考过程</div>
              <pre v-if="item.reasoning" class="trace-pre">{{
                isExpanded(ti, "reasoning") ? item.reasoning : previewText(item.reasoning)
              }}</pre>
              <p v-else class="trace-muted">本步未提供</p>
              <button
                v-if="item.reasoning && item.reasoning.length > 180"
                type="button"
                class="trace-expand"
                @click="toggleExpand(ti, 'reasoning')"
              >
                {{ isExpanded(ti, "reasoning") ? "收起" : "展开全文" }}
              </button>
            </div>
          </template>
        </div>
      </div>
      <template #footer>
        <NButton @click="closeStepTrace">关闭</NButton>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.page {
  flex: 1;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}
.layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 280px;
  gap: 12px;
  overflow: hidden;
}
.layout.workspace-layout {
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
}
.layout.create-layout {
  grid-template-columns: 280px minmax(0, 1fr);
}
.detail.workspace-detail {
  padding: 0;
  border-radius: 14px;
  background: #fff;
}
.workspace-shell {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f7f9fc;
}
.workspace-toolbar {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 12px;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.98);
  border-bottom: 1px solid var(--ra-border);
  flex: 0 0 auto;
  z-index: 3;
}
.workspace-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  flex: 1 1 320px;
}
.workspace-nav-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}
.workspace-title-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.workspace-title-copy strong {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  color: #1e293b;
}
.workspace-title-copy span {
  font-size: 11px;
  color: var(--ra-muted);
}
.workspace-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  flex: 0 1 auto;
}
.font-control {
  height: 28px;
  display: inline-flex;
  align-items: stretch;
  overflow: hidden;
  border: 1px solid var(--ra-border);
  border-radius: 7px;
  background: #fff;
}
.font-control button {
  min-width: 32px;
  padding: 0 8px;
  border: none;
  border-right: 1px solid var(--ra-border);
  background: transparent;
  color: #334155;
  font-size: 12px;
  cursor: pointer;
}
.font-control button:nth-child(2) {
  min-width: 52px;
  color: var(--ra-accent);
  font-variant-numeric: tabular-nums;
}
.font-control button:last-child {
  border-right: none;
}
.font-control button:hover:not(:disabled) {
  background: var(--ra-accent-soft);
}
.font-control button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.workspace-progress-track {
  height: 3px;
  background: #e8edf4;
  flex: 0 0 auto;
}
.workspace-progress-value {
  height: 100%;
  min-width: 2px;
  max-width: 100%;
  background: linear-gradient(90deg, #2e6fe8, #4b91f6);
  transition: width 0.3s ease;
}
.workspace-progress-value.pipeline-stage {
  position: relative;
  overflow: hidden;
}
.workspace-progress-value.pipeline-stage::after {
  content: "";
  position: absolute;
  inset: 0;
  width: 48%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.7), transparent);
  animation: workspaceProgressSweep 1.8s ease-in-out infinite;
}
.workspace-progress-panel {
  flex: 0 0 auto;
  max-height: min(310px, 38vh);
  overflow: auto;
  padding: 12px 14px 14px;
  background: #fff;
  border-bottom: 1px solid var(--ra-border);
  box-shadow: 0 10px 28px rgba(34, 51, 84, 0.08);
  z-index: 2;
}
.progress-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.progress-panel-head > div {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.progress-panel-head strong {
  font-size: 14px;
}
.progress-panel-head span {
  font-size: 11px;
  color: var(--ra-muted);
}
.workspace-step-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 8px;
}
.workspace-step-card {
  min-width: 0;
  min-height: 66px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: auto auto;
  align-items: center;
  gap: 3px 7px;
  padding: 8px 9px;
  text-align: left;
  border: 1px solid #e5eaf1;
  border-radius: 9px;
  background: #f8fafc;
  color: #263247;
}
.workspace-step-card.clickable {
  cursor: pointer;
}
.workspace-step-card.clickable:hover {
  border-color: #b9c9e4;
  background: #f4f7fc;
}
.workspace-step-card.running {
  border-color: #9ec1fb;
  background: #f0f6ff;
}
.workspace-step-card.failed {
  border-color: #fecaca;
  background: #fff5f5;
}
.workspace-step-card strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.workspace-step-card > span:last-child {
  grid-column: 1 / -1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
  color: var(--ra-muted);
}
.workspace-score-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--ra-muted);
}
.workspace-score-summary strong {
  font-size: 17px;
  color: var(--ra-accent);
}
.document-workspace {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(480px, 1fr) 292px;
  overflow: hidden;
}
.document-workspace.outline-hidden {
  grid-template-columns: minmax(480px, 1fr) 292px;
}
.document-workspace.sources-hidden {
  grid-template-columns: 260px minmax(480px, 1fr);
}
.document-workspace.outline-hidden.sources-hidden {
  grid-template-columns: minmax(0, 1fr);
}
.workspace-outline,
.workspace-sources {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 14px 12px;
  box-sizing: border-box;
  background: #fff;
}
.workspace-outline {
  border-right: 1px solid var(--ra-border);
}
.workspace-sources {
  border-left: 1px solid var(--ra-border);
}
.workspace-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex: 0 0 auto;
  margin-bottom: 12px;
}
.workspace-panel-head > div {
  display: flex;
  align-items: baseline;
  gap: 7px;
}
.workspace-panel-head span {
  font-size: 14px;
  font-weight: 700;
}
.workspace-panel-head small {
  font-size: 11px;
  color: var(--ra-muted);
}
.outline-report-title {
  flex: 0 0 auto;
  margin-bottom: 10px;
  padding: 0 4px;
  font-size: 15px;
  line-height: 1.45;
  font-weight: 650;
  color: #202a3a;
}
.outline-mainline-compact {
  flex: 0 0 auto;
  max-height: 58px;
  overflow: hidden;
  margin: 0 4px 10px;
  padding: 8px 9px;
  border-radius: 8px;
  background: #f6f8fb;
  color: #64748b;
  font-size: 11.5px;
  line-height: 1.55;
}
.workspace-outline-nav {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  overflow: auto;
  margin-bottom: 10px;
}
.outline-build-state {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  margin-bottom: 10px;
}
.outline-build-intro {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 2px 3px 13px;
  padding: 10px;
  border: 1px solid #dbe7fb;
  border-radius: 10px;
  background: linear-gradient(135deg, #f4f8ff, #f8fbff);
}
.outline-build-pulse {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--ra-accent);
  box-shadow: 0 0 0 5px rgba(57, 126, 236, 0.11);
  animation: pendingPulse 1.2s ease-in-out infinite;
}
.outline-build-intro > div,
.outline-phase-list li > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.outline-build-intro strong,
.outline-phase-list strong {
  color: #27344a;
  font-size: 12px;
}
.outline-build-intro small,
.outline-phase-list small {
  color: #7a879b;
  font-size: 10px;
  line-height: 1.4;
}
.outline-phase-list {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 0;
  padding: 0 3px;
  list-style: none;
}
.outline-phase-list li {
  position: relative;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 8px;
  min-height: 50px;
}
.outline-phase-list li:not(:last-child)::after {
  content: "";
  position: absolute;
  top: 20px;
  bottom: 0;
  left: 9px;
  width: 1px;
  background: #dce3ec;
}
.phase-status-mark {
  position: relative;
  z-index: 1;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border: 1px solid #d4dce7;
  border-radius: 50%;
  background: #fff;
  color: #fff;
  font-size: 10px;
}
.outline-phase-list li.completed .phase-status-mark {
  border-color: #2ba676;
  background: #2ba676;
}
.outline-phase-list li.running .phase-status-mark {
  border: 5px solid #dbe9ff;
  background: var(--ra-accent);
  animation: pendingPulse 1.2s ease-in-out infinite;
}
.outline-phase-list li.running strong {
  color: var(--ra-accent);
}
.workspace-outline-nav button {
  width: 100%;
  min-height: 44px;
  display: grid;
  grid-template-columns: 8px 20px minmax(0, 1fr);
  gap: 7px;
  align-items: center;
  padding: 7px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #536176;
  text-align: left;
  cursor: pointer;
}
.workspace-outline-nav button:hover {
  background: #f5f7fa;
}
.workspace-outline-nav button.active {
  background: var(--ra-accent-soft);
  color: #1d55ad;
}
.outline-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #cbd5e1;
}
.workspace-outline-nav button.ready .outline-status-dot {
  background: #29a46f;
}
.workspace-outline-nav button.writing .outline-status-dot {
  background: var(--ra-accent);
  box-shadow: 0 0 0 4px rgba(57, 126, 236, 0.12);
}
.outline-index {
  font-size: 14px;
  font-weight: 650;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}
.outline-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 600;
}
.workspace-document {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f3f6fa;
}
.generation-stage-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: clamp(22px, 4vw, 48px);
  box-sizing: border-box;
  background:
    radial-gradient(circle at 50% 0%, rgba(57, 126, 236, 0.1), transparent 34%),
    #f3f6fa;
}
.generation-stage-card {
  width: min(900px, 100%);
  margin: 0 auto;
  padding: clamp(28px, 4vw, 48px);
  box-sizing: border-box;
  border: 1px solid #dde6f3;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.97);
  box-shadow: 0 22px 60px rgba(39, 68, 112, 0.1);
}
.generation-stage-header {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 22px;
  align-items: center;
}
.generation-orbit {
  position: relative;
  width: 70px;
  height: 70px;
  display: grid;
  place-items: center;
  border-radius: 22px;
  background: linear-gradient(145deg, #eef5ff, #f8fbff);
  color: var(--ra-accent);
}
.generation-orbit::before,
.generation-orbit::after {
  content: "";
  position: absolute;
  inset: 9px;
  border: 1px solid rgba(57, 126, 236, 0.22);
  border-radius: 50%;
}
.generation-orbit::after {
  inset: 18px;
  border-color: rgba(57, 126, 236, 0.35);
}
.generation-orbit > span {
  position: absolute;
  z-index: 2;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ra-accent);
  box-shadow: 0 0 0 5px rgba(57, 126, 236, 0.1);
}
.generation-orbit > span:first-child {
  top: 8px;
  left: 31px;
  animation: generationOrbit 2.4s linear infinite;
  transform-origin: 4px 27px;
}
.generation-orbit > span:nth-child(2) {
  right: 12px;
  bottom: 14px;
  width: 6px;
  height: 6px;
  opacity: 0.65;
  animation: pendingPulse 1.4s ease-in-out infinite;
}
.generation-orbit strong {
  position: relative;
  z-index: 3;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}
.generation-stage-eyebrow {
  color: var(--ra-accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.generation-thinking-label {
  display: flex;
  align-items: center;
  gap: 8px;
  letter-spacing: 0;
}
.generation-thinking-label .thinking-shimmer-text {
  font-weight: 700;
}
.generation-stage-header h2 {
  margin: 5px 0 7px;
  color: #1f2a3d;
  font-size: clamp(22px, 2.3vw, 30px);
  line-height: 1.3;
}
.generation-stage-header p {
  max-width: 680px;
  margin: 0;
  color: #67758a;
  font-size: 14px;
  line-height: 1.7;
}
.generation-live-summary {
  display: grid;
  grid-template-columns: 1.35fr 0.8fr 0.8fr;
  gap: 10px;
  margin-top: 28px;
}
.generation-live-summary > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 15px 16px;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
  background: #f8fafc;
}
.generation-live-summary span,
.generation-next > span {
  color: #8a96a8;
  font-size: 11px;
}
.generation-live-summary strong {
  overflow: hidden;
  color: #263248;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.generation-live-summary small {
  overflow: hidden;
  color: #7a879a;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.generation-phase-rail {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 30px 0;
}
.generation-phase {
  position: relative;
  min-width: 0;
  display: flex;
  gap: 9px;
  padding-right: 12px;
}
.generation-phase:not(:last-child)::after {
  content: "";
  position: absolute;
  top: 13px;
  right: 4px;
  left: 34px;
  height: 2px;
  background: #e3e8ef;
}
.generation-phase.completed:not(:last-child)::after {
  background: #84d3b5;
}
.generation-phase-index {
  position: relative;
  z-index: 1;
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 1px solid #d7dee8;
  border-radius: 50%;
  background: #fff;
  color: #8b97a8;
  font-size: 11px;
  font-weight: 700;
}
.generation-phase.completed .generation-phase-index {
  border-color: #32aa7d;
  background: #32aa7d;
  color: #fff;
}
.generation-phase.running .generation-phase-index {
  border: 6px solid #dceaff;
  background: var(--ra-accent);
  color: transparent;
  animation: pendingPulse 1.2s ease-in-out infinite;
}
.generation-phase > div {
  position: relative;
  z-index: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #fff;
}
.generation-phase strong {
  color: #536176;
  font-size: 12px;
  white-space: nowrap;
}
.generation-phase.running strong {
  color: var(--ra-accent);
}
.generation-phase small {
  max-width: 112px;
  color: #8c98a9;
  font-size: 9px;
  line-height: 1.35;
}
.generation-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(210px, 0.75fr);
  gap: 12px;
}
.generation-activity,
.generation-next {
  min-width: 0;
  padding: 16px;
  border: 1px solid #e5eaf1;
  border-radius: 13px;
  background: #fff;
}
.generation-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.generation-section-head > div {
  display: flex;
  align-items: baseline;
  gap: 7px;
}
.generation-section-head strong {
  color: #2b374b;
  font-size: 13px;
}
.generation-section-head span {
  color: #2da87a;
  font-size: 10px;
}
.generation-activity-list {
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.generation-activity-item,
.generation-activity-empty {
  display: grid;
  grid-template-columns: 9px minmax(0, 1fr);
  gap: 9px;
}
.generation-activity-item > span {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: #76a8f6;
}
.generation-activity-item strong,
.generation-activity-empty strong {
  display: block;
  overflow: hidden;
  color: #425068;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.generation-activity-item p,
.generation-activity-empty p,
.generation-next p {
  margin: 3px 0 0;
  color: #7b889b;
  font-size: 10px;
  line-height: 1.55;
}
.activity-loader {
  width: 8px;
  height: 8px;
  margin-top: 4px;
  border: 2px solid #d7e6ff;
  border-top-color: var(--ra-accent);
  border-radius: 50%;
  animation: generationSpin 0.85s linear infinite;
}
.generation-next {
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: linear-gradient(145deg, #f3f7ff, #f8fbff);
}
.generation-next strong {
  margin-top: 6px;
  color: #2459aa;
  font-size: 14px;
  line-height: 1.45;
}
.document-status-bar {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 14px;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--ra-border);
  font-size: 12px;
  font-weight: 650;
  flex: 0 0 auto;
}
.document-status-bar > div {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}
.document-live-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  white-space: nowrap;
}
.document-live-status::before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ra-accent);
  animation: pendingPulse 1.2s ease-in-out infinite;
}
.thinking-shimmer-text {
  display: inline-block;
  color: #68768a;
  background: linear-gradient(
    100deg,
    #7d8999 0%,
    #7d8999 34%,
    #1f5fae 48%,
    #9ba6b5 62%,
    #7d8999 100%
  );
  background-size: 240% 100%;
  background-position: 120% 0;
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: thinkingShimmer 2.15s ease-in-out infinite;
}
.thinking-breathe-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--ra-accent);
  box-shadow: 0 0 0 0 rgba(57, 126, 236, 0.2);
  animation: thinkingBreathe 1.55s ease-in-out infinite;
}
.document-thinking-strip {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 10px;
  align-items: flex-start;
  padding: 10px 16px 11px;
  border-bottom: 1px solid #e4ebf5;
  background: linear-gradient(
    90deg,
    rgba(241, 246, 255, 0.98),
    rgba(249, 251, 255, 0.98)
  );
}
.document-thinking-strip .thinking-breathe-dot {
  margin-top: 5px;
}
.document-thinking-strip > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.document-thinking-strip strong {
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.document-thinking-strip small {
  overflow: hidden;
  color: #8290a3;
  font-size: 10px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workspace-editor-wrap {
  flex: 1 1 auto;
  min-height: 0;
  padding: 24px;
  overflow: hidden;
}
.workspace-editor {
  width: min(920px, 100%);
  height: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}
.workspace-editor :deep(.n-input-wrapper),
.workspace-editor :deep(.n-input__textarea) {
  height: 100%;
}
.workspace-editor :deep(textarea.n-input__textarea-el) {
  height: 100% !important;
  min-height: 320px;
  padding: 24px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--editor-font-size, 16px);
  line-height: 1.75;
}
.workspace-sources :deep(.cards-top) {
  display: none;
}
.workspace-run-footer {
  min-height: 34px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 18px;
  padding: 5px 14px;
  box-sizing: border-box;
  background: #fff;
  border-top: 1px solid var(--ra-border);
  color: var(--ra-muted);
  font-size: 11px;
  flex: 0 0 auto;
}
.workspace-run-footer span:first-child {
  margin-right: auto;
  color: #334155;
}
.workspace-run-footer strong {
  color: var(--ra-accent);
  font-variant-numeric: tabular-nums;
}
@keyframes workspaceProgressSweep {
  from { transform: translateX(-110%); }
  to { transform: translateX(250%); }
}
@keyframes generationSpin {
  to { transform: rotate(360deg); }
}
@keyframes generationOrbit {
  to { transform: rotate(360deg); }
}
@keyframes thinkingShimmer {
  0% { background-position: 120% 0; }
  58%, 100% { background-position: -120% 0; }
}
@keyframes thinkingBreathe {
  0%, 100% {
    opacity: 0.55;
    transform: scale(0.88);
    box-shadow: 0 0 0 0 rgba(57, 126, 236, 0.18);
  }
  50% {
    opacity: 1;
    transform: scale(1);
    box-shadow: 0 0 0 6px rgba(57, 126, 236, 0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .thinking-shimmer-text {
    background: none;
    -webkit-text-fill-color: currentColor;
    animation: none;
  }
  .thinking-breathe-dot {
    animation: none;
  }
}
.drawer-tasks {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}
.list,
.cards {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--ra-border);
  border-radius: 18px;
  padding: 14px;
  overflow: auto;
  min-height: 0;
  max-height: 100%;
}
.tasks {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.create-panel,
.intake-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  flex: 1;
}
.intake-panel h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}
.create-panel {
  gap: 18px;
  padding: 12px clamp(10px, 2.4vw, 36px) 28px;
}
.create-hero {
  width: min(100%, 1100px);
  margin: 0 auto;
}
.create-hero > span {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  color: #2f6fd3;
  background: #edf4ff;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 650;
}
.create-hero h2 {
  margin: 10px 0 5px;
  color: #1d2738;
  font-size: clamp(23px, 2vw, 30px);
  font-weight: 720;
  letter-spacing: -0.02em;
}
.create-hero p {
  margin: 0;
  color: #6d7b91;
  font-size: 13px;
  line-height: 1.6;
}
.create-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: min(100%, 1100px);
  margin: 0 auto;
}
.create-primary-field,
.create-field,
.knowledge-scope-section,
.create-option-row {
  border: 1px solid #e4eaf3;
  background: #fff;
  border-radius: 14px;
}
.create-primary-field {
  padding: 15px;
  border-color: #dbe5f4;
  box-shadow: 0 10px 26px rgba(31, 50, 81, 0.055);
}
.create-field {
  min-width: 0;
  padding: 13px 14px;
}
.create-field-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.create-field-heading label {
  color: #273244;
  font-size: 13px;
  font-weight: 680;
}
.create-field-heading span {
  color: #8a96a9;
  font-size: 11px;
}
.goal-input :deep(.n-input-wrapper) {
  padding: 10px 12px;
}
.goal-input :deep(textarea.n-input__textarea-el) {
  min-height: 148px;
  color: #273244;
  font-size: 15px;
  line-height: 1.75;
}
.goal-input :deep(textarea.n-input__textarea-el::placeholder) {
  color: #a1aaba;
}
.create-secondary-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
  gap: 12px;
}
.intake-brief ul {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.45;
}
.intake-questions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.intake-diagnostics,
.intake-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.intake-diagnostics {
  color: #748197;
  font-size: 11px;
}
.intake-diagnostics > span {
  padding: 3px 8px;
  background: #f3f6fa;
  border-radius: 999px;
}
.intake-actions {
  margin-top: 2px;
}
.qa-card {
  border: 1px solid var(--ra-border);
  border-radius: 12px;
  padding: 10px 12px;
  background: #fafbfc;
}
.qa-prompt {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
  margin-bottom: 4px;
}
.qa-why {
  margin: 0 0 8px;
}
.qa-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.cards {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cards :deep(.cards-panel) {
  flex: 1 1 auto;
  min-height: 0;
}
.detail {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--ra-border);
  border-radius: 18px;
  padding: 14px;
  min-height: 0;
  max-height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.detail-top {
  flex: 0 0 auto;
  min-height: 0;
}
.preview-pane {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--ra-border);
  padding-top: 10px;
  overflow: hidden;
}
.preview-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex: 0 0 auto;
  margin-bottom: 6px;
}
.preview-toolbar .label {
  margin-bottom: 0;
}
.warn-tag {
  display: inline-block;
  font-size: 12px;
  color: #a15c00;
  background: #fff4e5;
  border: 1px solid #f0c78a;
  border-radius: 4px;
  padding: 1px 6px;
}
.ok-tag {
  display: inline-block;
  font-size: 12px;
  color: #0f6b3a;
  background: #e8f7ef;
  border: 1px solid #9dd4b5;
  border-radius: 4px;
  padding: 1px 6px;
}
.preview-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.preview-editor {
  flex: 1 1 auto;
  min-height: 180px;
}
.preview-editor :deep(.n-input-wrapper) {
  height: 100%;
}
.preview-editor :deep(textarea.n-input__textarea-el) {
  height: 100% !important;
  min-height: 180px;
  font-family: ui-monospace, "Cascadia Mono", "Sarasa Mono SC", Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}
.scorecards-bar {
  margin-top: 4px;
}
.scorecards-scroll {
  max-height: 96px;
  overflow: auto;
}
.vault-path {
  margin-top: 10px;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
.template-hint {
  margin: 7px 0 0;
  color: #56709c;
  font-size: 11px;
  line-height: 1.5;
}
.knowledge-scope-section {
  padding: 12px 14px 14px;
  background: #fbfcfe;
}
.knowledge-scope-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.knowledge-scope-heading > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.knowledge-scope-heading strong {
  color: var(--ra-text);
  font-size: 12px;
}
.knowledge-scope-heading span {
  color: var(--ra-muted);
  font-size: 10px;
}
.knowledge-scope-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(122px, 1fr));
  gap: 7px;
}
.knowledge-scope-card {
  position: relative;
  display: grid;
  grid-template-columns: 25px minmax(0, 1fr) 15px;
  align-items: center;
  gap: 7px;
  width: 100%;
  min-height: 38px;
  padding: 6px 7px;
  overflow: hidden;
  text-align: left;
  color: var(--ra-text);
  background: #fff;
  border: 1px solid #e4eaf2;
  border-radius: 9px;
  cursor: pointer;
  transition:
    border-color 150ms ease,
    background 150ms ease,
    box-shadow 150ms ease,
    transform 150ms ease;
}
.knowledge-scope-card:hover {
  border-color: #a9c8fa;
  background: #f8fbff;
}
.knowledge-scope-card.selected {
  border-color: #c6dafb;
  background: #f5f9ff;
  box-shadow: none;
}
.knowledge-scope-glyph {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 25px;
  height: 25px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 700;
}
.knowledge-scope-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}
.knowledge-scope-copy strong {
  overflow: hidden;
  font-size: 11px;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.knowledge-scope-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  color: #fff;
  background: transparent;
  border: 1px solid #ccd6e4;
  border-radius: 50%;
  font-size: 9px;
  font-weight: 700;
}
.knowledge-scope-card.selected .knowledge-scope-check {
  background: var(--ra-accent);
  border-color: var(--ra-accent);
}
.create-option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 12px 14px;
  background: #fbfcfe;
}
.create-option-row > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.create-option-row strong {
  color: #344156;
  font-size: 12px;
}
.create-option-row span {
  color: #8290a4;
  font-size: 10px;
}
.create-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding-top: 2px;
}
.create-actions p {
  margin: 0;
  color: #7f8ca0;
  font-size: 10px;
  line-height: 1.55;
}
.create-actions :deep(.n-button) {
  min-width: 190px;
  padding-inline: 24px;
}
.task {
  position: relative;
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: #f8fafc;
  border-radius: 12px;
  padding: 10px 52px 10px 10px;
  margin-bottom: 0;
  cursor: pointer;
}
.task:focus-visible {
  outline: 2px solid rgba(57, 126, 236, 0.3);
  outline-offset: 1px;
}
.task-delete {
  position: absolute;
  top: 50%;
  right: 8px;
  min-width: 34px;
  padding: 4px 5px;
  color: #8b97a9;
  background: transparent;
  border: 0;
  border-radius: 7px;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transform: translateY(-50%);
  transition: color 140ms ease, background 140ms ease, opacity 140ms ease;
}
.task:hover .task-delete,
.task:focus-within .task-delete,
.task.on .task-delete {
  opacity: 1;
}
.task-delete:hover:not(:disabled) {
  color: #d14b5a;
  background: #fff0f2;
}
.task-delete:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}
.task.on {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
}
.t-goal {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.t-meta {
  font-size: 11px;
  color: var(--ra-muted);
  margin-top: 4px;
}
.tiny {
  font-size: 11px;
  margin: 0 0 4px;
  line-height: 1.4;
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.4;
}
.mid-split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
  height: 320px;
  max-height: 320px;
  margin-bottom: 8px;
}
.legacy-hint {
  margin: 0 0 6px;
  font-size: 11px;
  line-height: 1.4;
  color: #b45309;
  background: #fffbeb;
  border-radius: 8px;
  padding: 6px 8px;
  flex: 0 0 auto;
}
.mid-col {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.mid-steps .steps {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.outline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex: 0 0 auto;
}
.outline-head .label {
  margin-bottom: 0;
}
.raw-toggle {
  border: none;
  background: transparent;
  color: var(--ra-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.raw-toggle:hover {
  color: var(--ra-accent);
}
.outline-raw-wrap,
.outline-view {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  margin-top: 6px;
}
.outline-raw-wrap {
  display: flex;
  flex-direction: column;
}
.mid-outline .outline-input {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.mid-outline .outline-input :deep(.n-input-wrapper) {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.mid-outline .outline-input :deep(.n-input__textarea) {
  height: 100%;
}
.mid-outline .outline-input :deep(textarea.n-input__textarea-el) {
  height: 100% !important;
  max-height: none !important;
  overflow-y: auto !important;
  resize: none;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
}
.outline-title {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.4;
  margin-bottom: 6px;
}
.outline-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 11px;
}
.outline-mainline {
  margin-bottom: 8px;
}
.sub-label {
  font-size: 11px;
  color: var(--ra-muted);
  margin-bottom: 4px;
}
.mainline-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #334155;
  max-height: 7.5em;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.outline-chapters,
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chapter {
  box-sizing: border-box;
  height: 32px;
  min-height: 32px;
  max-height: 32px;
  padding: 0 8px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 12px;
  align-items: center;
  overflow: hidden;
}
.step {
  box-sizing: border-box;
  flex: 0 0 auto;
  width: 100%;
  height: auto;
  max-height: none;
  min-height: 32px;
  padding: 6px 8px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  /* 高度随内容撑开，文字不跑出底色框 */
  overflow: hidden;
}
.step.clickable {
  cursor: pointer;
  transition: background 0.15s ease, box-shadow 0.15s ease;
}
.step.clickable:hover {
  box-shadow: inset 0 0 0 1px var(--ra-border);
  background: #f1f5f9;
}
.step-hint {
  font-size: 10px;
  color: var(--ra-muted);
  line-height: 1.3;
}
.step-main {
  display: grid;
  grid-template-columns: auto 72px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-height: 22px;
  flex: 0 0 auto;
}
.step-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 2px;
  min-width: 0;
  flex: 0 0 auto;
}
.step-detail {
  font-size: 11px;
  line-height: 1.4;
  color: var(--ra-muted);
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.step-detail.skill {
  font-weight: 650;
  color: #0f766e;
}
.chapter {
  display: grid;
  grid-template-columns: 18px minmax(72px, 0.9fr) auto minmax(0, 1.1fr);
  gap: 8px;
}
.chapter-idx {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--ra-accent-soft);
  color: var(--ra-accent);
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.chapter-heading {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.chapter-heading-input,
.chapter-purpose-input {
  min-width: 0;
}
.chapter-heading-input :deep(.n-input__input-el),
.chapter-purpose-input :deep(.n-input__input-el) {
  height: 24px !important;
  font-size: 12px;
}
.chapter-budget {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: var(--ra-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.budget-input {
  width: 56px;
}
.budget-input :deep(.n-input__input-el) {
  height: 24px !important;
  font-size: 12px;
}
.chapter-purpose {
  margin: 0;
  font-size: 12px;
  color: var(--ra-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.step.running {
  background: var(--ra-accent-soft);
}
.step.failed {
  background: #fef2f2;
}
.trace-empty {
  font-size: 13px;
  color: var(--ra-muted);
  line-height: 1.6;
  padding: 8px 0 4px;
}
.trace-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: min(70vh, 640px);
  overflow: auto;
  padding-right: 4px;
}
.trace-item {
  border: 1px solid var(--ra-border);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fafbfc;
}
.trace-item.llm {
  background: #f8fafc;
}
.trace-item.llm_pending {
  background: #fffbeb;
  border-color: #fcd34d;
}
.trace-live-hint {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--ra-accent, #397eec);
}
.pending-pulse {
  animation: pendingPulse 1.2s ease-in-out infinite;
}
@keyframes pendingPulse {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 1;
  }
}
.trace-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.trace-title {
  font-size: 13px;
}
.trace-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--ra-muted);
}
.trace-summary {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--ra-muted);
  line-height: 1.5;
}
.trace-field {
  margin-top: 8px;
}
.trace-field-label {
  font-size: 11px;
  font-weight: 650;
  margin-bottom: 4px;
  color: var(--ra-text, #1e293b);
}
.trace-pre {
  margin: 0;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid var(--ra-border);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
  font-family: ui-monospace, Consolas, monospace;
}
.trace-expand {
  border: none;
  background: transparent;
  color: var(--ra-accent);
  font-size: 12px;
  cursor: pointer;
  padding: 4px 0 0;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.trace-muted {
  margin: 0;
  font-size: 12px;
  color: var(--ra-muted);
}
.step-label {
  font-weight: 600;
}
.step-msg {
  color: var(--ra-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.label {
  font-size: 12px;
  font-weight: 650;
  margin-bottom: 6px;
  flex: 0 0 auto;
}
.scorecard {
  border: 1px solid var(--ra-border);
  border-radius: 12px;
  padding: 10px;
  margin-bottom: 8px;
}
.sc-head {
  display: flex;
  gap: 8px;
  align-items: center;
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 6px;
}
.dims {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.6;
}
.preview-blocks {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.md :deep(p) {
  margin: 0 0 0.5em;
  font-size: 14px;
  line-height: 1.65;
}
.err {
  color: var(--ra-danger);
  font-size: 13px;
  margin-top: 8px;
}
@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 240px minmax(0, 1fr);
  }
  .layout.create-layout {
    grid-template-columns: 240px minmax(0, 1fr);
  }
  .cards {
    display: none;
  }
  .workspace-toolbar {
    align-items: flex-start;
  }
  .workspace-title-group {
    flex-basis: 240px;
  }
  .workspace-actions {
    max-width: 70%;
  }
  .document-workspace,
  .document-workspace.sources-hidden {
    grid-template-columns: 230px minmax(0, 1fr);
  }
  .document-workspace.outline-hidden,
  .document-workspace.outline-hidden.sources-hidden {
    grid-template-columns: minmax(0, 1fr);
  }
  .workspace-sources {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(330px, 88vw);
    z-index: 5;
    box-shadow: -16px 0 36px rgba(31, 47, 76, 0.15);
  }
  .generation-live-summary {
    grid-template-columns: 1fr 1fr;
  }
  .generation-live-summary > div:first-child {
    grid-column: 1 / -1;
  }
  .generation-phase small {
    display: none;
  }
}
@media (max-width: 900px) {
  .create-panel {
    padding-inline: 10px;
  }
  .create-secondary-grid {
    grid-template-columns: 1fr;
  }
  .create-actions {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
  }
  .create-actions :deep(.n-button) {
    width: 100%;
  }
  .mid-split {
    grid-template-columns: 1fr;
  }
  .workspace-toolbar {
    flex-direction: column;
  }
  .workspace-title-group,
  .workspace-actions {
    width: 100%;
    max-width: none;
  }
  .workspace-title-group {
    flex-wrap: wrap;
  }
  .workspace-actions {
    justify-content: flex-start;
  }
  .document-workspace,
  .document-workspace.sources-hidden {
    grid-template-columns: minmax(0, 1fr);
  }
  .workspace-outline {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(290px, 88vw);
    z-index: 5;
    box-shadow: 16px 0 36px rgba(31, 47, 76, 0.15);
  }
  .workspace-run-footer span:nth-child(2) {
    display: none;
  }
  .generation-stage-scroll {
    padding: 16px;
  }
  .generation-stage-card {
    padding: 24px;
    border-radius: 15px;
  }
  .generation-stage-header {
    grid-template-columns: 58px minmax(0, 1fr);
    gap: 14px;
  }
  .generation-orbit {
    width: 56px;
    height: 56px;
    border-radius: 17px;
  }
  .generation-orbit > span:first-child {
    top: 5px;
    left: 24px;
    transform-origin: 4px 23px;
  }
  .generation-phase-rail {
    grid-template-columns: 1fr;
    gap: 9px;
  }
  .generation-phase:not(:last-child)::after {
    top: 26px;
    bottom: -9px;
    left: 13px;
    width: 2px;
    height: auto;
  }
  .generation-phase > div {
    min-height: 31px;
  }
  .generation-detail-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .knowledge-scope-grid {
    grid-template-columns: 1fr;
  }
  .generation-live-summary {
    grid-template-columns: 1fr;
  }
  .generation-live-summary > div:first-child {
    grid-column: auto;
  }
  .generation-stage-header {
    grid-template-columns: 1fr;
  }
  .generation-orbit {
    display: none;
  }
}
</style>
