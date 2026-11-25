/** Vision mode: off | auto | force (mirrors web search) */

export type VisionMode = "off" | "auto" | "force";

export const VISION_MODE_OPTIONS = [
  { label: "关闭", value: "off" as const },
  { label: "智能", value: "auto" as const },
  { label: "强制", value: "force" as const },
];

export function normalizeVisionMode(
  mode?: string | null,
  enabled?: boolean | null,
): VisionMode {
  const raw = (mode || "").trim().toLowerCase();
  if (raw === "off" || raw === "auto" || raw === "force") return raw;
  if (enabled === true) return "force";
  if (enabled === false && mode == null) return "off";
  return "auto";
}

export function cycleVisionMode(current: VisionMode): VisionMode {
  if (current === "off") return "auto";
  if (current === "auto") return "force";
  return "off";
}

export function visionModeLabel(mode: VisionMode): string {
  return VISION_MODE_OPTIONS.find((o) => o.value === mode)?.label || mode;
}
