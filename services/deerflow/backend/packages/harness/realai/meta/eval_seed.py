"""Built-in golden evaluation suites (light + report skeleton)."""

from __future__ import annotations

from typing import Any

SEED_LIGHT_SUITE_ID = "suite-seed-light-golden"
SEED_REPORT_SUITE_ID = "suite-seed-report-golden"

SEED_LIGHT_NAME = "示例·轻量问答黄金集"
SEED_REPORT_NAME = "示例·报告写作黄金集"


def light_seed_cases() -> list[dict[str, Any]]:
    """~30 categorized cases aligned with PRD §20.3 + README golden questions."""
    data_cases: list[dict[str, Any]] = [
        {
            "question": "中卫压气站",
            "expect_keywords": ["中卫"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["data"],
            "expect_min_rows": 1,
            "intent": "data",
            "category": "data",
            "notes": "实体名片+问数行",
        },
        {
            "question": "济南西分输清管站",
            "expect_keywords": ["济南"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["data"],
            "category": "data",
            "intent": "data",
        },
        {
            "question": "泰安压气站有哪些管段",
            "expect_keywords": ["泰安"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["data"],
            "category": "data",
            "intent": "data",
        },
        {
            "question": "列出管径(mm)1422.0 设计压力10.0 管段长度大于80Km 的所有管段",
            "expect_keywords": [],
            "expect_evidence": False,
            "expect_min_rows": 0,
            "intent": "data",
            "category": "data",
            "notes": "筛选类；评测自动确认；无命中也算流程通过（不强制行数）",
        },
        {
            "question": "2024年智能调度+数字化巡检的综合运营成本是多少",
            "expect_keywords": ["成本", "10500"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["data"],
            "expect_number": 10500,
            "expect_unit": "万元",
            "number_tolerance": 0,
            "expect_table": {
                "columns": ["年份", "项目", "综合运营成本_万元"],
                "rows": [
                    {
                        "年份": 2024,
                        "项目": "智能调度+数字化巡检",
                        "综合运营成本_万元": 10500,
                    }
                ],
            },
            "expect_source_paths": ["dataqa/2024成本表"],
            "category": "data",
            "intent": "data",
            "tags": ["excel", "精确问数", "成本"],
            "difficulty": "easy",
        },
        {
            "question": "管径 1422 的管段",
            "expect_keywords": ["1422"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["data"],
            "category": "data",
            "intent": "data",
        },
        {
            "question": "设计压力 10 的管段有哪些",
            "expect_keywords": ["压力"],
            "expect_evidence": True,
            "category": "data",
            "intent": "data",
        },
        {
            "question": "中俄东线南段有哪些站点",
            "expect_keywords": ["中俄"],
            "expect_evidence": True,
            "category": "data",
            "intent": "ask",
        },
        {
            "question": "统计管段长度大于 50 的记录",
            "expect_keywords": [],
            "expect_evidence": False,
            "category": "data",
            "intent": "data",
        },
        {
            "question": "四线中段相关管段",
            "expect_keywords": ["四线"],
            "expect_evidence": True,
            "category": "data",
            "intent": "data",
        },
    ]

    retrieve_cases: list[dict[str, Any]] = [
        {
            "question": "2024 技术策略与成本",
            "expect_keywords": ["成本"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["kb"],
            "category": "retrieve",
            "intent": "research",
        },
        {
            "question": "介绍一下知识库里的示例文档",
            "expect_keywords": [],
            "expect_evidence": True,
            "category": "retrieve",
            "intent": "research",
        },
        {
            "question": "管道工程建设相关说明",
            "expect_keywords": [],
            "expect_evidence": True,
            "category": "retrieve",
            "intent": "research",
        },
        {
            "question": "查找成本表相关说明",
            "expect_keywords": ["成本"],
            "expect_evidence": True,
            "category": "retrieve",
            "intent": "research",
        },
        {
            "question": "Vault 里有哪些示例材料",
            "expect_keywords": [],
            "expect_evidence": True,
            "category": "retrieve",
            "intent": "ask",
        },
        {
            "question": "技术策略要点是什么",
            "expect_keywords": ["策略"],
            "expect_evidence": True,
            "category": "retrieve",
            "intent": "research",
        },
        {
            "question": "检索与压气站相关的文档",
            "expect_keywords": ["压气"],
            "expect_evidence": True,
            "category": "retrieve",
            "intent": "research",
        },
        {
            "question": "新能源相关知识有哪些",
            "expect_keywords": [],
            "expect_evidence": False,
            "category": "retrieve",
            "intent": "research",
            "notes": "库中可能无命中；不强制证据",
        },
    ]

    viz_cases: list[dict[str, Any]] = [
        {
            "question": "这张示意图说明了什么？请概括图意",
            "expect_keywords": [],
            "expect_evidence": True,
            "expect_evidence_kinds": ["viz"],
            "skip_if": "no_vision",
            "category": "viz",
            "intent": "ask",
            "notes": "多模态识图；Vault 无图时跳过；有图须产出 viz: 证据",
        },
        {
            "question": "看图读出可读数字",
            "expect_keywords": [],
            "expect_evidence": True,
            "expect_evidence_kinds": ["viz"],
            "skip_if": "no_vision",
            "category": "viz",
            "intent": "ask",
        },
        {
            "question": "画一下管径分布图",
            "expect_keywords": [],
            "expect_evidence": False,
            "expect_evidence_kinds": ["viz"],
            "skip_if": "no_vision",
            "category": "viz",
            "intent": "data",
            "notes": "问数图表；无表数据时可能跳过",
        },
        {
            "question": "用图表展示各管段长度",
            "expect_keywords": [],
            "expect_evidence": False,
            "expect_evidence_kinds": ["viz"],
            "skip_if": "no_vision",
            "category": "viz",
            "intent": "data",
        },
        {
            "question": "生成成本对比柱状图",
            "expect_keywords": ["成本"],
            "expect_evidence": False,
            "expect_evidence_kinds": ["viz"],
            "skip_if": "no_vision",
            "category": "viz",
            "intent": "data",
        },
    ]

    mixed_cases: list[dict[str, Any]] = [
        {
            "question": "介绍一下 济南西分输清管站_泰安压气站",
            "expect_keywords": ["济南"],
            "expect_evidence": True,
            "category": "mixed",
            "intent": "ask",
            "notes": "管段介绍 Skill",
        },
        {
            "question": "中卫压气站的管段参数和相关文档",
            "expect_keywords": ["中卫"],
            "expect_evidence": True,
            "expect_evidence_kinds": ["data"],
            "category": "mixed",
            "intent": "ask",
        },
        {
            "question": "结合成本表说明 2024 技术策略",
            "expect_keywords": ["成本"],
            "expect_evidence": True,
            "category": "mixed",
            "intent": "ask",
        },
        {
            "question": "泰安压气站概况及数据",
            "expect_keywords": ["泰安"],
            "expect_evidence": True,
            "category": "mixed",
            "intent": "ask",
        },
        {
            "question": "中俄东线南段有哪些关键站场，并给出数据依据",
            "expect_keywords": ["中俄"],
            "expect_evidence": True,
            "category": "mixed",
            "intent": "ask",
        },
        {
            "question": "管径 1422 管段的工程意义是什么",
            "expect_keywords": ["1422"],
            "expect_evidence": True,
            "category": "mixed",
            "intent": "ask",
        },
        {
            "question": "汇总知识库与表格中关于压气站的信息",
            "expect_keywords": ["压气"],
            "expect_evidence": True,
            "category": "mixed",
            "intent": "ask",
        },
    ]

    out: list[dict[str, Any]] = []
    for c in data_cases + retrieve_cases + viz_cases + mixed_cases:
        c.setdefault("mode", "light")
        c.setdefault("expect_evidence", True)
        c.setdefault("expect_keywords", [])
        out.append(c)
    return out


def report_seed_cases() -> list[dict[str, Any]]:
    return [
        {
            "question": "撰写管网工程建设简要规划报告大纲与核心发现",
            "expect_keywords": [],
            "expect_evidence": True,
            "expect_skill_valid": True,
            "mode": "report",
            "category": "report",
            "intent": "ask",
            "rubric": {
                "required_sections": ["规划", "核心发现"],
                "min_chars": 800,
                "min_citation_coverage": 0.3,
                "review_min_score": 60,
            },
            "tags": ["报告", "规划"],
            "notes": "报告路径；检查引用覆盖与证据审核",
        },
        {
            "question": "针对中卫压气站相关数据做专题研判汇报材料",
            "expect_keywords": ["中卫"],
            "expect_evidence": True,
            "mode": "report",
            "category": "report",
            "intent": "ask",
            "rubric": {
                "required_sections": ["中卫", "数据", "研判"],
                "min_chars": 800,
                "min_citation_coverage": 0.3,
                "review_min_score": 60,
            },
            "tags": ["报告", "专题研判"],
        },
    ]
