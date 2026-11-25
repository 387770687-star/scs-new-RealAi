"""Tests for realai.llm.sanitize and strategic main-line normalization."""

from __future__ import annotations

from realai.llm.sanitize import finalize_llm_text
from realai.report.strategic_pipeline import _normalize_strategic_main_line


def test_finalize_strips_think_into_reasoning() -> None:
    visible, reasoning = finalize_llm_text(
        "<think>secret plan</think>以能源安全为统领，以高质量发展为主线。",
        None,
    )
    assert "think" not in visible.lower()
    assert "能源安全" in visible
    assert reasoning and "secret plan" in reasoning


def test_finalize_unclosed_think_dropped() -> None:
    visible, reasoning = finalize_llm_text(
        "<think>The user wants me to write a long analysis without finishing",
        None,
    )
    assert visible == ""
    assert reasoning and "The user wants" in reasoning


def test_normalize_main_line_rejects_english_dump() -> None:
    junk = (
        "<think>The user wants me to write the strategic main line for a 2026 "
        "strategic planning report. Let me analyze the inputs carefully.</think>"
    )
    out = _normalize_strategic_main_line(junk, "2026年战略规划")
    assert "The user" not in out
    assert "主线" in out
    assert "2026年战略规划" in out


def test_normalize_main_line_keeps_chinese_paragraph() -> None:
    good = (
        "以服务国家能源安全为统领，以全国一张网高质量运行为主线，"
        "以互联互通和储运调峰为重点，统筹改革发展，推动高质量发展。"
    )
    assert _normalize_strategic_main_line(good, "测试") == good
