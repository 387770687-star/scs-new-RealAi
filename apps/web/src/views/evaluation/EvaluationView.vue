<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NDataTable,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NModal,
  NProgress,
  NSelect,
  NSpace,
  NStatistic,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
  type SelectOption,
} from "naive-ui";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import {
  addEvalCase,
  cancelEvalRun,
  createEvalSuite,
  deleteEvalCase,
  deleteEvalSuite,
  duplicateEvalCase,
  exportEvalSuite,
  fetchEvalOverview,
  fetchRealAiConfig,
  fetchSkillsWorkshop,
  getEvalSuite,
  importEvalSuite,
  listEvalRuns,
  listEvalSuites,
  pollEvalRun,
  retryFailedEvalRun,
  seedEvalSuites,
  startEvalRun,
  updateEvalCase,
  validateEvalSuite,
} from "@/api/realai";
import type { EvalCase, EvalCaseResult, EvalRun, EvalSuite, SkillSummary } from "@/api/types";

type ValidationResult = Awaited<ReturnType<typeof validateEvalSuite>>;
type Overview = Awaited<ReturnType<typeof fetchEvalOverview>>;

type CaseDraft = {
  id?: string;
  question: string;
  category: string;
  mode: string;
  intent: string;
  difficulty: string;
  expectAnswer: string;
  answerMatchMode: string;
  expectNumber: number | null;
  expectUnit: string;
  tolerance: number | null;
  keywords: string;
  expectEvidence: boolean;
  evidenceKinds: string[];
  sourcePaths: string;
  tableJson: string;
  rubricJson: string;
  fixtureJson: string;
  tags: string;
  notes: string;
};

const message = useMessage();
const dialog = useDialog();

const suites = ref<EvalSuite[]>([]);
const activeSuite = ref<EvalSuite | null>(null);
const runs = ref<EvalRun[]>([]);
const overview = ref<Overview | null>(null);
const validation = ref<ValidationResult | null>(null);
const loading = ref(false);
const seeding = ref(false);
const running = ref(false);
const runProgress = ref("");
const activeRunId = ref("");
const suiteName = ref("");
const suiteSearch = ref("");
const activeTab = ref("overview");
const categoryFilter = ref("");
const selectedRun = ref<EvalRun | null>(null);
const selectedResult = ref<EvalCaseResult | null>(null);
const detailOpen = ref(false);
const caseOpen = ref(false);
const savingCase = ref(false);
const cancelled = ref(false);

const webSearch = ref(false);
const modelOverride = ref("");
const judgeEnabled = ref(false);
const judgeModel = ref("");
const writerSkill = ref("");
const reviewSkill = ref("");
const concurrency = ref(3);
const lightTimeout = ref(180);
const reportTimeout = ref(900);
const models = ref<Array<{ id: string; label: string; apiModel: string }>>([]);
const skills = ref<SkillSummary[]>([]);

function emptyDraft(): CaseDraft {
  return {
    question: "",
    category: "data",
    mode: "light",
    intent: "data",
    difficulty: "medium",
    expectAnswer: "",
    answerMatchMode: "contains",
    expectNumber: null,
    expectUnit: "",
    tolerance: 0.01,
    keywords: "",
    expectEvidence: true,
    evidenceKinds: ["data"],
    sourcePaths: "",
    tableJson: '{\n  "columns": [],\n  "rows": [],\n  "match_mode": "subset"\n}',
    rubricJson: "{}",
    fixtureJson: "{}",
    tags: "",
    notes: "",
  };
}

const caseDraft = ref<CaseDraft>(emptyDraft());

const categoryOptions: SelectOption[] = [
  { label: "精确问数", value: "data" },
  { label: "知识检索", value: "retrieve" },
  { label: "图表 / 多模态", value: "viz" },
  { label: "综合分析", value: "mixed" },
  { label: "报告写作", value: "report" },
  { label: "拒答与安全", value: "safety" },
  { label: "其他", value: "general" },
];

const filterOptions: SelectOption[] = [{ label: "全部类型", value: "" }, ...categoryOptions];
const modeOptions: SelectOption[] = [
  { label: "轻量问答", value: "light" },
  { label: "报告", value: "report" },
];
const intentOptions: SelectOption[] = [
  { label: "问数 data", value: "data" },
  { label: "检索 research", value: "research" },
  { label: "综合问答 ask", value: "ask" },
];
const matchOptions: SelectOption[] = [
  { label: "包含", value: "contains" },
  { label: "完全一致", value: "exact" },
  { label: "正则表达式", value: "regex" },
];
const difficultyOptions: SelectOption[] = [
  { label: "简单", value: "easy" },
  { label: "中等", value: "medium" },
  { label: "困难", value: "hard" },
];
const evidenceOptions: SelectOption[] = [
  { label: "结构化数据", value: "data" },
  { label: "知识库", value: "kb" },
  { label: "图片 / 图表", value: "viz" },
  { label: "联网", value: "web" },
  { label: "推理", value: "inference" },
];

const filteredSuites = computed(() => {
  const q = suiteSearch.value.trim().toLowerCase();
  return q ? suites.value.filter((suite) => suite.name.toLowerCase().includes(q)) : suites.value;
});

const filteredCases = computed(() => {
  const list = activeSuite.value?.cases || [];
  return categoryFilter.value
    ? list.filter((item) => (item.category || "general") === categoryFilter.value)
    : list;
});

