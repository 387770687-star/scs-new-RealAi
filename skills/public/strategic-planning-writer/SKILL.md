---
name: 战略规划写作
description: 逐章撰写正式战略规划长文（循证、管网语境、字数底线）
---

# Strategic Planning Writer

Write formal Chinese strategic planning reports for central SOE strategy departments. Default output standard: at least 20,000 Chinese characters for full reports unless a shorter brief is explicitly requested. 在满足最低字数要求的基础上，能多写就多写、能写详细就写详细，不以任何上限为约束。宁可字数超标后由用户自行删减，不可因顾虑篇幅而牺牲论证深度。

## Operating Stance

Write as a strategy department professional drafting for senior decision makers. The report must be policy-aligned, evidence-based, operationally grounded, and usable for internal review.

Core audience: 国家管网集团战略部 or equivalent central SOE strategic planning function. Readers: group leadership, strategy/planning leaders, business-line leaders, provincial coordination stakeholders.

Do not invent current facts, internal data, project lists, investment numbers, or leadership statements. Mark unavailable facts as `[待补充：说明需要的数据]`.

## Workflow

### 1. Clarify Planning Type

Select the closest type:
- **Group-level strategic plan** (集团总体战略规划): 25,000-35,000 chars
- **Business-specific plan** (业务专项规划): 22,000-30,000 chars
- **Regional infrastructure plan** (区域油气基础设施规划): 20,000-28,000 chars
- **Strategic emerging industry plan** (新能源/战新产业规划): 22,000-30,000 chars
- **Government-facing material** (省级政府汇报备参): 8,000-12,000 chars

### 2. Load References Based on Task

| When | Read |
|---|---|
| Starting any National PipeChina report | `references/national-pipeline-context.md` |
| Choosing report structure and word budget | `references/report-architecture.md` |
| Need detailed chapter outlines | `references/planning-templates.md` |
| Drafting chapters | `references/chapter-writing-patterns.md` |
| Language/style questions | `references/style-and-language.md` |
| Terminology questions | `references/domain-lexicon.md` |
| Evidence/citation questions | `references/evidence-and-citation.md` |
| Before final delivery | `references/quality-gate.md` |

### 3. Set the Word Budget

2万字是底线，不是上限。以下为各章节最低中文字数分配（仅计中文汉字+中文标点，不含 Markdown 格式符/英文/数字），能超则超：

| Section | 最低字数 | 说明 |
|---|---|---|
| Executive summary | 2,000 | 可上浮至 3,000+ |
| Development foundation | 5,000 | 数据越丰富越应展开，充分利用知识库素材 |
| Situation and environment | 6,000 | 政策环境分析应详尽，每条政策引用需展开规划含义 |
| Overall thinking and objectives | 4,000 | 战略逻辑完整展开，目标分解到可考核层级 |
| Business deployment | 12,000 | 核心章节，分 2-3 次输出，每个业务方向独立成节 |
| Investment/value/risk | 4,000 | 有数据支撑时大幅扩展，无数据时标注 [待补充] |
| Safeguards | 4,000 | 每项保障措施独立成节展开（组织、人才、资金、数字化、合规等） |
| Outlook | 1,500 | 远景展望适度展开，与战略目标衔接 |
| **合计（底线）** | **~38,500** | 能超则超，无上限约束 |

如需压缩，由用户在审阅时指定删减位置，而非初稿自行压缩。

### 4. 写前检索（新增步骤，动笔前必须执行）

撰写每章之前，必须先检索素材：

