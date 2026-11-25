#!/usr/bin/env node
/**
 * One-shot local dev: deps check → backend → Vue frontend (vite) → Electron.
 * DeerFlow Next 默认不启动；可用 --deerflow 一并启动（仍不自动打开窗口）。
 *
 * Usage:
 *   node scripts/dev-all.js
 *   node scripts/dev-all.js --build        # vite build before preview/dev
 *   node scripts/dev-all.js --no-electron  # only backend + Vue
 *   node scripts/dev-all.js --install      # force install
 *   node scripts/dev-all.js --deerflow     # also start DeerFlow Next on :8400
 */
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");

const { PORTS, gatewayUrl, frontendUrl, vueFrontendUrl } = require("./ports");
const { ensureExtensionsConfig, ensureLocalConfig } = require("./ensure-config");

const repo = path.resolve(__dirname, "..");
const appRoot = process.env.REALAI_APP_ROOT || repo;
const dataRoot = process.env.REALAI_DATA_ROOT || repo;
const webDir = path.join(appRoot, "apps", "web");
const deerFrontendDir = path.join(appRoot, "services", "deerflow", "frontend");
const deer = path.join(appRoot, "services", "deerflow");
const backendDir = path.join(deer, "backend");
const harnessDir = path.join(backendDir, "packages", "harness");

const args = new Set(process.argv.slice(2));
const wantBuild = args.has("--build");
const wantInstall = args.has("--install");
const noElectron = args.has("--no-electron");
const wantFresh = args.has("--fresh");
const wantDeerflow = args.has("--deerflow");

const children = [];
let backendStartedByUs = false;
let vueStartedByUs = false;
let deerflowStartedByUs = false;

function log(tag, msg) {
  const line = msg.endsWith("\n") ? msg : `${msg}\n`;
  process.stdout.write(`[${tag}] ${line}`);
}

function runSync(cmd, cmdArgs, opts = {}) {
  log("dev", `$ ${cmd} ${cmdArgs.join(" ")}`);
  const res = spawnSync(cmd, cmdArgs, { stdio: "inherit", shell: true, ...opts });
  if (res.status !== 0) {
    throw new Error(`命令失败 (${res.status}): ${cmd} ${cmdArgs.join(" ")}`);
  }
}

function spawnTagged(tag, cmd, cmdArgs, opts = {}) {
  const proc = spawn(cmd, cmdArgs, {
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
    shell: false,
    ...opts,
  });
  proc.stdout.on("data", (buf) => {
    for (const line of buf.toString().split(/\r?\n/)) {
      if (line) log(tag, line);
    }
  });
  proc.stderr.on("data", (buf) => {
    for (const line of buf.toString().split(/\r?\n/)) {
      if (line) log(tag, line);
    }
  });
  proc.on("exit", (code, signal) => {
    if (code && code !== 0) log(tag, `进程退出 code=${code} signal=${signal || ""}`);
  });
  children.push(proc);
  return proc;
}

function httpOk(url, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 300);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForUrl(label, url, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await httpOk(url)) {
      log("dev", `${label} 就绪: ${url}`);
      return;
    }
    await new Promise((r) => setTimeout(r, 800));
  }
  throw new Error(`${label} 启动超时: ${url}`);
}

function getUvExe() {
  const local = path.join(process.env.USERPROFILE || "", ".local", "bin", "uv.exe");
  if (fs.existsSync(local)) return local;
  return "uv";
}

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

function corsOrigins() {
  return [
    vueFrontendUrl(),
    `http://127.0.0.1:${PORTS.vueFrontend || 8402}`,
    frontendUrl(),
    `http://127.0.0.1:${PORTS.frontend}`,
  ].join(",");
}

function backendEnv() {
  const configDir = path.join(dataRoot, "config");
  if (!fs.existsSync(configDir)) fs.mkdirSync(configDir, { recursive: true });
  ensureExtensionsConfig(configDir, appRoot);
  return {
    ...process.env,
    ...loadDotEnv(deer),
    REALAI_APP_ROOT: appRoot,
    REALAI_DATA_ROOT: dataRoot,
    REALAI_REPO_ROOT: appRoot,
    DEER_FLOW_SKILLS_PATH: path.join(dataRoot, "skills"),
    DEER_FLOW_EXTENSIONS_CONFIG_PATH: path.join(configDir, "extensions_config.json"),
    GATEWAY_PORT: String(PORTS.gateway),
    DEER_FLOW_AUTH_DISABLED: "1",
    DEER_FLOW_PROJECT_ROOT: deer,
    DEER_FLOW_CONFIG_PATH: path.join(deer, "config.yaml"),
    DEER_FLOW_HOME: path.join(deer, ".deer-flow"),
    PYTHONPATH: [backendDir, harnessDir].join(path.delimiter),
    GATEWAY_CORS_ORIGINS: corsOrigins(),
  };
}

