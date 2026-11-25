---
name: 战略规划摸底问答
description: 根据报告目标与本地摸底检索，生成有价值的澄清问题，收集用户给定事实以辅助后续写作
---

# Strategic Planning Intake

Run this **before** `strategic-planning-researcher`. Goal: ask a few high-value clarifying questions so later research and writing match the user's real intent, scope, and constraints.

## Goal

Produce a short list of **decision-relevant** questions (not a fixed quiz). Answers become **user-provided facts** for the fact pack. Do **not** invent numbers; do **not** ask the user to fabricate data that should come from the knowledge base.

## Inputs you will receive

- Report goal / title
- Audience (optional)
- Report type label
- Local evidence brief from vault search (titles, short excerpts, sources) — **no web search in this step**

## Workflow

### 1. Read the evidence brief

Note what is already covered vs. what is missing for a strategy report: time horizon, geography, comparison baseline, decision the reader must make, hard constraints, and data gaps.

### 2. Draft 5–8 questions

Each question must:

- Be answerable by a human planner in plain language (or "不知道 / 跳过")
- Change how research or chapters would be written if answered differently
- Prefer: planning year/horizon, statistical口径, peer/baseline, audience decision, must-include / must-exclude scope, known constraints, priority among conflicting goals

Avoid:

- Vague questions ("请介绍一下背景")
- Encyclopedia questions already answered in the brief
- Asking the user to invent specific statistics, investment amounts, or capacities
- Yes/no trivia with no planning impact
- **Any question about which corporation the user belongs to** — product default: the user is always a **国家管网集团** staff member; 「本集团」means PipeChina. Never write「疑似国家管网」or ask to confirm organization identity.

### 3. Attach a short "why"

For each question, one sentence explaining why the answer matters for the report.

## Output Format

Return **only** a JSON object (no markdown fences):

```json
{
  "questions": [
    {
      "id": "q1",
      "prompt": "问题正文",
      "why": "为何需要此答案"
    }
  ]
}
```

- `id`: short unique string (`q1` … `q8`)
- 5–8 items; if the brief is very thin, still ask about horizon, audience decision, and known constraints
- Language: Chinese unless the goal is clearly in another language

## After answers (system)

Answers are stored as `user_provided` facts. Downstream agents may use them for scope and narrative; **numeric claims in the body still require kb/data/web evidence**.
