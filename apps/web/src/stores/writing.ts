import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  cancelWritingTask,
  confirmWritingIntake,
  createWritingTask,
  deleteWritingTask,
  getWritingTask,
  listWritingTasks,
  patchWritingIntakeAnswers,
  patchWritingTask,
  pauseWritingTask,
  runWritingTaskStream,
  skipWritingIntake,
  startWritingIntake,
} from "@/api/realai";
import type { EvidenceItem, KnowledgeCard, Scorecard, WritingTask } from "@/api/types";
import { useConfigStore } from "@/stores/config";
import { extractCitationTokens, sourcePathFromCite } from "@/utils/citations";
import {
  applyChapterDelta,
  applyChapterDraft,
  assembleChaptersMarkdown,
  chaptersFromOutline,
  cleanChapterBody,
  countChineseChars,
  hydrateChaptersFromTask,
  resolveReportTitle,
  type ChapterCard,
  type ChapterDeltaPayload,
} from "@/utils/chapters";

export const useWritingStore = defineStore("writing", () => {
  const config = useConfigStore();
  const tasks = ref<WritingTask[]>([]);
  const activeId = ref<string | null>(null);
  const running = ref(false);
  const loading = ref(false);
  const intakeBusy = ref(false);
  const error = ref("");
  const statusFilter = ref("all");
  const livePreview = ref("");
  const liveChapters = ref<ChapterCard[]>([]);
  const liveCards = ref<KnowledgeCard[]>([]);
  const liveScorecards = ref<Scorecard[]>([]);
  /** 用户点了暂停/终止后，按钮先进入「等待边界」态 */
  const controlPending = ref<"pause" | "cancel" | null>(null);
  /** 左侧点「新建任务」后中间显示建任务表单 */
  const creatingMode = ref(false);

  const current = computed(
    () => tasks.value.find((t) => t.id === activeId.value) || null,
  );

  const filtered = computed(() => {
    if (statusFilter.value === "all") return tasks.value;
    return tasks.value.filter((t) => t.status === statusFilter.value);
  });

  function cardFromEvidence(item: EvidenceItem): KnowledgeCard {
    const kind =
      item.type === "data" ? "data" : item.type === "web" ? "web" : "retrieve";
    return {
      id: item.id,
      kind,
      type: item.type,
      title: String((item.meta as { title?: string } | undefined)?.title || item.source),
      source: item.source,
      excerpt: item.excerpt,
      meta: item.meta,
    };
  }

  function hasCardForCite(cards: KnowledgeCard[], cite: string): boolean {
    const path = sourcePathFromCite(cite);
    return cards.some((c) => {
      if (c.id === cite) return true;
      if (c.id.startsWith(cite) || cite.startsWith(c.id.split("#")[0] || c.id)) return true;
      if (path && (c.source === path || c.id.includes(path))) return true;
      return false;
    });
  }

  /** Merge saved cards + evidence pack + 正文里的 kb:/data: 引用，避免右侧空白。 */
  function mergeKnowledgeCards(task: WritingTask | null, live: KnowledgeCard[]): KnowledgeCard[] {
    const base = live.length
      ? [...live]
      : [...(task?.knowledge_cards || task?.result?.knowledge_cards || [])];
    const byId = new Map<string, KnowledgeCard>();
    for (const c of base) {
      if (c?.id) byId.set(c.id, c);
    }

    const evidenceItems = task?.result?.evidence?.items || [];
    for (const item of evidenceItems) {
      if (item?.id && !byId.has(item.id)) byId.set(item.id, cardFromEvidence(item));
    }

    const ledger = task?.result?.citation_ledger || [];
    for (const e of ledger) {
      const id = e.id;
      if (!id || byId.has(id)) continue;
      const kind =
        e.source_type === "问数" ? "data" : e.source_type === "联网" ? "web" : "retrieve";
      byId.set(id, {
        id,
        kind,
        title: e.label || sourcePathFromCite(id),
        source: sourcePathFromCite(id),
        excerpt: e.excerpt || "写作引用台账中的证据",
      });
    }

    const md = livePreview.value || task?.result?.preview_markdown || "";
    const list = [...byId.values()];
    for (const cite of extractCitationTokens(md)) {
      if (hasCardForCite(list, cite)) continue;
      const path = sourcePathFromCite(cite);
      const kind = cite.startsWith("data:")
        ? "data"
        : cite.startsWith("web:")
          ? "web"
          : "retrieve";
      const card: KnowledgeCard = {
        id: cite,
        kind,
        title: path.split("/").pop() || path || cite,
        source: path,
        excerpt: "正文中引用的证据（旧任务可能未实时推送卡片，已从引用自动补齐）",
      };
      byId.set(cite, card);
      list.push(card);
    }
    return [...byId.values()];
  }

  const currentCards = computed(() => mergeKnowledgeCards(current.value, liveCards.value));

  const currentScorecards = computed(() => {
    const fromTask = current.value?.scorecards || current.value?.result?.scorecards || [];
    return liveScorecards.value.length ? liveScorecards.value : fromTask;
  });

  function displayTitle(task: WritingTask | null): string {
    if (!task) return "战略规划报告";
    return resolveReportTitle(
      task.goal,
      String(task.outline?.title || ""),
      String(task.outline?.report_type_label || ""),
    );
  }

  const assembledPreview = computed(() => {
    if (liveChapters.value.length) {
      const t = current.value;
      return assembleChaptersMarkdown(
        displayTitle(t),
        String(t?.outline?.strategic_main_line || ""),
        liveChapters.value,
        t?.result?.citation_ledger || [],
      );
    }
    return cleanChapterBody(livePreview.value || current.value?.result?.preview_markdown || "");
  });

  function syncChaptersFromTask(task: WritingTask | null) {
    if (!task) {
      liveChapters.value = [];
      return;
    }
    liveChapters.value = hydrateChaptersFromTask(task);
    if (liveChapters.value.length) {
      livePreview.value = assembleChaptersMarkdown(
        displayTitle(task),
        String(task.outline?.strategic_main_line || ""),
        liveChapters.value,
        task.result?.citation_ledger || [],
      );
    } else {
      livePreview.value = cleanChapterBody(task.result?.preview_markdown || "");
    }
  }

  function onOutlineEvent(outline: Record<string, unknown>) {
    const t = tasks.value.find((x) => x.id === activeId.value);
    if (t) t.outline = outline;
    liveChapters.value = chaptersFromOutline(outline, liveChapters.value);
    const task = current.value;
    if (task && liveChapters.value.length) {
      livePreview.value = assembleChaptersMarkdown(
        displayTitle(task),
        String(outline.strategic_main_line || task.outline?.strategic_main_line || ""),
        liveChapters.value,
        task.result?.citation_ledger || [],
      );
    }
  }

  function onChapterEvent(payload: { chapter?: unknown; preview_markdown?: string }) {
    const draft =
      payload.chapter && typeof payload.chapter === "object"
        ? (payload.chapter as Record<string, unknown>)
        : null;
    if (draft) {
      liveChapters.value = applyChapterDraft(liveChapters.value, draft);
    }
    if (payload.preview_markdown) {
      livePreview.value = cleanChapterBody(payload.preview_markdown);
    } else if (liveChapters.value.length) {
      const task = current.value;
      livePreview.value = assembleChaptersMarkdown(
        displayTitle(task),
        String(task?.outline?.strategic_main_line || ""),
        liveChapters.value,
        task?.result?.citation_ledger || [],
      );
    }
  }

  function onChapterDeltaEvent(payload: ChapterDeltaPayload) {
    liveChapters.value = applyChapterDelta(liveChapters.value, payload);
  }

  async function refresh() {
    loading.value = true;
    error.value = "";
    try {
      const res = await listWritingTasks();
      tasks.value = res.tasks;
      if (!activeId.value && tasks.value[0]) activeId.value = tasks.value[0].id;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  async function select(id: string) {
    creatingMode.value = false;
    activeId.value = id;
    livePreview.value = "";
    liveChapters.value = [];
    liveCards.value = [];
    liveScorecards.value = [];
    try {
      const t = await getWritingTask(id);
      const idx = tasks.value.findIndex((x) => x.id === id);
      if (idx >= 0) tasks.value[idx] = t;
      else tasks.value.unshift(t);
      liveCards.value = t.knowledge_cards || t.result?.knowledge_cards || [];
      liveScorecards.value = t.scorecards || t.result?.scorecards || [];
      syncChaptersFromTask(t);
      if (t.status === "running" && !running.value) {
        // The backend worker is independent from this page. Re-entering a
        // running task only reattaches to its live stream; it must not launch
        // a duplicate report run.
        void runActive(true, t.outline, { resume: true, attach: true }).catch(() => {
          /* error state is already exposed by the store */
        });
      }
    } catch {
      /* keep list snapshot */
    }
  }

  async function syncCurrent() {
    const id = activeId.value;
    if (!id) return null;
    const task = await getWritingTask(id);
    const idx = tasks.value.findIndex((item) => item.id === id);
    if (idx >= 0) tasks.value[idx] = task;
    else tasks.value.unshift(task);
    liveCards.value = task.knowledge_cards || task.result?.knowledge_cards || [];
    liveScorecards.value = task.scorecards || task.result?.scorecards || [];
    syncChaptersFromTask(task);
    return task;
  }

  function beginCreate() {
    creatingMode.value = true;
    activeId.value = null;
    liveCards.value = [];
    liveScorecards.value = [];
    livePreview.value = "";
    liveChapters.value = [];
  }

  function replaceTask(updated: WritingTask) {
    const idx = tasks.value.findIndex((x) => x.id === updated.id);
    if (idx >= 0) tasks.value[idx] = updated;
    else tasks.value.unshift(updated);
    activeId.value = updated.id;
    return updated;
  }

  async function createTask(
    goal: string,
    opts?: {
      stepConfirm?: boolean;
      reportType?: string | null;
      audience?: string;
      scopePaths?: string[];
      skillProfileId?: string | null;
    },
  ) {
    const task = await createWritingTask(goal.trim(), opts);
    tasks.value.unshift(task);
    activeId.value = task.id;
    creatingMode.value = false;
    liveCards.value = [];
    liveScorecards.value = [];
    livePreview.value = "";
    liveChapters.value = [];
    return task;
  }

  async function startIntake(taskId?: string) {
    const id = taskId || current.value?.id;
    if (!id) throw new Error("请先选择任务");
    intakeBusy.value = true;
    error.value = "";
    try {
      const updated = await startWritingIntake(id);
      return replaceTask(updated);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      intakeBusy.value = false;
    }
  }

  async function saveIntakeAnswers(
    answers: Array<{ id: string; answer?: string; skipped?: boolean }>,
  ) {
    const task = current.value;
    if (!task) throw new Error("请先选择任务");
    const updated = await patchWritingIntakeAnswers(task.id, answers);
    return replaceTask(updated);
  }

  async function confirmIntake() {
    const task = current.value;
    if (!task) throw new Error("请先选择任务");
    intakeBusy.value = true;
    error.value = "";
    try {
      const updated = await confirmWritingIntake(task.id);
      return replaceTask(updated);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      intakeBusy.value = false;
    }
  }

  async function skipIntake() {
    const task = current.value;
    if (!task) throw new Error("请先选择任务");
    intakeBusy.value = true;
    error.value = "";
    try {
      const updated = await skipWritingIntake(task.id);
      return replaceTask(updated);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      intakeBusy.value = false;
    }
  }

  async function runActive(
    confirmed = false,
    outline?: Record<string, unknown>,
    opts?: { resume?: boolean; attach?: boolean },
  ) {
    const task = current.value;
    if (!task || running.value || (task.status === "running" && !opts?.attach)) return;
    running.value = true;
    controlPending.value = null;
    error.value = "";
    try {
      const resume =
        opts?.resume === true || (opts?.resume !== false && task.status === "paused");
      const updated = await runWritingTaskStream(
        task.id,
        {
          confirmed,
          outline,
          scope_paths: task.scope_paths,
          report_type: task.report_type,
          audience: task.audience,
          web_search_mode: config.webSearchMode,
          resume,
        },
        {
          onProgress: (steps) => {
            const t = tasks.value.find((x) => x.id === task.id);
            if (t) t.progress = steps;
          },
          onOutline: (outline) => {
            if (activeId.value === task.id) onOutlineEvent(outline);
          },
          onCard: (cards) => {
            if (activeId.value === task.id) {
              liveCards.value = [...liveCards.value, ...cards];
            }
          },
          onChapter: (payload) => {
            if (activeId.value === task.id) onChapterEvent(payload);
          },
          onChapterDelta: (payload) => {
            if (activeId.value === task.id) onChapterDeltaEvent(payload);
          },
          onScorecard: (sc) => {
            if (activeId.value === task.id) {
              liveScorecards.value = [...liveScorecards.value, sc];
            }
          },
        },
      );
      const idx = tasks.value.findIndex((x) => x.id === task.id);
      if (idx >= 0) tasks.value[idx] = updated;
      if (activeId.value === task.id) {
        liveCards.value = updated.knowledge_cards || updated.result?.knowledge_cards || liveCards.value;
        liveScorecards.value = updated.scorecards || updated.result?.scorecards || liveScorecards.value;
        syncChaptersFromTask(updated);
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      running.value = false;
      controlPending.value = null;
    }
  }

  async function resumeActive() {
    return runActive(true, current.value?.outline, { resume: true });
  }

  async function pauseActive() {
    const task = current.value;
    if (!task || (!running.value && task.status !== "running")) return;
    controlPending.value = "pause";
    try {
      await pauseWritingTask(task.id);
    } catch (err) {
      controlPending.value = null;
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    }
  }

  async function cancelActive() {
    const task = current.value;
    if (!task || (!running.value && task.status !== "running")) return;
    controlPending.value = "cancel";
    try {
      await cancelWritingTask(task.id);
    } catch (err) {
      controlPending.value = null;
      error.value = err instanceof Error ? err.message : String(err);
      throw err;
    }
  }

  async function confirmOutline(outline?: Record<string, unknown> | null) {
    const task = current.value;
    if (!task || running.value) return;
    running.value = true;
    try {
      const updated = await runWritingTaskStream(
        task.id,
        {
          confirmed: true,
          outline: outline || task.outline,
          scope_paths: task.scope_paths,
          report_type: task.report_type,
          audience: task.audience,
          web_search_mode: config.webSearchMode,
        },
        {
          onProgress: (steps) => {
            const t = tasks.value.find((x) => x.id === task.id);
            if (t) t.progress = steps;
          },
          onOutline: (ol) => {
            onOutlineEvent(ol);
          },
          onCard: (cards) => {
            liveCards.value = [...liveCards.value, ...cards];
          },
          onChapter: (payload) => {
            onChapterEvent(payload);
          },
          onChapterDelta: (payload) => {
            onChapterDeltaEvent(payload);
          },
          onScorecard: (sc) => {
            liveScorecards.value = [...liveScorecards.value, sc];
          },
        },
      );
      const idx = tasks.value.findIndex((x) => x.id === task.id);
      if (idx >= 0) tasks.value[idx] = updated;
      syncChaptersFromTask(updated);
      return updated;
    } finally {
      running.value = false;
    }
  }

  async function confirmChapter() {
    const task = current.value;
    if (!task || running.value) return;
    running.value = true;
    try {
      const next = task.result?.next_chapter_index;
      const updated = await runWritingTaskStream(
        task.id,
        {
          confirmed: true,
          confirmed_chapter: true,
          resume_chapter_index: next,
          outline: task.outline,
          scope_paths: task.scope_paths,
          report_type: task.report_type,
          audience: task.audience,
          web_search_mode: config.webSearchMode,
        },
        {
          onProgress: (steps) => {
            const t = tasks.value.find((x) => x.id === task.id);
            if (t) t.progress = steps;
          },
          onOutline: (ol) => {
            onOutlineEvent(ol);
          },
          onCard: (cards) => {
            liveCards.value = [...liveCards.value, ...cards];
          },
          onChapter: (payload) => {
            onChapterEvent(payload);
          },
          onChapterDelta: (payload) => {
            onChapterDeltaEvent(payload);
          },
          onScorecard: (sc) => {
            liveScorecards.value = [...liveScorecards.value, sc];
          },
        },
      );
      const idx = tasks.value.findIndex((x) => x.id === task.id);
      if (idx >= 0) tasks.value[idx] = updated;
      syncChaptersFromTask(updated);
      return updated;
    } finally {
      running.value = false;
    }
  }

  async function patchTask(
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
    const updated = await patchWritingTask(id, body);
    const idx = tasks.value.findIndex((x) => x.id === id);
    if (idx >= 0) tasks.value[idx] = updated;
    if (body.preview_markdown !== undefined) {
      livePreview.value = cleanChapterBody(
        updated.result?.preview_markdown || body.preview_markdown,
      );
      if (liveChapters.value.length) {
        syncChaptersFromTask(updated);
      }
    }
    return updated;
  }

  async function savePreview(markdown: string, rewriteExports = true) {
    const task = current.value;
    if (!task) throw new Error("请先选择任务");
    return patchTask(task.id, {
      preview_markdown: cleanChapterBody(markdown),
      rewrite_exports: rewriteExports,
    });
  }

  async function saveChapters(chapters: ChapterCard[], rewriteExports = true) {
    const task = current.value;
    if (!task) throw new Error("请先选择任务");
    liveChapters.value = chapters.map((c) => ({ ...c }));
    const md = assembleChaptersMarkdown(
      displayTitle(task),
      String(task.outline?.strategic_main_line || ""),
      chapters,
      task.result?.citation_ledger || [],
    );
    livePreview.value = md;
    const outline = {
      ...(task.outline || {}),
      chapter_drafts: chapters.map((c) => ({
        id: c.id,
        heading: c.heading,
        body: c.body,
        chinese_chars: c.chinese_chars,
        word_budget: c.word_budget ?? undefined,
      })),
    };
    return patchTask(task.id, {
      preview_markdown: md,
      outline,
      rewrite_exports: rewriteExports,
    });
  }

  async function remove(id: string) {
    await deleteWritingTask(id);
    tasks.value = tasks.value.filter((t) => t.id !== id);
    if (activeId.value === id) beginCreate();
  }

  function setFilter(v: string) {
    statusFilter.value = v;
  }

  function progressPct(task: WritingTask | null): number {
    if (!task) return 0;

    // 页面百分比只表达正文完成度。研究、架构等后台步骤单独展示，
    // 不能再出现“正文 0 字、流程却完成 43%”的误导。
    const chapters = task.id === activeId.value
      ? liveChapters.value
      : hydrateChaptersFromTask(task);
    const chapterChars = chapters.reduce(
      (sum, chapter) => sum + (chapter.chinese_chars || countChineseChars(chapter.body)),
      0,
    );
    const resultChars = Number(task.result?.chinese_chars || 0);
    // 有章节结构时只统计章节正文；封面标题和战略主线不算“报告已写”。
    const written = chapters.length ? chapterChars : resultChars;
    if (written <= 0) return 0;
    if (task.status === "completed") return 100;

    const outlineMin = Number(task.outline?.min_chars || task.result?.min_chars || 0);
    const sectionBudget = Array.isArray(task.outline?.sections)
      ? task.outline.sections.reduce((sum: number, section: unknown) => {
          if (!section || typeof section !== "object") return sum;
          return sum + Number((section as Record<string, unknown>).word_budget || 0);
        }, 0)
      : 0;
    const target = outlineMin > 0 ? outlineMin : sectionBudget;
    if (target <= 0) return chapters.some((chapter) => chapter.body.trim()) ? 1 : 0;
    return Math.min(99, Math.max(1, Math.round((written / target) * 100)));
  }

  return {
    tasks,
    activeId,
    running,
    loading,
    intakeBusy,
    error,
    statusFilter,
    livePreview,
    liveChapters,
    assembledPreview,
    controlPending,
    creatingMode,
    current,
    filtered,
    currentCards,
    currentScorecards,
    displayTitle,
    refresh,
    select,
    syncCurrent,
    beginCreate,
    createTask,
    startIntake,
    saveIntakeAnswers,
    confirmIntake,
    skipIntake,
    runActive,
    resumeActive,
    pauseActive,
    cancelActive,
    confirmOutline,
    confirmChapter,
    patchTask,
    savePreview,
    saveChapters,
    remove,
    setFilter,
    progressPct,
  };
});
