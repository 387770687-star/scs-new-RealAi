<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  NButton,
  NInput,
  NRadioButton,
  NRadioGroup,
  NSpace,
  NSwitch,
  NTag,
  NSpin,
  NModal,
  NUpload,
  useMessage,
  useDialog,
  type UploadCustomRequestOptions,
} from "naive-ui";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import DataTableCard from "@/components/DataTableCard.vue";
import {
  clearSkillOptimizeSession,
  deleteSkill,
  deleteSkillOptimizeMessage,
  executeSkill,
  fetchSkill,
  fetchSkillFile,
  fetchSkillOptimizeSession,
  fetchSkillsWorkshop,
  importSkillZip,
  postSkillOptimizeTurn,
  previewSkillDraft,
  saveSkill,
  setSkillEnabled,
} from "@/api/realai";
import {
  ApiError,
  type SkillDetail,
  type SkillDraft,
  type SkillPackageFile,
  type SkillSummary,
} from "@/api/types";
import { splitMarkdownBlocks, type MarkdownBlock } from "@/utils/format";

type PanelMode = "try" | "optimize";
type CreateStep = 1 | 2 | 3;
type CreateTemplateId = "general" | "extract" | "review" | "write";

type OptMsg = {
  id: string;
  role: string;
  content: Record<string, unknown>;
  created_at?: number;
};

const message = useMessage();
const dialog = useDialog();
const loading = ref(false);
const skills = ref<SkillSummary[]>([]);
const selectedId = ref<string | null>(null);
const detail = ref<SkillDetail | null>(null);
const detailLoading = ref(false);
const errorKind = ref<"empty" | "not_ready" | "network" | "error" | null>(null);
const errorMsg = ref("");
const runInput = ref("");
const runOutput = ref("");
const running = ref(false);

const panelMode = ref<PanelMode>("try");
const optMessages = ref<OptMsg[]>([]);
const optDraft = ref<SkillDraft | null>(null);
const optLoading = ref(false);
const optSending = ref(false);
const editorDirty = ref(false);

const activeFilePath = ref("SKILL.md");
const fileContent = ref("");
const fileLoading = ref(false);
const fileMessage = ref("");
/** formatted = Markdown 渲染；raw = 原文 */
const viewMode = ref<"formatted" | "raw">("formatted");

const editOpen = ref(false);
const editForm = ref({ id: "", name: "", description: "", body: "" });
const skillQuery = ref("");

const createOpen = ref(false);
const createStep = ref<CreateStep>(1);
const createError = ref("");
const createPreviewing = ref(false);
const createPublishing = ref(false);
const createForm = ref({
  template: "general" as CreateTemplateId,
  goal: "",
  id: "",
  name: "",
  description: "",
  body: "",
  testInput: "",
  testOutput: "",
  testPassed: false,
});

const CREATE_TEMPLATES: Array<{
  id: CreateTemplateId;
  name: string;
  description: string;
  testInput: string;
  body: (goal: string) => string;
}> = [
  {
    id: "general",
    name: "通用任务",
    description: "适合流程处理、内容整理和通用助手",
    testInput: "请根据一段示例输入执行这个任务。",
    body: (goal) =>
      `## 目标\n\n${goal}\n\n## 输入要求\n\n- 接收用户提供的任务材料；信息不足时先说明缺口。\n\n## 执行步骤\n\n1. 理解用户目标与约束。\n2. 按照目标完成处理，并检查遗漏。\n3. 输出可直接使用的结果。\n\n## 输出要求\n\n- 结构清晰，结论明确。\n- 不补充输入中不存在的事实。`,
  },
  {
    id: "extract",
    name: "文档提炼",
    description: "适合摘要、要点、结论、行动项提取",
    testInput: "项目计划下周完成评审，本周需要整理风险清单并确认责任人。",
    body: (goal) =>
      `## 目标\n\n${goal}\n\n## 输入要求\n\n- 接收文档、会议纪要或材料片段。\n\n## 执行步骤\n\n1. 识别主题与关键事实。\n2. 提取结论、关键数据、风险和行动项。\n3. 对无法从原文确认的信息标注“原文未说明”。\n\n## 输出格式\n\n1. 核心结论\n2. 关键数据与事实\n3. 风险与限制\n4. 行动项`,
  },
  {
    id: "review",
    name: "分析评审",
    description: "适合方案审查、问题识别和改进建议",
    testInput: "请评审一份只写了目标、没有实施计划和风险措施的方案。",
    body: (goal) =>
      `## 目标\n\n${goal}\n\n## 评审维度\n\n- 目标完整性\n- 事实与依据\n- 可执行性\n- 风险与约束\n\n## 执行步骤\n\n1. 总结被评审内容的主张。\n2. 按评审维度识别问题并分级。\n3. 给出可操作的修改建议。\n\n## 输出格式\n\n- 总体结论\n- 问题清单（严重程度、位置、原因）\n- 修改建议`,
  },
  {
    id: "write",
    name: "内容写作",
    description: "适合报告、方案、通知和正式材料撰写",
    testInput: "请写一段项目启动说明，强调目标、范围和下一步安排。",
    body: (goal) =>
      `## 目标\n\n${goal}\n\n## 输入要求\n\n- 明确主题、读者、用途和必要事实。\n\n## 执行步骤\n\n1. 提炼写作主线与结构。\n2. 按正式书面表达完成正文。\n3. 检查事实、逻辑、语气和格式。\n\n## 输出要求\n\n- 标题清晰，层次完整。\n- 语言正式、简洁，不虚构数据和来源。`,
  },
];

