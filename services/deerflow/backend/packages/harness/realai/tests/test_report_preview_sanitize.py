"""Tests for report markdown sanitize and outline chapter split."""

from __future__ import annotations

import pytest
from realai.evidence.types import EvidencePack
from realai.llm.sanitize import (
    clean_report_markdown,
    is_usable_report_body,
    validate_report_revision,
)
from realai.report.strategic_pipeline import (
    _assemble_markdown,
    _fallback_report_title,
    _needs_outline_confirmation,
    _normalize_report_title,
    _parse_architecture_copy,
    _parse_custom_outline,
    _report_title_needs_generation,
    normalize_report_references,
    split_markdown_by_outline,
)


def test_clean_report_strips_think_and_meta() -> None:
    raw = "<think>The user wants me to act as a citation reviewer</think>\n\n# 2026规划\n\n## 摘要\n\n以能源安全为统领推进高质量发展。"
    out = clean_report_markdown(raw)
    assert "think" not in out.lower()
    assert "The user" not in out
    assert "摘要" in out


def test_clean_report_strips_obsidian_highlight_markers() -> None:
    out = clean_report_markdown("## 风险\n\n主要风险为==一是投资错配==；[待补充：口径]。")
    assert "==" not in out
    assert "一是投资错配" in out


def test_usable_body_rejects_english_roleplay() -> None:
    junk = "The user wants me to act as a citation reviewer for the report."
    assert not is_usable_report_body(junk, min_chinese=20, require_heading=False)


def test_revision_guard_rejects_audit_table_replacing_report() -> None:
    baseline = "# 新疆备参\n\n## 汇报摘要\n\n" + "新疆是国家重要能源战略基地，应统筹管网建设、安全保供和区域协同。" * 40 + "\n\n## 基础与成效\n\n" + "现有干线、支线和储气调峰设施共同构成区域能源输送保障体系。" * 40
    audit_table = (
        "# 新疆备参\n\n"
        "## 汇报摘要\n\n"
        "| 标注 | 被引用论断（原文节选） | 实际来源 |\n"
        "|---|---|---|\n"
        "|【1】| 推动跨部门协同 | 绿电直连通知 |\n\n"
        "> 审核意见：引用存在错配，建议删除标注。\n\n"
        "## 基础与成效\n\n"
        "| 标注 | 被引用论断（原文节选） | 实际来源 |\n"
        "|---|---|---|\n"
        "|【2】| 构建现代能源体系 | 相关政策 |\n"
    )

    accepted, reason = validate_report_revision(
        baseline,
        audit_table,
        required_headings=["汇报摘要", "基础与成效"],
        min_retention_ratio=0.8,
    )

    assert accepted is False
    assert "审计" in reason or "缩减" in reason


def test_revision_guard_accepts_complete_prose_revision() -> None:
    baseline = "# 新疆备参\n\n## 汇报摘要\n\n" + "新疆是国家重要能源战略基地，应统筹管网建设、安全保供和区域协同。" * 20 + "\n\n## 基础与成效\n\n" + "现有干线、支线和储气调峰设施共同构成区域能源输送保障体系。" * 20
    candidate = baseline.replace(
        "应统筹管网建设、安全保供和区域协同",
        "应进一步统筹管网建设、安全保供、改革发展和区域协同",
    )

    accepted, reason = validate_report_revision(
        baseline,
        candidate,
        required_headings=["汇报摘要", "基础与成效"],
        min_retention_ratio=0.8,
    )

    assert accepted is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_citer_keeps_original_when_model_returns_audit_table(monkeypatch) -> None:
    from realai.report import strategic_pipeline

    baseline = "# 新疆备参\n\n## 汇报摘要\n\n" + "新疆是国家重要能源战略基地，应统筹管网建设、安全保供和区域协同。" * 30 + "\n\n## 基础与成效\n\n" + "现有干线、支线和储气调峰设施共同构成区域能源输送保障体系。" * 30
    audit = "# 引用审核结果\n\n## 汇报摘要\n\n| 标注 | 被引用论断（原文节选） | 实际来源 |\n|---|---|---|\n" + "|【1】| 需要强化能源安全保障 | 某政策文件 |\n" * 12 + "\n## 基础与成效\n\n> 审核意见：建议逐条核对并删除错配引用。"

    async def fake_chat_turn(*_args, **_kwargs):
        return {"content": audit}

    monkeypatch.setattr(strategic_pipeline, "chat_turn", fake_chat_turn)
    polished, _ = await strategic_pipeline._run_citer(
        baseline,
        EvidencePack(),
        "strategic-planning-citer",
        required_headings=["汇报摘要", "基础与成效"],
    )

    assert "现有干线、支线和储气调峰设施" in polished
    assert "被引用论断" not in polished


