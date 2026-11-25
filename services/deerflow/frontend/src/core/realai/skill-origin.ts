import type { SkillSummary } from "@/core/realai/types";

/** RealAi project preset skills (Chinese, editable). Keep in sync with deerflow_bridge.REALAI_PRESET_IDS */
export const REALAI_PROJECT_SKILL_IDS = new Set([
  "weekly-digest",
  "document-highlights",
  "pipeline-asset-intro",
  "strategic-planning-intake",
  "strategic-planning-researcher",
  "strategic-planning-architect",
  "strategic-planning-writer",
  "strategic-planning-citer",
  "strategic-planning-reviewer",
  "strategic-planning-optimizer",
]);

export function isRealAiProjectSkill(skill: Pick<SkillSummary, "id" | "category" | "source">) {
  if (REALAI_PROJECT_SKILL_IDS.has(skill.id)) return true;
  if (skill.category === "custom" || skill.category === "legacy") return true;
  return false;
}

export function isDeerflowBuiltinSkill(skill: Pick<SkillSummary, "id" | "category" | "source" | "read_only">) {
  return !isRealAiProjectSkill(skill);
}

export function canEditSkill(skill: Pick<SkillSummary, "id" | "category" | "source" | "read_only" | "editable">) {
  if (isDeerflowBuiltinSkill(skill)) return false;
  if (REALAI_PROJECT_SKILL_IDS.has(skill.id)) return true;
  if (skill.category === "custom" || skill.category === "legacy") return true;
  return skill.read_only !== true && skill.editable !== false;
}

export function canDeleteSkill(skill: Pick<SkillSummary, "id" | "category" | "source" | "read_only">) {
  return isRealAiProjectSkill(skill);
}