const KIND_LABEL: Record<string, string> = {
  main: "主文件",
  reference: "参考资料",
  script: "脚本",
  template: "模板",
  asset: "资源",
  other: "其他",
};

function isBuiltin(s: SkillSummary) {
  return s.group === "deerflow_builtin" || s.read_only === true || s.source === "deerflow";
}

const normalizedSkillQuery = computed(() => skillQuery.value.trim().toLowerCase());
const businessSkills = computed(() =>
  skills.value.filter(
    (s) =>
      !isBuiltin(s) &&
      (!normalizedSkillQuery.value ||
        `${s.name} ${s.id} ${s.description}`
          .toLowerCase()
          .includes(normalizedSkillQuery.value)),
  ),
);
const builtinSkills = computed(() =>
  skills.value.filter(
    (s) =>
      isBuiltin(s) &&
      (!normalizedSkillQuery.value ||
        `${s.name} ${s.id} ${s.description}`
          .toLowerCase()
          .includes(normalizedSkillQuery.value)),
  ),
);

const selectedReadonly = computed(
  () => Boolean(detail.value && (detail.value.read_only || isBuiltin(detail.value))),
);

const packageFiles = computed<SkillPackageFile[]>(() => {
  const files = detail.value?.files || [];
  if (!files.length && detail.value) {
    return [
      {
        path: "SKILL.md",
        size: (detail.value.raw || detail.value.body || "").length,
        kind: "main",
        text: true,
      },
    ];
  }
  return files;
});

const auxFiles = computed(() => packageFiles.value.filter((f) => f.kind !== "main"));

const isMarkdownFile = computed(() => {
  const p = activeFilePath.value.toLowerCase();
  return p.endsWith(".md") || p.endsWith(".markdown");
});

/** 带格式预览时去掉 YAML frontmatter，只渲染正文 */
function markdownBodyForPreview(raw: string): string {
  const m = raw.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n([\s\S]*)$/);
  return (m ? m[1] : raw).trim();
}

const formattedBlocks = computed<MarkdownBlock[]>(() => {
  if (!fileContent.value || !isMarkdownFile.value) return [];
  return splitMarkdownBlocks(markdownBodyForPreview(fileContent.value));
});

function formatSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function load() {
  loading.value = true;
  errorKind.value = null;
  try {
    const res = await fetchSkillsWorkshop();
    skills.value = res.skills;
    if (!res.skills.length) errorKind.value = "empty";
    const prefer =
      selectedId.value ||
      businessSkills.value[0]?.id ||
      builtinSkills.value[0]?.id ||
      res.skills[0]?.id;
    if (prefer) await selectSkill(prefer);
  } catch (err) {
    skills.value = [];
    if (err instanceof ApiError) {
      errorKind.value =
        err.kind === "network" ? "network" : err.kind === "not_ready" ? "not_ready" : "error";
      errorMsg.value = err.message;
    } else {
      errorKind.value = "error";
      errorMsg.value = String(err);
    }
  } finally {
    loading.value = false;
  }
}

async function selectSkill(id: string) {
  selectedId.value = id;
  detailLoading.value = true;
  runOutput.value = "";
  runInput.value = "";
  panelMode.value = "try";
  optMessages.value = [];
  optDraft.value = null;
  editorDirty.value = false;
  activeFilePath.value = "SKILL.md";
  fileContent.value = "";
  fileMessage.value = "";
  try {
    detail.value = await fetchSkill(id);
    await openPackageFile("SKILL.md");
  } catch (err) {
    detail.value = null;
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    detailLoading.value = false;
  }
}

function msgText(m: OptMsg): string {
  const c = m.content || {};
  return String(c.text || c.answer || "").trim();
}

function msgDraft(m: OptMsg): SkillDraft | null {
  const d = m.content?.draft;
  if (!d || typeof d !== "object") return null;
  const draft = d as Record<string, unknown>;
  if (!draft.body && !draft.raw) return null;
  return {
    skill_id: String(draft.skill_id || detail.value?.id || ""),
    name: String(draft.name || ""),
    description: String(draft.description || ""),
    body: String(draft.body || ""),
    raw: String(draft.raw || ""),
  };
}

async function loadOptimizeSession() {
  if (!detail.value || selectedReadonly.value) return;
  optLoading.value = true;
  try {
    const res = await fetchSkillOptimizeSession(detail.value.id);
    optMessages.value = (res.session?.messages || []) as OptMsg[];
    if (res.latest_draft) optDraft.value = res.latest_draft;
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    optLoading.value = false;
  }
}

async function startOptimizeMode() {
  if (!detail.value) return;
  if (selectedReadonly.value) {
    message.warning("内置 Skill 不可优化，请选择业务场景 Skill");
    return;
  }
  panelMode.value = "optimize";
  runInput.value = "";
  await loadOptimizeSession();
}

function backToTryMode() {
  panelMode.value = "try";
  runInput.value = "";
}

async function sendOptimize() {
  if (!detail.value || !runInput.value.trim() || optSending.value) return;
  const text = runInput.value.trim();
  optSending.value = true;
  try {
    const res = await postSkillOptimizeTurn(detail.value.id, {
      message: text,
      current_draft: optDraft.value,
    });
    runInput.value = "";
    if (res.session?.messages) {
      optMessages.value = res.session.messages as OptMsg[];
    } else {
      await loadOptimizeSession();
    }
    if (res.draft) optDraft.value = res.draft;
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    optSending.value = false;
  }
}

