const fs = require("fs");
const path = require("path");

const DEFAULT_EXTENSIONS = {
  mcpServers: {},
  skills: {},
};

/**
 * Ensure config/extensions_config.json exists (DeerFlow requires it when
 * DEER_FLOW_EXTENSIONS_CONFIG_PATH is set).
 */
function ensureExtensionsConfig(configDir, appRoot) {
  const target = path.join(configDir, "extensions_config.json");
  if (fs.existsSync(target)) return target;

  fs.mkdirSync(configDir, { recursive: true });

  const candidates = [
    path.join(configDir, "extensions_config.example.json"),
    path.join(appRoot, "config", "extensions_config.example.json"),
    path.join(appRoot, "services", "deerflow", "extensions_config.example.json"),
  ];

  for (const src of candidates) {
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, target);
      return target;
    }
  }

  fs.writeFileSync(target, JSON.stringify(DEFAULT_EXTENSIONS, null, 2), "utf8");
  return target;
}

/** Initialize first-run files while preserving existing local values. */
function ensureLocalConfig(appRoot, dataRoot = appRoot) {
  const configDir = path.join(dataRoot, "config");
  fs.mkdirSync(configDir, { recursive: true });
  const settings = path.join(configDir, "settings.json");
  if (!fs.existsSync(settings)) {
    fs.copyFileSync(path.join(appRoot, "config", "settings.example.json"), settings);
    fs.chmodSync(settings, 0o600);
  }
  const deerRoot = path.join(appRoot, "services", "deerflow");
  const gatewayConfig = path.join(deerRoot, "config.yaml");
  if (!fs.existsSync(gatewayConfig)) {
    fs.copyFileSync(path.join(deerRoot, "config.example.yaml"), gatewayConfig);
    fs.chmodSync(gatewayConfig, 0o600);
  }
  const envFile = path.join(deerRoot, ".env");
  if (!fs.existsSync(envFile)) {
    fs.writeFileSync(envFile, "# Local credentials; configure models in the application.\nMINIMAX_API_KEY=\n", { mode: 0o600 });
  }
  fs.mkdirSync(path.join(dataRoot, "vault"), { recursive: true });
  return ensureExtensionsConfig(configDir, appRoot);
}

if (require.main === module) {
  const appRoot = process.env.REALAI_APP_ROOT || path.resolve(__dirname, "..");
  ensureLocalConfig(appRoot, process.env.REALAI_DATA_ROOT || appRoot);
  console.log("[setup] Local configuration is ready.");
}

module.exports = { ensureExtensionsConfig, ensureLocalConfig, DEFAULT_EXTENSIONS };
