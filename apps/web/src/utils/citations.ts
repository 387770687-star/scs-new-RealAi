import type { EvidenceItem, EvidenceType } from "@/api/types";

/** Align with EvidencePanel tabs: 知识库 → 问数 → 视觉 → 联网 → 推测 */
export const EVIDENCE_TYPE_ORDER: EvidenceType[] = [
  "kb",
  "data",
  "viz",
  "web",
  "inference",
];

/** Match [kb:…] or bare kb:… / data:… (LLM often omits brackets or #c:hash) */
const CITE_TOKEN_RE =
  /\[((?:kb|data|viz|web):[^\]]+)\]|((?:kb|data|viz|web):[^\s\[\]（）()【】,，。；;！!？?]+)/g;

export function orderEvidenceItems(items: EvidenceItem[]): EvidenceItem[] {
  const buckets = new Map<EvidenceType, EvidenceItem[]>();
  for (const t of EVIDENCE_TYPE_ORDER) buckets.set(t, []);
  const other: EvidenceItem[] = [];
  for (const item of items) {
    const list = buckets.get(item.type);
    if (list) list.push(item);
    else other.push(item);
  }
  const ordered: EvidenceItem[] = [];
  for (const t of EVIDENCE_TYPE_ORDER) {
    ordered.push(...(buckets.get(t) || []));
  }
  ordered.push(...other);
  return ordered;
}

export function buildCitationIndex(items: EvidenceItem[]): {
  ordered: EvidenceItem[];
  idToNum: Map<string, number>;
} {
  const ordered = orderEvidenceItems(items);
  const idToNum = new Map<string, number>();
  ordered.forEach((item, i) => {
    if (!idToNum.has(item.id)) idToNum.set(item.id, i + 1);
  });
  return { ordered, idToNum };
}

function normalizeCiteToken(raw: string): string {
  return raw
    .trim()
    .replace(/^[【\[]+/, "")
    .replace(/[】\]]+$/, "")
    .replace(/[。．，,;；]+$/, "");
}

/**
 * Map a cited token to evidence number.
 * Accepts exact id, prefix (kb:path without #c:hash), or source-path forms.
 */
export function resolveCitationNumber(
  rawCite: string,
  ordered: EvidenceItem[],
  idToNum: Map<string, number>,
): number | null {
  const cite = normalizeCiteToken(rawCite);
  if (!cite) return null;

  const exact = idToNum.get(cite);
  if (exact != null) return exact;

  // Prefer longest id that matches as prefix / extension of the cite token
  let best: { n: number; score: number } | null = null;
  for (const item of ordered) {
    const id = item.id;
    const n = idToNum.get(id);
    if (n == null) continue;

    let score = 0;
    if (id === cite) score = 1000;
    else if (id.startsWith(cite + "#") || id.startsWith(cite + ":")) score = 800 + cite.length;
    else if (cite.startsWith(id)) score = 700 + id.length;
    else if (id.startsWith(cite)) score = 600 + cite.length;
    else if (item.type === "kb" && cite.startsWith("kb:")) {
      const path = cite.slice(3).split("#")[0];
      if (path && (item.source === path || id.includes(path))) score = 500 + path.length;
    } else if (item.type === "data" && cite.startsWith("data:")) {
      const rest = cite.slice(5);
      if (rest && (item.source === rest || item.source.startsWith(rest) || id.includes(rest))) {
        score = 500 + Math.min(rest.length, 80);
      }
    } else if (item.type === "web" && cite.startsWith("web:")) {
      if (id.startsWith(cite) || cite.startsWith(id)) score = 400;
    }

    if (score > 0 && (!best || score > best.score)) {
      best = { n, score };
    }
  }
  return best?.n ?? null;
}

/**
 * Replace evidence citations in answer text with [1], [2], …
 */
export function replaceEvidenceCitations(
  text: string,
  idToNum: Map<string, number>,
  ordered: EvidenceItem[] = [],
): string {
  if (!text || idToNum.size === 0) return text;
  const list = ordered.length ? ordered : [...idToNum.keys()].map(
    (id) => ({ id, type: "kb", source: "", excerpt: "" }) as EvidenceItem,
  );

  return text.replace(CITE_TOKEN_RE, (full, bracketed: string | undefined, bare: string | undefined) => {
    const raw = bracketed || bare || full;
    const n = resolveCitationNumber(raw, list, idToNum);
    if (n == null) return full;
    return `[${n}]`;
  });
}

export function formatAnswerWithCitations(
  text: string,
  items: EvidenceItem[] | undefined,
): string {
  if (!text) return text;
  if (!items?.length) return text;
  const { ordered, idToNum } = buildCitationIndex(items);
  return replaceEvidenceCitations(text, idToNum, ordered);
}

/** Extract unique kb:/data:/viz:/web: tokens from report or chat text. */
export function extractCitationTokens(text: string): string[] {
  if (!text) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  const re = new RegExp(CITE_TOKEN_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const raw = normalizeCiteToken(m[1] || m[2] || "");
    if (!raw || seen.has(raw)) continue;
    seen.add(raw);
    out.push(raw);
  }
  return out;
}

export function sourcePathFromCite(cite: string): string {
  const c = normalizeCiteToken(cite);
  const colon = c.indexOf(":");
  if (colon < 0) return c;
  return c.slice(colon + 1).split("#")[0] || c;
}
