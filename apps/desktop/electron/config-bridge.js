const path = require("path");
const fs = require("fs");
const { syncDeerFlowConfigViaPython } = require("./config-sync-python");
const {
  getRepoRoot,
  getAppRoot,
  getDataRoot,
  ensureDataLayout,
} = require("./paths");

const DEFAULTS = {
  obsidianVaultPath: "./vault",
  onboarding: { completed: false },
  llm: {
    provider: "minimax",
    apiKey: "",
    modelId: "minimax-m3",
    model: "MiniMax M3",
    baseUrl: "https://api.minimaxi.com/v1",
  },
  report: {
    outputDir: "./vault/reports",
    stepConfirm: false,
    writerSkillId: "pipeline-report-writing",
    reviewSkillId: "pipeline-report-review",
  },
  search: {
    webSearchMode: "auto",
    webSearchEnabled: false,
  },
  data: {
    excelRoots: ["./vault"],
    databases: [],
  },
};

function getConfigDir() {
  ensureDataLayout(getDataRoot());
  const dir = path.join(getDataRoot(), "config");
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function getSettingsPath() {
  return path.join(getConfigDir(), "settings.json");
}

function getExtensionsConfigPath() {
  return path.join(getConfigDir(), "extensions_config.json");
}

function getSkillsRoot() {
  return path.join(getDataRoot(), "skills");
}

function loadSettings() {
  const p = getSettingsPath();
  if (!fs.existsSync(p)) return JSON.parse(JSON.stringify(DEFAULTS));
  try {
    return { ...DEFAULTS, ...JSON.parse(fs.readFileSync(p, "utf8")) };
  } catch {
    return JSON.parse(JSON.stringify(DEFAULTS));
  }
}

function saveSettings(settings) {
  const p = getSettingsPath();
  fs.writeFileSync(p, JSON.stringify(settings, null, 2), "utf8");
}

/** @deprecated use Python realai.config_sync — kept as fallback when uv unavailable */
function syncDeerFlowConfigLegacy(settings) {
  const appRoot = getAppRoot();
  const deerRoot = path.join(appRoot, "services", "deerflow");
  const envPath = path.join(deerRoot, ".env");
  const lines = [];
  if (settings.llm?.apiKey) {
    lines.push(`MINIMAX_API_KEY=${settings.llm.apiKey}`);
  } else if (fs.existsSync(envPath)) {
    const existing = fs.readFileSync(envPath, "utf8");
    const m = existing.match(/^MINIMAX_API_KEY=(.*)$/m);
    if (m) lines.push(`MINIMAX_API_KEY=${m[1]}`);
  } else {
    lines.push("MINIMAX_API_KEY=");
  }
  fs.writeFileSync(envPath, lines.join("\n") + "\n", "utf8");

  const cfgPath = path.join(deerRoot, "config.yaml");
  if (!fs.existsSync(cfgPath)) {
    fs.copyFileSync(path.join(deerRoot, "config.example.yaml"), cfgPath);
  }
  let text = fs.readFileSync(cfgPath, "utf8");
  const baseUrl = settings.llm?.baseUrl || DEFAULTS.llm.baseUrl;
  text = text.replace(/base_url:\s*https:\/\/api\.minimaxi\.com\/v1/g, `base_url: ${baseUrl}`);
  fs.writeFileSync(cfgPath, text, "utf8");
}

function syncDeerFlowConfig(settings) {
  const appRoot = getAppRoot();
  try {
    syncDeerFlowConfigViaPython(appRoot);
  } catch (err) {
    console.warn("[realai] falling back to legacy sync", err);
    syncDeerFlowConfigLegacy(settings);
  }
}

module.exports = {
  getRepoRoot,
  getAppRoot,
  getDataRoot,
  getSettingsPath,
  getExtensionsConfigPath,
  getSkillsRoot,
  loadSettings,
  saveSettings,
  syncDeerFlowConfig,
  DEFAULTS,
};
