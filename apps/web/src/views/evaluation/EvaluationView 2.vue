<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from "vue";
import {
  NButton,
  NInput,
  NInputNumber,
  NSpace,
  NSwitch,
  NDataTable,
  NSelect,
  NModal,
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
  createEvalSuite,
  deleteEvalCase,
  deleteEvalSuite,
  exportEvalSuite,
  getEvalSuite,
  importEvalSuite,
  listEvalRuns,
  listEvalSuites,
  pollEvalRun,
  seedEvalSuites,
  startEvalRun,
} from "@/api/realai";
import type { EvalCase, EvalCaseResult, EvalRun, EvalSuite } from "@/api/types";

const message = useMessage();
const dialog = useDialog();

const suites = ref<EvalSuite[]>([]);
const activeSuite = ref<EvalSuite | null>(null);
const runs = ref<EvalRun[]>([]);
const loading = ref(false);
const seeding = ref(false);
const running = ref(false);
const runProgress = ref("");
const suiteName = ref("");
const question = ref("");
const keywords = ref("");
const expectEvidence = ref(true);
const expectNumber = ref<number | null>(null);
const caseCategory = ref("general");
const caseMode = ref("light");
const webSearch = ref(false);
const modelOverride = ref("");
const writerSkill = ref("");
const reviewSkill = ref("");
const categoryFilter = ref<string>("");
const selectedRun = ref<EvalRun | null>(null);
const detailOpen = ref(false);
const cancelled = ref(false);

const categoryOptions: SelectOption[] = [
  { label: "全部类别", value: "" },
  { label: "问数 data", value: "data" },
  { label: "检索 retrieve", value: "retrieve" },
  { label: "图表 viz", value: "viz" },
  { label: "综合 mixed", value: "mixed" },
  { label: "报告 report", value: "report" },
  { label: "其他 general", value: "general" },
];

const modeOptions: SelectOption[] = [
  { label: "轻量问答", value: "light" },
  { label: "报告", value: "report" },
];

const filteredCases = computed(() => {
  const list = activeSuite.value?.cases || [];
  if (!categoryFilter.value) return list;
  return list.filter((c) => (c.category || "general") === categoryFilter.value);
});

const caseColumns: DataTableColumns<EvalCase> = [
  {
    title: "类别",
    key: "category",
    width: 90,
    render: (r) => r.category || "general",
  },
  {
    title: "模式",
    key: "mode",
    width: 70,
    render: (r) => r.mode || "light",
  },
  { title: "问题", key: "question", ellipsis: { tooltip: true } },
  {
    title: "关键词",
    key: "expect_keywords",
    width: 120,
    render: (r) => (r.expect_keywords || []).join(", "),
  },
  {
    title: "证据",
    key: "expect_evidence",
    width: 60,
    render: (r) => (r.expect_evidence ? "是" : "否"),
  },
  {
    title: "",
    key: "a",
    width: 70,
    render: (r) =>
      h(
        NButton,
        {
          size: "tiny",
          quaternary: true,
          onClick: () => confirmDeleteCase(r),
        },
        { default: () => "删" },
      ),
  },
];

const runColumns: DataTableColumns<EvalRun> = [
  {
    title: "状态",
    key: "status",
    width: 90,
    render: (r) =>
      h(
        NTag,
        {
          size: "small",
          type:
            r.status === "completed"
              ? "success"
              : r.status === "running"
                ? "warning"
                : "default",
        },
        { default: () => r.status },
      ),
  },
  {
    title: "通过",
    key: "passed",
    width: 90,
    render: (r) => (r.passed == null ? "—" : `${r.passed}/${r.total ?? "?"}`),
  },
  {
    title: "通过率",
    key: "pass_rate",
    width: 80,
    render: (r) =>
      r.pass_rate == null ? "—" : `${Math.round(Number(r.pass_rate) * 100)}%`,
  },
  {
    title: "时间",
    key: "created_at",
    width: 160,
    render: (r) => new Date(r.created_at * 1000).toLocaleString(),
  },
  {
    title: "",
    key: "detail",
    width: 80,
    render: (r) =>
      h(
        NButton,
        {
          size: "tiny",
          type: "primary",
          quaternary: true,
          onClick: () => openRunDetail(r),
        },
        { default: () => "详情" },
      ),
  },
];

const resultColumns: DataTableColumns<EvalCaseResult> = [
  {
    title: "结果",
    key: "passed",
    width: 70,
    render: (r) =>
      r.skipped ? "跳过" : r.passed ? "通过" : "失败",
  },
  {
    title: "类别",
    key: "category",
    width: 80,
  },
  {
    title: "问题",
    key: "question",
    ellipsis: { tooltip: true },
  },
  {
    title: "原因",
    key: "reasons",
    ellipsis: { tooltip: true },
    render: (r) => (r.reasons || []).join("；"),
  },
  {
    title: "预览",
    key: "answer_preview",
    ellipsis: { tooltip: true },
  },
];

