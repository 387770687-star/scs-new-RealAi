# scs-new-RealAi

## 项目入口

- `apps/web/`：Vue 工作台、知识库、Wiki 图谱、战略写作和设置。
- `apps/desktop/`：Electron 桌面壳。
- `services/deerflow/`：完整保留的 DeerFlow 与 RealAi 后端；修改其模块时读取对应 AGENTS.md。
- `skills/` 与 `pack-assets/demo-vault/`：业务技能与演示资料。

## Mac 交付

- `./Start-RealAi-Web.command` 安装依赖并启动浏览器版。
- `./Start-RealAi-Dev.command` 启动 Electron 桌面版。
- `--setup-only` 仅安装。Python 依赖从 `uv.lock` 导出，保持锁定版本。
- `scripts/ensure-config.js` 为首次启动创建配置，保留已有配置值。
- `config/ports.json` 是端口来源，默认后端 8401、前端 8402。
- API Key、用户知识库、会话数据库和缓存在本机保存。

## 验证

```bash
node --test tests/setup.test.js
npm --prefix apps/web run build
```

启动器改动应在独立目录和独立端口验证首次启动及停止流程。保留上游 LICENSE 与 VENDOR.md；同步更新 README 和启动说明。
