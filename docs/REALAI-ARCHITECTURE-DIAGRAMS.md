# RealAi 功能架构与技术架构图

> 本文基于当前仓库源码整理，并与 FigJam 中的可编辑图保持一致。  
> 设计原则：功能图只回答“系统能做什么”，技术图只回答“系统用什么技术、怎样运行”。

## 1. 功能架构图

### 图的主旨

`管知识 → 问数据 → 做研究 → 写报告`

```mermaid
flowchart TD
    user(["国家管网战略规划人员"])

    subgraph workbenchDomain ["工作台｜研究与决策"]
        direction LR
        question["选择知识范围"] --> analysis["循证问答 · 精确问数 · 联网看图"] --> decision["结论 · 表格 · 图表 · 证据"]
    end

    subgraph writingDomain ["战略规划生成｜长报告"]
        direction LR
        goal["目标 · 读者 · 模板"] --> intake["智能补缺 · 资料研究"] --> outline["大纲生成 · 用户确认"] --> authoring["流式逐章 · 引用评审 · 自动优化"] --> delivery["在线编辑 · MD Word PDF"]
    end

    subgraph knowledgeDomain ["知识库｜知识资产运营"]
        direction LR
        ingest["文档 · 表格 · 图片导入"] --> governance["解析 · 去重 · 分类 · 质量门禁"] --> enrichment["Wiki 卡 · 实体图谱 · 指标规则"] --> catalog["七类目录 · 预览 · 健康度"]
    end

    subgraph supportLayer ["平台与可信支撑"]
        direction LR
        platform["平台治理：Skill 工坊 · 模型中心 · 系统管理"] --> trust["可信底座：统一证据 · 会话断点 · 过程审计"] --> outcomes["业务成果：研究结论 · 知识资产 · 战略报告"]
    end

    user --> question
    user --> goal
    user --> ingest
    decision --> trust
    delivery --> trust
    catalog --> trust

    style workbenchDomain fill:#C2E5FF,stroke:#3DADFF
    style writingDomain fill:#DCCCFF,stroke:#874FFF
    style knowledgeDomain fill:#C6FAF6,stroke:#5AD8CC
    style supportLayer fill:#FFECBD,stroke:#FFC943
    style outcomes fill:#CDF4D3,stroke:#66D575
```

### 三条核心用户路径

| 功能域 | 用户要完成的事 | 系统提供的能力 | 主要产出 |
|---|---|---|---|
| 工作台 | 查资料、问指标、做判断 | 知识范围、多会话、分层检索、精确问数、按需联网与看图 | 结论、表格、图表、证据 |
| 战略规划生成 | 从目标形成正式长报告 | 智能补缺、资料研究、大纲确认、逐章流式写作、引用核验、内容审校与优化 | 可编辑报告、Markdown、Word、PDF |
| 知识库 | 把分散资料变成可复用知识 | 多模态导入、解析分类、去重、质量门禁、Wiki 卡、实体图谱、指标规则 | 七类知识目录、实体关系、指标口径、报告成果 |

平台治理集中承载 Skill 工坊、模型中心和系统管理；可信底座统一承载 `kb:`、`data:`、`viz:`、`web:` 证据、永久会话、任务检查点和运行轨迹。

## 2. 技术架构图

### 图的主旨

`接入与交互 → API 与运行时 → RealAi 单体核心引擎 → 本地持久化 → 外部依赖`

