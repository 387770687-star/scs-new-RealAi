/** Web search mode: off | auto | force */

export type WebSearchMode = "off" | "auto" | "force";

export const WEB_SEARCH_MODE_OPTIONS = [
  { label: "关闭", value: "off" as const },
  { label: "智能", value: "auto" as const },
  { label: "强制", value: "force" as const },
];

export function normalizeWebSearchMode(
  mode?: string | null,
  enabled?: boolean | null,
): WebSearchMode {
  const raw = (mode || "").trim().toLowerCase();
  if (raw === "off" || raw === "auto" || raw === "force") return raw;
  if (enabled === true) return "force";
  if (enabled === false && mode == null) return "off";
  return "auto";
}

export function cycleWebSearchMode(current: WebSearchMode): WebSearchMode {
  if (current === "off") return "auto";
  if (current === "auto") return "force";
  return "off";
}

export function webSearchModeLabel(mode: WebSearchMode): string {
  return WEB_SEARCH_MODE_OPTIONS.find((o) => o.value === mode)?.label || mode;
}
