/** Client-side table copy / download helpers (TSV, CSV, Markdown, XLSX). */

export type TableMatrix = {
  columns: string[];
  rows: Record<string, unknown>[];
  /** Display labels for headers (fallback to column key). */
  labels?: Record<string, string> | ((key: string) => string);
};

function headerLabel(
  key: string,
  labels?: Record<string, string> | ((key: string) => string),
): string {
  if (!labels) return key;
  if (typeof labels === "function") return labels(key);
  return labels[key] || key;
}

function cell(row: Record<string, unknown>, key: string): string {
  const v = row[key];
  return v == null ? "" : String(v);
}

export function toTsv(matrix: TableMatrix): string {
  const { columns, rows, labels } = matrix;
  const head = columns.map((c) => headerLabel(c, labels)).join("\t");
  const body = rows.map((r) => columns.map((c) => cell(r, c).replace(/\t/g, " ")).join("\t"));
  return [head, ...body].join("\r\n");
}

function csvEscape(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function toCsv(matrix: TableMatrix): string {
  const { columns, rows, labels } = matrix;
  const head = columns.map((c) => csvEscape(headerLabel(c, labels))).join(",");
  const body = rows.map((r) => columns.map((c) => csvEscape(cell(r, c))).join(","));
  return [head, ...body].join("\r\n");
}

export function toMarkdownTable(matrix: TableMatrix): string {
  const { columns, rows, labels } = matrix;
  const head = columns.map((c) => headerLabel(c, labels));
  const sep = columns.map(() => "---");
  const body = rows.map((r) => columns.map((c) => cell(r, c).replace(/\|/g, "\\|")));
  const line = (cells: string[]) => `| ${cells.join(" | ")} |`;
  return [line(head), line(sep), ...body.map(line)].join("\n");
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** UTF-8 BOM so Excel opens Chinese correctly. */
export function downloadCsv(matrix: TableMatrix, filename: string) {
  const bom = "\uFEFF";
  const blob = new Blob([bom + toCsv(matrix)], { type: "text/csv;charset=utf-8" });
  downloadBlob(blob, filename.endsWith(".csv") ? filename : `${filename}.csv`);
}

export async function downloadXlsx(matrix: TableMatrix, filename: string) {
  const XLSX = await import("xlsx");
  const { columns, rows, labels } = matrix;
  const aoa: string[][] = [
    columns.map((c) => headerLabel(c, labels)),
    ...rows.map((r) => columns.map((c) => cell(r, c))),
  ];
  const ws = XLSX.utils.aoa_to_sheet(aoa);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
  const name = filename.endsWith(".xlsx") ? filename : `${filename}.xlsx`;
  XLSX.writeFile(wb, name);
}

export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
}

export function safeFilename(title: string, fallback = "table"): string {
  const base = title
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 80);
  return base || fallback;
}

export function rowsFromMatrix(header: string[], body: string[][]): Record<string, string>[] {
  const cols = header.length ? header : ["col1"];
  return body.map((cells) => {
    const row: Record<string, string> = {};
    cols.forEach((c, i) => {
      row[c] = cells[i] ?? "";
    });
    return row;
  });
}