async function load() {
  loading.value = true;
  try {
    const res = await listEvalSuites();
    suites.value = res.suites;
    if (activeSuite.value) await openSuite(activeSuite.value.id);
    else if (res.suites[0]) await openSuite(res.suites[0].id);
    else {
      activeSuite.value = null;
      runs.value = [];
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

async function openSuite(id: string) {
  try {
    activeSuite.value = await getEvalSuite(id);
    const rr = await listEvalRuns(id);
    runs.value = rr.runs;
  } catch (e) {
    message.error(e instanceof Error ? e.message : "打开套件失败");
  }
}

async function createSuite() {
  if (!suiteName.value.trim()) {
    message.warning("请先填写套件名称");
    return;
  }
  try {
    const s = await createEvalSuite(suiteName.value.trim());
    suiteName.value = "";
    message.success("已新建套件");
    await load();
    await openSuite(s.id);
  } catch (e) {
    message.error(e instanceof Error ? e.message : "新建失败");
  }
}

async function importSeed(recreate = false) {
  seeding.value = true;
  try {
    const res = await seedEvalSuites(recreate);
    message.success(recreate ? "已重建示例黄金套件" : "已导入示例黄金套件");
    await load();
    const first = res.suite_ids?.[0];
    if (first) await openSuite(first);
  } catch (e) {
    message.error(e instanceof Error ? e.message : "导入示例失败");
  } finally {
    seeding.value = false;
  }
}

async function addCase() {
  if (!activeSuite.value) {
    message.warning("请先选择或新建套件");
    return;
  }
  if (!question.value.trim()) {
    message.warning("请填写问题");
    return;
  }
  try {
    await addEvalCase(activeSuite.value.id, {
      question: question.value.trim(),
      expect_keywords: keywords.value
        .split(/[,，\s]+/)
        .map((x) => x.trim())
        .filter(Boolean),
      expect_evidence: expectEvidence.value,
      expect_number: expectNumber.value,
      category: caseCategory.value || "general",
      mode: caseMode.value || "light",
      intent: caseMode.value === "report" ? "ask" : "ask",
    });
    question.value = "";
    keywords.value = "";
    expectNumber.value = null;
    message.success("已加题");
    await openSuite(activeSuite.value.id);
  } catch (e) {
    message.error(e instanceof Error ? e.message : "加题失败");
  }
}

async function run() {
  if (!activeSuite.value) {
    message.warning("请先选择套件");
    return;
  }
  const n = activeSuite.value.cases?.length || 0;
  if (!n) {
    message.warning("当前套件没有用例，请加题或导入示例");
    return;
  }
  running.value = true;
  runProgress.value = `准备跑批 0/${n}…`;
  try {
    const skillOverrides: Record<string, string> = {};
    if (writerSkill.value.trim()) skillOverrides.writer = writerSkill.value.trim();
    if (reviewSkill.value.trim()) skillOverrides.review = reviewSkill.value.trim();
    const prevCompleted = runs.value.find((r) => r.status === "completed");
    const started = await startEvalRun(activeSuite.value.id, {
      webSearchEnabled: webSearch.value,
      modelOverride: modelOverride.value.trim() || null,
      skillOverrides,
      compareBaseRunId: prevCompleted?.id || null,
    });
    message.info("已开始跑批，请稍候…");
    const finished = await pollEvalRun(started.id, (tick) => {
      if (cancelled.value) return;
      const done = tick.progress?.done ?? 0;
      const total = tick.progress?.total ?? n;
      runProgress.value = `跑批中 ${done}/${total}…`;
    });
    runProgress.value = "";
    message.success(
      `已跑完：通过 ${finished.passed ?? 0}/${finished.total ?? n}` +
        (finished.skipped ? `，跳过 ${finished.skipped}` : ""),
    );
    await openSuite(activeSuite.value.id);
    openRunDetail(finished);
  } catch (e) {
    runProgress.value = "";
    message.error(e instanceof Error ? e.message : "跑批失败");
    if (activeSuite.value) await openSuite(activeSuite.value.id);
  } finally {
    running.value = false;
  }
}

function confirmDeleteCase(r: EvalCase) {
  dialog.warning({
    title: "删除用例",
    content: `确定删除「${r.question.slice(0, 40)}」？`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await deleteEvalCase(r.id);
        message.success("已删除");
        if (activeSuite.value) await openSuite(activeSuite.value.id);
      } catch (e) {
        message.error(e instanceof Error ? e.message : "删除失败");
      }
    },
  });
}

function removeSuite() {
  if (!activeSuite.value) return;
  const name = activeSuite.value.name;
  dialog.warning({
    title: "删除套件",
    content: `确定删除套件「${name}」及全部用例/跑批记录？`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await deleteEvalSuite(activeSuite.value!.id);
        activeSuite.value = null;
        message.success("已删除套件");
        await load();
      } catch (e) {
        message.error(e instanceof Error ? e.message : "删除失败");
      }
    },
  });
}