const modelOptions = computed<SelectOption[]>(() =>
  models.value.map((model) => ({
    label: `${model.label} · ${model.apiModel}`,
    value: model.id,
  })),
);

const skillOptions = computed<SelectOption[]>(() =>
  skills.value
    .filter((skill) => skill.valid && skill.enabled !== false)
    .map((skill) => ({ label: skill.name, value: skill.id })),
);

const latest = computed(() => overview.value?.latest || null);
const latestPass = computed(() =>
  latest.value?.pass_rate == null ? null : Math.round(Number(latest.value.pass_rate) * 100),
);
const validationTone = computed(() =>
  validation.value?.errors ? "error" : validation.value?.warnings ? "warning" : "success",
);

function categoryLabel(value?: string) {
  return String(categoryOptions.find((item) => item.value === value)?.label || value || "其他");
}

function statusLabel(status?: string) {
  return (
    {
      completed: "已完成",
      running: "运行中",
      failed: "已中断",
      cancelled: "已取消",
      empty: "无结果",
    }[status || ""] || status || "未知"
  );
}

function statusType(status?: string): "success" | "warning" | "error" | "default" {
  if (status === "completed") return "success";
  if (status === "running") return "warning";
  if (status === "failed") return "error";
  return "default";
}

function stageLabel(stage?: unknown) {
  const value = String(stage || "");
  return (
    {
      calculation: "数值计算",
      structured_data: "表格结果",
      query_planning: "查询规划",
      data_retrieval: "数据命中",
      source_selection: "来源选择",
      retrieval: "知识检索",
      citation: "引用支撑",
      writing: "报告写作",
      model: "模型调用",
      synthesis: "答案生成",
      timeout: "执行超时",
      runtime: "运行异常",
    }[value] || value || "—"
  );
}

function assertionSummary(row: EvalCase) {
  const parts: string[] = [];
  if (row.expect_answer) parts.push("答案");
  if (row.expect_number != null) parts.push(`数值 ${row.expect_number}${row.expect_unit || ""}`);
  if ((row.expect_table?.columns || []).length || (row.expect_table?.rows || []).length) parts.push("表格");
  if ((row.expect_source_paths || []).length) parts.push("指定来源");
  if (row.expect_evidence) parts.push("证据");
  if (Object.keys(row.rubric || {}).length) parts.push("评分规则");
  if ((row.expect_keywords || []).length) parts.push("关键词");
  return parts.length ? parts.join(" · ") : "未配置可验证结果";
}

const caseColumns: DataTableColumns<EvalCase> = [
  {
    title: "类型",
    key: "category",
    width: 110,
    render: (row) => h(NTag, { size: "small", bordered: false }, { default: () => categoryLabel(row.category) }),
  },
  {
    title: "问题",
    key: "question",
    minWidth: 260,
    ellipsis: { tooltip: true },
  },
  {
    title: "验证标准",
    key: "assertions",
    minWidth: 260,
    ellipsis: { tooltip: true },
    render: assertionSummary,
  },
  {
    title: "难度",
    key: "difficulty",
    width: 70,
    render: (row) => ({ easy: "简单", medium: "中等", hard: "困难" })[row.difficulty || "medium"],
  },
  {
    title: "版本",
    key: "version",
    width: 60,
    render: (row) => `v${row.version || 1}`,
  },
  {
    title: "操作",
    key: "actions",
    width: 190,
    render: (row) =>
      h(
        NSpace,
        { size: 2, wrap: false },
        {
          default: () => [
            h(NButton, { size: "tiny", quaternary: true, type: "primary", onClick: () => openEditCase(row) }, { default: () => "编辑" }),
            h(NButton, { size: "tiny", quaternary: true, onClick: () => copyCase(row) }, { default: () => "复制" }),
            h(NButton, { size: "tiny", quaternary: true, type: "error", onClick: () => confirmDeleteCase(row) }, { default: () => "删除" }),
          ],
        },
      ),
  },
];

const runColumns: DataTableColumns<EvalRun> = [
  {
    title: "状态",
    key: "status",
    width: 90,
    render: (row) =>
      h(NTag, { size: "small", type: statusType(row.status), bordered: false }, { default: () => statusLabel(row.status) }),
  },
  {
    title: "通过",
    key: "passed",
    width: 90,
    render: (row) => (row.passed == null ? "—" : `${row.passed}/${Math.max(0, Number(row.total || 0) - Number(row.skipped || 0))}`),
  },
  {
    title: "准确率",
    key: "pass_rate",
    width: 88,
    render: (row) => (row.pass_rate == null ? "—" : `${Math.round(Number(row.pass_rate) * 100)}%`),
  },
  {
    title: "综合得分",
    key: "score",
    width: 90,
    render: (row) => (row.metrics?.avg_score == null ? "—" : Number(row.metrics.avg_score).toFixed(1)),
  },
  {
    title: "平均耗时",
    key: "latency",
    width: 100,
    render: (row) => (row.metrics?.avg_latency_ms == null ? "—" : `${(Number(row.metrics.avg_latency_ms) / 1000).toFixed(1)}s`),
  },
  {
    title: "模型",
    key: "model",
    minWidth: 140,
    ellipsis: { tooltip: true },
    render: (row) => row.model_override || String((row.snapshot as any)?.llm?.model || "系统默认"),
  },
  {
    title: "时间",
    key: "created_at",
    width: 170,
    render: (row) => new Date(row.created_at * 1000).toLocaleString(),
  },
  {
    title: "",
    key: "detail",
    width: 76,
    render: (row) =>
      h(NButton, { size: "tiny", type: "primary", quaternary: true, onClick: () => openRunDetail(row) }, { default: () => "详情" }),
  },
];