function applyDraftToEditor(draft?: SkillDraft | null) {
  const d = draft || optDraft.value;
  if (!d || !detail.value) {
    message.warning("暂无草案可应用");
    return;
  }
  const raw =
    d.raw ||
    `---\nname: ${d.name}\ndescription: ${d.description}\n---\n\n${d.body || ""}`;
  fileContent.value = raw;
  activeFilePath.value = "SKILL.md";
  viewMode.value = "raw";
  editForm.value = {
    id: detail.value.id,
    name: d.name || detail.value.name,
    description: d.description || detail.value.description,
    body: d.body || detail.value.body,
  };
  optDraft.value = d;
  editorDirty.value = true;
  message.success("已写入编辑区，请点「保存到 Skill」落盘");
}

async function saveEditorDraft() {
  if (!detail.value || selectedReadonly.value) return;
  const name = editForm.value.name || detail.value.name;
  const description = editForm.value.description || detail.value.description;
  let body = editForm.value.body || detail.value.body;
  if (editorDirty.value && fileContent.value) {
    const m = fileContent.value.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n([\s\S]*)$/);
    if (m) body = m[1].trim();
    else if (!editForm.value.body) body = fileContent.value;
  }
  try {
    await saveSkill(
      detail.value.id,
      { name, description, body },
      true,
    );
    message.success("已保存到 Skill");
    editorDirty.value = false;
    await selectSkill(detail.value.id);
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

async function deleteOptMessage(messageId: string) {
  if (!detail.value) return;
  try {
    const res = await deleteSkillOptimizeMessage(detail.value.id, messageId);
    optMessages.value = (res.session?.messages || []) as OptMsg[];
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

function confirmClearOptimize() {
  if (!detail.value) return;
  dialog.warning({
    title: "清空优化对话",
    content: "确认清空本 Skill 的全部优化对话？此操作不可恢复。",
    positiveText: "清空",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        const res = await clearSkillOptimizeSession(detail.value!.id);
        optMessages.value = (res.session?.messages || []) as OptMsg[];
        optDraft.value = null;
        message.success("已清空");
      } catch (err) {
        message.error(err instanceof Error ? err.message : String(err));
      }
    },
  });
}

async function runTry() {
  if (!detail.value) return;
  if (!runInput.value.trim()) {
    message.warning("请输入试跑内容");
    return;
  }
  running.value = true;
  try {
    const res = await executeSkill(detail.value.id, runInput.value);
    runOutput.value = res.output;
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  } finally {
    running.value = false;
  }
}

async function onPanelPrimary() {
  if (panelMode.value === "optimize") {
    await sendOptimize();
  } else {
    await runTry();
  }
}

async function openPackageFile(path: string) {
  if (!selectedId.value) return;
  activeFilePath.value = path;
  const lower = path.toLowerCase();
  viewMode.value =
    lower.endsWith(".md") || lower.endsWith(".markdown") ? "formatted" : "raw";
  fileLoading.value = true;
  fileMessage.value = "";
  try {
    if (path === "SKILL.md" && detail.value) {
      fileContent.value = detail.value.raw || detail.value.body || "";
      return;
    }
    const res = await fetchSkillFile(selectedId.value, path);
    if (res.content != null) {
      fileContent.value = res.content;
    } else {
      fileContent.value = "";
      fileMessage.value = res.message || "无法预览";
    }
  } catch (err) {
    fileContent.value = "";
    fileMessage.value = err instanceof Error ? err.message : String(err);
  } finally {
    fileLoading.value = false;
  }
}

function openCreate() {
  createForm.value = {
    template: "general",
    goal: "",
    id: "",
    name: "",
    description: "",
    body: "",
    testInput: "",
    testOutput: "",
    testPassed: false,
  };
  createStep.value = 1;
  createError.value = "";
  createOpen.value = true;
}

function createTemplate() {
  return (
    CREATE_TEMPLATES.find((item) => item.id === createForm.value.template) ||
    CREATE_TEMPLATES[0]
  );
}

function generatedSkillId() {
  const now = new Date();
  const parts = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
    String(now.getSeconds()).padStart(2, "0"),
  ];
  return `custom-skill-${parts.join("")}`;
}

