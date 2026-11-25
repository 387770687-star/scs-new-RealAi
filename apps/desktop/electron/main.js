const { app, BrowserWindow, ipcMain, shell, Menu, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const { PORTS, gatewayUrl } = require("../../../scripts/ports");
const { spawn } = require("child_process");
const {
  getAppRoot,
  getDataRoot,
  defaultDataRootSibling,
  ensureDataLayout,
  isPortableMode,
} = require("./paths");

function initPortableEnv() {
  const appRoot = process.env.REALAI_APP_ROOT || path.resolve(__dirname, "..", "..", "..");
  process.env.REALAI_APP_ROOT = appRoot;
  if (!process.env.REALAI_DATA_ROOT) {
    if (app.isPackaged || process.env.REALAI_PORTABLE === "1") {
      const dataRoot = defaultDataRootSibling(appRoot);
      ensureDataLayout(dataRoot);
      process.env.REALAI_DATA_ROOT = dataRoot;
    }
  } else {
    ensureDataLayout(process.env.REALAI_DATA_ROOT);
  }
  process.env.REALAI_REPO_ROOT = appRoot;
}

initPortableEnv();

const {
  getSettingsPath,
  loadSettings,
  saveSettings,
  syncDeerFlowConfig,
} = require("./config-bridge");
const { startBackend, stopBackend, waitForHealth } = require("./process-manager");

const isDev = process.argv.includes("--dev");
const DEERFLOW_PORT = Number(process.env.PORT || PORTS.frontend);
const VUE_PORT = Number(process.env.VUE_PORT || PORTS.vueFrontend || 8402);
const GATEWAY_PORT = Number(process.env.GATEWAY_PORT || PORTS.gateway);
const PRODUCT_NAME = "战略规划域多源多模态知识大脑";

app.setName(PRODUCT_NAME);

let mainWindow = null;
let deerflowWindow = null;
let vueProc = null;
let deerflowProc = null;

function getUvExe() {
  const appRoot = getAppRoot();
  const bundled = path.join(appRoot, "runtime", "uv", "uv.exe");
  if (fs.existsSync(bundled)) return bundled;
  const local = path.join(process.env.USERPROFILE || "", ".local", "bin", "uv.exe");
  if (fs.existsSync(local)) return local;
  return "uv";
}

function getNodeExe() {
  const appRoot = getAppRoot();
  const bundled = path.join(appRoot, "runtime", "node", "node.exe");
  if (fs.existsSync(bundled)) return bundled;
  return process.execPath;
}

function sendMenuAction(action, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("menu:action", action, payload);
  }
}

function resolveVaultAbs() {
  const settings = loadSettings();
  const vault = settings.obsidianVaultPath || path.join(getDataRoot(), "vault");
  const abs = path.isAbsolute(vault) ? vault : path.resolve(getAppRoot(), vault);
  return abs;
}

/** 常见 Obsidian 安装路径（Windows） */
function findObsidianExe() {
  const candidates = [
    path.join(process.env.LOCALAPPDATA || "", "Obsidian", "Obsidian.exe"),
    path.join(process.env.PROGRAMFILES || "", "Obsidian", "Obsidian.exe"),
    path.join(process.env["PROGRAMFILES(X86)"] || "", "Obsidian", "Obsidian.exe"),
  ];
  for (const p of candidates) {
    if (p && fs.existsSync(p)) return p;
  }
  return null;
}

/**
 * 打开 Obsidian 管理界面（本机已安装的 Obsidian App）。
 * Vault 即设置中的知识库路径；无 .obsidian 时补一个空目录以便识别为库。
 */
async function openObsidianWindow() {
  const abs = resolveVaultAbs();
  if (!fs.existsSync(abs)) {
    await dialog.showMessageBox({
      type: "warning",
      title: "无法打开 Obsidian",
      message: "知识库文件夹不存在",
      detail: abs,
    });
    return;
  }
  const marker = path.join(abs, ".obsidian");
  if (!fs.existsSync(marker)) {
    try {
      fs.mkdirSync(marker, { recursive: true });
    } catch (err) {
      console.warn("[realai] ensure .obsidian failed", err);
    }
  }

  const uri = `obsidian://open?path=${encodeURIComponent(abs)}`;
  const exe = findObsidianExe();

  try {
    if (exe) {
      spawn(exe, [uri], { detached: true, stdio: "ignore" }).unref();
      return;
    }
    await shell.openExternal(uri);
  } catch (err) {
    console.warn("[realai] open Obsidian failed", err);
    await shell.openPath(abs);
    await dialog.showMessageBox({
      type: "info",
      title: "未检测到 Obsidian",
      message: "已在资源管理器中打开知识库文件夹",
      detail:
        "请安装 Obsidian（https://obsidian.md），用「打开文件夹作为库」选择该路径。\n之后可从「窗口 → 打开 Obsidian」直接进入。",
    });
  }
}

