"""Report types, word budgets, and default chapter maps for strategic writing."""

from __future__ import annotations

from typing import Any

REPORT_TYPES: dict[str, dict[str, Any]] = {
    "group": {
        "label": "集团总体战略规划",
        "min_chars": 25000,
        "sections": [
            {"id": "exec", "heading": "摘要", "word_budget": 2000},
            {"id": "foundation", "heading": "发展基础", "word_budget": 5000},
            {"id": "environment", "heading": "形势与环境", "word_budget": 6000},
            {"id": "objectives", "heading": "总体思路与目标", "word_budget": 4000},
            {"id": "deployment", "heading": "重点任务与业务部署", "word_budget": 12000},
            {"id": "investment", "heading": "投资价值与风险", "word_budget": 4000},
            {"id": "safeguards", "heading": "保障措施", "word_budget": 4000},
            {"id": "outlook", "heading": "展望", "word_budget": 1500},
        ],
    },
    "business": {
        "label": "业务专项规划",
        "min_chars": 22000,
        "sections": [
            {"id": "exec", "heading": "摘要", "word_budget": 1800},
            {"id": "foundation", "heading": "发展基础", "word_budget": 4500},
            {"id": "environment", "heading": "形势与环境", "word_budget": 5000},
            {"id": "objectives", "heading": "总体思路与目标", "word_budget": 3500},
            {"id": "deployment", "heading": "重点任务与业务部署", "word_budget": 10000},
            {"id": "investment", "heading": "投资价值与风险", "word_budget": 3500},
            {"id": "safeguards", "heading": "保障措施", "word_budget": 3500},
            {"id": "outlook", "heading": "展望", "word_budget": 1200},
        ],
    },
    "regional": {
        "label": "区域油气基础设施规划",
        "min_chars": 20000,
        "sections": [
            {"id": "exec", "heading": "摘要", "word_budget": 1600},
            {"id": "foundation", "heading": "发展基础", "word_budget": 4000},
            {"id": "environment", "heading": "形势与环境", "word_budget": 4500},
            {"id": "objectives", "heading": "总体思路与目标", "word_budget": 3200},
            {"id": "deployment", "heading": "重点任务与业务部署", "word_budget": 9000},
            {"id": "investment", "heading": "投资价值与风险", "word_budget": 3200},
            {"id": "safeguards", "heading": "保障措施", "word_budget": 3200},
            {"id": "outlook", "heading": "展望", "word_budget": 1000},
        ],
    },
    "emerging": {
        "label": "新能源/战新产业规划",
        "min_chars": 22000,
        "sections": [
            {"id": "exec", "heading": "摘要", "word_budget": 1800},
            {"id": "foundation", "heading": "发展基础", "word_budget": 4500},
            {"id": "environment", "heading": "形势与环境", "word_budget": 5000},
            {"id": "objectives", "heading": "总体思路与目标", "word_budget": 3500},
            {"id": "deployment", "heading": "重点任务与业务部署", "word_budget": 10000},
            {"id": "investment", "heading": "投资价值与风险", "word_budget": 3500},
            {"id": "safeguards", "heading": "保障措施", "word_budget": 3500},
            {"id": "outlook", "heading": "展望", "word_budget": 1200},
        ],
    },
    "gov_brief": {
        "label": "省级政府汇报备参",
        "min_chars": 8000,
        "sections": [
            {"id": "exec", "heading": "汇报摘要", "word_budget": 1200},
            {"id": "foundation", "heading": "基础与成效", "word_budget": 2000},
            {"id": "environment", "heading": "形势与诉求", "word_budget": 1800},
            {"id": "objectives", "heading": "思路与目标", "word_budget": 1500},
            {"id": "deployment", "heading": "重点工作", "word_budget": 2500},
            {"id": "safeguards", "heading": "保障与协同", "word_budget": 1000},
        ],
    },
}


def normalize_report_type(report_type: str | None) -> str:
    key = (report_type or "regional").strip().lower()
    if key in REPORT_TYPES:
        return key
    aliases = {
        "集团": "group",
        "集团总体": "group",
        "专项": "business",
        "业务": "business",
        "区域": "regional",
        "新能源": "emerging",
        "战新": "emerging",
        "备参": "gov_brief",
        "汇报": "gov_brief",
    }
    for k, v in aliases.items():
        if k in (report_type or ""):
            return v
    return "regional"


def default_outline(goal: str, report_type: str) -> dict[str, Any]:
    rt = normalize_report_type(report_type)
    meta = REPORT_TYPES[rt]
    return {
        "title": goal,
        "report_type": rt,
        "report_type_label": meta["label"],
        "min_chars": meta["min_chars"],
        "strategic_main_line": "",
        "sections": [dict(s) for s in meta["sections"]],
        "pipeline_agents": [
            "intake",
            "researcher",
            "architect",
            "writer",
            "citer",
            "reviewer",
            "optimizer",
        ],
    }
