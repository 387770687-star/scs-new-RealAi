<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  NButton,
  NInput,
  NSelect,
  NSpace,
  NScrollbar,
  useMessage,
} from "naive-ui";
import EvidencePanel from "@/components/EvidencePanel.vue";
import ChartBlock from "@/components/ChartBlock.vue";
import DataTableCard from "@/components/DataTableCard.vue";
import FilterConfirmCard from "@/components/FilterConfirmCard.vue";
import StatusDot from "@/components/StatusDot.vue";
import WebSearchModeSelect from "@/components/WebSearchModeSelect.vue";
import VisionModeSelect from "@/components/VisionModeSelect.vue";
import { fetchSkills } from "@/api/realai";
import type { FilterDraft } from "@/api/types";
import { useWorkbenchStore } from "@/stores/workbench";
import { useHealthStore } from "@/stores/health";
import type { EvidenceItem, WorkbenchIntent } from "@/api/types";
import { formatAnswerWithCitations } from "@/utils/citations";
import { splitMarkdownBlocks, type MarkdownBlock } from "@/utils/format";

const workbench = useWorkbenchStore();
const health = useHealthStore();
const message = useMessage();
const scrollRef = ref<InstanceType<typeof NScrollbar> | null>(null);
const triRef = ref<HTMLElement | null>(null);
const imageInputRef = ref<HTMLInputElement | null>(null);
const skillOptions = ref<Array<{ label: string; value: string }>>([]);

const COL_STORAGE_KEY = "realai.workbench.colWidths";
const DEFAULT_CTX_W = 200;
const DEFAULT_EV_W = 300;
const MIN_CTX_W = 140;
const MAX_CTX_W = 420;
const MIN_EV_W = 220;
const MAX_EV_W = 520;
const MIN_CHAT_W = 280;
const SPLITTER_W = 6;