function startVueFrontend() {
  const appRoot = getAppRoot();
  const webDir = path.join(appRoot, "apps", "web");
  const viteBin = path.join(webDir, "node_modules", "vite", "bin", "vite.js");
  if (!fs.existsSync(viteBin)) {
    console.warn("[realai] Vue frontend not installed — run: npm run web:install");
    return null;
  }
  const distIndex = path.join(webDir, "dist", "index.html");
  const nodeExe = getNodeExe();
  if (isDev) {
    console.log(`[realai] Vue vite dev on :${VUE_PORT}`);
    const proc = spawn(nodeExe, [viteBin, "--host", "127.0.0.1", "--port", String(VUE_PORT)], {
      cwd: webDir,
      env: { ...process.env, VITE_GATEWAY_PORT: String(GATEWAY_PORT) },
      stdio: "inherit",
      windowsHide: true,
    });
    proc.on("error", (err) => console.error("[realai] vue frontend error", err));
    return proc;
  }
  if (fs.existsSync(distIndex)) {
    console.log(`[realai] Vue preview on :${VUE_PORT}`);
    const proc = spawn(
      nodeExe,
      [viteBin, "preview", "--host", "127.0.0.1", "--port", String(VUE_PORT), "--strictPort"],
      {
        cwd: webDir,
        env: { ...process.env },
        stdio: "inherit",
        windowsHide: true,
      },
    );
    proc.on("error", (err) => console.error("[realai] vue preview error", err));
    return proc;
  }
  console.warn("[realai] Vue dist missing — run: npm run web:build");
  return null;
}

function startDeerflowFrontend() {
  const appRoot = getAppRoot();
  const frontendDir = path.join(appRoot, "services", "deerflow", "frontend");
  const nextBin = path.join(frontendDir, "node_modules", "next", "dist", "bin", "next");
  if (!fs.existsSync(nextBin)) {
    console.warn("[realai] DeerFlow frontend not installed");
    return null;
  }
  if (!isDev && !fs.existsSync(path.join(frontendDir, ".next"))) {
    console.warn("[realai] DeerFlow frontend not built");
    return null;
  }
  const env = {
    ...process.env,
    PORT: String(DEERFLOW_PORT),
    DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: gatewayUrl(),
    DEER_FLOW_AUTH_DISABLED: "1",
    GATEWAY_CORS_ORIGINS: [
      `http://127.0.0.1:${DEERFLOW_PORT}`,
      `http://localhost:${DEERFLOW_PORT}`,
      `http://127.0.0.1:${VUE_PORT}`,
      `http://localhost:${VUE_PORT}`,
    ].join(","),
  };
  const nodeExe = getNodeExe();
  const nextArgs = isDev
    ? ["dev", "--turbo", "-p", String(DEERFLOW_PORT)]
    : ["start", "-p", String(DEERFLOW_PORT)];
  console.log(`[realai] DeerFlow frontend ${isDev ? "dev" : "start"} on :${DEERFLOW_PORT}`);
  const proc = spawn(nodeExe, [nextBin, ...nextArgs], {
    cwd: frontendDir,
    env,
    stdio: "inherit",
    windowsHide: true,
  });
  proc.on("error", (err) => console.error("[realai] deerflow frontend error", err));
  return proc;
}

async function ensureDeerflowRunning() {
  if (deerflowProc && !deerflowProc.killed) return true;
  if (process.env.REALAI_SKIP_DEERFLOW === "1") return false;
  deerflowProc = startDeerflowFrontend();
  if (!deerflowProc) return false;
  try {
    await waitForHealth(`http://127.0.0.1:${DEERFLOW_PORT}`, 180000);
    return true;
  } catch {
    return false;
  }
}

