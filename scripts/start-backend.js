#!/usr/bin/env node
/** Start DeerFlow gateway only (no nginx/docker). */
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const { PORTS } = require("./ports");
const { ensureExtensionsConfig, ensureLocalConfig } = require("./ensure-config");

const repo = path.resolve(__dirname, "..");
const appRoot = process.env.REALAI_APP_ROOT || repo;
const dataRoot = process.env.REALAI_DATA_ROOT || repo;
ensureLocalConfig(appRoot, dataRoot);
const skillsRoot = path.join(dataRoot, "skills");
const configDir = path.join(dataRoot, "config");
if (!fs.existsSync(configDir)) fs.mkdirSync(configDir, { recursive: true });
ensureExtensionsConfig(configDir, appRoot);

const gatewayPort = process.env.GATEWAY_PORT || String(PORTS.gateway);
const deer = path.join(appRoot, "services", "deerflow");
const backend = path.join(deer, "backend");
const harness = path.join(backend, "packages", "harness");
const uv =
  process.env.UV_EXE ||
  (fs.existsSync(path.join(process.env.USERPROFILE || "", ".local", "bin", "uv.exe"))
    ? path.join(process.env.USERPROFILE, ".local", "bin", "uv.exe")
    : "uv");

function loadDotEnv(deerRoot) {
  const envPath = path.join(deerRoot, ".env");
  if (!fs.existsSync(envPath)) return {};
  const out = {};
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m) out[m[1].trim()] = m[2].trim();
  }
  return out;
}

const embeddedPy = path.join(appRoot, "runtime", "venv", "Scripts", "python.exe");
const localPy = path.join(backend, ".venv", process.platform === "win32" ? "Scripts" : "bin", process.platform === "win32" ? "python.exe" : "python");
const pythonExe = fs.existsSync(embeddedPy) ? embeddedPy : localPy;
const useLocalPython = fs.existsSync(pythonExe);

const env = {
  ...process.env,
  ...loadDotEnv(deer),
  REALAI_APP_ROOT: appRoot,
  REALAI_DATA_ROOT: dataRoot,
  REALAI_REPO_ROOT: appRoot,
  DEER_FLOW_SKILLS_PATH: skillsRoot,
  DEER_FLOW_EXTENSIONS_CONFIG_PATH: path.join(configDir, "extensions_config.json"),
  GATEWAY_PORT: gatewayPort,
  DEER_FLOW_AUTH_DISABLED: "1",
  DEER_FLOW_PROJECT_ROOT: deer,
  DEER_FLOW_CONFIG_PATH: path.join(deer, "config.yaml"),
  DEER_FLOW_HOME: path.join(deer, ".deer-flow"),
  PYTHONPATH: [backend, harness].join(path.delimiter),
  GATEWAY_CORS_ORIGINS: `http://127.0.0.1:${PORTS.frontend},http://localhost:${PORTS.frontend}`,
};

const child = useLocalPython
  ? spawn(
      pythonExe,
      [
        "-m",
        "uvicorn",
        "app.gateway.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        gatewayPort,
      ],
      { cwd: backend, env, stdio: "inherit", shell: false },
    )
  : spawn(
      uv,
      ["run", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", gatewayPort],
      { cwd: backend, env, stdio: "inherit", shell: false },
    );

child.on("exit", (code) => process.exit(code ?? 0));