function inferredSkillName(goal: string) {
  const firstClause = goal.split(/[，。！？!?；;\n\r]/, 1)[0] || goal;
  const compact = firstClause
    .replace(/[《》“”"'。，、！？!?：:；;\n\r]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^(?:请帮我|请|帮我)\s*/, "");
  return compact.slice(0, 24) || "自定义 Skill";
}

function bodyHasContent(body: string) {
  return Boolean(
    body
      .replace(/^\s{0,3}#{1,6}\s+.*$/gm, "")
      .replace(/^\s*(?:[-*+]|\d+[.)])\s*$/gm, "")
      .replace(/[\s`*_>#-]+/g, ""),
  );
}

function prepareCreateDraft() {
  const template = createTemplate();
  const goal = createForm.value.goal.trim();
  createForm.value.name = inferredSkillName(goal);
  createForm.value.description = goal;
  createForm.value.id = generatedSkillId();
  createForm.value.body = template.body(goal);
  createForm.value.testInput = template.testInput;
  createForm.value.testOutput = "";
  createForm.value.testPassed = false;
}

function validateCreateConfig() {
  const form = createForm.value;
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.id.trim())) {
    return "系统标识仅允许小写字母、数字和连字符";
  }
  if (!form.name.trim()) return "请填写 Skill 名称";
  if (!form.description.trim()) return "请填写用途说明";
  if (!bodyHasContent(form.body)) return "执行规则需要包含实际内容";
  return "";
}

function nextCreateStep() {
  createError.value = "";
  if (createStep.value === 1) {
    if (!createForm.value.goal.trim()) {
      createError.value = "请先描述希望 Skill 完成的任务";
      return;
    }
    prepareCreateDraft();
    createStep.value = 2;
    return;
  }
  const error = validateCreateConfig();
  if (error) {
    createError.value = error;
    return;
  }
  createStep.value = 3;
}

function previousCreateStep() {
  createError.value = "";
  if (createStep.value > 1) {
    createStep.value = (createStep.value - 1) as CreateStep;
  }
}

async function runCreatePreview() {
  const error = validateCreateConfig();
  if (error) {
    createError.value = error;
    return;
  }
  if (!createForm.value.testInput.trim()) {
    createError.value = "请输入一条测试内容";
    return;
  }
  createError.value = "";
  createPreviewing.value = true;
  createForm.value.testOutput = "";
  createForm.value.testPassed = false;
  try {
    const result = await previewSkillDraft({
      name: createForm.value.name.trim(),
      description: createForm.value.description.trim(),
      body: createForm.value.body,
      input: createForm.value.testInput.trim(),
    });
    createForm.value.testOutput = result.output;
    createForm.value.testPassed = true;
  } catch (err) {
    createError.value = err instanceof Error ? err.message : String(err);
  } finally {
    createPreviewing.value = false;
  }
}

async function publishCreate() {
  if (!createForm.value.testPassed) {
    createError.value = "请先完成一次试跑，再创建 Skill";
    return;
  }
  const error = validateCreateConfig();
  if (error) {
    createError.value = error;
    return;
  }
  createPublishing.value = true;
  createError.value = "";
  const id = createForm.value.id.trim();
  try {
    await saveSkill(id, {
      name: createForm.value.name.trim(),
      description: createForm.value.description.trim(),
      body: createForm.value.body,
    });
    message.success("Skill 已创建并启用");
    createOpen.value = false;
    await load();
    await selectSkill(id);
  } catch (err) {
    createError.value = err instanceof Error ? err.message : String(err);
  } finally {
    createPublishing.value = false;
  }
}

function openEdit() {
  if (!detail.value || selectedReadonly.value) return;
  editForm.value = {
    id: detail.value.id,
    name: detail.value.name,
    description: detail.value.description,
    body: detail.value.body,
  };
  editOpen.value = true;
}

async function saveEdit() {
  try {
    const id = editForm.value.id;
    if (!editForm.value.name.trim()) {
      message.warning("请填写名称");
      return;
    }
    if (!editForm.value.description.trim()) {
      message.warning("请填写说明");
      return;
    }
    if (!bodyHasContent(editForm.value.body)) {
      message.warning("正文需要包含实际执行内容");
      return;
    }
    await saveSkill(
      id,
      {
        name: editForm.value.name,
        description: editForm.value.description,
        body: editForm.value.body,
      },
      true,
    );
    message.success("已保存");
    editOpen.value = false;
    await load();
    await selectSkill(id);
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

function confirmDelete() {
  if (!detail.value || selectedReadonly.value) return;
  dialog.warning({
    title: "删除",
    content: `确认删除 ${detail.value.id}？`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      await deleteSkill(detail.value!.id);
      message.success("已删除");
      selectedId.value = null;
      detail.value = null;
      await load();
    },
  });
}

async function toggleEnabled(v: boolean) {
  if (!detail.value) return;
  try {
    await setSkillEnabled(detail.value.id, v);
    message.success(v ? "已启用" : "已停用");
    await load();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}

async function onImport({ file, onFinish, onError }: UploadCustomRequestOptions) {
  try {
    if (!file.file) throw new Error("无文件");
    const res = await importSkillZip(file.file);
    message.success(`已导入：${(res.imported || []).join(", ") || "完成"}`);
    await load();
    onFinish();
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
    onError();
  }
}

watch(
  () => detail.value?.id,
  () => {
    if (detail.value && activeFilePath.value === "SKILL.md") {
      fileContent.value = detail.value.raw || detail.value.body || "";
    }
  },
);

watch(
  () => [
    createForm.value.id,
    createForm.value.name,
    createForm.value.description,
    createForm.value.body,
    createForm.value.testInput,
  ],
  () => {
    if (
      createStep.value === 3 &&
      createForm.value.testPassed &&
      !createPreviewing.value
    ) {
      createForm.value.testPassed = false;
      createForm.value.testOutput = "";
    }
  },
);

onMounted(load);
</script>

<template>
  <div class="ra-page ra-fade-in">
    <PageHeader title="Skill">
      <template #actions>
        <NSpace :wrap="false" align="center">
          <NButton secondary @click="load">刷新</NButton>
          <NUpload accept=".zip" :show-file-list="false" :custom-request="onImport">
            <NButton secondary>导入</NButton>
          </NUpload>
          <NButton type="primary" @click="openCreate">新建</NButton>
        </NSpace>
      </template>
    </PageHeader>

    <NSpin :show="loading">
      <EmptyState
        v-if="errorKind && errorKind !== 'empty'"
        :kind="errorKind"
        :text="errorMsg || undefined"
        action-label="重试"
        @action="load"
      />
      <div v-else class="grid">
        <aside class="ra-panel list">
          <NInput
            v-model:value="skillQuery"
            clearable
            size="small"
            placeholder="搜索名称、说明或标识"
            class="skill-search"
          />
          <EmptyState v-if="errorKind === 'empty'" text="暂无 Skill" />
          <template v-else>
            <div class="group">
              <div class="group-title">业务场景</div>
              <button
                v-for="s in businessSkills"
                :key="s.id"
                type="button"
                class="skill-item"
                :class="{ active: s.id === selectedId }"
                @click="selectSkill(s.id)"
              >
                <div class="s-name">
                  {{ s.name }}
                  <NTag v-if="!s.valid" type="error" size="tiny">无效</NTag>
                </div>
                <div class="s-desc">{{ s.description }}</div>
              </button>
              <p v-if="!businessSkills.length" class="muted tiny">暂无</p>
            </div>

            <div class="group">
              <div class="group-title">系统内置</div>
              <button
                v-for="s in builtinSkills"
                :key="s.id"
                type="button"
                class="skill-item"
                :class="{ active: s.id === selectedId }"
                @click="selectSkill(s.id)"
              >
                <div class="s-name">
                  {{ s.name }}
                  <NTag size="tiny" :bordered="false">只读</NTag>
                </div>
                <div class="s-desc">{{ s.description }}</div>
              </button>
              <p v-if="!builtinSkills.length" class="muted tiny">暂无</p>
            </div>
          </template>
        </aside>

        <section class="ra-panel detail-panel">
          <NSpin :show="detailLoading">
            <EmptyState v-if="!detail" text="选择 Skill" />
            <div v-else class="detail-body">
              <div class="detail-head">
                <div>
                  <h2>{{ detail.name }}</h2>
                  <p class="muted">
                    {{ detail.id }}
                    ·
                    {{ selectedReadonly ? "系统内置" : "业务场景" }}
                    · {{ packageFiles.length }} 个文件
                  </p>
                </div>
                <NSpace>
                  <NSwitch :value="detail.enabled !== false" @update:value="toggleEnabled">
                    <template #checked>启用</template>
                    <template #unchecked>停用</template>
                  </NSwitch>
                  <NButton v-if="!selectedReadonly" secondary @click="openEdit">编辑</NButton>
                  <NButton
                    v-if="!selectedReadonly"
                    type="error"
                    secondary
                    @click="confirmDelete"
                  >
                    删除
                  </NButton>
                </NSpace>
              </div>
              <p v-if="selectedReadonly" class="tip">内置不可改、不可删；不可优化</p>

              <div class="pkg-layout">
                <aside class="file-tree">
                  <div class="sub">包内文件</div>
                  <div class="file-tree-scroll">
                    <button
                      v-for="f in packageFiles"
                      :key="f.path"
                      type="button"
                      class="file-item"
                      :class="{ on: f.path === activeFilePath }"
                      @click="openPackageFile(f.path)"
                    >
                      <div class="file-top">
                        <NTag size="tiny" :bordered="false">
                          {{ KIND_LABEL[f.kind] || f.kind }}
                        </NTag>
                        <span class="file-size">{{ formatSize(f.size) }}</span>
                      </div>
                      <div class="file-path">{{ f.path }}</div>
                    </button>
                    <p v-if="!auxFiles.length" class="muted tiny file-hint">
                      仅有主文件；导入含 references / scripts / templates 的包后会显示在此
                    </p>
                  </div>
                </aside>

                <div class="file-view">
                  <div class="file-view-head">
                    <span class="sub">{{ activeFilePath }}</span>
                    <NRadioGroup
                      v-if="isMarkdownFile && !fileMessage"
                      v-model:value="viewMode"
                      size="small"
                    >
                      <NRadioButton value="formatted">带格式</NRadioButton>
                      <NRadioButton value="raw">原文</NRadioButton>
                    </NRadioGroup>
                  </div>
                  <div class="file-view-body">
                    <NSpin :show="fileLoading">
                      <p v-if="fileMessage" class="file-msg">{{ fileMessage }}</p>
                      <div
                        v-else-if="viewMode === 'formatted' && isMarkdownFile"
                        class="body md-view"
                      >
                        <template v-for="(block, bi) in formattedBlocks" :key="bi">
                          <div v-if="block.type === 'html'" class="md" v-html="block.html" />
                          <DataTableCard
                            v-else
                            :title="block.title || '表格'"
                            :columns="block.columns"
                            :rows="block.rows"
                          />
                        </template>
                        <p v-if="!formattedBlocks.length" class="muted tiny">（无正文）</p>
                      </div>
                      <pre v-else class="body">{{ fileContent }}</pre>
                    </NSpin>
                  </div>
                </div>
              </div>

              <div class="try">
                <div class="try-head">
                  <div class="sub">{{ panelMode === "optimize" ? "优化对话" : "试跑" }}</div>
                  <NSpace size="small">
                    <NButton
                      v-if="panelMode === 'try' && !selectedReadonly"
                      size="tiny"
                      secondary
                      @click="startOptimizeMode"
                    >
                      开始优化对话
                    </NButton>
                    <NButton
                      v-if="panelMode === 'optimize'"
                      size="tiny"
                      quaternary
                      @click="backToTryMode"
                    >
                      返回试跑
                    </NButton>
                    <NButton
                      v-if="panelMode === 'optimize'"
                      size="tiny"
                      quaternary
                      :disabled="!optMessages.length"
                      @click="confirmClearOptimize"
                    >
                      清空对话
                    </NButton>
                    <NButton
                      v-if="editorDirty && !selectedReadonly"
                      size="tiny"
                      type="primary"
                      @click="saveEditorDraft"
                    >
                      保存到 Skill
                    </NButton>
                  </NSpace>
                </div>
                <p v-if="selectedReadonly" class="tip tiny">内置不可改、不可删；不可优化</p>
                <p v-else-if="panelMode === 'optimize'" class="tip tiny">
                  本 Skill 优化对话会永久保留；草案点「应用到编辑区」后，再点「保存到 Skill」才落盘。
                </p>

                <div v-if="panelMode === 'optimize'" class="opt-chat">
                  <NSpin :show="optLoading">
                    <div v-if="!optMessages.length" class="muted tiny">暂无优化消息，说一句想怎么改吧。</div>
                    <div
                      v-for="m in optMessages"
                      :key="m.id"
                      class="opt-msg"
                      :class="m.role"
                    >
                      <div class="opt-role">{{ m.role === "user" ? "你" : "助手" }}</div>
                      <div class="opt-text">{{ msgText(m) }}</div>
                      <NSpace size="small" style="margin-top: 4px">
                        <NButton
                          v-if="m.role === 'assistant' && msgDraft(m)"
                          size="tiny"
                          secondary
                          @click="applyDraftToEditor(msgDraft(m))"
                        >
                          应用到编辑区
                        </NButton>
                        <NButton size="tiny" quaternary @click="deleteOptMessage(m.id)">
                          删除
                        </NButton>
                      </NSpace>
                    </div>
                  </NSpin>
                </div>

                <NInput
                  v-model:value="runInput"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 4 }"
                  :placeholder="
                    panelMode === 'optimize'
                      ? '用自然语言描述要怎么改这个 Skill'
                      : '试跑输入'
                  "
                  @keydown.ctrl.enter="onPanelPrimary"
                />
                <NButton
                  style="margin-top: 8px"
                  type="primary"
                  secondary
                  :loading="panelMode === 'optimize' ? optSending : running"
                  :disabled="
                    !runInput.trim() ||
                    (panelMode === 'optimize' && selectedReadonly)
                  "
                  @click="onPanelPrimary"
                >
                  {{ panelMode === "optimize" ? "发送" : "执行" }}
                </NButton>
                <pre v-if="panelMode === 'try' && runOutput" class="out">{{ runOutput }}</pre>
              </div>
            </div>
          </NSpin>
        </section>
      </div>
    </NSpin>

    <NModal
      v-model:show="createOpen"
      preset="card"
      title="新建 Skill"
      style="width: min(880px, calc(100vw - 48px))"
      :mask-closable="false"
    >
      <div class="create-wizard">
        <div class="wizard-steps" aria-label="创建步骤">
          <div
            v-for="item in [
              { step: 1, label: '定义用途' },
              { step: 2, label: '配置规则' },
              { step: 3, label: '试跑发布' },
            ]"
            :key="item.step"
            class="wizard-step"
            :class="{
              active: createStep === item.step,
              done: createStep > item.step,
            }"
          >
            <span>{{ createStep > item.step ? "✓" : item.step }}</span>
            <strong>{{ item.label }}</strong>
          </div>
        </div>

        <section v-if="createStep === 1" class="wizard-panel">
          <div class="wizard-heading">
            <h3>这个 Skill 要帮助用户完成什么？</h3>
            <p>选择一个接近的模板，再用自然语言描述实际任务。</p>
          </div>
          <div class="template-grid">
            <button
              v-for="template in CREATE_TEMPLATES"
              :key="template.id"
              type="button"
              class="template-card"
              :class="{ active: createForm.template === template.id }"
              @click="createForm.template = template.id"
            >
              <strong>{{ template.name }}</strong>
              <span>{{ template.description }}</span>
            </button>
          </div>
          <label class="form-field">
            <span>任务描述</span>
            <NInput
              v-model:value="createForm.goal"
              type="textarea"
              :autosize="{ minRows: 4, maxRows: 7 }"
              placeholder="例如：阅读用户上传的会议纪要，提取关键结论、责任人、截止时间和待办事项。"
            />
            <small>系统会据此生成名称、执行规则和测试样例，后续仍可修改。</small>
          </label>
        </section>

        <section v-else-if="createStep === 2" class="wizard-panel">
          <div class="wizard-heading">
            <h3>确认名称和执行规则</h3>
            <p>普通用户只需调整业务内容；系统标识已经自动生成。</p>
          </div>
          <div class="form-grid">
            <label class="form-field">
              <span>Skill 名称</span>
              <NInput
                v-model:value="createForm.name"
                placeholder="用户看到的名称"
              />
            </label>
            <label class="form-field">
              <span>系统标识</span>
              <NInput
                v-model:value="createForm.id"
                placeholder="custom-skill-20260723"
              />
              <small>仅允许小写字母、数字和连字符；创建后不可修改。</small>
            </label>
            <label class="form-field full">
              <span>用途说明</span>
              <NInput
                v-model:value="createForm.description"
                placeholder="说明何时使用这个 Skill"
              />
            </label>
            <label class="form-field full">
              <span>执行规则</span>
              <NInput
                v-model:value="createForm.body"
                type="textarea"
                :autosize="{ minRows: 13, maxRows: 20 }"
                placeholder="写明目标、输入要求、执行步骤和输出格式"
              />
            </label>
          </div>
        </section>

        <section v-else class="wizard-panel">
          <div class="wizard-heading">
            <h3>创建前先验证一次</h3>
            <p>试跑不会创建文件；确认输出符合预期后再发布。</p>
          </div>
          <div class="draft-summary">
            <div>
              <span>名称</span>
              <strong>{{ createForm.name }}</strong>
            </div>
            <div>
              <span>系统标识</span>
              <strong>{{ createForm.id }}</strong>
            </div>
            <div class="full">
              <span>用途</span>
              <strong>{{ createForm.description }}</strong>
            </div>
          </div>
          <label class="form-field">
            <span>测试输入</span>
            <NInput
              v-model:value="createForm.testInput"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 6 }"
              placeholder="输入一条真实任务，检查 Skill 的输出"
            />
          </label>
          <div class="preview-actions">
            <NButton
              type="primary"
              secondary
              :loading="createPreviewing"
              :disabled="!createForm.testInput.trim()"
              @click="runCreatePreview"
            >
              运行试跑
            </NButton>
            <span
              v-if="createForm.testPassed"
              class="preview-passed"
            >
              ✓ 试跑完成，可以创建
            </span>
          </div>
          <div v-if="createForm.testOutput" class="preview-result">
            <div>试跑结果</div>
            <pre>{{ createForm.testOutput }}</pre>
          </div>
        </section>

        <div v-if="createError" class="wizard-error">{{ createError }}</div>

        <div class="wizard-footer">
          <NButton
            v-if="createStep > 1"
            secondary
            @click="previousCreateStep"
          >
            上一步
          </NButton>
          <span class="wizard-spacer" />
          <NButton
            v-if="createStep < 3"
            type="primary"
            @click="nextCreateStep"
          >
            下一步
          </NButton>
          <NButton
            v-else
            type="primary"
            :loading="createPublishing"
            :disabled="!createForm.testPassed"
            @click="publishCreate"
          >
            创建并启用
          </NButton>
        </div>
      </div>
    </NModal>

    <NModal
      v-model:show="editOpen"
      preset="card"
      title="编辑 Skill"
      style="width: 640px"
    >
      <NSpace vertical style="width: 100%">
        <label class="form-field">
          <span>名称</span>
          <NInput v-model:value="editForm.name" placeholder="名称" />
        </label>
        <label class="form-field">
          <span>说明</span>
          <NInput v-model:value="editForm.description" placeholder="说明" />
        </label>
        <label class="form-field">
          <span>执行规则</span>
          <NInput
            v-model:value="editForm.body"
            type="textarea"
            :autosize="{ minRows: 10, maxRows: 20 }"
            placeholder="正文"
          />
        </label>
        <NButton type="primary" @click="saveEdit">保存修改</NButton>
      </NSpace>
    </NModal>
  </div>
</template>

<style scoped>
.ra-page {
  overflow: hidden;
}
.ra-page :deep(.n-spin-container),
.ra-page :deep(.n-spin-content) {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 12px;
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.list {
  overflow: auto;
  min-height: 0;
  max-height: 100%;
}
.skill-search {
  margin-bottom: 14px;
}
.detail-panel {
  overflow: hidden;
  min-height: 0;
  max-height: 100%;
  display: flex;
  flex-direction: column;
}
.detail-panel :deep(.n-spin-container),
.detail-panel :deep(.n-spin-content) {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.group {
  margin-bottom: 16px;
}
.group-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--ra-muted);
  margin-bottom: 8px;
  letter-spacing: 0.02em;
}
.skill-item {
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
.skill-item.active {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
}
.s-name {
  font-size: 13px;
  font-weight: 650;
  display: flex;
  align-items: center;
  gap: 6px;
}
.s-desc {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ra-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.detail-head h2 {
  margin: 0;
  font-size: 18px;
}
.muted {
  color: var(--ra-muted);
  font-size: 12px;
  margin: 4px 0 0;
}
.tiny {
  font-size: 12px;
}
.tip {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--ra-warning);
  flex-shrink: 0;
}
.pkg-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  margin-bottom: 8px;
  align-items: stretch;
  overflow: hidden;
}
.file-tree {
  border: 1px solid var(--ra-border);
  border-radius: 12px;
  padding: 10px;
  background: #fafbfc;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.file-tree > .sub {
  flex-shrink: 0;
}
.file-tree-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.file-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: #fff;
  border-radius: 10px;
  padding: 8px;
  margin-bottom: 6px;
  cursor: pointer;
}
.file-item.on {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
}
.file-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}
.file-size {
  font-size: 10px;
  color: var(--ra-muted);
}
.file-path {
  margin-top: 4px;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
  line-height: 1.35;
}
.file-hint {
  margin-top: 8px;
  line-height: 1.45;
}
.file-view {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.file-view-head {
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.file-view-head .sub {
  margin-bottom: 0;
}
.file-view-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.file-view-body :deep(.n-spin-container),
.file-view-body :deep(.n-spin-content) {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.body,
.out {
  white-space: pre-wrap;
  word-break: break-word;
  background: #f8fafc;
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.55;
  min-height: 0;
  overflow: auto;
  flex: 1 1 auto;
  height: 100%;
  margin: 0;
}
.md-view {
  white-space: normal;
}
.md-view :deep(h3),
.md-view :deep(h4),
.md-view :deep(h5) {
  margin: 0.9em 0 0.4em;
  font-weight: 700;
  line-height: 1.35;
}
.md-view :deep(h3) {
  font-size: 1.25em;
}
.md-view :deep(h4) {
  font-size: 1.1em;
}
.md-view :deep(h5) {
  font-size: 1em;
}
.md-view :deep(p) {
  margin: 0 0 0.65em;
  line-height: 1.65;
}
.md-view :deep(ul) {
  margin: 0 0 0.75em;
  padding-left: 1.35em;
}
.md-view :deep(li) {
  margin: 0.25em 0;
  line-height: 1.55;
}
.md-view :deep(strong) {
  font-weight: 700;
}
.md-view :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  background: rgba(15, 23, 42, 0.06);
  padding: 0.1em 0.35em;
  border-radius: 4px;
}
.file-msg {
  margin: 0;
  padding: 16px;
  font-size: 13px;
  color: var(--ra-muted);
  background: #f8fafc;
  border-radius: 10px;
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.try {
  margin-top: 8px;
  border-top: 1px solid var(--ra-border);
  padding-top: 10px;
  flex-shrink: 0;
  max-height: 40vh;
  overflow: auto;
}
.try-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.try-head .sub {
  margin-bottom: 0;
}
.opt-chat {
  max-height: 180px;
  overflow: auto;
  margin-bottom: 8px;
  padding: 6px 8px;
  background: var(--ra-bg-soft, #f7f8fa);
  border-radius: 6px;
}
.opt-msg {
  margin-bottom: 10px;
  font-size: 13px;
}
.opt-msg.user .opt-text {
  color: #333;
}
.opt-msg.assistant .opt-text {
  color: #1a1a1a;
  white-space: pre-wrap;
}
.opt-role {
  font-size: 11px;
  color: #888;
  margin-bottom: 2px;
}
.tiny {
  font-size: 12px;
}
.sub {
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 13px;
}
.create-wizard {
  display: flex;
  flex-direction: column;
  min-height: 540px;
}
.wizard-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 24px;
}
.wizard-step {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  color: var(--ra-muted);
  background: #f7f9fc;
  border: 1px solid var(--ra-border);
  border-radius: 10px;
}
.wizard-step span {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border-radius: 50%;
  color: #64748b;
  background: #e8edf4;
  font-size: 12px;
  font-weight: 700;
}
.wizard-step strong {
  font-size: 13px;
}
.wizard-step.active,
.wizard-step.done {
  color: var(--ra-accent);
  border-color: color-mix(in srgb, var(--ra-accent) 35%, white);
  background: var(--ra-accent-soft);
}
.wizard-step.active span,
.wizard-step.done span {
  color: #fff;
  background: var(--ra-accent);
}
.wizard-panel {
  flex: 1;
  min-height: 0;
}
.wizard-heading {
  margin-bottom: 18px;
}
.wizard-heading h3 {
  margin: 0;
  font-size: 20px;
}
.wizard-heading p {
  margin: 6px 0 0;
  color: var(--ra-muted);
  font-size: 13px;
}
.template-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}
.template-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 82px;
  padding: 14px;
  text-align: left;
  color: inherit;
  background: #fff;
  border: 1px solid var(--ra-border);
  border-radius: 12px;
  cursor: pointer;
}
.template-card:hover {
  border-color: color-mix(in srgb, var(--ra-accent) 45%, white);
  background: #fbfdff;
}
.template-card.active {
  border-color: var(--ra-accent);
  background: var(--ra-accent-soft);
  box-shadow: 0 0 0 1px var(--ra-accent);
}
.template-card strong {
  font-size: 14px;
}
.template-card span {
  color: var(--ra-muted);
  font-size: 12px;
  line-height: 1.5;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  width: 100%;
}
.form-field > span {
  font-size: 13px;
  font-weight: 650;
}
.form-field small {
  color: var(--ra-muted);
  font-size: 11px;
  line-height: 1.45;
}
.form-field.full,
.draft-summary .full {
  grid-column: 1 / -1;
}
.draft-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
  padding: 14px;
  background: #f7f9fc;
  border: 1px solid var(--ra-border);
  border-radius: 12px;
}
.draft-summary > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.draft-summary span {
  color: var(--ra-muted);
  font-size: 11px;
}
.draft-summary strong {
  font-size: 13px;
}
.preview-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}
.preview-passed {
  color: #14804a;
  font-size: 12px;
  font-weight: 650;
}
.preview-result {
  margin-top: 14px;
  border: 1px solid var(--ra-border);
  border-radius: 12px;
  overflow: hidden;
}
.preview-result > div {
  padding: 9px 12px;
  background: #f7f9fc;
  border-bottom: 1px solid var(--ra-border);
  font-size: 12px;
  font-weight: 650;
}
.preview-result pre {
  max-height: 220px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.55;
}
.wizard-error {
  margin-top: 14px;
  padding: 10px 12px;
  color: #b42318;
  background: #fff1f0;
  border: 1px solid #ffd3cf;
  border-radius: 10px;
  font-size: 12px;
}
.wizard-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 22px;
  padding-top: 16px;
  border-top: 1px solid var(--ra-border);
}
.wizard-spacer {
  flex: 1;
}
@media (max-width: 960px) {
  .pkg-layout {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(140px, 30%) minmax(0, 1fr);
  }
  .template-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }
  .form-field.full,
  .draft-summary .full {
    grid-column: auto;
  }
}
@media (max-width: 680px) {
  .wizard-step {
    justify-content: center;
  }
  .wizard-step strong {
    display: none;
  }
  .draft-summary {
    grid-template-columns: 1fr;
  }
}
</style>