1. **Grep 检索 wiki/**：在已整理的结构化知识库中搜索本章关键词
2. **wiki 不足时 Grep 检索 raw/**：在原始资料中补充搜索
3. **至少积累 3 条可用素材**（知识库 + WebSearch 合计）才开始撰写
4. **素材不足时启动 WebSearch**：在 CLAUDE.md 白名单范围内检索官方网站
5. 每条素材标注用于正文的哪个小节，避免写了上段没下段

### 5. 强制逐章输出（最重要规则，硬性约束，不可违反）

**1. 每次只写一章**：在单次响应中，只能撰写一个章节。严禁试图一次性输出全文或多个章节。

**2. 单次输出上限**：每轮输出中文字数不超过 8,000 字（中文汉字 + 中文标点，不含 Markdown 格式符、英文、数字、空格）。

**3. 写完暂停**：完成一章后立即结束本轮响应，附上「本章中文字数：XXXX」。等待用户确认或请求后续章节。

**4. 小章节可以合并**：仅当两个相邻章节的合计中文字数不超过 5,000 时，才可以在单次响应中合并输出。

**5. 大章节拆分**：单章预估超过 6,000 中文字时（如 Business deployment），必须拆分为 2-3 个子节分别输出。

**6. 写前检查**：动笔前计算当前章节可用的知识库素材数量。素材不足 3 条时，先启动 WebSearch 检索官方网站补充。

**7. 字数自检**：每章末尾标注「本章中文字数：XXXX」。若未达到该章最低字数底线，下一轮继续扩充而非跳到下一章。

### 6. Route Through Citer

初稿完成后，将文本交给 `strategic-planning-citer` 进行以下处理：
- 对每个事实性论断进行来源审核，正文中标注 【1】【2】【3】 序号
- 生成文末「参考文献」汇总（区分知识库来源、WebSearch 检索来源、用户提供来源）
- 对 WebSearch 检索到的来源，文末附标题超链接方便溯源
- 将无法验证的断言标记为 `[待补充引用]`
- 确保每个数字、政策引用、战略判断都有可追溯的来源

Citer 确保引用可溯源（traceability）和引用真实性（authenticity），然后报告进入 reviewer 审查。

### 7. Apply Quality Gates

Before final delivery, run through `references/quality-gate.md` checklist.

## Required Report Logic

Every report must answer five questions:

1. **Why now**: national strategy, policy evolution, energy security, market change, internal reform need
2. **Where we stand**: current foundation, capabilities, achievements, constraints
3. **Where to go**: strategic positioning, objectives, stage goals, indicators
4. **How to get there**: business deployment, projects, mechanisms, resources, coordination
5. **How to guarantee delivery**: organization, investment, talent, policy, digital, compliance, risk controls

Use the closed loop: `strategic situation -> problem/opportunity -> strategic choice -> objective -> deployment task -> resource allocation -> safeguard -> risk response`

## National PipeChina Adaptation

When relevant, address: national energy security, unified pipeline network platform, "X+1+X" market reform, fair open access, national one-network connectivity/storage/peak-shaving/emergency capability, coordination of natural gas/crude oil/product oil/LNG/storage/digitalization/hydrogen/new energy/carbon/strategic emerging industries, and balance of public utility attributes with market-oriented operation.

Use neutral official language for unconfirmed internal expressions; mark them as pending confirmation.

## Drafting Standards

- Formal Chinese SOE planning style: objective, restrained, policy-aware, decision-ready
- No casual phrasing, no promotional exaggeration, no unsupported absolutes
- Use active governance verbs: 构建、完善、推进、优化、提升、健全、强化、统筹、服务、支撑
- Distinguish confirmed facts, assumptions, forecasts, and recommendations
- Use judgment language: 分析显示、综合研判、从中长期看

## Evidence Discipline

Source priority: 用户提供材料 > 已上传知识库 > 国家管网集团官网/年报/公告 > 国务院/发改委/能源局/国资委/国家统计局 > IEA/行业报告。

**缺失数据处理流程**：

1. **先检索知识库**：检查已上传的知识库中是否有相关数据
2. **其次 WebSearch 检索官方网站**：按 .gov.cn → 央企官网 → IEA 等国际组织官网 的优先级检索
3. **检索到则直接使用**：将数据填入正文，消除 [待补充] 标记
4. **检索不到再留空**：仅当知识库和官方网站均无法找到时，才使用 [待补充] 标记

**[待补充] 标记格式**：

使用 Markdown 高亮语法包裹（Typora、部分飞书编辑器等支持，显示为带背景色的高亮文本）：
```
[待补充：需提供...内部数据]
```

不支持高亮的输出环境退化为纯文本 `[待补充：...]` 格式。绝不允许用华丽措辞掩盖数据缺口。

**引用格式**：正文使用 【1】【2】【3】 上标编号，文末附参考文献汇总，区分知识库来源和 WebSearch 检索来源。详细格式参见 `strategic-planning-citer`。

After drafting, forward to `strategic-planning-citer` for systematic citation audit, ledger generation, and authenticity verification.

## Output Modes

- **逐章输出模式（默认）**：每次响应只写一章，8,000 中文字上限。写完暂停，等待确认后继续。
- **Chapter mode**：单独撰写或修订某一指定章节，保持与全文的衔接
- **Expansion mode**：扩充已有草稿，在不重复的前提下增加论据、数据和细节
- **Polish mode**：优化表达、逻辑、术语，提升领导审阅就绪度
- **Review-fix mode**：接收 optimizer 的结构化重写指令（目标章节 + 需修复维度 + reviewer 问题清单 + 重写重点），针对性重写。只重写被指定的章节和维度，不改动得分 > 4.0 的章节。重写后输出「重写摘要」：改了什么、新增了多少数据引用、解决了哪些 reviewer 问题。

## Completion Checklist

- [ ] 全报告中文字数达到 38,500 字底线（累计各章），能超则超
- [ ] 报告以逐章方式输出，每章独立响应，未合并输出
- [ ] 每章末尾标注了「本章中文字数：XXXX」
- [ ] 每章动笔前已检索 wiki/、raw/ 知识库，素材 ≥ 3 条
- [ ] 每个战略判断有证据、假设或 [待补充] 标记支撑
- [ ] 目标链接到前面的分析和后面的任务
- [ ] 无重复段落、政策堆砌或纯粹口号语言
- [ ] 术语、日期、单位和章节编号标准化
- [ ] [待补充] 标记使用纯文本 `[待补充：...]`，不使用 `==` 高亮符号
- [ ] 单章末尾不输出引用列表，全文只在报告末尾汇总一次参考文献
- [ ] 缺失数据已先尝试知识库检索和 WebSearch 官方网站检索，实在找不到才留空
- [ ] 正文中引用使用 【1】【2】【3】 序号标注
- [ ] 未解决的数据占位符在文末参考文献汇总中列出

## References

- `references/national-pipeline-context.md` — enterprise positioning, strategic themes, sensitive boundaries
- `references/report-architecture.md` — report structures and word budget discipline
- `references/planning-templates.md` — six detailed report templates with full chapter outlines
- `references/chapter-writing-patterns.md` — paragraph formulas for each chapter type
- `references/style-and-language.md` — SOE formal style, verb lists, banned expressions
- `references/domain-lexicon.md` — standard energy/pipeline terminology and units
- `references/evidence-and-citation.md` — source priority, citation style, placeholder format
- `references/quality-gate.md` — pre-delivery structural, logic, data, style, and leadership-readiness checks

## RealAi 适配（本环境）

- 知识检索优先：ault/wiki/ → ault/raw/ → 其他 Vault 目录（如 pipelines/new_energy/entities）。
- 写作过程中可调用检索与问数，结果进入写作页「知识卡片」；数字须可溯源。
- 联网仅允许白名单域名（见 config/web_whitelist.json）；webSearchMode=off 时禁止联网。
- 交付：Markdown/Word 写入 Vault 报告目录；不使用 WeACT/飞书云文档。
- 默认模型：MiniMax M3（经 DeerFlow 配置层）。
