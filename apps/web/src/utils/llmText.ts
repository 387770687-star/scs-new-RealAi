/** Strip leaked model thinking tags from visible text (MiniMax etc.). */
export function stripThinkBlocks(text: string): string {
  if (!text) return "";
  let s = text.replace(/<think\b[^>]*>[\s\S]*?<\/think\s*>/gi, "");
  const open = s.search(/<think\b[^>]*>/i);
  if (open >= 0) s = s.slice(0, open);
  return s.trim();
}

/** Outline strategic main line for display: strip think + collapse whitespace. */
export function formatStrategicMainLine(raw: string): string {
  const cleaned = stripThinkBlocks(raw || "");
  const oneLine = cleaned.replace(/\s*\n+\s*/g, "").trim();
  if (/^(The user|I need|Let me|Okay|Sure)\b/i.test(oneLine)) return "";
  const cn = (oneLine.match(/[\u4e00-\u9fff]/g) || []).length;
  if (cn < 8) return "";
  return oneLine.length > 500 ? `${oneLine.slice(0, 500)}…` : oneLine;
}
