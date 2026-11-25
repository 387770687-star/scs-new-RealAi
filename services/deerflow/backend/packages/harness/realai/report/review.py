"""P2: pipeline domain review (oil/gas pipeline engineering)."""

from __future__ import annotations

from realai.report.blocks import ReportBlock

PIPELINE_KEYWORDS = ("管道", "管网", "油气", "输量", "站场", "焊接", "试压", "开工")


def review_with_pipeline_rules(
    goal: str,
    blocks: list[ReportBlock],
    *,
    review_skill_hint: str = "",
) -> dict:
    score = 70
    suggestions: list[str] = []
    is_pipeline = any(k in goal for k in PIPELINE_KEYWORDS)

    headings = [b.heading for b in blocks]
    required = ["背景", "发现", "建议"]
    for req in required:
        if not any(req in h for h in headings):
            suggestions.append(f"建议包含「{req}」相关章节，贴合工程建设报告结构。")
            score -= 5

    for block in blocks:
        if not block.evidence_ids and block.heading and "发现" in block.heading:
            suggestions.append(f"「{block.heading}」建议绑定 kb:/data: 证据 ID。")
            score -= 3

    if is_pipeline:
        suggestions.append("管网适配：请核对术语（站场/线路/焊接/试压）与工程进展描述是否完整。")
        score += 10
    else:
        suggestions.append("未检测到管网主题关键词；通用报告评审已应用。")

    if review_skill_hint:
        suggestions.append(f"评审 Skill 指引：{review_skill_hint[:280]}")

    score = max(0, min(100, score))
    return {"score": score, "suggestions": suggestions, "pipeline_adapted": is_pipeline}
