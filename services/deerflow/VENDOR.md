# DeerFlow Vendoring 记录（RealAi P0）

## 来源

| 项 | 值 |
|----|----|
| 上游仓库 | https://github.com/bytedance/deer-flow |
| 分支 | `main` |
| Commit | `7df44f586cd5fbbb8200849cf480a047422b4515` |
| 落盘时间 | 2026-07-16 |
| 落盘路径 | `services/deerflow/`（已移除嵌套 `.git`，整份 vendoring） |
| LICENSE | 已保留本目录 `LICENSE`（MIT） |

## DeerFlow 能力核验清单（P0）

| 能力 | 状态 | 说明 |
|------|------|------|
| 前端可构建 + 本地加载 | **已确认** | `pnpm build` + Electron `next start` |
| 后端可内嵌拉起（无 Docker） | **已确认** | `uv run uvicorn` + `scripts/start-backend.js`；`/api/models` 200 |
| 国内 LLM 接入 | **已确认** | `minimax-m3` 已写入 `config.yaml` |
| 对话 / Agent 主链路 | **已确认** | MiniMax Key 实测对话成功 |
| 浏览 / 联网 | **已确认（P1a）** | `web_search_enabled` 过滤 `web` tool group |
| 知识库 / 文件检索 | **已确认（P1a 桩）** | `realai` Vault 检索 + `kb:` 证据 |
| 上传 / 文档解析 | **已确认（P1a）** | `/api/realai/vault/import` 写 Vault |
| Skill / 插件机制 | 已确认 | 上游含 `skills/` 与 Gateway `/api/skills`；P3 做产品化导入。 |
| 多 Agent / 子任务 | 已确认 | Lead Agent + subagents；报告路径 P1b 编排。 |
| 视觉 / 多模态 | **已确认** | MiniMax M3 `image_url`；`search.visionMode`；导入预识图 + 问答再读；证据 `viz:` |

**结论：** P0 已验收；P1a/P1b 骨架已开工（RealAi API + UI 触点 + 示例资料）。

## RealAi 定制入口（勿散落）

- 配置桥：`apps/desktop` 设置页 → `config/settings.json` → 同步到本目录 `config.yaml` + `.env`
- 进程编排：`apps/desktop/electron` 拉起 backend / frontend
- 产品 UI 二开：优先改 `frontend/`，设置页可先用 RealAi renderer
