#!/usr/bin/env node
/**
 * P4 portable directory packer.
 * Output: dist/RealAi/ (app) + dist/RealAiData/ (user data template)
 *
 * Prerequisites on build machine:
 *   npm run backend:sync
 *   npm run web:build
 */
const fs = require("fs");
const path = require("path");

const repo = path.resolve(__dirname, "..");
const distRoot = path.join(repo, "dist");
const appOut = path.join(distRoot, "RealAi");
const dataOut = path.join(distRoot, "RealAiData");

/** Directories to skip when copying large trees (DeerFlow etc.). */
const EXCLUDE_DIRS = new Set([
  "node_modules",
  ".git",
  ".venv",
  ".next",
  "__pycache__",
  ".pytest_cache",
  "dist",
  ".deer-flow",
  "logs",
]);

function rimraf(target) {
  if (fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
}

function copyRecursive(src, dest, { excludeDirs = EXCLUDE_DIRS } = {}) {
  if (!fs.existsSync(src)) return;
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const name of fs.readdirSync(src)) {
      if (excludeDirs.has(name)) continue;
      copyRecursive(path.join(src, name), path.join(dest, name), { excludeDirs });
    }
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function copyDirFiltered(src, dest, opts) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  for (const name of fs.readdirSync(src)) {
    if (EXCLUDE_DIRS.has(name)) continue;
    copyRecursive(path.join(src, name), path.join(dest, name), opts);
  }
}

/** Copy a tree including normally-excluded dirs (e.g. electron, web dist). */
function copyTreeAllowAll(src, dest) {
  if (!fs.existsSync(src)) return;
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const name of fs.readdirSync(src)) {
      copyTreeAllowAll(path.join(src, name), path.join(dest, name));
    }
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function ensureVenv() {
  const venvSrc = path.join(repo, "services", "deerflow", "backend", ".venv");
  if (!fs.existsSync(venvSrc)) {
    console.error("Missing backend .venv — run: npm run backend:sync");
    process.exit(1);
  }
  const venvDest = path.join(appOut, "runtime", "venv");
  console.log("Copying Python venv (may take a few minutes)…");
  copyTreeAllowAll(venvSrc, venvDest);
}

function ensureElectron() {
  const electronSrc = path.join(repo, "apps", "desktop", "node_modules", "electron");
  if (!fs.existsSync(path.join(electronSrc, "cli.js"))) {
    console.error("Missing Electron — run: npm install (workspace apps/desktop)");
    process.exit(1);
  }
  const electronDest = path.join(appOut, "apps", "desktop", "node_modules", "electron");
  console.log("Copying Electron runtime…");
  copyTreeAllowAll(electronSrc, electronDest);
}

function ensureVueDist() {
  const vueDistSrc = path.join(repo, "apps", "web", "dist");
  const indexHtml = path.join(vueDistSrc, "index.html");
  if (!fs.existsSync(indexHtml)) {
    console.error("Missing Vue dist — run: npm run web:build");
    process.exit(1);
  }
  const vueDistDest = path.join(appOut, "apps", "web", "dist");
  console.log("Copying Vue dist…");
  copyTreeAllowAll(vueDistSrc, vueDistDest);
  // package.json 便于排查版本；运行不依赖 node_modules
  const pkg = path.join(repo, "apps", "web", "package.json");
  if (fs.existsSync(pkg)) {
    fs.copyFileSync(pkg, path.join(appOut, "apps", "web", "package.json"));
  }
}