function loadColWidths(): { ctx: number; ev: number } {
  try {
    const raw = localStorage.getItem(COL_STORAGE_KEY);
    if (!raw) return { ctx: DEFAULT_CTX_W, ev: DEFAULT_EV_W };
    const parsed = JSON.parse(raw) as { ctx?: number; ev?: number };
    return {
      ctx: clamp(Number(parsed.ctx) || DEFAULT_CTX_W, MIN_CTX_W, MAX_CTX_W),
      ev: clamp(Number(parsed.ev) || DEFAULT_EV_W, MIN_EV_W, MAX_EV_W),
    };
  } catch {
    return { ctx: DEFAULT_CTX_W, ev: DEFAULT_EV_W };
  }
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

const saved = loadColWidths();
const ctxWidth = ref(saved.ctx);
const evWidth = ref(saved.ev);
const resizing = ref<"ctx" | "ev" | null>(null);

function persistColWidths() {
  try {
    localStorage.setItem(
      COL_STORAGE_KEY,
      JSON.stringify({ ctx: ctxWidth.value, ev: evWidth.value }),
    );
  } catch {
    /* ignore */
  }
}

/** 与写作页共享默认知识范围；可多选；清空 = 全库 */
const SCOPE_CATEGORIES = [
  { id: "wiki", label: "整理知识", hint: "wiki", icon: "摘" },
  { id: "raw", label: "原始资料", hint: "raw", icon: "原" },
  { id: "pipelines", label: "管网", hint: "pipelines", icon: "管" },
  { id: "new_energy", label: "新能源", hint: "new_energy", icon: "新" },
  { id: "dataqa", label: "问数统计", hint: "dataqa", icon: "数" },
  { id: "entities", label: "实体", hint: "entities", icon: "实" },
  { id: "05_Metrics", label: "口径", hint: "05_Metrics", icon: "径" },
] as const;

const askSuggestions = [
  {
    query: "近五年各区域天然气需求变化",
    kicker: "趋势研判",
    title: "区域天然气需求变化",
    icon: "↗",
  },
  {
    query: "管网建设投资与里程对比",
    kicker: "结构化问数",
    title: "投资与建设里程对比",
    icon: "▥",
  },
  {
    query: "相关报告如何解释增幅原因",
    kicker: "证据检索",
    title: "解释指标增幅原因",
    icon: "⌕",
  },
];

const INTENT_META: Record<
  WorkbenchIntent,
  { label: string; description: string; short: string }
> = {
  ask: {
    label: "问答",
    description: "综合理解知识库内容并给出有依据的回答",
    short: "综合分析",
  },
  data: {
    label: "问数",
    description: "对结构化数据执行精确查询与计算",
    short: "精确计算",
  },
  research: {
    label: "检索",
    description: "跨资料检索原文、政策和外部来源",
    short: "深度检索",
  },
};

const showEvidenceCol = computed(() => workbench.evidenceOpen);
const suggestions = computed(() => askSuggestions);
const activeIntentMeta = computed(() => INTENT_META[workbench.intent]);

const triStyle = computed(() => ({
  "--ctx-w": `${ctxWidth.value}px`,
  "--ev-w": showEvidenceCol.value ? `${evWidth.value}px` : "0px",
  "--splitter-w": `${SPLITTER_W}px`,
}));

function startResize(which: "ctx" | "ev", e: PointerEvent) {
  e.preventDefault();
  resizing.value = which;
  const startX = e.clientX;
  const startCtx = ctxWidth.value;
  const startEv = evWidth.value;
  const triW = triRef.value?.clientWidth ?? 0;

  const onMove = (ev: PointerEvent) => {
    const dx = ev.clientX - startX;
    if (which === "ctx") {
      const maxByChat = Math.max(
        MIN_CTX_W,
        triW - MIN_CHAT_W - SPLITTER_W - (showEvidenceCol.value ? startEv + SPLITTER_W : 0),
      );
      ctxWidth.value = clamp(startCtx + dx, MIN_CTX_W, Math.min(MAX_CTX_W, maxByChat));
    } else {
      const maxByChat = Math.max(
        MIN_EV_W,
        triW - startCtx - SPLITTER_W - MIN_CHAT_W - SPLITTER_W,
      );
      // drag left edge of evidence: moving pointer right shrinks evidence
      evWidth.value = clamp(startEv - dx, MIN_EV_W, Math.min(MAX_EV_W, maxByChat));
    }
  };

  const onUp = () => {
    resizing.value = null;
    persistColWidths();
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  };

  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

function onResizeKeydown(which: "ctx" | "ev", e: KeyboardEvent) {
  const step = e.shiftKey ? 24 : 8;
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  e.preventDefault();
  const dir = e.key === "ArrowRight" ? 1 : -1;
  if (which === "ctx") {
    // 分隔条右移 → 左侧栏变宽
    ctxWidth.value = clamp(ctxWidth.value + dir * step, MIN_CTX_W, MAX_CTX_W);
  } else {
    // 分隔条右移 → 证据栏变窄
    evWidth.value = clamp(evWidth.value - dir * step, MIN_EV_W, MAX_EV_W);
  }
  persistColWidths();
}

const scopeSummary = computed(() => {
  const ids = workbench.scopePaths;
  if (!ids.length) return "全库";
  return ids
    .map((id) => SCOPE_CATEGORIES.find((c) => c.id === id)?.label || id)
    .join("、");
});

onMounted(async () => {
  await Promise.all([
    workbench.loadSessions(),
    fetchSkills(false)
      .then((res) => {
        skillOptions.value = res.skills
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
      })
      .catch(() => {
        skillOptions.value = [];
      }),
  ]);
});

onUnmounted(() => {
  resizing.value = null;
});

watch(
  () => [
    workbench.messages.length,
    workbench.messages.map((m) => m.trajectory?.length ?? 0).join(","),
    workbench.asking,
  ],
  async () => {
    await nextTick();
    scrollRef.value?.scrollTo({ top: 999999, behavior: "smooth" });
  },
);

async function submit() {
  if (!health.online) {
    message.error("服务离线");
    return;
  }
  await workbench.ask();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void submit();
  }
}

function toggleScope(categoryId: string) {
  const i = workbench.scopePaths.indexOf(categoryId);
  if (i >= 0) workbench.scopePaths.splice(i, 1);
  else workbench.scopePaths.push(categoryId);
}

function clearScope() {
  workbench.scopePaths.splice(0, workbench.scopePaths.length);
}

function setMode(m: WorkbenchIntent) {
  workbench.setIntent(m);
}

/** 问数表常见英文字段 → 中文表头（未知字段原样显示） */
const TABLE_COL_LABELS: Record<string, string> = {
  source_file: "来源文件",
  pipe_section_name: "管段名称",
  pipeline_name: "管线名称",
  start_station_name: "起始站",
  end_station_name: "终止站",
  pipe_section_length: "管段长度(km)",
  pipe_diameter: "管径(mm)",
  design_pressure: "设计压力",
  design_trans_flow_rate: "设计输量",
  medium_tran: "介质",
  use_status: "使用状态",
  owner_company: "所属单位",
  build_status: "建设状态",
  administrative_division_name: "行政区",
};

function colLabel(c: string) {
  return TABLE_COL_LABELS[c] || c;
}

function skillTriggerLabel(trigger?: string) {
  if (trigger === "slash") return "斜杠指定";
  if (trigger === "selected") return "手动选择";
  if (trigger === "auto_rule") return "规则匹配";
  return "已启用";
}

function evidenceItemsForMessage(m: {
  evidence?: { items?: EvidenceItem[] };
  id: string;
  role: string;
}) {
  if (m.evidence?.items?.length) return m.evidence.items;
  // 当前选中的最新助手消息：侧栏 lastEvidence 兜底
  const lastAssistant = [...workbench.messages].reverse().find((x) => x.role === "assistant");
  if (lastAssistant && m.id === lastAssistant.id && workbench.lastEvidence?.items?.length) {
    return workbench.lastEvidence.items;
  }
  return undefined;
}

function assistantBlocks(
  content: string,
  m: { evidence?: { items?: EvidenceItem[] }; id: string; role: string },
): MarkdownBlock[] {
  return splitMarkdownBlocks(formatAnswerWithCitations(content, evidenceItemsForMessage(m)));
}

function trajIsCurrent(
  m: { pending?: boolean; filterStatus?: string; trajectory?: string[] },
  si: number,
) {
  const traj = m.trajectory || [];
  if (m.filterStatus === "pending" && traj[si] === "等待确认筛选条件") return true;
  return !!m.pending && si === traj.length - 1;
}

function onConfirmFilter(messageId: string, draft: FilterDraft) {
  void workbench.confirmFilter(messageId, draft);
}

function onCancelFilter(messageId: string) {
  workbench.cancelFilter(messageId);
}

function pickImage() {
  imageInputRef.value?.click();
}

async function onImagePicked(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    await workbench.attachImage(file);
    message.success(`已添加图片：${file.name}`);
  } catch (err) {
    message.error(err instanceof Error ? err.message : String(err));
  }
}
</script>