function startBackend() {
  const uv = getUvExe();
  const embeddedPy = path.join(appRoot, "runtime", "venv", "Scripts", "python.exe");
  const localPy = path.join(backendDir, ".venv", process.platform === "win32" ? "Scripts" : "bin", process.platform === "win32" ? "python.exe" : "python");
  const pythonExe = fs.existsSync(embeddedPy) ? embeddedPy : localPy;
  if (fs.existsSync(pythonExe)) {
    return spawnTagged(
      "backend",
      pythonExe,
      ["-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", String(PORTS.gateway)],
      { cwd: backendDir, env: backendEnv() },
    );
  }
  return spawnTagged(
    "backend",
    uv,
    ["run", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", String(PORTS.gateway)],
    { cwd: backendDir, env: backendEnv() },
  );
}

function startVueDev() {
  const viteBin = path.join(webDir, "node_modules", "vite", "bin", "vite.js");
  return spawnTagged(
    "vue",
    process.execPath,
    [viteBin, "--host", "127.0.0.1", "--port", String(PORTS.vueFrontend || 8402)],
    { cwd: webDir, env: { ...process.env } },
  );
}

function startDeerflowDev() {
  const nextBin = path.join(deerFrontendDir, "node_modules", "next", "dist", "bin", "next");
  const env = {
    ...process.env,
    PORT: String(PORTS.frontend),
    DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: gatewayUrl(),
    DEER_FLOW_AUTH_DISABLED: "1",
    GATEWAY_CORS_ORIGINS: corsOrigins(),
  };
  return spawnTagged(
    "deerflow",
    process.execPath,
    [nextBin, "dev", "--turbo", "-p", String(PORTS.frontend)],
    { cwd: deerFrontendDir, env },
  );
}

function startElectron() {
  const desktopDir = path.join(repo, "apps", "desktop");
  let electronCli;
  try {
    const electronPackage = require.resolve("electron/package.json", {
      paths: [desktopDir, repo],
    });
    electronCli = path.join(path.dirname(electronPackage), "cli.js");
  } catch {
    throw new Error("未找到 Electron，请在仓库根目录执行: npm install");
  }
  const env = {
    ...process.env,
    REALAI_SKIP_BACKEND: "1",
    REALAI_SKIP_VUE: "1",
    REALAI_SKIP_DEERFLOW: "1",
  };
  const proc = spawn(process.execPath, [electronCli, desktopDir, "--dev"], {
    cwd: desktopDir,
    env,
    stdio: "inherit",
    windowsHide: false,
  });
  children.push(proc);
  return proc;
}

function killPortWindows(port) {
  if (process.platform !== "win32") return 0;
  const res = spawnSync("netstat", ["-ano"], { encoding: "utf8", shell: true });
  if (res.status !== 0 || !res.stdout) return 0;
  const pids = new Set();
  for (const line of res.stdout.split(/\r?\n/)) {
    if (!line.includes("LISTENING")) continue;
    if (!line.includes(`:${port}`)) continue;
    const parts = line.trim().split(/\s+/);
    const pid = parts[parts.length - 1];
    if (/^\d+$/.test(pid) && pid !== "0") pids.add(pid);
  }
  let killed = 0;
  for (const pid of pids) {
    log("dev", `释放端口 ${port}：结束 PID ${pid}`);
    spawnSync("taskkill", ["/PID", pid, "/F"], { stdio: "ignore", shell: true });
    killed++;
  }
  return killed;
}

function killPortPosix(port) {
  const res = spawnSync("lsof", [`-tiTCP:${port}`, "-sTCP:LISTEN"], {
    encoding: "utf8",
    shell: false,
  });
  if (!res.stdout) return 0;
  const pids = new Set(
    res.stdout
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter((value) => /^\d+$/.test(value)),
  );
  let killed = 0;
  for (const pid of pids) {
    log("dev", `释放端口 ${port}：结束 PID ${pid}`);
    try {
      process.kill(Number(pid), "SIGTERM");
      killed++;
    } catch {
      /* process may have exited between lsof and kill */
    }
  }
  return killed;
}

function killPort(port) {
  return process.platform === "win32" ? killPortWindows(port) : killPortPosix(port);
}

function killAll() {
  for (const proc of children) {
    if (proc && !proc.killed) {
      try {
        proc.kill();
      } catch {
        /* ignore */
      }
    }
  }
}

async function ensureBackend() {
  const healthUrl = `${gatewayUrl()}/api/realai/health`;
  if (!wantFresh && (await httpOk(healthUrl))) {
    log("dev", `后端已在 ${gatewayUrl()} 运行，复用现有进程（跳过重复启动）`);
    return;
  }
  log("dev", "启动后端…");
  startBackend();
  backendStartedByUs = true;
  await waitForUrl("后端", healthUrl);
}

async function ensureVueDev() {
  const url = vueFrontendUrl();
  if (!wantFresh && (await httpOk(url))) {
    log("dev", `Vue 前端已在 ${url} 运行，复用现有进程`);
    return;
  }
  log("dev", "启动 Vue 前端 (vite)…");
  startVueDev();
  vueStartedByUs = true;
  await waitForUrl("Vue 前端", url);
}

async function ensureDeerflowDev() {
  const url = frontendUrl();
  if (!wantFresh && (await httpOk(url))) {
    log("dev", `DeerFlow 前端已在 ${url} 运行，复用现有进程`);
    return;
  }
  log("dev", "启动 DeerFlow 前端 (封存，默认不打开窗口)…");
  startDeerflowDev();
  deerflowStartedByUs = true;
  await waitForUrl("DeerFlow 前端", url);
}

async function main() {
  ensureLocalConfig(appRoot, dataRoot);
  log("dev", "战略规划域多源多模态知识大脑 · 本地一键启动");
  log("dev", `后端 ${gatewayUrl()} · Vue ${vueFrontendUrl()} · DeerFlow(可选) ${frontendUrl()}`);

  const configDir = path.join(dataRoot, "config");
  if (!fs.existsSync(configDir)) fs.mkdirSync(configDir, { recursive: true });
  ensureExtensionsConfig(configDir, appRoot);

  const webModules = path.join(webDir, "node_modules");
  if (wantInstall || !fs.existsSync(webModules)) {
    log("dev", "安装 Vue 前端依赖…");
    runSync("npm", ["install"], { cwd: webDir });
  }

  if (wantDeerflow) {
    const feModules = path.join(deerFrontendDir, "node_modules");
    if (wantInstall || !fs.existsSync(feModules)) {
      log("dev", "安装 DeerFlow 前端依赖 (pnpm install)…");
      runSync("pnpm", ["install"], { cwd: deerFrontendDir });
    }
  }

  if (wantBuild) {
    log("dev", "编译 Vue 前端 (vite build)…");
    runSync("npm", ["run", "build"], { cwd: webDir });
  } else {
    log("dev", "开发模式：Vue 由 vite 边编译边运行（加 --build 可先全量 build）");
  }

  if (wantFresh) {
    log("dev", "清理占用端口（8401 / 8402 / 8400）…");
    killPort(PORTS.gateway);
    killPort(PORTS.vueFrontend || 8402);
    killPort(PORTS.frontend);
    await new Promise((r) => setTimeout(r, 1200));
  }

  await ensureBackend();
  await ensureVueDev();
  if (wantDeerflow) {
    await ensureDeerflowDev();
  }

  if (noElectron) {
    log("dev", "已跳过大桌面壳。浏览器打开: " + vueFrontendUrl());
    log("dev", "按 Ctrl+C 停止后端与前端");
    await new Promise(() => {});
    return;
  }

  log("dev", "启动 Electron 桌面窗口（主界面 = Vue）…");
  const electron = startElectron();
  electron.on("exit", (code) => {
    log("dev", `Electron 已退出 (${code ?? 0})，正在停止本脚本启动的服务…`);
    if (backendStartedByUs || vueStartedByUs || deerflowStartedByUs) killAll();
    process.exit(code ?? 0);
  });
}

process.on("SIGINT", () => {
  log("dev", "收到 Ctrl+C，正在停止…");
  if (backendStartedByUs || vueStartedByUs || deerflowStartedByUs) killAll();
  process.exit(0);
});
process.on("SIGTERM", () => {
  if (backendStartedByUs || vueStartedByUs || deerflowStartedByUs) killAll();
  process.exit(0);
});

main().catch((err) => {
  console.error("[dev] 启动失败:", err.message || err);
  if (backendStartedByUs || vueStartedByUs || deerflowStartedByUs) killAll();
  process.exit(1);
});