async function openDeerflowWindow() {
  const ok = await ensureDeerflowRunning();
  if (!ok) {
    dialog.showMessageBox({
      type: "warning",
      title: "DeerFlow 旧界面",
      message: "无法启动 DeerFlow 前端。请确认已安装并构建 services/deerflow/frontend。",
    });
    return;
  }
  if (deerflowWindow && !deerflowWindow.isDestroyed()) {
    deerflowWindow.focus();
    return;
  }
  deerflowWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: `${PRODUCT_NAME} · DeerFlow（封存）`,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  await deerflowWindow.loadURL(`http://localhost:${DEERFLOW_PORT}/workspace/chats`);
  deerflowWindow.on("closed", () => {
    deerflowWindow = null;
  });
}

function showAboutDialog() {
  return dialog.showMessageBox({
    type: "info",
    title: `关于 ${PRODUCT_NAME}`,
    message: PRODUCT_NAME,
    detail:
      "功能入口：左侧菜单（工作台 / 写作 / 知识库等）\n" +
      "顶栏：打开 Vault / Obsidian、刷新、快捷键动作\n" +
      "知识库：Obsidian Vault（「文件 → 打开 Obsidian」）\n" +
      "智能引擎：DeerFlow（后端）\n" +
      "DeerFlow 旧界面与开发者工具在「帮助 → 高级」",
  });
}

function buildMenu() {
  const template = [
    {
      label: "文件",
      submenu: [
        {
          label: "打开 Vault 文件夹",
          click: () => {
            void shell.openPath(resolveVaultAbs());
          },
        },
        {
          label: "打开配置文件夹",
          click: () => {
            void shell.openPath(path.dirname(getSettingsPath()));
          },
        },
        {
          label: "打开 Obsidian",
          accelerator: "CmdOrCtrl+Shift+O",
          click: () => void openObsidianWindow(),
        },
        { type: "separator" },
        { role: "quit", label: "退出" },
      ],
    },
    {
      label: "编辑",
      submenu: [
        { role: "undo", label: "撤销" },
        { role: "redo", label: "重做" },
        { type: "separator" },
        { role: "cut", label: "剪切" },
        { role: "copy", label: "复制" },
        { role: "paste", label: "粘贴" },
        ...(process.platform === "darwin"
          ? [{ role: "pasteAndMatchStyle", label: "粘贴并匹配样式" }]
          : []),
        { role: "delete", label: "删除" },
        { type: "separator" },
        { role: "selectAll", label: "全选" },
      ],
    },
    {
      label: "视图",
      submenu: [
        { role: "reload", label: "刷新" },
        {
          label: "重载主界面",
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) mainWindow.reload();
          },
        },
        {
          label: "显示/隐藏证据栏",
          accelerator: "CmdOrCtrl+E",
          click: () => sendMenuAction("toggle-evidence"),
        },
      ],
    },
    {
      label: "快捷",
      submenu: [
        {
          label: "新建问答",
          accelerator: "CmdOrCtrl+N",
          click: () => sendMenuAction("new-ask"),
        },
        {
          label: "新建报告任务",
          accelerator: "CmdOrCtrl+Shift+N",
          click: () => sendMenuAction("new-report"),
        },
        {
          label: "切换联网模式（关闭/智能/强制）",
          click: () => sendMenuAction("toggle-web-search"),
        },
      ],
    },
    {
      label: "帮助",
      submenu: [
        {
          label: "打开设置",
          click: () => sendMenuAction("navigate", "/system"),
        },
        {
          label: `关于 ${PRODUCT_NAME}`,
          click: () => void showAboutDialog(),
        },
        {
          label: "高级",
          submenu: [
            { role: "toggleDevTools", label: "开发者工具" },
            {
              label: "打开 DeerFlow 旧界面",
              click: () => void openDeerflowWindow(),
            },
          ],
        },
      ],
    },
  ];
  if (process.platform === "darwin") {
    template.unshift({
      label: PRODUCT_NAME,
      submenu: [
        { label: `关于 ${PRODUCT_NAME}`, click: () => void showAboutDialog() },
        { type: "separator" },
        { role: "services", label: "服务" },
        { type: "separator" },
        { role: "hide", label: `隐藏 ${PRODUCT_NAME}` },
        { role: "hideOthers", label: "隐藏其他" },
        { role: "unhide", label: "全部显示" },
        { type: "separator" },
        { role: "quit", label: `退出 ${PRODUCT_NAME}` },
      ],
    });
  }
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