const resultColumns: DataTableColumns<EvalCaseResult> = [
  {
    title: "结果",
    key: "passed",
    width: 72,
    render: (row) =>
      h(
        NTag,
        { size: "small", bordered: false, type: row.skipped ? "default" : row.passed ? "success" : "error" },
        { default: () => (row.skipped ? "跳过" : row.passed ? "通过" : "失败") },
      ),
  },
  { title: "问题", key: "question", minWidth: 240, ellipsis: { tooltip: true } },
  {
    title: "得分",
    key: "score",
    width: 70,
    render: (row) => String((row.meta as any)?.overall_score ?? "—"),
  },
  {
    title: "失败环节",
    key: "stage",
    width: 100,
    render: (row) => stageLabel((row.meta as any)?.failure_stage),
  },
  {
    title: "耗时",
    key: "duration",
    width: 78,
    render: (row) => (row.duration_ms == null ? "—" : `${(row.duration_ms / 1000).toFixed(1)}s`),
  },
  {
    title: "",
    key: "detail",
    width: 70,
    render: (row) =>
      h(NButton, { size: "tiny", quaternary: true, type: "primary", onClick: () => (selectedResult.value = row) }, { default: () => "诊断" }),
  },
];

async function loadCapabilities() {
  try {
    const [config, workshop] = await Promise.all([fetchRealAiConfig(), fetchSkillsWorkshop()]);
    models.value = (config.settings?.llm?.models || []).map((model) => ({
      id: model.id,
      label: model.label || model.apiModel,
      apiModel: model.apiModel,
    }));
    skills.value = workshop.skills || [];
  } catch {
    models.value = [];
    skills.value = [];
  }
}

async function load() {
  loading.value = true;
  try {
    const response = await listEvalSuites();
    suites.value = response.suites;
    if (activeSuite.value && response.suites.some((suite) => suite.id === activeSuite.value?.id)) {
      await openSuite(activeSuite.value.id);
    } else if (response.suites[0]) {
      await openSuite(response.suites[0].id);
    } else {
      activeSuite.value = null;
      runs.value = [];
      overview.value = null;
      validation.value = null;
    }
  } catch (error) {
    message.error(error instanceof Error ? error.message : "加载评测中心失败");
  } finally {
    loading.value = false;
  }
}

async function openSuite(id: string) {
  try {
    const [suite, history, summary, checked] = await Promise.all([
      getEvalSuite(id),
      listEvalRuns(id),
      fetchEvalOverview(id),
      validateEvalSuite(id),
    ]);
    activeSuite.value = suite;
    runs.value = history.runs;
    overview.value = summary;
    validation.value = checked;
    selectedResult.value = null;
  } catch (error) {
    message.error(error instanceof Error ? error.message : "打开评测套件失败");
  }
}

async function createSuite() {
  const name = suiteName.value.trim();
  if (!name) {
    message.warning("请填写套件名称");
    return;
  }
  try {
    const suite = await createEvalSuite(name);
    suiteName.value = "";
    await load();
    await openSuite(suite.id);
    activeTab.value = "cases";
    openNewCase();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "新建失败");
  }
}

async function importSeed(recreate = false) {
  seeding.value = true;
  try {
    const response = await seedEvalSuites(recreate);
    message.success(recreate ? "示例套件已按新版标准重建" : "已导入示例套件");
    await load();
    if (response.suite_ids?.[0]) await openSuite(response.suite_ids[0]);
  } catch (error) {
    message.error(error instanceof Error ? error.message : "导入示例失败");
  } finally {
    seeding.value = false;
  }
}

function openNewCase() {
  caseDraft.value = emptyDraft();
  caseOpen.value = true;
}

function openEditCase(row: EvalCase) {
  caseDraft.value = {
    id: row.id,
    question: row.question,
    category: row.category || "general",
    mode: row.mode || "light",
    intent: row.intent || "ask",
    difficulty: row.difficulty || "medium",
    expectAnswer: row.expect_answer || "",
    answerMatchMode: row.answer_match_mode || "contains",
    expectNumber: row.expect_number ?? null,
    expectUnit: row.expect_unit || "",
    tolerance: row.number_tolerance ?? 0.01,
    keywords: (row.expect_keywords || []).join("，"),
    expectEvidence: row.expect_evidence !== false,
    evidenceKinds: row.expect_evidence_kinds || [],
    sourcePaths: (row.expect_source_paths || []).join("\n"),
    tableJson: JSON.stringify(row.expect_table || {}, null, 2),
    rubricJson: JSON.stringify(row.rubric || {}, null, 2),
    fixtureJson: JSON.stringify(row.fixture || {}, null, 2),
    tags: (row.tags || []).join("，"),
    notes: row.notes || "",
  };
  caseOpen.value = true;
}