def test_split_stops_before_references() -> None:
    md = "# 目标\n\n## 摘要\n\n摘要正文一二三四五六七八九十。\n\n## 发展基础\n\n基础正文一二三四五六七八九十。\n\n## 参考文献\n\n【1】来源\n"
    drafts = split_markdown_by_outline(
        md,
        [
            {"id": "exec", "heading": "摘要", "word_budget": 100},
            {"id": "foundation", "heading": "发展基础", "word_budget": 200},
        ],
    )
    assert drafts[0]["body"] == "摘要正文一二三四五六七八九十。"
    assert "参考文献" not in drafts[1]["body"]
    assert "基础正文" in drafts[1]["body"]


def test_references_are_hoisted_to_single_report_footer() -> None:
    md = "# 规划\n\n## 第一章\n\n第一章正文【1】。\n\n---\n\n**证据引用**\n\n【1】旧列表\n\n## 第二章\n\n第二章正文【2】。\n\n### 证据引用\n\n【2】旧列表\n"
    ledger = [
        {"n": 1, "id": "kb:a", "label": "【1】来源A", "source_type": "知识库", "url": ""},
        {"n": 2, "id": "web:b", "label": "【2】来源B", "source_type": "联网", "url": "https://example.com/b"},
    ]
    out = normalize_report_references(md, ledger)
    assert "证据引用" not in out
    assert out.count("## 参考文献") == 1
    assert out.index("## 参考文献") > out.index("## 第二章")
    assert "【1】来源A" in out
    assert "【2】来源B" in out


def test_custom_outline_parser_builds_no_template_outline() -> None:
    raw = """```json
    {
      "title": "人工智能时代企业管理规划",
      "strategic_main_line": "以价值创造为统领，以人机协同为主线，统筹组织、流程与能力变革，推动管理模式系统升级。",
      "sections": [
        {"id": "context", "heading": "变革背景与战略判断", "purpose": "回答为何变革", "word_budget": 2200},
        {"id": "model", "heading": "目标管理模式", "purpose": "定义目标状态", "word_budget": 3200},
        {"id": "roadmap", "heading": "实施路径与保障", "purpose": "形成落地闭环", "word_budget": 3000}
      ]
    }
    ```"""
    outline = _parse_custom_outline(raw, "企业管理变革", "regional")
    assert outline["report_type_label"] == "自定义规划"
    assert [section["heading"] for section in outline["sections"]] == [
        "变革背景与战略判断",
        "目标管理模式",
        "实施路径与保障",
    ]
    assert outline["min_chars"] == 20000


def test_no_template_requires_outline_only_confirmation() -> None:
    assert _needs_outline_confirmation(
        step_confirm=False,
        outline_confirm_required=True,
        confirmed=False,
        resume_chapter_index=None,
        resume_from=None,
    )
    assert not _needs_outline_confirmation(
        step_confirm=False,
        outline_confirm_required=True,
        confirmed=True,
        resume_chapter_index=None,
        resume_from=None,
    )


def test_report_title_is_not_the_full_user_instruction() -> None:
    goal = "根据张伟董事长的文章《以‘人才、知识、资本’三要素激发价值创造新动能》，写一篇国家管网集团贯彻文章精神的发展行动方案"
    title = _fallback_report_title(goal, "集团总体战略规划")
    assert title == "国家管网集团发展行动方案"
    assert title != goal


def test_placeholder_title_is_replaced_from_title_shaped_goal() -> None:
    goal = "国家管网集团贯彻落实重要文章精神加快培育发展未来产业行动方案"

    assert _report_title_needs_generation("自定义规划", goal)
    assert _normalize_report_title("自定义规划", goal, "自定义规划") == goal
    assert _assemble_markdown(
        goal,
        {
            "title": "自定义规划",
            "report_type_label": "自定义规划",
            "sections": [],
        },
        [],
    ).startswith(f"# {goal}")


def test_custom_outline_placeholder_requests_model_title_refinement() -> None:
    raw = """{
      "title": "自定义规划",
      "strategic_main_line": "以未来产业培育为主线，推动创新发展。",
      "sections": [
        {"id": "one", "heading": "形势研判", "purpose": "研判背景"},
        {"id": "two", "heading": "总体目标", "purpose": "明确目标"},
        {"id": "three", "heading": "重点行动", "purpose": "部署任务"}
      ]
    }"""
    goal = "国家管网集团未来产业发展行动方案"

    outline = _parse_custom_outline(raw, goal, "regional")

    assert outline["title"] == goal
    assert outline["_title_needs_generation"] is True


def test_architect_copy_parses_title_and_markdown_uses_it() -> None:
    title, main_line = _parse_architecture_copy(
        '{"title":"国家管网集团价值创造行动方案","strategic_main_line":"以价值创造为统领，以人才、知识、资本协同为主线，统筹组织与能力建设，推动高质量发展。"}',
        goal="请根据一篇文章撰写行动方案",
        report_type_label="集团总体战略规划",
    )
    assert title == "国家管网集团价值创造行动方案"
    assert "价值创造" in main_line
    markdown = _assemble_markdown(
        "请根据一篇文章撰写行动方案",
        {"title": title, "sections": []},
        [],
    )
    assert markdown.startswith("# 国家管网集团价值创造行动方案")
