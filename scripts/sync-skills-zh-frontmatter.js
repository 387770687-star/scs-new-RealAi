#!/usr/bin/env node
/** Sync Chinese name/description for RealAi preset skills only (skills/public). */
const fs = require("fs");
const path = require("path");

const repo = path.resolve(__dirname, "..");

/** RealAi project-specific skills — keep Chinese in the workshop. */
const REALAI_PRESET_IDS = new Set([
  "weekly-digest",
  "document-highlights",
  "pipeline-asset-intro",
  "strategic-planning-researcher",
  "strategic-planning-architect",
  "strategic-planning-writer",
  "strategic-planning-citer",
  "strategic-planning-reviewer",
  "strategic-planning-optimizer",
]);

const ZH_META = {
  "weekly-digest": {
    name: "周报整理",
    description: "将本周工作要点整理为结构化周报（进展/问题/计划）",
  },
  "document-highlights": {
    name: "文档要点提取",
    description: "从长文档提取要点、结论与待办（适合规范/方案/会议纪要）",
  },
  "pipeline-asset-intro": {
    name: "管段站点介绍",
    description: "管段/站场介绍模板（结构固定、循证）",
  },
  "strategic-planning-researcher": {
    name: "战略规划研究",
    description: "为战略报告收集事实包：wiki/raw 检索、问数与白名单联网校验",
  },
  "strategic-planning-architect": {
    name: "战略规划架构",
    description: "设计战略报告大纲、战略主线、字数预算与撰写顺序",
  },
  "strategic-planning-writer": {
    name: "战略规划写作",
    description: "逐章撰写正式战略规划长文（循证、管网语境、字数底线）",
  },
  "strategic-planning-citer": {
    name: "战略规划引用审核",
    description: "审核引用真实性、生成【N】标注与参考文献台账",
  },
  "strategic-planning-reviewer": {
    name: "战略规划评审",
    description: "七维评分与 P0–P3 问题清单（含管网适配）",
  },
  "strategic-planning-optimizer": {
    name: "战略规划迭代优化",
    description: "按评分自动重写薄弱章节，最多 5 轮直至收敛",
  },
};

function patchSkillFile(filePath, folderId) {
  if (!REALAI_PRESET_IDS.has(folderId)) return false;
  const meta = ZH_META[folderId];
  if (!meta) return false;
  if (!fs.existsSync(filePath)) return false;

  const raw = fs.readFileSync(filePath, "utf8");
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!m) {
    console.warn("skip (no frontmatter):", filePath);
    return false;
  }

  const body = m[2];
  const front = `---\nname: ${meta.name}\ndescription: ${meta.description}\n---\n`;
  fs.writeFileSync(filePath, front + body, "utf8");
  return true;
}

function syncTree(rootDir) {
  let count = 0;
  const publicDir = path.join(rootDir, "public");
  if (!fs.existsSync(publicDir)) return count;
  for (const id of fs.readdirSync(publicDir)) {
    if (!REALAI_PRESET_IDS.has(id)) continue;
    const skillPath = path.join(publicDir, id, "SKILL.md");
    if (patchSkillFile(skillPath, id)) {
      count++;
      console.log("OK", path.relative(repo, skillPath));
    }
  }
  return count;
}

const roots = [path.join(repo, "skills")];

let total = 0;
for (const root of roots) {
  total += syncTree(root);
}
console.log(`\nUpdated ${total} RealAi preset SKILL.md file(s).`);
