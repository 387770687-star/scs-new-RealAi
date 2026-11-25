const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const { PORTS } = require("../../../scripts/ports");
const { ensureExtensionsConfig } = require("../../../scripts/ensure-config");
const {
  getAppRoot,
  getDataRoot,
  getExtensionsConfigPath,
  getSkillsRoot,
} = require("./config-bridge");

let backendProc = null;

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

function resolvePython(appRoot) {
  const win = path.join(appRoot, "runtime", "venv", "Scripts", "python.exe");
  if (fs.existsSync(win)) return { cmd: win, args: ["-m", "uvicorn"] };
  const unix = path.join(appRoot, "runtime", "venv", "bin", "python");
  if (fs.existsSync(unix)) return { cmd: unix, args: ["-m", "uvicorn"] };
  return null;
}

function startBackend({ uvExe = "uv", port = PORTS.gateway } = {}) {
  if (backendProc && !backendProc.killed) {
    return Promise.resolve(backendProc);
  }
  const appRoot = getAppRoot();
  const dataRoot = getDataRoot();
  const deerRoot = path.join(appRoot, "services", "deerflow");
  const backendDir = path.join(deerRoot, "backend");
  const configDir = path.join(dataRoot, "config");
  ensureExtensionsConfig(configDir, appRoot);
  const logsDir = path.join(deerRoot, "logs");
  if (!fs.existsSync(logsDir)) fs.mkdirSync(logsDir, { recursive: true });

  const dotenv = loadDotEnv(deerRoot);
  // 构建干净的环境变量：删除会干扰 uv 的 Python 虚拟环境变量，
  // uv 会自动检测并使用 backendDir/.venv
  const cleanEnv = { ...process.env };
  delete cleanEnv.VIRTUAL_ENV;
  delete cleanEnv.VIRTUAL_ENV_PROMPT;
  delete cleanEnv.CONDA_PREFIX;
  delete cleanEnv.CONDA_DEFAULT_ENV;
  delete cleanEnv.PYTHONHOME;
  delete cleanEnv.PIP_REQUIRE_VIRTUALENV;
  const env = {
    ...cleanEnv,
    ...dotenv,
    REALAI_APP_ROOT: appRoot,
    REALAI_DATA_ROOT: dataRoot,
    REALAI_REPO_ROOT: appRoot,
    DEER_FLOW_SKILLS_PATH: getSkillsRoot(),
    DEER_FLOW_EXTENSIONS_CONFIG_PATH: getExtensionsConfigPath(),
    GATEWAY_PORT: String(port),
    DEER_FLOW_AUTH_DISABLED: "1",
    DEER_FLOW_PROJECT_ROOT: deerRoot,
    DEER_FLOW_CONFIG_PATH: path.join(deerRoot, "config.yaml"),
    DEER_FLOW_HOME: path.join(deerRoot, ".deer-flow"),
    PYTHONPATH: `${backendDir}${path.delimiter}${path.join(backendDir, "packages", "harness")}`,
    GATEWAY_CORS_ORIGINS: [
      `http://127.0.0.1:${PORTS.vueFrontend || 8402}`,
      `http://localhost:${PORTS.vueFrontend || 8402}`,
      `http://127.0.0.1:${PORTS.frontend}`,
      `http://localhost:${PORTS.frontend}`,
    ].join(","),
  };

  const embedded = resolvePython(appRoot);
  let cmd = uvExe;
  let args = [
    "run",
    "uvicorn",
    "app.gateway.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ];
  if (embedded) {
    cmd = embedded.cmd;
    args = [
      ...embedded.args,
      "app.gateway.app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ];
  }

  return new Promise((resolve, reject) => {
    backendProc = spawn(cmd, args, {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    const logStream = fs.createWriteStream(path.join(logsDir, "gateway-realai.log"), {
      flags: "a",
    });
    backendProc.stdout.pipe(logStream);
    backendProc.stderr.pipe(logStream);
    backendProc.on("error", reject);
    backendProc.on("spawn", () => resolve(backendProc));
  });
}

function stopBackend() {
  if (backendProc && !backendProc.killed) {
    backendProc.kill();
    backendProc = null;
  }
}

async function waitForHealth(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastErr = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(3000) });
      if (res.ok || res.status === 401 || res.status === 404) return true;
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, 800));
  }
  throw lastErr || new Error(`health check timeout: ${url}`);
}

module.exports = { startBackend, stopBackend, waitForHealth };
