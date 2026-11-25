"""Regression tests for the bounded intelligent-gap intake."""

from __future__ import annotations

from realai.report.intake import (
    _can_build_questions_locally,
    _fallback_questions_for_fields,
)


def test_standard_time_and_scope_gaps_are_generated_without_model_wait() -> None:
    fields = ["time_scope", "scope"]

    assert _can_build_questions_locally(fields) is True
    questions = _fallback_questions_for_fields(
        "国家管网集团未来产业发展行动方案",
        "董事会",
        fields,
    )
    assert [question["field"] for question in questions] == fields
    assert "规划期" in questions[0]["prompt"]
    assert "地理区域" in questions[1]["prompt"]


def test_ambiguous_objective_gap_keeps_bounded_model_path() -> None:
    assert _can_build_questions_locally(["objective"]) is False
