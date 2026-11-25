export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatTime(ts: number) {
  // vault mtime 多为秒
  const ms = ts < 1e12 ? ts * 1000 : ts;
  return new Date(ms).toLocaleString();
}

export type MarkdownHtmlBlock = { type: "html"; html: string };
export type MarkdownTableBlock = {
  type: "table";
  columns: string[];
  rows: Record<string, string>[];
  title?: string;
};
export type MarkdownBlock = MarkdownHtmlBlock | MarkdownTableBlock;

/**
 * Split markdown into HTML chunks and structured tables (for Vue table cards).
 * Tables are not embedded in HTML so callers can render DataTableCard.
 */
export function splitMarkdownBlocks(text: string): MarkdownBlock[] {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const lines = escaped.split(/\r?\n/);
  const blocks: MarkdownBlock[] = [];
  let htmlBuf: string[] = [];
  let inList = false;
  let i = 0;

  const flushList = () => {
    if (inList) {
      htmlBuf.push("</ul>");
      inList = false;
    }
  };

  const flushHtml = () => {
    flushList();
    if (!htmlBuf.length) return;
    const html = htmlBuf.join("");
    htmlBuf = [];
    if (html.replace(/<br\s*\/?>/gi, "").trim()) {
      blocks.push({ type: "html", html });
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    if (isTableRow(line) && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flushHtml();
      const header = splitTableCells(line).map(stripInlineMarkup);
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) {
        body.push(splitTableCells(lines[i]).map(stripInlineMarkup));
        i += 1;
      }
      const columns = uniqueColumns(header);
      const rows = body.map((cells) => {
        const row: Record<string, string> = {};
        columns.forEach((c, idx) => {
          row[c] = decodeEntities(cells[idx] ?? "");
        });
        return row;
      });
      const titleHint = columns.slice(0, 3).filter(Boolean).join(" · ") || "表格";
      blocks.push({
        type: "table",
        columns,
        rows,
        title: `表格 · ${titleHint}`,
      });
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = heading[1].length;
      htmlBuf.push(`<h${level + 2}>${inline(heading[2])}</h${level + 2}>`);
      i += 1;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      if (!inList) {
        htmlBuf.push("<ul>");
        inList = true;
      }
      htmlBuf.push(`<li>${inline(line.replace(/^[-*]\s+/, ""))}</li>`);
      i += 1;
      continue;
    }
    flushList();
    if (!line.trim()) {
      htmlBuf.push("<br/>");
    } else {
      htmlBuf.push(`<p>${inline(line)}</p>`);
    }
    i += 1;
  }
  flushHtml();
  return blocks;
}

/** 极简 Markdown：标题/粗体/列表/表格 → 安全 HTML（无脚本）；表格仍内联（兼容旧调用） */
export function simpleMarkdown(text: string): string {
  return splitMarkdownBlocks(text)
    .map((b) => {
      if (b.type === "html") return b.html;
      return renderMarkdownTable(
        b.columns,
        b.rows.map((r) => b.columns.map((c) => r[c] ?? "")),
      );
    })
    .join("");
}

function uniqueColumns(header: string[]): string[] {
  const seen = new Map<string, number>();
  return header.map((h, i) => {
    const base = h.trim() || `列${i + 1}`;
    const n = (seen.get(base) || 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}_${n}`;
  });
}

function stripInlineMarkup(s: string): string {
  return decodeEntities(
    s
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/`(.+?)`/g, "$1"),
  );
}

function decodeEntities(s: string): string {
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function isTableRow(line: string): boolean {
  const t = line.trim();
  if (!t.includes("|")) return false;
  if (isTableSeparator(t)) return false;
  return /^\|?.+\|.+\|?$/.test(t);
}

function isTableSeparator(line: string): boolean {
  const t = line.trim();
  if (!t.includes("-")) return false;
  let s = t;
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  const parts = s.split("|").map((p) => p.trim());
  if (!parts.length) return false;
  return parts.every((p) => /^:?-{1,}:?$/.test(p));
}

function splitTableCells(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderMarkdownTable(header: string[], body: string[][]): string {
  const cols = header.length;
  const th = header.map((c) => `<th>${inline(escapeHtml(c))}</th>`).join("");
  const rows = body
    .map((cells) => {
      const padded = [...cells];
      while (padded.length < cols) padded.push("");
      const tds = padded
        .slice(0, cols)
        .map((c) => `<td>${inline(escapeHtml(c))}</td>`)
        .join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inline(s: string) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}