<template>
  <div class="workbench ra-fade-in">
    <header class="topbar">
      <div class="topbar-title">
        <div class="topbar-kicker">智能研究中枢</div>
        <h1>工作台</h1>
      </div>
      <NSpace align="center" :size="8" class="topbar-actions">
        <StatusDot :online="health.online" />
        <WebSearchModeSelect />
        <VisionModeSelect />
        <NButton size="small" secondary round @click="workbench.toggleEvidence">证据</NButton>
        <NButton size="small" quaternary round @click="workbench.newSession()">新会话</NButton>
        <NButton size="small" quaternary @click="workbench.clearChat">清空本页</NButton>
      </NSpace>
    </header>

    <div
      ref="triRef"
      class="tri"
      :class="{ resizing: !!resizing }"
      :style="triStyle"
    >
      <aside class="col ctx">
        <section class="ctx-section sessions-section">
          <div class="section-head">
            <div>
              <div class="label">最近会话</div>
              <div class="section-caption">{{ workbench.sessions.length }} 个历史任务</div>
            </div>
            <span class="section-count">{{ workbench.sessions.length }}</span>
          </div>
          <button
            type="button"
            class="new-session"
            @click="workbench.newSession()"
          >
            <span class="new-session-icon">＋</span>
            <span>新建会话</span>
            <span class="new-session-arrow">↗</span>
          </button>
          <div class="session-list ra-scroll">
            <button
              v-for="s in workbench.sessions"
              :key="s.id"
              type="button"
              class="asset session"
              :class="{ on: workbench.sessionId === s.id }"
              @click="workbench.openSession(s.id)"
            >
              <span class="session-dot" />
              <span class="sess-title">{{ s.title || "未命名" }}</span>
              <span
                class="sess-del"
                title="删除"
                @click.stop="workbench.removeSession(s.id)"
              >×</span>
            </button>
            <p v-if="!workbench.sessions.length" class="muted tiny empty-copy">
              暂无历史会话
            </p>
          </div>
        </section>

        <section class="ctx-section scope-section">
          <div class="section-head">
            <div>
              <div class="label">知识范围</div>
              <div class="section-caption">可多选，不选即检索全库</div>
            </div>
            <span class="scope-state">
              {{ workbench.scopePaths.length || "全" }}
            </span>
          </div>
          <div class="scope-grid">
            <button
              v-for="c in SCOPE_CATEGORIES"
              :key="c.id"
              type="button"
              class="asset scope-cat"
              :class="{ on: workbench.scopePaths.includes(c.id) }"
              @click="toggleScope(c.id)"
            >
              <span class="scope-icon">{{ c.icon }}</span>
              <span class="scope-copy">
                <span class="sess-title">{{ c.label }}</span>
                <span class="scope-hint">{{ c.hint }}</span>
              </span>
              <span class="scope-check">✓</span>
            </button>
          </div>
          <button
            v-if="workbench.scopePaths.length"
            type="button"
            class="scope-reset"
            @click="clearScope"
          >
            恢复全库范围
          </button>
        </section>
      </aside>

      <div
        class="splitter"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整左侧栏宽度"
        tabindex="0"
        @pointerdown="startResize('ctx', $event)"
        @keydown="onResizeKeydown('ctx', $event)"
      />

      <main class="col chat">
        <div class="intent-shell">
          <div class="intent-bar">
            <button
              v-for="(meta, mode) in INTENT_META"
              :key="mode"
              type="button"
              class="intent-option"
              :class="{ active: workbench.intent === mode }"
              @click="setMode(mode)"
            >
              <span>{{ meta.label }}</span>
              <small>{{ meta.short }}</small>
            </button>
          </div>
          <div class="intent-caption">
            <span class="intent-caption-dot" />
            {{ activeIntentMeta.description }}
          </div>
        </div>

        <NScrollbar ref="scrollRef" class="chat-scroll">
          <div v-if="!workbench.messages.length" class="hero">
            <div class="hero-visual" aria-hidden="true">
              <div class="hero-ring ring-one" />
              <div class="hero-ring ring-two" />
              <div class="hero-node node-one" />
              <div class="hero-node node-two" />
              <div class="hero-node node-three" />
              <svg viewBox="0 0 64 64" class="hero-mark">
                <path
                  d="M18 22.5C18 16.7 22.7 12 28.5 12c2.4 0 4.7.8 6.5 2.2A11 11 0 0 1 50 24.5c0 1.8-.4 3.5-1.2 5A10.5 10.5 0 0 1 43 49H22a10 10 0 0 1-4-19.2 11 11 0 0 1 0-7.3Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="3.2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  d="M25 27h14M25 34h14M29 41h6"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="3.2"
                  stroke-linecap="round"
                />
              </svg>
            </div>
            <div class="hero-badge">
              <span class="hero-badge-dot" />
              战略规划智能工作空间
            </div>
            <h2>
              <span>战略规划域</span>
              <span class="hero-gradient">多源多模态知识大脑</span>
            </h2>
            <p class="hero-desc">
              连接企业知识、结构化数据与可信来源，让检索、问数和研判在同一个工作台完成。
            </p>
            <div class="hero-capabilities" role="list" aria-label="核心能力">
              <div role="listitem">
                <span class="cap-icon">01</span>
                <strong>多源知识检索</strong>
                <small>政策、报告与业务资料</small>
              </div>
              <div role="listitem">
                <span class="cap-icon">02</span>
                <strong>结构化精确问数</strong>
                <small>Excel 数据直接计算</small>
              </div>
              <div role="listitem">
                <span class="cap-icon">03</span>
                <strong>全链路证据溯源</strong>
                <small>结果、口径与原文可追踪</small>
              </div>
            </div>
            <div class="suggest-label">试试这些问题</div>
            <div class="suggests">
              <button
                v-for="s in suggestions"
                :key="s.query"
                type="button"
                class="suggest-card"
                @click="workbench.useSuggestion(s.query)"
              >
                <span class="suggest-icon">{{ s.icon }}</span>
                <span class="suggest-copy">
                  <small>{{ s.kicker }}</small>
                  <strong>{{ s.title }}</strong>
                </span>
                <span class="suggest-arrow">→</span>
              </button>
            </div>
          </div>

          <div v-for="m in workbench.messages" :key="m.id" class="msg" :class="m.role">
            <div class="bubble">
              <div v-if="m.role === 'assistant' && m.skillUsed" class="skill-runtime-chip">
                <span>Skill</span>
                <strong>{{ m.skillUsed.name || m.skillUsed.id }}</strong>
                <small>{{ skillTriggerLabel(m.skillUsed.trigger) }}</small>
              </div>
              <ol
                v-if="m.role === 'assistant' && m.trajectory?.length"
                class="msg-trajectory"
              >
                <li
                  v-for="(step, si) in m.trajectory"
                  :key="`${m.id}-${si}-${step}`"
                  :class="{
                    done:
                      m.filterStatus === 'pending'
                        ? step !== '等待确认筛选条件' &&
                          !(m.pending && si === m.trajectory.length - 1)
                        : !m.pending || si < m.trajectory.length - 1,
                    current: trajIsCurrent(m, si),
                  }"
                >
                  <span
                    v-if="trajIsCurrent(m, si)"
                    class="ra-thinking traj-spin"
                  >
                    <span class="ra-thinking-dot" />
                  </span>
                  <span v-else class="traj-mark">✓</span>
                  {{ step }}
                </li>
              </ol>
              <div
                v-else-if="m.role === 'assistant' && m.pending"
                class="msg-pending"
              >
                <span class="ra-thinking"><span class="ra-thinking-dot" />处理中</span>
              </div>
              <FilterConfirmCard
                v-if="m.filterDraft && m.filterStatus && m.filterStatus !== 'cancelled'"
                :draft="m.filterDraft"
                :status="m.filterStatus"
                :loading="workbench.asking && m.filterStatus === 'pending'"
                @confirm="(d) => onConfirmFilter(m.id, d)"
                @cancel="onCancelFilter(m.id)"
              />
              <div v-if="m.role === 'assistant' && m.content" class="answer-blocks">
                <template v-for="(block, bi) in assistantBlocks(m.content, m)" :key="bi">
                  <div v-if="block.type === 'html'" class="md" v-html="block.html" />
                  <DataTableCard
                    v-else
                    :title="block.title || '表格'"
                    :columns="block.columns"
                    :rows="block.rows"
                  />
                </template>
              </div>
              <pre v-else-if="m.role !== 'assistant'">{{ m.content }}</pre>
              <div v-if="m.entityProfile" class="entity-profile">
                <div class="ep-title">
                  实体名片 · {{ m.entityProfile.name }}
                  <span v-if="m.entityProfile.type" class="ep-type">{{ m.entityProfile.type }}</span>
                </div>
                <ul v-if="m.entityProfile.summary_bullets?.length" class="ep-bullets">
                  <li v-for="(b, bi) in m.entityProfile.summary_bullets" :key="bi">{{ b }}</li>
                </ul>
                <div v-if="m.entityProfile.related?.length" class="ep-related">
                  相关：{{ m.entityProfile.related.slice(0, 8).join("、") }}
                </div>
              </div>
              <div v-if="m.tables?.some((t) => t.columns?.length)" class="tables">
                <DataTableCard
                  v-for="t in m.tables.filter((x) => x.columns?.length)"
                  :key="t.id"
                  :title="t.title?.startsWith('筛选结果') ? t.title : `问数结果 · ${t.title}`"
                  :columns="t.columns"
                  :rows="t.rows || []"
                  :column-labels="colLabel"
                  :source-hint="t.title"
                />
              </div>
              <ChartBlock
                v-if="m.chartSpec?.series?.some((s) => s.data?.some((v) => v !== 0 && !Number.isNaN(v)))"
                :spec="m.chartSpec"
              />
              <div
                v-if="m.role === 'assistant' && !m.pending && m.filterStatus !== 'pending'"
                class="msg-actions"
              >
                <NButton
                  v-if="m.evidence?.items?.length"
                  size="tiny"
                  secondary
                  @click="workbench.showEvidence(m.evidence, m.trajectory)"
                >
                  证据 {{ m.evidence.items.length }}
                </NButton>
              </div>
            </div>
          </div>
        </NScrollbar>

        <div class="composer">
          <input
            ref="imageInputRef"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
            class="hidden-file"
            @change="onImagePicked"
          />
          <div v-if="workbench.pendingImages.length" class="pending-images">
            <span
              v-for="img in workbench.pendingImages"
              :key="img.path"
              class="img-chip"
            >
              {{ img.name }}
              <button type="button" class="img-x" @click="workbench.removePendingImage(img.path)">×</button>
            </span>
          </div>
          <div class="composer-skill-row">
            <div>
              <strong>回答 Skill</strong>
              <span>选择后按该方法回答；清空恢复默认，也可输入 /skill-id 问题</span>
            </div>
            <NSelect
              v-model:value="workbench.selectedSkillId"
              class="composer-skill-select"
              :options="skillOptions"
              clearable
              filterable
              size="small"
              placeholder="系统默认"
              :disabled="workbench.asking"
            />
          </div>
          <NInput
            v-model:value="workbench.draft"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="提问（可添加图片看图识表）"
            :disabled="workbench.asking"
            @keydown="onKeydown"
          />
          <div class="composer-actions">
            <span class="scope-summary" :title="scopeSummary">
              <span class="scope-summary-dot" />
              知识范围：{{ scopeSummary }}
            </span>
            <div class="composer-btns">
              <span class="keyboard-hint">Enter 发送 · Shift + Enter 换行</span>
              <NButton
                size="small"
                secondary
                round
                :loading="workbench.uploadingImage"
                :disabled="workbench.asking"
                @click="pickImage"
              >
                添加图片
              </NButton>
              <NButton type="primary" round :loading="workbench.asking" @click="submit">
                发送
              </NButton>
            </div>
          </div>
        </div>
      </main>

      <div
        v-show="showEvidenceCol"
        class="splitter"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整证据栏宽度"
        tabindex="0"
        @pointerdown="startResize('ev', $event)"
        @keydown="onResizeKeydown('ev', $event)"
      />

      <aside v-show="showEvidenceCol" class="col ev">
        <EvidencePanel
          :evidence="workbench.lastEvidence"
          :trajectory="workbench.lastTrajectory"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped>