function parseJsonField(text: string, label: string) {
  const value = text.trim();
  if (!value) return {};
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label}不是有效 JSON`);
  }
}

async function saveCase() {
  if (!activeSuite.value || !caseDraft.value.question.trim()) {
    message.warning("请填写测试问题");
    return;
  }
  savingCase.value = true;
  try {
    const draft = caseDraft.value;
    const payload: Partial<EvalCase> & { question: string } = {
      question: draft.question.trim(),
      category: draft.category,
      mode: draft.mode,
      intent: draft.mode === "report" ? "ask" : draft.intent,
      difficulty: draft.difficulty,
      expect_answer: draft.expectAnswer.trim() || null,
      answer_match_mode: draft.answerMatchMode,
      expect_number: draft.expectNumber,
      expect_unit: draft.expectUnit.trim() || null,
      number_tolerance: draft.tolerance,
      expect_keywords: draft.keywords.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean),
      expect_evidence: draft.expectEvidence,
      expect_evidence_kinds: draft.evidenceKinds,
      expect_source_paths: draft.sourcePaths.split(/\n|[,，]/).map((item) => item.trim()).filter(Boolean),
      expect_table: parseJsonField(draft.tableJson, "期望表格"),
      rubric: parseJsonField(draft.rubricJson, "评分规则"),
      fixture: parseJsonField(draft.fixtureJson, "测试附件"),
      tags: draft.tags.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean),
      notes: draft.notes,
    };
    if (draft.id) await updateEvalCase(draft.id, payload);
    else await addEvalCase(activeSuite.value.id, payload);
    message.success(draft.id ? "用例已更新并生成新版本" : "用例已添加");
    caseOpen.value = false;
    await openSuite(activeSuite.value.id);
  } catch (error) {
    message.error(error instanceof Error ? error.message : "保存用例失败");
  } finally {
    savingCase.value = false;
  }
}

async function copyCase(row: EvalCase) {
  try {
    await duplicateEvalCase(row.id);
    message.success("已复制用例");
    if (activeSuite.value) await openSuite(activeSuite.value.id);
  } catch (error) {
    message.error(error instanceof Error ? error.message : "复制失败");
  }
}

function confirmDeleteCase(row: EvalCase) {
  dialog.warning({
    title: "删除用例",
    content: `确定删除「${row.question.slice(0, 50)}」？历史运行结果不会被改写。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      await deleteEvalCase(row.id);
      message.success("用例已删除");
      if (activeSuite.value) await openSuite(activeSuite.value.id);
    },
  });
}

async function run() {
  if (!activeSuite.value) return;
  if (!activeSuite.value.cases?.length) {
    message.warning("当前套件没有用例");
    return;
  }
  running.value = true;
  cancelled.value = false;
  runProgress.value = `准备运行 0/${activeSuite.value.cases.length}`;
  activeTab.value = "runs";
  try {
    validation.value = await validateEvalSuite(activeSuite.value.id);
    if (validation.value.errors) {
      message.error(`套件有 ${validation.value.errors} 个阻断问题，请先修复`);
      activeTab.value = "cases";
      return;
    }
    const previous = runs.value.find((item) => item.status === "completed");
    const started = await startEvalRun(activeSuite.value.id, {
      webSearchEnabled: webSearch.value,
      modelOverride: modelOverride.value || null,
      skillOverrides: {
        ...(writerSkill.value ? { writer: writerSkill.value } : {}),
        ...(reviewSkill.value ? { review: reviewSkill.value } : {}),
      },
      compareBaseRunId: previous?.id || null,
      concurrency: concurrency.value,
      lightTimeoutSeconds: lightTimeout.value,
      reportTimeoutSeconds: reportTimeout.value,
      judgeEnabled: judgeEnabled.value,
      judgeModelOverride: judgeModel.value || null,
    });
    activeRunId.value = started.id;
    const finished = await pollEvalRun(started.id, (tick) => {
      if (cancelled.value) return;
      runProgress.value = `正在运行 ${tick.progress?.done || 0}/${tick.progress?.total || activeSuite.value?.cases?.length || 0}`;
    });
    await openSuite(activeSuite.value.id);
    openRunDetail(finished);
    if (finished.status === "completed") {
      message.success(`评测完成：${finished.passed || 0}/${Math.max(0, Number(finished.total || 0) - Number(finished.skipped || 0))} 通过`);
    } else {
      message.warning(statusLabel(finished.status));
    }
  } catch (error) {
    message.error(error instanceof Error ? error.message : "运行失败");
    if (activeSuite.value) await openSuite(activeSuite.value.id);
  } finally {
    running.value = false;
    activeRunId.value = "";
    runProgress.value = "";
  }
}

async function cancelCurrent() {
  if (!activeRunId.value) return;
  try {
    await cancelEvalRun(activeRunId.value);
    cancelled.value = true;
    message.info("正在取消评测任务");
  } catch (error) {
    message.error(error instanceof Error ? error.message : "取消失败");
  }
}

async function retryFailed(row: EvalRun) {
  try {
    const started = await retryFailedEvalRun(row.id);
    message.success(`已重新运行失败用例：${started.total || 0} 题`);
    if (activeSuite.value) await openSuite(activeSuite.value.id);
    activeTab.value = "runs";
  } catch (error) {
    message.error(error instanceof Error ? error.message : "重跑失败");
  }
}

function openRunDetail(row: EvalRun) {
  selectedRun.value = row;
  selectedResult.value = null;
  detailOpen.value = true;
}

function pretty(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

async function doExport() {
  if (!activeSuite.value) return;
  const payload = await exportEvalSuite(activeSuite.value.id);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = `${payload.name || "eval-suite"}.json`;
  anchor.click();
  URL.revokeObjectURL(anchor.href);
}

function doImportFile() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/json,.json";
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      if (!payload.name || !Array.isArray(payload.cases)) throw new Error("JSON需要包含 name 与 cases");
      const suite = await importEvalSuite(payload);
      message.success("评测套件已导入");
      await load();
      await openSuite(suite.id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "导入失败");
    }
  };
  input.click();
}