/**
 * Chromium 在 Electron 中不会自动为输入框提供右键编辑菜单。
 * 根据当前元素的 editFlags 启用对应命令，与应用级「编辑」菜单保持一致。
 */
function installEditContextMenu(targetWindow) {
  targetWindow.webContents.on("context-menu", (_event, params) => {
    const flags = params.editFlags || {};
    const hasSelection = Boolean(params.selectionText);
    if (!params.isEditable && !hasSelection) return;

    const template = [];
    if (params.isEditable) {
      template.push(
        { role: "undo", label: "撤销", enabled: Boolean(flags.canUndo) },
        { role: "redo", label: "重做", enabled: Boolean(flags.canRedo) },
        { type: "separator" },
      );
    }
    template.push(
      { role: "cut", label: "剪切", enabled: params.isEditable && Boolean(flags.canCut) },
      { role: "copy", label: "复制", enabled: hasSelection && Boolean(flags.canCopy) },
    );
    if (params.isEditable) {
      template.push(
        { role: "paste", label: "粘贴", enabled: Boolean(flags.canPaste) },
        { role: "delete", label: "删除", enabled: Boolean(flags.canDelete) },
      );
    }
    template.push(
      { type: "separator" },
      { role: "selectAll", label: "全选", enabled: Boolean(flags.canSelectAll) },
    );

    Menu.buildFromTemplate(template).popup({ window: targetWindow });
  });
}

async function setBootStatus(text, progress) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    const progArg = typeof progress === "number" ? `, ${JSON.stringify(progress)}` : "";
    await mainWindow.webContents.executeJavaScript(
      `window.__setBootStatus && window.__setBootStatus(${JSON.stringify(text)}${progArg})`,
      true,
    );
  } catch {
    /* ignore if page not ready */
  }
}

async function finishBootSplash() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    await mainWindow.webContents.executeJavaScript(
      `window.__finishBootSplash ? window.__finishBootSplash() : Promise.resolve()`,
      true,
    );
  } catch {
    /* ignore */
  }
}

async function createWindow() {
  buildMenu();

  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    title: PRODUCT_NAME,
  });
  installEditContextMenu(mainWindow);

  mainWindow.once("ready-to-show", () => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show();
  });

  mainWindow.webContents.on("did-fail-load", (_e, code, desc, url) => {
    console.error("[realai] did-fail-load", { code, desc, url });
    void setBootStatus(`页面加载失败：${desc || code}。请检查终端日志，或浏览器打开 http://127.0.0.1:${VUE_PORT}`);
  });

  // 立刻显示启动页，避免空白窗体「一直转圈」无提示
  const bootHtml = path.join(__dirname, "..", "renderer", "boot.html");
  try {
    await mainWindow.loadFile(bootHtml);
  } catch (err) {
    console.warn("[realai] boot splash failed", err);
  }

  if (isPortableMode()) {
    console.log("[realai] portable mode", { app: getAppRoot(), data: getDataRoot() });
  }

  const settings = loadSettings();
  syncDeerFlowConfig(settings);

  const skipBackend = process.env.REALAI_SKIP_BACKEND === "1";
  const skipVue = process.env.REALAI_SKIP_VUE === "1";

  try {
    if (!skipBackend) {
      await setBootStatus("正在启动后端 Gateway…", 22);
      await startBackend({ uvExe: getUvExe(), port: GATEWAY_PORT });
      await setBootStatus("等待后端就绪…", 45);
      await waitForHealth(`http://127.0.0.1:${GATEWAY_PORT}/api/realai/health`, 120000);
      await setBootStatus("后端已就绪", 62);
    } else {
      console.log("[realai] skip backend (REALAI_SKIP_BACKEND=1)");
      await setBootStatus("检查后端是否已就绪…", 30);
      // npm run dev 已拉起后端：短等即可，失败也不堵死界面
      try {
        await waitForHealth(`http://127.0.0.1:${GATEWAY_PORT}/api/realai/health`, 8000);
        await setBootStatus("后端已就绪", 55);
      } catch (err) {
        console.warn("[realai] backend not ready yet, continue to UI", err);
        await setBootStatus("后端暂未响应，先打开界面（可稍后在设置里重试）…", 50);
      }
    }
  } catch (err) {
    console.error("[realai] backend failed", err);
    await setBootStatus("后端启动失败，尝试打开界面…", 55);
  }

  // 主界面：Vue。DeerFlow Next 默认不启动，仅菜单打开时再起。
  if (!skipVue) {
    await setBootStatus("正在启动 Vue 前端…", 72);
    vueProc = startVueFrontend();
  } else {
    console.log("[realai] skip Vue spawn (REALAI_SKIP_VUE=1)");
  }

  const vueReady = vueProc || skipVue;
  if (vueReady) {
    try {
      await setBootStatus(`等待 Vue 前端（端口 ${VUE_PORT}）…`, 85);
      // npm run dev 已等过 Vue：短超时；自启 Vite 时给足时间
      await waitForHealth(`http://127.0.0.1:${VUE_PORT}`, skipVue ? 15000 : 180000);
      await setBootStatus("正在加载主界面…", 96);
      await finishBootSplash();
      await mainWindow.loadURL(`http://127.0.0.1:${VUE_PORT}/`);
      return;
    } catch (err) {
      console.warn("[realai] Vue frontend unavailable, try dist file", err);
      await setBootStatus("Vue 开发服未就绪，尝试加载本地构建产物…", 90);
    }
  }

  const distIndex = path.join(getAppRoot(), "apps", "web", "dist", "index.html");
  if (fs.existsSync(distIndex)) {
    await finishBootSplash();
    await mainWindow.loadFile(distIndex);
    return;
  }

  await setBootStatus("未找到 Vue 界面，打开简易设置页…", 95);
  await finishBootSplash();
  await mainWindow.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  stopBackend();
  if (vueProc && !vueProc.killed) vueProc.kill();
  if (deerflowProc && !deerflowProc.killed) deerflowProc.kill();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopBackend();
  if (vueProc && !vueProc.killed) vueProc.kill();
  if (deerflowProc && !deerflowProc.killed) deerflowProc.kill();
});