.workbench {
  flex: 1;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
  position: relative;
}
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  min-height: 44px;
  padding: 0 4px;
}
.topbar-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.topbar-kicker {
  order: 2;
  color: #8a97aa;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.topbar h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 750;
  letter-spacing: -0.035em;
  color: #172033;
}
.topbar-actions {
  padding: 4px 6px;
  border: 1px solid rgba(57, 126, 236, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.66);
  box-shadow: 0 8px 24px rgba(37, 67, 116, 0.04);
  backdrop-filter: blur(16px);
}
.muted {
  color: var(--ra-muted);
  font-size: 12px;
}
.tiny {
  font-size: 12px;
}
.hint {
  margin-top: 8px;
  line-height: 1.4;
}
.tri {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  gap: 0;
  border-radius: 24px;
}
.tri.resizing {
  cursor: col-resize;
  user-select: none;
}
.tri.resizing * {
  cursor: col-resize !important;
}
.col {
  min-height: 0;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  overflow: auto;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(57, 126, 236, 0.1);
  border-radius: 22px;
  padding: 14px;
  min-width: 0;
  box-shadow:
    0 18px 54px rgba(43, 82, 140, 0.055),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(18px);
}
.col.ctx {
  flex: 0 0 var(--ctx-w, 200px);
  width: var(--ctx-w, 200px);
  gap: 14px;
  overflow: hidden;
  background:
    radial-gradient(260px 180px at 0% 0%, rgba(57, 126, 236, 0.08), transparent 70%),
    rgba(255, 255, 255, 0.9);
}
.col.chat {
  flex: 1 1 auto;
  overflow: hidden; /* 聊天区由内部 scrollbar 滚 */
  padding: 0;
  background:
    radial-gradient(520px 300px at 50% 12%, rgba(57, 126, 236, 0.055), transparent 72%),
    rgba(255, 255, 255, 0.92);
}
.col.ev {
  flex: 0 0 var(--ev-w, 300px);
  width: var(--ev-w, 300px);
  overflow: hidden; /* 证据栏顶部固定，列表内部滚 */
  background:
    radial-gradient(280px 180px at 100% 0%, rgba(50, 207, 252, 0.075), transparent 72%),
    rgba(255, 255, 255, 0.9);
}
.splitter {
  flex: 0 0 var(--splitter-w, 6px);
  width: var(--splitter-w, 6px);
  margin: 0 2px;
  border-radius: 999px;
  cursor: col-resize;
  touch-action: none;
  background: transparent;
  position: relative;
}
.splitter::after {
  content: "";
  position: absolute;
  top: 44%;
  bottom: auto;
  left: 50%;
  width: 3px;
  height: 52px;
  transform: translateX(-50%);
  border-radius: 2px;
  background: rgba(104, 132, 173, 0.2);
  opacity: 0.8;
  transition: background 0.15s ease, opacity 0.15s ease, width 0.15s ease;
}
.splitter:hover::after,
.splitter:focus-visible::after,
.tri.resizing .splitter::after {
  width: 3px;
  background: var(--ra-accent, #397eec);
  opacity: 1;
}
.splitter:focus-visible {
  outline: none;
}
.label {
  font-size: 13px;
  font-weight: 700;
  color: #1f2a3d;
  letter-spacing: -0.01em;
}
.ctx-section {
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.sessions-section {
  flex: 1 1 42%;
}
.scope-section {
  flex: 0 1 auto;
  padding-top: 14px;
  border-top: 1px solid rgba(57, 126, 236, 0.09);
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.section-caption {
  margin-top: 2px;
  color: #98a4b5;
  font-size: 10px;
  line-height: 1.35;
}
.section-count,
.scope-state {
  flex: 0 0 auto;
  min-width: 24px;
  height: 24px;
  padding: 0 7px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #eef4fd;
  color: #5f7ea9;
  font-size: 10px;
  font-weight: 700;
}
.scope-state {
  background: rgba(57, 126, 236, 0.11);
  color: var(--ra-accent);
}
.new-session {
  width: 100%;
  min-height: 42px;
  margin-bottom: 9px;
  padding: 7px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #2f73e8 0%, #438af2 58%, #55a1f5 100%);
  color: #fff;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(57, 126, 236, 0.22);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.new-session:hover {
  transform: translateY(-1px);
  box-shadow: 0 13px 28px rgba(57, 126, 236, 0.28);
}
.new-session-icon {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.16);
  font-size: 16px;
  line-height: 1;
}
.new-session-arrow {
  margin-left: auto;
  opacity: 0.72;
  font-size: 13px;
}
.session-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}
.asset {
  display: flex;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 11px;
  padding: 8px 9px;
  margin-bottom: 3px;
  font-size: 12px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #455269;
  transition: 0.16s ease;
}
.asset:hover {
  background: rgba(241, 246, 253, 0.9);
  color: #24344d;
}
.asset.on {
  border-color: rgba(57, 126, 236, 0.11);
  background: linear-gradient(90deg, rgba(57, 126, 236, 0.12), rgba(57, 126, 236, 0.055));
  color: #1f64ce;
  box-shadow: inset 3px 0 0 var(--ra-accent);
}
.asset.session,
.asset.scope-cat {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: normal;
}
.session-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  border-radius: 50%;
  background: #c9d4e3;
}
.asset.session.on .session-dot {
  background: var(--ra-accent);
  box-shadow: 0 0 0 3px rgba(57, 126, 236, 0.11);
}
.sess-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sess-del {
  flex-shrink: 0;
  opacity: 0;
  padding: 0 4px;
  transition: opacity 0.16s ease;
}
.asset.session:hover .sess-del,
.asset.session:focus-visible .sess-del {
  opacity: 0.45;
}
.sess-del:hover {
  opacity: 1;
  color: #b91c1c;
}
.scope-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(86px, 1fr));
  gap: 6px;
}
.asset.scope-cat {
  position: relative;
  min-height: 48px;
  margin: 0;
  padding: 7px;
  align-items: center;
  gap: 7px;
  border-color: rgba(57, 126, 236, 0.075);
  background: rgba(248, 250, 253, 0.7);
  white-space: normal;
}
.asset.scope-cat.on {
  border-color: rgba(57, 126, 236, 0.19);
  background: linear-gradient(145deg, #edf5ff, #f7faff);
  box-shadow: none;
}
.scope-icon {
  width: 25px;
  height: 25px;
  flex: 0 0 25px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #edf2f8;
  color: #76869d;
  font-size: 10px;
  font-weight: 700;
}
.asset.scope-cat.on .scope-icon {
  background: var(--ra-accent);
  color: #fff;
  box-shadow: 0 5px 12px rgba(57, 126, 236, 0.2);
}
.scope-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.scope-hint {
  overflow: hidden;
  color: #9aa6b8;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scope-check {
  position: absolute;
  top: 4px;
  right: 5px;
  color: var(--ra-accent);
  font-size: 9px;
  font-weight: 800;
  opacity: 0;
}
.asset.scope-cat.on .scope-check {
  opacity: 1;
}
.scope-reset {
  align-self: center;
  margin-top: 9px;
  padding: 3px 8px;
  border: none;
  background: transparent;
  color: #8491a4;
  font-size: 10px;
  cursor: pointer;
}
.scope-reset:hover {
  color: var(--ra-accent);
}
.empty-copy {
  padding: 12px 8px;
  text-align: center;
}
.draft-box {
  margin-top: 10px;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #f8fafc;
  border-radius: 12px;
  padding: 10px;
}
.draft-title {
  font-weight: 650;
  font-size: 13px;
}
.draft-body {
  margin: 8px 0 0;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
  color: #334155;
}
.intent-shell {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 68px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(57, 126, 236, 0.085);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(18px);
}
.intent-bar {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 14px;
  background: #f1f5fa;
  box-shadow: inset 0 0 0 1px rgba(57, 126, 236, 0.055);
}
.intent-option {
  min-width: 74px;
  height: 38px;
  padding: 4px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: none;
  border-radius: 11px;
  background: transparent;
  color: #5b687c;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: 0.18s ease;
}
.intent-option small {
  display: none;
  font-size: 9px;
  font-weight: 500;
  opacity: 0.75;
}
.intent-option:hover {
  color: #1e5dbd;
  background: rgba(255, 255, 255, 0.7);
}
.intent-option.active {
  color: #fff;
  background: linear-gradient(135deg, #2f73e8, #438af2);
  box-shadow: 0 7px 16px rgba(57, 126, 236, 0.22);
}
.intent-caption {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #8290a3;
  font-size: 11px;
  line-height: 1.4;
  text-align: right;
}
.intent-caption-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: #4f91f2;
  box-shadow: 0 0 0 4px rgba(57, 126, 236, 0.09);
}
.chat-scroll {
  flex: 1;
  min-height: 0;
}
.chat-scroll :deep(.n-scrollbar-content) {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 18px 0;
}
.hero {
  flex: 1;
  min-height: 560px;
  width: min(900px, 100%);
  margin: auto;
  padding: clamp(34px, 6vh, 72px) 24px 36px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.hero-visual {
  position: relative;
  width: 86px;
  height: 86px;
  margin-bottom: 20px;
  display: grid;
  place-items: center;
  border-radius: 28px;
  color: #fff;
  background: linear-gradient(145deg, #195fd4 0%, #397eec 54%, #5da9f6 100%);
  box-shadow:
    0 20px 44px rgba(57, 126, 236, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.34);
}
.hero-mark {
  position: relative;
  z-index: 2;
  width: 50px;
  height: 50px;
}
.hero-ring {
  position: absolute;
  border: 1px solid rgba(57, 126, 236, 0.15);
  border-radius: 50%;
  pointer-events: none;
}
.ring-one {
  width: 128px;
  height: 128px;
}
.ring-two {
  width: 172px;
  height: 172px;
  border-style: dashed;
  opacity: 0.64;
}
.hero-node {
  position: absolute;
  z-index: 3;
  width: 8px;
  height: 8px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: var(--ra-cyan);
  box-shadow: 0 3px 10px rgba(57, 126, 236, 0.24);
}
.node-one {
  top: -17px;
  right: -9px;
}
.node-two {
  left: -37px;
  bottom: 1px;
  background: var(--ra-purple);
}
.node-three {
  right: -42px;
  bottom: -15px;
  background: #55d4a5;
}
.hero-badge {
  margin-bottom: 10px;
  padding: 6px 11px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid rgba(57, 126, 236, 0.13);
  border-radius: 999px;
  background: rgba(241, 247, 255, 0.9);
  color: #4672af;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.06em;
}
.hero-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2eb48e;
  box-shadow: 0 0 0 3px rgba(46, 180, 142, 0.11);
}
.hero h2 {
  margin: 0;
  color: var(--ra-text);
  font-size: clamp(27px, 2.7vw, 38px);
  font-weight: 750;
  letter-spacing: -0.055em;
  line-height: 1.18;
}
.hero h2 > span {
  display: block;
}
.hero-gradient {
  margin-top: 3px;
  background: linear-gradient(92deg, #1b5bc8 4%, #397eec 54%, #4ba7dd 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero-desc {
  max-width: 630px;
  margin: 14px auto 0;
  color: #76849a;
  font-size: 13px;
  line-height: 1.7;
}
.hero-capabilities {
  width: min(700px, 100%);
  margin-top: 24px;
  padding: 13px 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-top: 1px solid rgba(77, 106, 148, 0.1);
  border-bottom: 1px solid rgba(77, 106, 148, 0.1);
}
.hero-capabilities > div {
  position: relative;
  min-width: 0;
  padding: 0 22px;
  display: grid;
  grid-template-columns: 24px 1fr;
  grid-template-areas:
    "icon title"
    "icon copy";
  column-gap: 9px;
  text-align: left;
}
.hero-capabilities > div:not(:last-child)::after {
  content: "";
  position: absolute;
  top: 2px;
  right: 0;
  bottom: 2px;
  width: 1px;
  background: rgba(77, 106, 148, 0.1);
}
.cap-icon {
  grid-area: icon;
  align-self: start;
  padding-top: 1px;
  color: #8aa4c7;
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.04em;
}
.hero-capabilities strong {
  grid-area: title;
  color: #28364c;
  font-size: 11px;
  font-weight: 700;
}
.hero-capabilities small {
  grid-area: copy;
  margin-top: 2px;
  overflow: hidden;
  color: #8a97a9;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.suggest-label {
  width: min(700px, 100%);
  margin: 27px auto 9px;
  color: #8a97a9;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.06em;
  text-align: left;
}
.suggests {
  width: min(700px, 100%);
  display: flex;
  gap: 9px;
  justify-content: stretch;
}
.suggest-card {
  flex: 1;
  min-width: 0;
  padding: 10px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid rgba(57, 126, 236, 0.1);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  color: #26364f;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(46, 75, 118, 0.04);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.suggest-card:hover {
  transform: translateY(-2px);
  border-color: rgba(57, 126, 236, 0.28);
  box-shadow: 0 13px 30px rgba(57, 126, 236, 0.09);
}
.suggest-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: linear-gradient(145deg, #edf5ff, #e8f0fd);
  color: var(--ra-accent);
  font-size: 15px;
  font-weight: 700;
}
.suggest-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.suggest-copy small {
  color: #96a2b3;
  font-size: 9px;
}
.suggest-copy strong {
  overflow: hidden;
  font-size: 10px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.suggest-arrow {
  margin-left: auto;
  color: #9cabc0;
  font-size: 13px;
}
.msg {
  display: flex;
  margin-bottom: 14px;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: min(92%, 980px);
  padding: 14px 16px;
  border-radius: 18px;
  background: #fff;
  border: 1px solid rgba(57, 126, 236, 0.095);
  box-shadow: 0 9px 26px rgba(43, 72, 114, 0.045);
}
.msg.user .bubble {
  background: linear-gradient(135deg, #2f73e8, #438af2);
  color: #fff;
  border: none;
  box-shadow: 0 10px 24px rgba(57, 126, 236, 0.2);
}
.msg.system .bubble {
  background: #fff7ed;
}
.bubble pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
}
.md :deep(p) {
  margin: 0 0 0.5em;
  font-size: 14px;
  line-height: 1.65;
}
.answer-blocks {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.msg-trajectory {
  margin: 0 0 10px;
  padding: 0 0 0 1.1em;
  font-size: 12px;
  line-height: 1.55;
  color: var(--ra-muted, #64748b);
  list-style: none;
}
.msg-trajectory li {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
  padding-left: 0;
}
.msg-trajectory li.done {
  color: #475569;
}
.msg-trajectory li.current {
  color: var(--ra-accent, #397eec);
  font-weight: 550;
}
.traj-mark {
  flex-shrink: 0;
  width: 1em;
  text-align: center;
  color: #94a3b8;
  font-size: 11px;
}
.msg-trajectory li.done .traj-mark {
  color: #16a34a;
}
.traj-spin {
  flex-shrink: 0;
}
.msg-pending {
  margin-bottom: 4px;
}
.msg-actions {
  margin-top: 8px;
  display: flex;
  gap: 6px;
}
.tables {
  margin-top: 4px;
}
.entity-profile {
  margin: 8px 0 4px;
  padding: 10px 12px;
  border: 1px solid rgba(57, 126, 236, 0.24);
  border-radius: 10px;
  background: linear-gradient(180deg, #f2f7ff 0%, #fff 100%);
}
.ep-title {
  font-size: 13px;
  font-weight: 650;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ep-type {
  font-size: 11px;
  font-weight: 500;
  color: var(--ra-accent);
  background: var(--ra-accent-soft);
  border-radius: 999px;
  padding: 1px 8px;
}
.ep-bullets {
  margin: 8px 0 0;
  padding-left: 1.1em;
  font-size: 12px;
  line-height: 1.55;
  color: #334155;
}
.ep-related {
  margin-top: 8px;
  font-size: 11px;
  color: var(--ra-muted, #64748b);
  line-height: 1.45;
}
.skill-runtime-chip {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 9px;
  padding: 4px 8px;
  color: #49617f;
  border: 1px solid rgba(57, 126, 236, 0.14);
  border-radius: 999px;
  background: #f4f8ff;
  font-size: 10px;
}
.skill-runtime-chip > span {
  color: #2f75dc;
  font-weight: 700;
}
.skill-runtime-chip strong {
  font-size: 10px;
}
.skill-runtime-chip small {
  color: #8a97aa;
}
.composer {
  position: relative;
  z-index: 3;
  flex-shrink: 0;
  margin: 0 16px 14px;
  padding: 11px 12px 10px;
  border: 1px solid rgba(57, 126, 236, 0.14);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow:
    0 18px 42px rgba(42, 74, 120, 0.1),
    0 2px 8px rgba(42, 74, 120, 0.04);
  backdrop-filter: blur(18px);
}
.composer :deep(.n-input) {
  --n-border: 0 !important;
  --n-border-hover: 0 !important;
  --n-border-focus: 0 !important;
  --n-box-shadow-focus: none !important;
  --n-color: transparent !important;
  --n-color-focus: transparent !important;
  --n-padding-left: 2px !important;
  --n-padding-right: 2px !important;
  background: transparent !important;
}
.composer :deep(.n-input__textarea-el) {
  padding: 3px 2px !important;
  color: #27354a;
  font-size: 13px;
  line-height: 1.65;
}
.composer :deep(.n-input__placeholder) {
  color: #a6b0bf;
}
.hidden-file {
  display: none;
}
.pending-images {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.composer-skill-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 7px;
  padding: 0 2px 8px;
  border-bottom: 1px solid rgba(57, 126, 236, 0.07);
}
.composer-skill-row > div {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.composer-skill-row strong {
  flex: 0 0 auto;
  color: #45556c;
  font-size: 11px;
}
.composer-skill-row span {
  overflow: hidden;
  color: #94a0b1;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.composer-skill-select {
  width: min(320px, 42%);
  flex: 0 0 auto;
}
.img-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef5ff;
  color: var(--ra-muted, #64748b);
}
.img-x {
  border: none;
  background: transparent;
  cursor: pointer;
  color: inherit;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}
.composer-actions {
  margin-top: 7px;
  padding-top: 8px;
  border-top: 1px solid rgba(57, 126, 236, 0.07);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.scope-summary {
  min-width: 0;
  max-width: 48%;
  display: flex;
  align-items: center;
  gap: 7px;
  overflow: hidden;
  color: #8190a4;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scope-summary-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  border-radius: 50%;
  background: var(--ra-accent);
  box-shadow: 0 0 0 3px rgba(57, 126, 236, 0.09);
}
.composer-btns {
  display: flex;
  align-items: center;
  gap: 8px;
}
.keyboard-hint {
  color: #a1acba;
  font-size: 9px;
}

@media (max-width: 1080px) {
  .intent-caption,
  .keyboard-hint {
    display: none;
  }
  .hero-capabilities {
    grid-template-columns: 1fr;
    max-width: 440px;
    padding: 3px 0;
  }
  .hero-capabilities > div {
    padding: 9px 6px;
  }
  .hero-capabilities > div:not(:last-child)::after {
    top: auto;
    right: 6px;
    bottom: 0;
    left: 6px;
    width: auto;
    height: 1px;
  }
  .hero {
    min-height: 620px;
  }
  .suggests {
    max-width: 440px;
    flex-direction: column;
  }
  .suggest-label {
    max-width: 440px;
  }
}

@media (max-height: 760px) {
  .hero {
    min-height: 480px;
    padding-top: 28px;
    padding-bottom: 26px;
  }
  .hero-visual {
    width: 68px;
    height: 68px;
    margin-bottom: 14px;
    border-radius: 22px;
  }
  .hero-mark {
    width: 41px;
    height: 41px;
  }
  .ring-one {
    width: 102px;
    height: 102px;
  }
  .ring-two {
    width: 138px;
    height: 138px;
  }
  .hero-capabilities {
    margin-top: 18px;
  }
  .suggest-label {
    margin-top: 18px;
  }
}
</style>