function removeSuite() {
  if (!activeSuite.value) return;
  const target = activeSuite.value;
  dialog.warning({
    title: "删除评测套件",
    content: `将删除「${target.name}」、全部用例和历史运行记录，此操作不可恢复。`,
    positiveText: "确认删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      await deleteEvalSuite(target.id);
      activeSuite.value = null;
      await load();
    },
  });
}

onMounted(async () => {
  await Promise.all([loadCapabilities(), load()]);
});

onUnmounted(() => {
  cancelled.value = true;
});
</script>

<template>
  <div class="page ra-fade-in">
    <PageHeader title="评测中心">
      <template #actions>
        <NSpace>
          <NButton secondary :loading="loading" @click="load">刷新</NButton>
          <NButton secondary @click="doImportFile">导入套件</NButton>
        </NSpace>
      </template>
    </PageHeader>

    <div class="workspace">
      <aside class="suite-panel">
        <div class="suite-create">
          <NInput v-model:value="suiteName" size="small" placeholder="新套件名称" @keyup.enter="createSuite" />
          <NButton size="small" type="primary" @click="createSuite">新建</NButton>
        </div>
        <NInput v-model:value="suiteSearch" size="small" clearable placeholder="搜索套件" />
        <div class="suite-list">
          <button
            v-for="suite in filteredSuites"
            :key="suite.id"
            type="button"
            class="suite-item"
            :class="{ active: activeSuite?.id === suite.id }"
            @click="openSuite(suite.id)"
          >
            <span class="suite-name">{{ suite.name }}</span>
            <span class="suite-meta">{{ suite.case_count ?? suite.cases?.length ?? 0 }} 题</span>
          </button>
        </div>
        <NButton block secondary type="primary" :loading="seeding" @click="importSeed(false)">
          导入系统示例
        </NButton>
      </aside>

      <main class="main-panel">
        <template v-if="activeSuite">
          <div class="suite-head">
            <div>
              <div class="title-line">
                <h2>{{ activeSuite.name }}</h2>
                <NTag
                  v-if="validation"
                  size="small"
                  :type="validationTone"
                  :bordered="false"
                >
                  {{
                    validation.errors
                      ? `${validation.errors} 个阻断问题`
                      : validation.warnings
                        ? `${validation.warnings} 条质量提醒`
                        : "可运行"
                  }}
                </NTag>
              </div>
              <p>{{ activeSuite.description || "通过黄金用例持续验证模型、Skill与知识库质量。" }}</p>
            </div>
            <NSpace>
              <NButton tertiary @click="doExport">导出</NButton>
              <NButton tertiary :loading="seeding" @click="importSeed(true)">重建系统示例</NButton>
              <NButton tertiary type="error" @click="removeSuite">删除</NButton>
              <NButton v-if="running" type="error" secondary @click="cancelCurrent">取消运行</NButton>
              <NButton v-else type="primary" @click="run">开始评测</NButton>
            </NSpace>
          </div>

          <NAlert v-if="runProgress" type="info" :show-icon="false" class="run-alert">
            {{ runProgress }}
            <NProgress
              type="line"
              :percentage="
                Math.round(
                  ((Number(runProgress.match(/(\d+)\/(\d+)/)?.[1]) || 0) /
                    (Number(runProgress.match(/(\d+)\/(\d+)/)?.[2]) || 1)) *
                    100,
                )
              "
              :show-indicator="false"
              style="margin-top: 8px"
            />
          </NAlert>

          <NTabs v-model:value="activeTab" type="line" animated>
            <NTabPane name="overview" tab="质量概览">
              <NGrid :cols="4" :x-gap="12" responsive="screen">
                <NGridItem>
                  <NCard size="small" class="metric-card">
                    <NStatistic label="最新准确率" :value="latestPass == null ? '—' : `${latestPass}%`" />
                  </NCard>
                </NGridItem>
                <NGridItem>
                  <NCard size="small" class="metric-card">
                    <NStatistic label="综合得分" :value="latest?.metrics?.avg_score == null ? '—' : Number(latest.metrics.avg_score).toFixed(1)" />
                  </NCard>
                </NGridItem>
                <NGridItem>
                  <NCard size="small" class="metric-card">
                    <NStatistic label="平均响应" :value="latest?.metrics?.avg_latency_ms == null ? '—' : `${(Number(latest.metrics.avg_latency_ms) / 1000).toFixed(1)}s`" />
                  </NCard>
                </NGridItem>
                <NGridItem>
                  <NCard size="small" class="metric-card">
                    <NStatistic label="有效运行" :value="overview?.completed_count ?? 0" />
                  </NCard>
                </NGridItem>
              </NGrid>

              <div class="overview-grid">
                <NCard title="质量趋势" size="small">
                  <div v-if="overview?.trend?.length" class="trend-list">
                    <div v-for="item in overview.trend" :key="item.id" class="trend-row">
                      <span>{{ new Date(item.created_at * 1000).toLocaleDateString() }}</span>
                      <NProgress
                        type="line"
                        :percentage="Math.round(Number(item.pass_rate || 0) * 100)"
                        :status="Number(item.pass_rate || 0) >= 0.8 ? 'success' : 'warning'"
                      />
                      <span>{{ item.avg_score == null ? "—" : Number(item.avg_score).toFixed(1) }} 分</span>
                    </div>
                  </div>
                  <EmptyState v-else text="完成一次评测后显示趋势" />
                </NCard>
                <NCard title="失败归因" size="small">
                  <div v-if="Object.keys(overview?.failure_stages || {}).length" class="failure-grid">
                    <div v-for="(count, stage) in overview?.failure_stages" :key="stage" class="failure-item">
                      <span>{{ stageLabel(stage) }}</span>
                      <strong>{{ count }}</strong>
                    </div>
                  </div>
                  <EmptyState v-else text="暂无失败数据" />
                </NCard>
              </div>

              <NAlert
                v-if="validation && (validation.errors || validation.warnings)"
                :type="validation.errors ? 'error' : 'warning'"
                class="quality-alert"
              >
                <strong>套件质量检查</strong>
                <div v-for="(issue, index) in validation.issues.slice(0, 8)" :key="index">
                  · {{ activeSuite.cases?.find((item) => item.id === issue.case_id)?.question || issue.case_id }}：{{ issue.message }}
                </div>
              </NAlert>
            </NTabPane>

            <NTabPane name="cases" :tab="`用例库 ${activeSuite.cases?.length || 0}`">
              <div class="toolbar">
                <NSelect
                  v-model:value="categoryFilter"
                  :options="filterOptions"
                  size="small"
                  style="width: 160px"
                />
                <span class="toolbar-spacer" />
                <NButton type="primary" @click="openNewCase">新建用例</NButton>
              </div>
              <NDataTable
                v-if="filteredCases.length"
                :columns="caseColumns"
                :data="filteredCases"
                :bordered="false"
                size="small"
                :pagination="{ pageSize: 12 }"
              />
              <EmptyState v-else text="当前分类暂无评测用例" />
            </NTabPane>

            <NTabPane name="runs" tab="运行与历史">
              <NCard title="运行配置" size="small" class="run-config">
                <div class="config-grid">
                  <label>
                    <span>执行模型</span>
                    <NSelect
                      v-model:value="modelOverride"
                      :options="modelOptions"
                      clearable
                      placeholder="系统默认模型"
                    />
                  </label>
                  <label>
                    <span>写作 Skill</span>
                    <NSelect v-model:value="writerSkill" :options="skillOptions" clearable placeholder="系统默认" />
                  </label>
                  <label>
                    <span>评审 Skill</span>
                    <NSelect v-model:value="reviewSkill" :options="skillOptions" clearable placeholder="系统默认" />
                  </label>
                  <label>
                    <span>并发数</span>
                    <NInputNumber v-model:value="concurrency" :min="1" :max="6" />
                  </label>
                  <label>
                    <span>问答超时（秒）</span>
                    <NInputNumber v-model:value="lightTimeout" :min="30" :max="1800" />
                  </label>
                  <label>
                    <span>报告超时（秒）</span>
                    <NInputNumber v-model:value="reportTimeout" :min="60" :max="3600" />
                  </label>
                  <label class="switch-label">
                    <span>允许联网</span>
                    <NSwitch v-model:value="webSearch" />
                  </label>
                  <label class="switch-label">
                    <span>智能裁判</span>
                    <NSwitch v-model:value="judgeEnabled" />
                  </label>
                  <label v-if="judgeEnabled">
                    <span>裁判模型</span>
                    <NSelect v-model:value="judgeModel" :options="modelOptions" clearable placeholder="与执行模型一致" />
                  </label>
                </div>
                <div class="run-actions">
                  <span class="muted">本次运行会固化模型、Skill、知识库快照和用例版本，可与上一次结果直接比较。</span>
                  <NButton v-if="running" type="error" secondary @click="cancelCurrent">取消</NButton>
                  <NButton v-else type="primary" @click="run">运行全部用例</NButton>
                </div>
              </NCard>

              <h3>运行历史</h3>
              <NDataTable
                v-if="runs.length"
                :columns="runColumns"
                :data="runs"
                :bordered="false"
                size="small"
                :pagination="{ pageSize: 10 }"
              />
              <EmptyState v-else text="暂无运行记录" />
            </NTabPane>

            <NTabPane name="compare" tab="版本对比">
              <template v-if="runs.some((item) => item.status === 'completed')">
                <NAlert type="info" :show-icon="false">
                  每次运行会自动与上一次成功运行比较，下面展示最近一次回归结果。打开任一运行详情可查看逐题得分变化。
                </NAlert>
                <div v-if="latest?.regression" class="compare-grid">
                  <NCard size="small" title="新增失败">
                    <NStatistic :value="latest.regression.new_failures?.length || 0" />
                    <p v-for="item in latest.regression.new_failures || []" :key="item.case_id || item.question">
                      {{ item.question }}
                    </p>
                  </NCard>
                  <NCard size="small" title="已修复">
                    <NStatistic :value="latest.regression.fixed?.length || 0" />
                    <p v-for="item in latest.regression.fixed || []" :key="item.case_id || item.question">
                      {{ item.question }}
                    </p>
                  </NCard>
                  <NCard size="small" title="得分变化">
                    <p v-for="item in latest.regression.score_changes || []" :key="item.case_id || item.question">
                      {{ item.question }}：{{ item.before }} → {{ item.after }}
                    </p>
                    <span v-if="!latest.regression.score_changes?.length" class="muted">暂无变化</span>
                  </NCard>
                </div>
                <EmptyState v-else text="再运行一次同一套件后生成版本对比" />
              </template>
              <EmptyState v-else text="尚无可对比的已完成运行" />
            </NTabPane>
          </NTabs>
        </template>

        <div v-else class="empty-main">
          <EmptyState text="新建或选择一个评测套件开始" />
          <NButton type="primary" :loading="seeding" @click="importSeed(false)">导入系统示例</NButton>
        </div>
      </main>
    </div>

    <NModal
      v-model:show="caseOpen"
      preset="card"
      :title="caseDraft.id ? '编辑评测用例' : '新建评测用例'"
      style="width: min(980px, 96vw)"
      :bordered="false"
    >
      <div class="case-form">
        <label class="full">
          <span>测试问题 / 报告目标</span>
          <NInput v-model:value="caseDraft.question" type="textarea" :rows="2" />
        </label>
        <label>
          <span>场景类型</span>
          <NSelect v-model:value="caseDraft.category" :options="categoryOptions" />
        </label>
        <label>
          <span>执行模式</span>
          <NSelect v-model:value="caseDraft.mode" :options="modeOptions" />
        </label>
        <label>
          <span>意图路由</span>
          <NSelect v-model:value="caseDraft.intent" :options="intentOptions" :disabled="caseDraft.mode === 'report'" />
        </label>
        <label>
          <span>难度</span>
          <NSelect v-model:value="caseDraft.difficulty" :options="difficultyOptions" />
        </label>
        <label class="wide">
          <span>期望答案</span>
          <NInput v-model:value="caseDraft.expectAnswer" placeholder="可填写关键结论或完整标准答案" />
        </label>
        <label>
          <span>答案匹配方式</span>
          <NSelect v-model:value="caseDraft.answerMatchMode" :options="matchOptions" />
        </label>
        <label>
          <span>期望数值</span>
          <NInputNumber v-model:value="caseDraft.expectNumber" clearable />
        </label>
        <label>
          <span>单位</span>
          <NInput v-model:value="caseDraft.expectUnit" placeholder="万元、%、km…" />
        </label>
        <label>
          <span>允许误差</span>
          <NInputNumber v-model:value="caseDraft.tolerance" :min="0" />
        </label>
        <label>
          <span>关键词</span>
          <NInput v-model:value="caseDraft.keywords" placeholder="逗号分隔" />
        </label>
        <label class="wide">
          <span>必须引用的来源路径</span>
          <NInput v-model:value="caseDraft.sourcePaths" type="textarea" :rows="2" placeholder="每行一个文件、表或目录路径" />
        </label>
        <label>
          <span>证据要求</span>
          <div class="evidence-box">
            <NCheckbox v-model:checked="caseDraft.expectEvidence">必须返回证据</NCheckbox>
            <NSelect
              v-model:value="caseDraft.evidenceKinds"
              :options="evidenceOptions"
              multiple
              clearable
              placeholder="指定证据类型"
            />
          </div>
        </label>
        <label class="full">
          <span>期望表格 JSON</span>
          <NInput v-model:value="caseDraft.tableJson" type="textarea" :rows="6" class="code-input" />
        </label>
        <label class="wide">
          <span>报告/智能评审规则 JSON</span>
          <NInput v-model:value="caseDraft.rubricJson" type="textarea" :rows="6" class="code-input" />
        </label>
        <label>
          <span>测试附件 JSON</span>
          <NInput
            v-model:value="caseDraft.fixtureJson"
            type="textarea"
            :rows="6"
            class="code-input"
            placeholder='{"image_paths":[],"scope_paths":[]}'
          />
        </label>
        <label>
          <span>标签</span>
          <NInput v-model:value="caseDraft.tags" placeholder="Excel，回归，核心链路" />
        </label>
        <label class="wide">
          <span>维护说明</span>
          <NInput v-model:value="caseDraft.notes" placeholder="数据口径、维护人、用例背景…" />
        </label>
      </div>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="caseOpen = false">取消</NButton>
          <NButton type="primary" :loading="savingCase" @click="saveCase">保存用例</NButton>
        </NSpace>
      </template>
    </NModal>

    <NModal
      v-model:show="detailOpen"
      preset="card"
      title="运行诊断"
      style="width: min(1120px, 97vw)"
      :bordered="false"
    >
      <template v-if="selectedRun">
        <div class="detail-head">
          <div>
            <NTag :type="statusType(selectedRun.status)" :bordered="false">{{ statusLabel(selectedRun.status) }}</NTag>
            <strong>{{ selectedRun.passed ?? 0 }}/{{ Math.max(0, Number(selectedRun.total || 0) - Number(selectedRun.skipped || 0)) }} 通过</strong>
            <span class="muted">{{ selectedRun.id }}</span>
          </div>
          <NSpace>
            <NButton
              v-if="selectedRun.results?.some((item) => !item.passed && !item.skipped)"
              type="primary"
              secondary
              @click="retryFailed(selectedRun)"
            >
              仅重跑失败项
            </NButton>
            <NButton v-if="selectedResult" @click="selectedResult = null">返回结果列表</NButton>
          </NSpace>
        </div>

        <template v-if="!selectedResult">
          <NGrid :cols="4" :x-gap="10" style="margin: 14px 0">
            <NGridItem><NCard size="small"><NStatistic label="准确率" :value="selectedRun.pass_rate == null ? '—' : `${Math.round(selectedRun.pass_rate * 100)}%`" /></NCard></NGridItem>
            <NGridItem><NCard size="small"><NStatistic label="综合得分" :value="selectedRun.metrics?.avg_score ?? '—'" /></NCard></NGridItem>
            <NGridItem><NCard size="small"><NStatistic label="平均耗时" :value="selectedRun.metrics?.avg_latency_ms == null ? '—' : `${(selectedRun.metrics.avg_latency_ms / 1000).toFixed(1)}s`" /></NCard></NGridItem>
            <NGridItem><NCard size="small"><NStatistic label="Token" :value="Number(selectedRun.metrics?.prompt_tokens || 0) + Number(selectedRun.metrics?.completion_tokens || 0)" /></NCard></NGridItem>
          </NGrid>
          <NAlert v-if="selectedRun.error" type="error" style="margin-bottom: 12px">{{ selectedRun.error }}</NAlert>
          <NDataTable
            :columns="resultColumns"
            :data="selectedRun.results || []"
            :bordered="false"
            size="small"
            :pagination="{ pageSize: 12 }"
          />
        </template>

        <template v-else>
          <div class="diagnosis-title">
            <div>
              <NTag :type="selectedResult.passed ? 'success' : 'error'" :bordered="false">
                {{ selectedResult.passed ? "通过" : "失败" }}
              </NTag>
              <strong>{{ selectedResult.question }}</strong>
            </div>
            <span>综合得分 {{ (selectedResult.meta as any)?.overall_score ?? "—" }}</span>
          </div>
          <div class="diagnosis-grid">
            <NCard title="失败原因" size="small">
              <p><strong>定位：</strong>{{ stageLabel((selectedResult.meta as any)?.failure_stage) }}</p>
              <p v-for="reason in selectedResult.reasons || []" :key="reason">· {{ reason }}</p>
            </NCard>
            <NCard title="分项得分" size="small">
              <div
                v-for="(dimension, name) in ((selectedResult.meta as any)?.dimensions || {})"
                :key="name"
                class="dimension-row"
              >
                <span>{{ name }}</span>
                <NProgress
                  type="line"
                  :percentage="Number((dimension as any).score || 0)"
                  :status="(dimension as any).passed ? 'success' : 'error'"
                />
              </div>
            </NCard>
          </div>
          <NCard title="完整回答" size="small" style="margin-top: 12px">
            <div class="answer-body">{{ selectedResult.answer || selectedResult.answer_preview || "未生成回答" }}</div>
          </NCard>
          <div class="diagnosis-grid">
            <NCard title="SQL / 数据查询" size="small">
              <pre>{{ pretty((selectedResult.response as any)?.data_query || {}) }}</pre>
            </NCard>
            <NCard title="模型调用" size="small">
              <pre>{{ pretty(selectedResult.model_calls || []) }}</pre>
            </NCard>
          </div>
          <NCard title="证据与完整响应" size="small" style="margin-top: 12px">
            <pre class="response-pre">{{ pretty(selectedResult.response || {}) }}</pre>
          </NCard>
        </template>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: 12px;
}
.suite-panel,
.main-panel {
  min-height: 0;
  overflow: auto;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid var(--ra-border);
  border-radius: 18px;
}
.suite-panel {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.suite-create {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px;
}
.suite-list {
  flex: 1;
  min-height: 120px;
  overflow: auto;
}
.suite-item {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  border: 1px solid transparent;
  background: #f8fafc;
  border-radius: 12px;
  padding: 11px 10px;
  margin-bottom: 6px;
  text-align: left;
  cursor: pointer;
}
.suite-item.active {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
}
.suite-name {
  font-size: 13px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.suite-meta,
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
.main-panel {
  padding: 16px;
}
.suite-head,
.title-line,
.detail-head,
.diagnosis-title,
.run-actions,
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.suite-head {
  align-items: flex-start;
  margin-bottom: 4px;
}
.suite-head h2 {
  margin: 0;
  font-size: 22px;
}
.suite-head p {
  margin: 4px 0 0;
  color: var(--ra-muted);
  font-size: 13px;
}
.title-line {
  justify-content: flex-start;
}
.run-alert {
  margin: 10px 0;
}
.metric-card {
  min-height: 96px;
}
.overview-grid,
.diagnosis-grid,
.compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.compare-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.trend-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.trend-row {
  display: grid;
  grid-template-columns: 90px minmax(120px, 1fr) 64px;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.failure-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.failure-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 10px;
}
.quality-alert {
  margin-top: 12px;
  line-height: 1.8;
}
.toolbar {
  margin-bottom: 12px;
}
.toolbar-spacer {
  flex: 1;
}
.run-config {
  margin-bottom: 16px;
}
.config-grid,
.case-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.config-grid label,
.case-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #344054;
  font-size: 12px;
}
.switch-label {
  align-items: flex-start;
}
.run-actions {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--ra-border);
}
.case-form {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.case-form .wide {
  grid-column: span 2;
}
.case-form .full {
  grid-column: 1 / -1;
}
.evidence-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.code-input :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.empty-main {
  min-height: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
}
h3 {
  margin: 18px 0 8px;
  font-size: 15px;
}
.detail-head > div,
.diagnosis-title > div {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dimension-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.answer-body {
  white-space: pre-wrap;
  line-height: 1.75;
  max-height: 360px;
  overflow: auto;
}
pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  max-height: 260px;
  overflow: auto;
}
.response-pre {
  max-height: 420px;
}
@media (max-width: 1100px) {
  .workspace {
    grid-template-columns: 210px minmax(0, 1fr);
  }
  .config-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .case-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