function writeStartScripts() {
  const cmd = `@echo off
setlocal
set "APP_ROOT=%~dp0"
set "REALAI_APP_ROOT=%APP_ROOT%"
set "REALAI_DATA_ROOT=%APP_ROOT%..\\RealAiData"
set "REALAI_PORTABLE=1"
if not exist "%REALAI_DATA_ROOT%\\config" mkdir "%REALAI_DATA_ROOT%\\config"
if not exist "%REALAI_DATA_ROOT%\\vault" mkdir "%REALAI_DATA_ROOT%\\vault"
if not exist "%REALAI_DATA_ROOT%\\skills\\custom" mkdir "%REALAI_DATA_ROOT%\\skills\\custom"
cd /d "%APP_ROOT%apps\\desktop"
"%APP_ROOT%runtime\\node\\node.exe" "%APP_ROOT%apps\\desktop\\node_modules\\electron\\cli.js" .
`;
  fs.writeFileSync(path.join(appOut, "Start-RealAi.cmd"), cmd, "utf8");

  const readme = `# RealAi 便携包

## 目录

- \`RealAi/\` — 程序（可整包替换升级）
- \`RealAiData/\` — 你的数据（config、vault、skills），**换程序包不丢**

## 启动

双击 \`RealAi\\Start-RealAi.cmd\`。

首次启动会弹出设置向导：填写 MiniMax Key、可选导入示例资料、运行健康检查。

## 换机使用

把 \`RealAi\` 与旁边的 \`RealAiData\` **一起**拷到 U 盘或另一台 Windows 电脑即可。
目标机一般不需要再装 Node / Python / Docker。

## 数据位置

- 配置：\`RealAiData/config/settings.json\`
- 知识库：\`RealAiData/vault/\`
- 自定义 Skill：\`RealAiData/skills/custom/\`

`;
  fs.writeFileSync(path.join(distRoot, "README-PORTABLE.txt"), readme, "utf8");
}

function copyNodeRuntime() {
  const nodeExe = process.execPath;
  const nodeDir = path.join(appOut, "runtime", "node");
  fs.mkdirSync(nodeDir, { recursive: true });
  fs.copyFileSync(nodeExe, path.join(nodeDir, "node.exe"));
}

function main() {
  console.log("P4 pack →", distRoot);
  rimraf(appOut);
  rimraf(dataOut);

  fs.mkdirSync(appOut, { recursive: true });

  const copyList = [
    ["apps/desktop", "apps/desktop"],
    ["services/deerflow", "services/deerflow"],
    ["skills/public", "skills/public"],
    ["pack-assets", "pack-assets"],
    ["scripts/ports.js", "scripts/ports.js"],
    ["scripts/ensure-config.js", "scripts/ensure-config.js"],
    ["config/ports.json", "config/ports.json"],
    ["config/settings.example.json", "config/settings.example.json"],
  ];

  for (const [from, to] of copyList) {
    const src = path.join(repo, from);
    const dest = path.join(appOut, to);
    if (!fs.existsSync(src)) {
      console.warn("skip missing", from);
      continue;
    }
    console.log("copy", from);
    if (fs.statSync(src).isDirectory()) copyDirFiltered(src, dest);
    else copyRecursive(src, dest);
  }

  ensureVueDist();
  ensureElectron();
  ensureVenv();
  copyNodeRuntime();

  for (const sub of ["config", "vault", "skills/custom", "skills/public"]) {
    fs.mkdirSync(path.join(dataOut, sub), { recursive: true });
  }
  fs.copyFileSync(
    path.join(repo, "config", "settings.example.json"),
    path.join(dataOut, "config", "settings.example.json"),
  );

  const publicSkills = path.join(repo, "skills", "public");
  if (fs.existsSync(publicSkills)) {
    console.log("copy skills/public → RealAiData");
    copyDirFiltered(publicSkills, path.join(dataOut, "skills", "public"));
  }

  writeStartScripts();

  const vueDist = path.join(appOut, "apps", "web", "dist", "index.html");
  const electronCli = path.join(appOut, "apps", "desktop", "node_modules", "electron", "cli.js");
  const py = path.join(appOut, "runtime", "venv", "Scripts", "python.exe");
  const node = path.join(appOut, "runtime", "node", "node.exe");

  const checks = [
    ["Vue dist", vueDist],
    ["Electron", electronCli],
    ["Python venv", py],
    ["Node runtime", node],
    ["Start script", path.join(appOut, "Start-RealAi.cmd")],
  ];
  let ok = true;
  for (const [label, p] of checks) {
    if (fs.existsSync(p)) {
      console.log("✓", label);
    } else {
      console.error("✗ missing", label, "→", p);
      ok = false;
    }
  }
  if (!ok) process.exit(1);

  console.log("\nDone.");
  console.log("  App:", appOut);
  console.log("  Data template:", dataOut);
  console.log("  启动: 双击 dist/RealAi/Start-RealAi.cmd");
  console.log("  换机: 拷贝整个 dist 下的 RealAi + RealAiData 两个文件夹");
}

main();
