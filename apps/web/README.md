# RealAi Vue 主前端

Vue 3 + Vite + TypeScript + Naive UI + Pinia + Vue Router。

## 开发

```bash
# 仓库根目录
npm run web:install
npm run backend:start   # 另开终端，或用 Start-RealAi-Dev.bat
npm run web:dev         # http://127.0.0.1:8402
```

`/api` 由 Vite 代理到 Gateway `:8401`。

## 构建

```bash
npm run web:build
```

产物在 `apps/web/dist/`。Electron 生产模式用 `vite preview` 或加载 dist。

## 模块

工作台 · 知识库 · 写作任务 · Skill 工坊 · 模型中心 · 评测中心 · 系统管理

无后端能力的页面使用真实空态，不填充假数据。
