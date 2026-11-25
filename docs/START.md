# 战略规划域多源多模态知识大脑 · 本地启动与打包

给「自己在电脑上跑起来 / 打成可拷贝应用」用。Windows 和 macOS 均可在项目根目录操作；便携打包交付仍以 Windows 为主。

---

## 0. 首次准备（只做一次或依赖变了再做）

需要已安装：

- **Node.js 22+**
- **Python 3.12** + [uv](https://github.com/astral-sh/uv)（后端依赖用 uv）

在项目根目录执行：

```bat
npm install
npm run web:install
npm run backend:sync
```

说明：

| 命令 | 作用 |
|------|------|
| `npm install` | 根目录 + Electron 桌面壳依赖 |
| `npm run web:install` | Vue 主前端（`apps/web`）依赖 |
| `npm run backend:sync` | DeerFlow/RealAi 后端 Python 依赖 |

配置 API Key：打开 `config/settings.json`（或启动后进应用「设置」），填入国内模型 Key（默认 MiniMax）。**不要把真实 Key 提交到 git。**

---

## 1. 改完代码后，怎样让「最新代码」生效

分三块看：

### 1.1 后端（Python / RealAi / DeerFlow）

- 开发态一般用 `npm run backend:start` 或一键脚本拉起，**改 `.py` 后通常需重启后端**才会加载新代码。
- 若新增了 Python 包：再跑一次 `npm run backend:sync`，然后重启后端。

单独重启后端：

```bat
npm run backend:start
```

默认监听：**http://127.0.0.1:8401**

### 1.2 Vue 主前端（`apps/web`）

两种用法：

| 方式 | 命令 | 最新代码何时生效 |
|------|------|------------------|
| **开发热更新（推荐日常改 UI）** | `npm run web:dev` | 保存文件后 Vite 自动刷新，一般不用手编 |
| **先编译再给 Electron 用构建产物** | `npm run web:build` | 必须重新 `web:build`，Electron `loadFile` 才会读到新界面 |

一键开发里若加了 `--build`，会在启动前自动执行一次 `web:build`：

```bat
Start-RealAi-Dev.bat --build
```

或：

```bat
npm run dev:build
```

### 1.3 Electron 桌面壳（`apps/desktop`）

- 改壳子代码（`apps/desktop/electron/*`）后，**关掉窗口再重新开桌面进程**。
- 日常只改 Vue/后端时，不必每次重装桌面依赖。

### 1.4 端口被占用时

先腾端口再启动：

```bat
Start-RealAi-Dev.bat --fresh
```

常用端口：

| 端口 | 用途 |
|------|------|
| 8401 | Gateway 后端 |
| 8402 | Vue（Vite 开发服） |
| 8400 | 封存的 DeerFlow React（可选） |

---

## 2. 本地怎么启动

### 方式 A：一键（最省事）

Windows 双击或在项目根执行：

```bat
Start-RealAi-Dev.bat
```

macOS 双击 `Start-RealAi-Dev.command`，或执行：

```bash
npm run dev:mac
```

macOS 启动器会自动识别并安装当前平台的 Web、Electron 和 Python 依赖；国内网络默认使用镜像下载 Electron 与 Python 包，可通过 `ELECTRON_MIRROR` / `REALAI_PYPI_INDEX_URL` 覆盖。浏览器版运行 `./Start-RealAi-Web.command`。首次克隆请优先阅读 [MAC_START.md](MAC_START.md)。

等价：

```bat
npm run dev
```

顺序大致是：**检查依赖 → 启后端 → 启 Vue → 打开 Electron 窗口**。  
关掉 Electron 或在该窗口按 **Ctrl+C**，会结束整套开发服务。

常用参数：

| 参数 | 说明 |
|------|------|
| `--build` | 启动前先编译 Vue（`web:build`），保证壳子加载的是最新构建产物 |
| `--install` | 强制重装 Vue 依赖 |
| `--no-electron` | 只启后端 + Vue，用浏览器打开 http://127.0.0.1:8402 |
| `--fresh` | 先释放 8400/8401/8402 |
| `--deerflow` | 额外后台启动封存的 DeerFlow React（默认不弹窗） |

示例：

```bat
Start-RealAi-Dev.bat --fresh --build
Start-RealAi-Dev.bat --no-electron
```

### 方式 B：分步启动（方便单独看日志）

开 **三个** 终端（都在项目根）：

```bat
REM 终端 1：后端
npm run backend:start

REM 终端 2：Vue 热更新
npm run web:dev

REM 终端 3：桌面窗口（可选；也可用浏览器打开 8402）
npm run desktop:dev
```

只要后端 + Vue：浏览器访问 **http://127.0.0.1:8402**（走 Vite 代理到 8401）。

### 启动后快速自检

1. 打开 http://127.0.0.1:8401/api/realai/health ，应返回 JSON（含 vault 路径等）。
2. 工作台能提问；知识库能看到 Vault 文件。
3. 无 Key 时应提示去设置，而不是静默崩溃。

### Electron 一直转圈 / 白屏

1. 看启动页文字停在哪一步（后端 / Vue / 加载主界面）。
2. 浏览器直接打开 http://127.0.0.1:8402 ：若浏览器正常、Electron 不行，多半是壳子卡在等待；关掉窗口后执行 `npm run dev -- --fresh` 再开。
3. 若 8402 打不开：先 `npm run web:install`，再 `npm run dev -- --fresh`。
4. 仍不行：用 `npm run dev -- --no-electron`，只用浏览器开发。

---

## 3. 怎么打包成可拷贝应用（便携包）

交付形态是 **便携目录**（含启动脚本），不是「先装 Docker」。用户把整个文件夹拷到别的 Windows 机器即可用。

### 3.1 打包前编译

```bat
npm run backend:sync
npm run web:build
npm run p4:pack
```

说明：

| 步骤 | 作用 |
|------|------|
| `backend:sync` | 确保后端依赖齐全（打包会带走内嵌 Python 环境） |
| `web:build` | 把 Vue 编成静态文件（相对路径，供 Electron `loadFile`） |
| `p4:pack` | 生成便携目录到 `dist/`（含 Electron、Node、Python、Vue 界面） |

若漏了 `web:build`，打包会直接失败并提示缺少 Vue dist。

### 3.2 产出目录

| 路径 | 含义 |
|------|------|
| `dist/RealAi/` | **程序包**（Electron、内嵌运行时、Vue 构建产物、DeerFlow 后端等） |
| `dist/RealAiData/` | **用户数据模板**（config / vault / skills 等） |

### 3.3 打包后怎么启动

进入 `dist/RealAi/`，双击：

```text
Start-RealAi.cmd
```

### 3.4 升级时不丢用户数据

- 升级：**只替换** `RealAi/` 程序目录。
- **保留**旁边的 `RealAiData/`（配置、知识库、会话元数据等在数据侧）。

开发机自测便携模式时，可按打包脚本提示设置 `REALAI_PORTABLE=1` 再启动（见打包结束时的控制台说明）。

### 3.5 发版前自检（建议）

- [ ] 干净 Windows：只拷贝便携夹，能启动桌面端  
- [ ] 改配置后重启仍生效  
- [ ] 整个文件夹挪到其他盘符仍能找到相对资源  
- [ ] 无 Key 时提示去设置，而不是闪退  

---

## 4. 常见问题

| 现象 | 处理 |
|------|------|
| `WinError 10048` / 端口占用 | `Start-RealAi-Dev.bat --fresh`，或手动结束占用 8401/8402 的进程 |
| 改了 Vue 界面但 Electron 里没变 | 开发请用 `web:dev`；若用构建产物，再跑 `npm run web:build` 并重启桌面 |
| 改了后端逻辑没变 | 重启 `npm run backend:start` |
| 后端起不来 / 缺模块 | `npm run backend:sync` 后重启 |
| 想只要浏览器、不要桌面窗 | `Start-RealAi-Dev.bat --no-electron` |

---

## 5. 相关文档

- 产品与功能总览：[README.md](../README.md)
- 技术细节：[TECH.md](TECH.md)
- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)