ipcMain.handle("settings:load", () => loadSettings());
ipcMain.handle("settings:save", (_e, settings) => {
  saveSettings(settings);
  syncDeerFlowConfig(settings);
  return { ok: true };
});

ipcMain.handle("realai:paths", () => ({
  appRoot: getAppRoot(),
  dataRoot: getDataRoot(),
  portable: isPortableMode(),
}));

ipcMain.handle("chat:send", async (_e, { message }) => {
  const settings = loadSettings();
  syncDeerFlowConfig(settings);
  const base = `http://127.0.0.1:${GATEWAY_PORT}`;
  const threadRes = await fetch(`${base}/api/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ metadata: { source: "realai-p0" } }),
  });
  if (!threadRes.ok) {
    const t = await threadRes.text();
    throw new Error(`创建会话失败: ${threadRes.status} ${t}`);
  }
  const thread = await threadRes.json();
  const threadId = thread.thread_id || thread.id;

  const waitRes = await fetch(`${base}/api/threads/${threadId}/runs/wait`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      assistant_id: "lead_agent",
      input: {
        messages: [{ role: "user", content: message }],
      },
      context: {
        model_name: settings.llm?.modelId || "minimax-m3",
        thinking_enabled: false,
      },
    }),
  });
  if (!waitRes.ok) {
    const t = await waitRes.text();
    throw new Error(`对话失败: ${waitRes.status} ${t}`);
  }
  const body = await waitRes.json();
  const messages = body.messages || [];
  const last = [...messages].reverse().find((m) => {
    const role = m.role || m.type;
    return role === "assistant" || role === "ai";
  });
  const content =
    typeof last?.content === "string"
      ? last.content
      : Array.isArray(last?.content)
        ? last.content.map((c) => (typeof c === "string" ? c : c.text || "")).join("\n")
        : body.error
          ? String(body.error)
          : JSON.stringify(body, null, 2);
  return { content, raw: body };
});

ipcMain.handle("shell:openSettingsFolder", () => {
  shell.openPath(path.dirname(getSettingsPath()));
});

ipcMain.handle("shell:openVaultFolder", () => {
  return shell.openPath(resolveVaultAbs());
});

ipcMain.handle("shell:openObsidian", async () => {
  await openObsidianWindow();
  return { ok: true };
});