```mermaid
flowchart TD
    l1["L1 接入与交互层<br/>桌面容器：Electron 35 · Embedded Node.js<br/>前端工程：Vue 3.5 · TypeScript · Vite 6<br/>交互与可视化：Naive UI · Pinia · ECharts"]
    l2["L2 API 与应用运行时层<br/>API 调用：TypeScript API Client<br/>服务接口：FastAPI · Uvicorn · REST · SSE<br/>应用运行时：Python 3.12 · DeerFlow 2.1 · RealAi 单体"]
    l3["L3 核心引擎层｜RealAi 单体边界<br/>任务编排：Light QA · 七步战略报告<br/>知识引擎：Vault 检索 · Wiki · Graph<br/>数据引擎：DuckDB 1.4 · NL2SQL · SELECT Only<br/>AI 网关：httpx · LLM Router · Vision · Search<br/>报告导出：python-docx · fpdf2 · Markdown"]
    l4["L4 本地持久化与配置层<br/>知识与报告：Obsidian Vault<br/>元数据与状态：SQLite · 任务 · 会话 · 图谱 · 表目录 · 日志<br/>能力与配置：Skills · JSON · YAML · ENV"]
    l5["L5 外部依赖层<br/>大模型：MiniMax · OpenAI-Compatible · Anthropic<br/>搜索：MiniMax Search API<br/>外部业务库：PostgreSQL · MySQL（只读）"]

    l1 --> l2 --> l3 --> l4 --> l5

    style l1 fill:#E6F4FF,stroke:#3DADFF
    style l2 fill:#E6FAF8,stroke:#5AD8CC
    style l3 fill:#F0E9FF,stroke:#874FFF
    style l4 fill:#EAF8EC,stroke:#66D575
    style l5 fill:#F2F2F2,stroke:#B3B3B3
```

### 技术分层说明

| 层 | 核心技术 | 职责 |
|---|---|---|
| 桌面与前端 | Electron 35、Vue 3.5、TypeScript、Vite 6、Naive UI、Pinia、ECharts | 桌面承载、页面交互、状态管理、表图展示 |
| 接口与运行时 | TypeScript API Client、FastAPI、Uvicorn、REST、SSE、Python 3.12 | API 接入、流式输出、后台任务、单体应用运行 |
| 核心引擎 | DeerFlow 2.1、RealAi、DuckDB、NL2SQL、httpx、LLM Router、python-docx、fpdf2 | 双路径编排、检索、问数、模型调用、联网看图、报告导出 |
| 本地数据 | Obsidian Vault、SQLite、Skill 包、JSON/YAML/ENV | 知识真相源、任务和会话持久化、图谱与表目录索引、运行配置 |
| 外部服务 | MiniMax、OpenAI 兼容接口、Anthropic、MiniMax Search、PostgreSQL/MySQL | 模型推理、视觉识别、网页搜索和可选只读数据源 |

### 关键技术边界

- 后端是 `Python + FastAPI + DeerFlow` 单进程单体，图中的引擎是进程内逻辑模块，不是微服务。
- Electron 负责内嵌运行时、进程拉起、健康检查和退出回收；最终用户主路径不依赖 Docker。
- Vault 是知识与报告的真相源；SQLite 保存任务、会话、检查点、表目录、图谱索引和调用记录。
- DuckDB 在进程内只读扫描 CSV/Excel，并限制为 `SELECT`。
- 模型客户端支持 OpenAI 兼容协议与 Anthropic 协议，并按主、高速、视觉、备用角色路由。
- 主前端是 Vue；封存的 React 旧界面不属于主业务链路，因此不放入主图。

## 3. 源码落位

| 架构区域 | 主要代码位置 |
|---|---|
| Vue 页面与路由 | `apps/web/src/views/`、`apps/web/src/router/index.ts` |
| 前端 API 与状态 | `apps/web/src/api/realai.ts`、`apps/web/src/stores/` |
| Electron 编排 | `apps/desktop/electron/main.js`、`apps/desktop/electron/process-manager.js` |
| FastAPI 接口 | `services/deerflow/backend/app/gateway/routers/realai*.py` |
| 轻量问答 | `services/deerflow/backend/packages/harness/realai/agents/light_qa.py` |
| 报告流水线 | `services/deerflow/backend/packages/harness/realai/report/strategic_pipeline.py` |
| 问数引擎 | `services/deerflow/backend/packages/harness/realai/data/` |
| Vault 与 Wiki | `services/deerflow/backend/packages/harness/realai/vault/` |
| 元数据 | `services/deerflow/backend/packages/harness/realai/meta/` |
| 模型路由 | `services/deerflow/backend/packages/harness/realai/llm/client.py` |
| Skill 包 | `skills/public/`、`skills/custom/` |
