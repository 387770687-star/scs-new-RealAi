# RealAi P0 本地开发启动（Windows，无 Docker）

## 前置（一次性）

```powershell
# 建议镜像（国内网络）
$env:UV_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
$env:Path = "D:\nvm\v22.3.0;$env:USERPROFILE\.local\bin;$env:Path"

cd services\deerflow\backend
uv sync --python 3.12

cd ..\..\apps\desktop
pnpm install
```

## 启动

**终端 1 — Gateway（默认端口 `8401`，见 `config/ports.json`）**

```powershell
node scripts/start-backend.js
```

**终端 2 — 桌面**

```powershell
cd apps\desktop
pnpm start
```

在应用里填写 MiniMax API Key → 保存 → 发送测试消息。

## 说明

- 个人本地模式启用 `DEER_FLOW_AUTH_DISABLED=1`（仅本机，勿用于生产）。
- DeerFlow 前端未构建时，Electron 会回退到 `loadFile` 设置/通聊页。
- 密钥写入 `config/settings.json` 与 `services/deerflow/.env`，均不入 git。