async function doExport() {
  if (!activeSuite.value) return;
  try {
    const payload = await exportEvalSuite(activeSuite.value.id);
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${payload.name || "eval-suite"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    message.success("已导出 JSON");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "导出失败");
  }
}

function doImportFile() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/json,.json";
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text) as {
        name?: string;
        description?: string;
        cases?: Array<Partial<EvalCase> & { question: string }>;
      };
      if (!data.name || !Array.isArray(data.cases)) {
        message.error("JSON 格式不对：需要 name 与 cases");
        return;
      }
      const s = await importEvalSuite({
        name: data.name,
        description: data.description,
        cases: data.cases,
      });
      message.success("已导入套件");
      await load();
      await openSuite(s.id);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导入失败");
    }
  };
  input.click();
}

function openRunDetail(r: EvalRun) {
  selectedRun.value = r;
  detailOpen.value = true;
}

const categorySummary = computed(() => {
  const stats = selectedRun.value?.category_stats || {};
  return Object.entries(stats)
    .filter(([k]) => !k.startsWith("_"))
    .map(([k, v]) => `${k}: ${v.passed ?? 0}/${v.total ?? 0}`);
});

onMounted(load);
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
          <NButton secondary @click="doImportFile">导入 JSON</NButton>
        </NSpace>
      </template>
    </PageHeader>

    <div class="layout">
      <aside class="panel">
        <div class="row">
          <NInput v-model:value="suiteName" size="small" placeholder="套件名" @keyup.enter="createSuite" />
          <NButton size="small" type="primary" @click="createSuite">新建</NButton>
        </div>
        <NButton
          block
          size="small"
          type="primary"
          secondary
          :loading="seeding"
          style="margin-bottom: 10px"
          @click="importSeed(false)"
        >
          一键导入示例黄金套件
        </NButton>
        <button
          v-for="s in suites"
          :key="s.id"
          type="button"
          class="item"
          :class="{ on: activeSuite?.id === s.id }"
          @click="openSuite(s.id)"
        >
          <div class="name">{{ s.name }}</div>
          <div class="meta">
            {{ s.case_count ?? s.cases?.length ?? 0 }} 题
            <span v-if="s.kind" class="kind"> · {{ s.kind }}</span>
          </div>
        </button>
        <div v-if="!suites.length" class="guide">
          <EmptyState text="还没有评测套件" />
          <p class="guide-text">
            评测用来批量考「问答/问数/报告」答得对不对。点上方按钮导入示例题，或自己新建套件再加题。
          </p>
          <NButton type="primary" block :loading="seeding" @click="importSeed(false)">
            导入示例黄金套件
          </NButton>
        </div>
      </aside>

      <main class="panel main">
        <template v-if="activeSuite">
          <div class="head">
            <div>
              <h2>{{ activeSuite.name }}</h2>
              <p v-if="activeSuite.description" class="desc">{{ activeSuite.description }}</p>
            </div>
            <NSpace wrap>
              <span class="muted">联网</span>
              <NSwitch v-model:value="webSearch" size="small" />
              <NButton
                type="primary"
                :loading="running"
                :disabled="!(activeSuite.cases?.length)"
                @click="run"
              >
                跑批
              </NButton>
              <NButton quaternary @click="doExport">导出</NButton>
              <NButton quaternary @click="importSeed(true)">重建示例</NButton>
              <NButton quaternary @click="removeSuite">删除套件</NButton>
            </NSpace>
          </div>
          <p v-if="runProgress" class="progress">{{ runProgress }}</p>

          <div class="advanced">
            <NInput
              v-model:value="modelOverride"
              size="small"
              placeholder="模型覆盖（可选，写入快照）"
              style="max-width: 220px"
            />
            <NInput
              v-model:value="writerSkill"
              size="small"
              placeholder="写作 Skill Id（报告对比）"
              style="max-width: 200px"
            />
            <NInput
              v-model:value="reviewSkill"
              size="small"
              placeholder="评审 Skill Id"
              style="max-width: 180px"
            />
          </div>

          <div class="add">
            <NInput v-model:value="question" placeholder="问题 / 报告目标" />
            <NInput v-model:value="keywords" placeholder="期望关键词（逗号分隔）" style="margin-top: 8px" />
            <NSpace style="margin-top: 8px" align="center" wrap>
              <NSelect
                v-model:value="caseCategory"
                :options="categoryOptions.filter((o) => o.value)"
                size="small"
                style="width: 140px"
              />
              <NSelect
                v-model:value="caseMode"
                :options="modeOptions"
                size="small"
                style="width: 120px"
              />
              <span class="muted">需证据</span>
              <NSwitch v-model:value="expectEvidence" size="small" />
              <NInputNumber v-model:value="expectNumber" clearable placeholder="期望数值" size="small" />
              <NButton size="small" type="primary" @click="addCase">加题</NButton>
            </NSpace>
          </div>

          <div class="filter-row">
            <span class="muted">筛选类别</span>
            <NSelect
              v-model:value="categoryFilter"
              :options="categoryOptions"
              size="small"
              placeholder="全部"
              style="width: 160px"
            />
          </div>

          <NDataTable
            v-if="filteredCases.length"
            :columns="caseColumns"
            :data="filteredCases"
            size="small"
            :bordered="false"
          />
          <EmptyState v-else text="暂无用例 — 点「加题」或「一键导入示例」" />

          <h3>跑批历史</h3>
          <NDataTable
            v-if="runs.length"
            :columns="runColumns"
            :data="runs"
            size="small"
            :bordered="false"
          />
          <EmptyState v-else text="暂无跑批 — 点「跑批」开始" />
        </template>
        <div v-else class="guide-main">
          <EmptyState text="从左侧选择套件，或导入示例开始" />
          <NButton type="primary" :loading="seeding" @click="importSeed(false)">
            一键导入示例黄金套件
          </NButton>
        </div>
      </main>
    </div>

    <NModal
      v-model:show="detailOpen"
      preset="card"
      title="跑批详情"
      style="width: min(920px, 96vw)"
      :bordered="false"
    >
      <template v-if="selectedRun">
        <p class="muted">
          {{ selectedRun.id }} ·
          通过 {{ selectedRun.passed }}/{{ selectedRun.total }}
          <span v-if="selectedRun.skipped"> · 跳过 {{ selectedRun.skipped }}</span>
          <span v-if="selectedRun.pass_rate != null">
            · {{ Math.round(Number(selectedRun.pass_rate) * 100) }}%
          </span>
        </p>
        <p v-if="categorySummary.length" class="muted">按类：{{ categorySummary.join(" · ") }}</p>
        <p v-if="selectedRun.snapshot" class="muted snap">
          快照：模型 {{ (selectedRun.snapshot as any).llm?.model || "—" }} · Vault mtime
          {{ (selectedRun.snapshot as any).vault_mtime ?? "—" }}
        </p>
        <div v-if="selectedRun.regression" class="regression">
          <strong>相对上次回归</strong>
          <p class="muted">
            新增失败 {{ selectedRun.regression.new_failures?.length ?? 0 }} ·
            已修复 {{ selectedRun.regression.fixed?.length ?? 0 }} ·
            仍失败 {{ selectedRun.regression.still_failing?.length ?? 0 }}
          </p>
          <ul v-if="selectedRun.regression.new_failures?.length">
            <li v-for="(f, i) in selectedRun.regression.new_failures" :key="i">
              新增失败：{{ f.question }} — {{ (f.reasons || []).join("；") }}
            </li>
          </ul>
        </div>
        <NDataTable
          :columns="resultColumns"
          :data="selectedRun.results || []"
          size="small"
          :bordered="false"
          style="margin-top: 12px"
        />
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
.layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 12px;
}
.panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--ra-border);
  border-radius: 18px;
  padding: 14px;
  overflow: auto;
}
.row {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}
.item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: #f8fafc;
  border-radius: 12px;
  padding: 10px;
  margin-bottom: 6px;
  cursor: pointer;
}
.item.on {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
}
.name {
  font-weight: 600;
  font-size: 13px;
}
.meta {
  font-size: 11px;
  color: var(--ra-muted);
  margin-top: 2px;
}
.kind {
  opacity: 0.8;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.head h2 {
  margin: 0;
  font-size: 18px;
}
.desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ra-muted);
}
.add {
  margin-bottom: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--ra-border);
}
.advanced {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
.progress {
  color: var(--ra-accent);
  font-size: 13px;
  margin: 0 0 10px;
}
h3 {
  margin: 18px 0 8px;
  font-size: 14px;
}
.guide,
.guide-main {
  margin-top: 12px;
  text-align: center;
}
.guide-text {
  font-size: 13px;
  color: var(--ra-muted);
  line-height: 1.5;
  margin: 8px 0 14px;
}
.guide-main {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px 20px;
}
.regression {
  margin-top: 10px;
  padding: 10px;
  background: #f8fafc;
  border-radius: 10px;
  font-size: 13px;
}
.regression ul {
  margin: 6px 0 0;
  padding-left: 18px;
}
.snap {
  word-break: break-all;
}
</style>
