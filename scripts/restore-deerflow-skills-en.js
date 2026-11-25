#!/usr/bin/env node
/** Restore English frontmatter for DeerFlow built-in skills (excludes RealAi presets). */
const fs = require("fs");
const path = require("path");

const repo = path.resolve(__dirname, "..");

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

/** Original DeerFlow upstream name/description (English). */
const EN_META = {
  "academic-paper-review": {
    name: "academic-paper-review",
    description:
      "Use this skill when the user requests to review, analyze, critique, or summarize academic papers, research articles, preprints, or scientific publications. Supports comprehensive structured reviews covering methodology assessment, contribution evaluation, literature positioning, and constructive feedback generation. Trigger on queries involving paper URLs, uploaded PDFs, arXiv links, or requests like \"review this paper\", \"analyze this research\", \"summarize this study\", or \"write a peer review\".",
  },
  bootstrap: {
    name: "bootstrap",
    description:
      "Generate a personalized SOUL.md through a warm, adaptive onboarding conversation. Trigger when the user wants to create, set up, or initialize their AI partner's identity — e.g., \"create my SOUL.md\", \"bootstrap my agent\", \"set up my AI partner\", \"define who you are\", \"let's do onboarding\", \"personalize this AI\", \"make you mine\", or when a SOUL.md is missing. Also trigger for updates: \"update my SOUL.md\", \"change my AI's personality\", \"tweak the soul\".",
  },
  "chart-visualization": {
    name: "chart-visualization",
    description:
      "This skill should be used when the user wants to visualize data. It intelligently selects the most suitable chart type from 26 available options, extracts parameters based on detailed specifications, and generates a chart image using a JavaScript script.",
  },
  "claude-to-deerflow": {
    name: "claude-to-deerflow",
    description:
      "Interact with DeerFlow AI agent platform via its HTTP API. Use this skill when the user wants to send messages or questions to DeerFlow for research/analysis, start a DeerFlow conversation thread, check DeerFlow status or health, list available models/skills/agents in DeerFlow, manage DeerFlow memory, upload files to DeerFlow threads, or delegate complex research tasks to DeerFlow.",
  },
  "code-documentation": {
    name: "code-documentation",
    description:
      "Use this skill when the user requests to generate, create, or improve documentation for code, APIs, libraries, repositories, or software projects. Supports README generation, API reference documentation, inline code comments, architecture documentation, changelog generation, and developer guides.",
  },
  "consulting-analysis": {
    name: "consulting-analysis",
    description:
      "Use this skill when the user requests to generate, create, or write professional research reports including but not limited to market analysis, consumer insights, brand analysis, financial analysis, industry research, competitive intelligence, investment due diligence, or any consulting-grade analytical report.",
  },
  "data-analysis": {
    name: "data-analysis",
    description:
      "Use this skill when the user uploads Excel (.xlsx/.xls) or CSV files and wants to perform data analysis, generate statistics, create summaries, pivot tables, SQL queries, or any form of structured data exploration.",
  },
  "deep-research": {
    name: "deep-research",
    description:
      "Use this skill instead of WebSearch for ANY question requiring web research. Trigger on queries like \"what is X\", \"explain X\", \"compare X and Y\", \"research X\", or before content generation tasks.",
  },
  "find-skills": {
    name: "find-skills",
    description:
      "Helps users discover and install agent skills when they ask questions like \"how do I do X\", \"find a skill for X\", \"is there a skill that can...\", or express interest in extending capabilities.",
  },
  "frontend-design": {
    name: "frontend-design",
    description:
      "Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications.",
  },
  "github-deep-research": {
    name: "github-deep-research",
    description:
      "Conduct multi-round deep research on any GitHub Repo. Use when users request comprehensive analysis, timeline reconstruction, competitive analysis, or in-depth investigation of GitHub.",
  },
  "image-generation": {
    name: "image-generation",
    description:
      "Use this skill when the user requests to generate, create, imagine, or visualize images including characters, scenes, products, or any visual content.",
  },
  "music-generation": {
    name: "music-generation",
    description:
      "Use this skill when the user requests to generate, create, compose, or produce music or songs — background music, theme songs, jingles, or instrumental tracks.",
  },
  "newsletter-generation": {
    name: "newsletter-generation",
    description:
      "Use this skill when the user requests to generate, create, write, or draft a newsletter, email digest, weekly roundup, industry briefing, or curated content summary.",
  },
  "podcast-generation": {
    name: "podcast-generation",
    description:
      "Use this skill when the user requests to generate, create, or produce podcasts from text content. Converts written content into a two-host conversational podcast audio format.",
  },
  "ppt-generation": {
    name: "ppt-generation",
    description:
      "Use this skill when the user requests to generate, create, or make presentations (PPT/PPTX). Creates visually rich slides by generating images for each slide and composing them into a PowerPoint file.",
  },
  "skill-creator": {
    name: "skill-creator",
    description:
      "Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill.",
  },
  "skill-reviewer": {
    name: "skill-reviewer",
    description:
      "Reviews DeerFlow skill packages for readiness, triggers, safety boundaries, resources, and evidence. Invoke when users ask to audit, grade, or production-check an existing skill.",
  },
  "surprise-me": {
    name: "surprise-me",
    description:
      "Create a delightful, unexpected \"wow\" experience for the user by dynamically discovering and creatively combining other enabled skills. Triggers when the user says \"surprise me\".",
  },
  "systematic-literature-review": {
    name: "systematic-literature-review",
    description:
      "Use this skill when the user wants a systematic literature review, survey, or synthesis across multiple academic papers on a topic.",
  },
  "vercel-deploy-claimable": {
    name: "vercel-deploy",
    description:
      "Deploy applications and websites to Vercel. Use this skill when the user requests deployment actions such as \"Deploy my app\", \"Deploy this to production\", or \"Create a preview deployment\".",
  },
  "video-generation": {
    name: "video-generation",
    description:
      "Use this skill when the user requests to generate, create, or imagine videos. Supports structured prompts and reference image for guided generation.",
  },
  "web-design-guidelines": {
    name: "web-design-guidelines",
    description:
      "Review UI code for Web Interface Guidelines compliance. Use when asked to \"review my UI\", \"check accessibility\", \"audit design\", \"review UX\", or \"check my site against best practices\".",
  },
};

function patchSkillFile(filePath, folderId) {
  if (REALAI_PRESET_IDS.has(folderId)) return false;
  const meta = EN_META[folderId];
  if (!meta) return false;
  if (!fs.existsSync(filePath)) return false;

  const raw = fs.readFileSync(filePath, "utf8");
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!m) return false;

  const body = m[2];
  const safeDesc = meta.description.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const frontmatter = `---\nname: ${meta.name}\ndescription: "${safeDesc}"\n---\n`;
  fs.writeFileSync(filePath, frontmatter + body, "utf8");
  return true;
}

function syncTree(rootDir) {
  let count = 0;
  const publicDir = path.join(rootDir, "public");
  if (!fs.existsSync(publicDir)) return count;
  for (const id of fs.readdirSync(publicDir)) {
    if (REALAI_PRESET_IDS.has(id)) continue;
    const skillPath = path.join(publicDir, id, "SKILL.md");
    if (patchSkillFile(skillPath, id)) {
      count++;
      console.log("EN", path.relative(repo, skillPath));
    }
  }
  return count;
}

const roots = [path.join(repo, "skills"), path.join(repo, "services", "deerflow", "skills")];
let total = 0;
for (const root of roots) total += syncTree(root);
console.log(`\nRestored English frontmatter on ${total} DeerFlow built-in SKILL.md file(s).`);
