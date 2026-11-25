import { stripThinkBlocks } from "@/utils/llmText";
import type { CitationLedgerEntry } from "@/api/types";

export type ChapterCardStatus = "pending" | "writing" | "ready";

export type ChapterCard = {
  id: string;
  heading: string;
  body: string;
  word_budget?: number | null;
  chinese_chars: number;
  status: ChapterCardStatus;
};

export type ChapterDeltaPayload = {
  chapter_id?: string;
  chapter_index?: number;
  heading?: string;
  delta?: string;
  body?: string;
  replace?: boolean;
  attempt?: number;
};

function headingKey(h: string): string {
  return String(h || "")
    .replace(/^#{1,6}\s*/, "")
    .replace(/\s+/g, "")
    .trim();
}

export function countChineseChars(text: string): number {
  // Align with backend realai.report.llm_client.count_chinese_chars
  let n = 0;
  for (const ch of text || "") {
    const o = ch.codePointAt(0) ?? 0;
    if (
      (o >= 0x4e00 && o <= 0x9fff) ||
      (o >= 0x3000 && o <= 0x303f) ||
      (o >= 0xff00 && o <= 0xffef)
    ) {
      n += 1;
    }
  }
  return n;
}

/**
 * Turn a writing instruction into a presentable report title while the
 * architect is still generating (and for legacy tasks whose title equalled
 * the full user query).
 */
export function resolveReportTitle(
  goal: string,
  proposed?: string | null,
  reportTypeLabel?: string | null,
): string {
  const placeholderTitles = new Set([
    "自定义规划",
    "战略规划",
    "战略规划报告",
    "规划报告",
    "报告",
    "报告标题",
  ]);
  const instruction = String(goal || "").replace(/\s+/g, " ").trim();
  const candidate = String(proposed || "")
    .replace(/^#{1,6}\s*/, "")
    .replace(/^(?:报告)?标题[:：]\s*/, "")
    .replace(/^[《“"]+|[》”"]+$/g, "")
    .replace(/[。；;，,]+$/g, "")
    .replace(/国家官网集团/g, "国家管网集团")
    .trim();
  if (
    candidate &&
    !placeholderTitles.has(candidate.replace(/\s+/g, "")) &&
    candidate !== instruction &&
    candidate.length <= 60
  ) {
    return candidate;
  }

  const actionTitle = instruction.match(
    /(?:撰写|编制|制定|形成|起草|写)(?:一篇|一份|一个)?\s*([^，。！？\n]{4,80}?(?:行动方案|实施方案|工作方案|发展规划|专项规划|总体规划|规划|研究报告|报告|计划|意见|备参))(?:[，。！？]|$)/,
  )?.[1];
  if (actionTitle) {
    return actionTitle
      .replace(/国家官网集团/g, "国家管网集团")
      .replace(/(?:遵循|贯彻)(?:该|上述)?(?:文章|文件)?(?:精神和指示|精神|指示)的?/g, "")
      .trim()
      .slice(0, 60);
  }
  const titleLike = instruction.match(
    /([^，。！？\n]{4,60}?(?:行动方案|实施方案|工作方案|发展规划|专项规划|总体规划|规划|研究报告|报告|计划|意见|备参))(?:[，。！？]|$)/,
  )?.[1];
  if (titleLike) return titleLike.replace(/国家官网集团/g, "国家管网集团").trim();
  if (instruction && instruction.length <= 60) {
    return instruction.replace(/国家官网集团/g, "国家管网集团");
  }
  const label = String(reportTypeLabel || "").trim();
  if (label && !placeholderTitles.has(label.replace(/\s+/g, ""))) return label;
  return "战略规划报告";
}

export function cleanChapterBody(text: string): string {
  // Obsidian 的 ==高亮== 在当前 HTML 渲染器中会原样露出；报告正文统一降级为纯文本。
  let s = stripThinkBlocks(text || "").replace(/==/g, "");
  const paras = s.split(/\n{2,}/);
  const kept: string[] = [];
  let skipping = true;
  for (const p of paras) {
    const t = p.trim();
    if (!t) continue;
    const first = t.split(/\n/)[0]?.trim() || "";
    if (
      skipping &&
      /^(The user|I need|Let me|Okay|Sure|I'll |I will |As a |You are |Acting as )/i.test(first)
    ) {
      continue;
    }
    skipping = false;
    kept.push(t);
  }
  return kept.join("\n\n").trim();
}

const REFERENCE_HEADING_RE =
  /^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:证据引用|参考文献|参考来源|引用来源|参考资料)(?:\*\*)?\s*[:：]?\s*$/i;

/**
 * Writer 偶尔会在单章末尾追加「证据引用」。预览与导出只保留正文，
 * 引用统一使用 pipeline 的 citation ledger 在全文末尾汇总。
 */
export function stripChapterReferenceSection(text: string): string {
  const cleaned = cleanChapterBody(text);
  if (!cleaned) return "";
  const lines = cleaned.split(/\r?\n/);
  const index = lines.findIndex((line) => REFERENCE_HEADING_RE.test(line));
  if (index < 0) return cleaned;
  let end = index;
  while (end > 0 && !lines[end - 1].trim()) end -= 1;
  if (end > 0 && /^\s*(?:---+|___+|\*\*\*+)\s*$/.test(lines[end - 1])) end -= 1;
  return cleanChapterBody(lines.slice(0, end).join("\n"));
}

function referenceMarkdown(entry: CitationLedgerEntry, index: number): string {
  const n = entry.n || index + 1;
  const label = String(entry.label || entry.id || `来源 ${n}`).replace(/^【\d+】\s*/, "");
  if (entry.url) {
    return `【${n}】${label}。检索自：[查看原文](${entry.url})`;
  }
  const sourceType = entry.source_type || "知识库";
  const id = entry.id ? `（${entry.id}）` : "";
  return `【${n}】${label}。来源：${sourceType}${id}`;
}

function draftList(outline: Record<string, unknown> | null | undefined): Array<Record<string, unknown>> {
  const raw = outline?.chapter_drafts;
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
}

function sectionList(outline: Record<string, unknown> | null | undefined): Array<Record<string, unknown>> {
  const raw = outline?.sections;
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
}

/** Sync chapter cards from outline sections; keep bodies from drafts when ids match. */
export function chaptersFromOutline(
  outline: Record<string, unknown> | null | undefined,
  prev: ChapterCard[] = [],
): ChapterCard[] {
  if (!outline) return [];
  const sections = sectionList(outline);
  // The outline is the sole source of chapter order. Keeping previous cards
  // when it is empty can combine a stale streamed chapter with a new task.
  if (!sections.length) return [];
  const drafts = draftList(outline);
  const draftById = new Map(drafts.map((d) => [String(d.id || ""), d]));
  const prevById = new Map(prev.map((c) => [c.id, c]));

  return sections.map((sec, i) => {
    const id = String(sec.id || `sec-${i + 1}`);
    const heading = String(sec.heading || `第 ${i + 1} 章`);
    const budget =
      typeof sec.word_budget === "number"
        ? sec.word_budget
        : Number(sec.word_budget) || null;
    const draft = draftById.get(id);
    const prevCard = prevById.get(id);
    const body = cleanChapterBody(
      String(draft?.body ?? prevCard?.body ?? ""),
    );
    const status: ChapterCardStatus = body.trim()
      ? "ready"
      : prevCard?.status === "writing"
        ? "writing"
        : "pending";
    return {
      id,
      heading,
      body,
      word_budget: budget,
      chinese_chars: countChineseChars(body),
      status,
    };
  });
}

export function applyChapterDraft(
  chapters: ChapterCard[],
  draft: Record<string, unknown> | null | undefined,
): ChapterCard[] {
  if (!draft) return chapters;
  const id = String(draft.id || "");
  const body = cleanChapterBody(String(draft.body || ""));
  const heading = String(draft.heading || "");
  if (!id && !heading) return chapters;
  const idx = chapters.findIndex(
    (c) => c.id === id || headingKey(c.heading) === headingKey(heading),
  );
  if (idx < 0) {
    // Never invent chapter order from an out-of-order stream event. The
    // backend will send/replay the authoritative outline first.
    return chapters;
  }
  const next = [...chapters];
  next[idx] = {
    ...next[idx],
    heading: heading || next[idx].heading,
    body,
    chinese_chars: countChineseChars(body),
    status: body ? "ready" : next[idx].status,
    word_budget:
      typeof draft.word_budget === "number"
        ? draft.word_budget
        : next[idx].word_budget,
  };
  return next;
}

/** Apply a throttled model token delta without waiting for the whole chapter. */
export function applyChapterDelta(
  chapters: ChapterCard[],
  payload: ChapterDeltaPayload,
): ChapterCard[] {
  const id = String(payload.chapter_id || "");
  const chapterIndex = Number(payload.chapter_index);
  let index = id ? chapters.findIndex((chapter) => chapter.id === id) : -1;
  if (index < 0 && Number.isInteger(chapterIndex) && chapterIndex >= 0) {
    index = chapterIndex < chapters.length ? chapterIndex : -1;
  }

  const streamedText = payload.replace
    ? String(payload.body || "")
    : `${index >= 0 ? chapters[index]?.body || "" : ""}${String(payload.delta || "")}`;
  // Content deltas exclude provider reasoning. Keep whitespace/partial Markdown intact,
  // but remove the unsupported Obsidian highlight marker immediately.
  const body = streamedText.replace(/==/g, "");

  if (index < 0) {
    // A token delta cannot establish chapter identity or order. Ignoring it
    // until the outline arrives avoids showing “第 1 章” with chapter-five
    // content when concurrent calls finish out of order.
    return chapters;
  }

  const next = [...chapters];
  next[index] = {
    ...next[index],
    id: id || next[index].id,
    heading: String(payload.heading || next[index].heading),
    body,
    chinese_chars: countChineseChars(body),
    status: "writing",
  };
  return next;
}

export function assembleChaptersMarkdown(
  title: string,
  mainLine: string,
  chapters: ChapterCard[],
  citationLedger: CitationLedgerEntry[] = [],
): string {
  const lines: string[] = [`# ${title || "报告"}`, ""];
  const ml = cleanChapterBody(mainLine);
  if (ml) {
    lines.push(`> 战略主线：${ml}`, "");
  }
  for (const ch of chapters) {
    const body = stripChapterReferenceSection(ch.body);
    lines.push(`## ${ch.heading}`, "", body, "");
    lines.push(`<!-- 本章中文字数：${countChineseChars(body)} -->`, "");
  }
  if (citationLedger.length) {
    lines.push("## 参考文献", "");
    citationLedger.forEach((entry, index) => lines.push(referenceMarkdown(entry, index), ""));
  }
  return lines.join("\n").trim() + "\n";
}

/** Best-effort split full markdown into bodies keyed by outline headings. */
export function splitMarkdownIntoChapters(
  md: string,
  chapters: ChapterCard[],
): ChapterCard[] {
  const text = cleanChapterBody(md);
  if (!text || !chapters.length) return chapters;
  const headingRe = /^(#{1,3})\s+(.+?)\s*$/gm;
  const matches: Array<{ key: string; start: number; endTitle: number }> = [];
  let m: RegExpExecArray | null;
  while ((m = headingRe.exec(text))) {
    matches.push({
      key: headingKey(m[2] || ""),
      start: m.index,
      endTitle: m.index + m[0].length,
    });
  }
  return chapters.map((ch) => {
    const key = headingKey(ch.heading);
    const i = matches.findIndex(
      (x) =>
        x.key !== "参考文献" &&
        (x.key === key || x.key.includes(key) || key.includes(x.key)),
    );
    if (i < 0) return ch;
    const bodyStart = matches[i].endTitle;
    const bodyEnd = i + 1 < matches.length ? matches[i + 1].start : text.length;
    const body = cleanChapterBody(text.slice(bodyStart, bodyEnd));
    return {
      ...ch,
      body,
      chinese_chars: countChineseChars(body),
      status: body ? "ready" : ch.status,
    };
  });
}

export function hydrateChaptersFromTask(task: {
  goal?: string;
  outline?: Record<string, unknown>;
  result?: { preview_markdown?: string } | null;
}): ChapterCard[] {
  let cards = chaptersFromOutline(task.outline);
  const drafts = draftList(task.outline);
  if (drafts.length) {
    for (const d of drafts) cards = applyChapterDraft(cards, d);
  } else if (task.result?.preview_markdown && cards.length) {
    cards = splitMarkdownIntoChapters(task.result.preview_markdown, cards);
  }
  return cards;
}
