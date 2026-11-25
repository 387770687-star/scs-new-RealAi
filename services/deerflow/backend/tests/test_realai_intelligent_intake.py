from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from realai.report import intake


def test_extract_context_and_skip_when_detailed_goal_is_sufficient():
    goal = "请以北京管道公司战略规划专家身份，编制“十五五”天然气管网发展规划，面向董事会，提出2030年输量目标，必须采用规范国企公文文风并注明引用来源。"

    context = intake._extract_local_context(goal, "")

    assert "十五五" in context["time_scope"]
    assert "2030年" in context["time_scope"]
    assert "北京" in context["regions"]
    assert "天然气" in context["business_scope"]
    assert "董事会" in context["audience"]
    assert context["hard_constraints"]
    assert intake._missing_critical_fields(goal, context) == []


def test_vague_goal_only_requests_at_most_two_critical_fields():
    goal = "写一份战略规划报告"

    context = intake._extract_local_context(goal, "")
    missing = intake._missing_critical_fields(goal, context)
    questions = intake._fallback_questions_for_fields(goal, "", missing)

    assert missing == ["time_scope", "scope"]
    assert len(questions) == 2
    assert {row["field"] for row in questions} == {"time_scope", "scope"}


def test_structured_question_parser_keeps_two_allowed_fields():
    raw = """
    {
      "questions": [
        {"id":"q1","field":"time_scope","prompt":"规划期到哪一年？","why":"统一时间口径"},
        {"id":"q2","field":"scope","prompt":"业务范围包括哪些板块？","why":"限定边界"}
      ]
    }
    """

    questions, parse_error = intake._parse_question_payload(
        raw,
        allowed_fields=["time_scope", "scope"],
    )

    assert parse_error is None
    assert len(questions) == 2
    assert [row["field"] for row in questions] == ["time_scope", "scope"]


def test_prioritized_retrieve_is_actually_limited_to_three(monkeypatch):
    rows = [
        SimpleNamespace(
            id=f"e-{idx}",
            source=f"doc-{idx}.md",
            excerpt="相关内容",
            meta={},
        )
        for idx in range(8)
    ]
    monkeypatch.setattr(
        "realai.shared_retrieve.prioritized_retrieve_quota",
        lambda *_args, **_kwargs: SimpleNamespace(items=rows),
    )

    assert len(intake._prioritized_retrieve("目标", [], limit=3)) == 3


@pytest.mark.asyncio
async def test_start_intake_skips_model_and_retrieval_when_context_is_sufficient(
    monkeypatch,
):
    task = {
        "id": "wt-auto",
        "goal": "编制北京地区“十五五”天然气管网发展规划，提出2030年输量目标。",
        "audience": "董事会",
        "scope_paths": [],
        "report_type": "regional",
        "meta": {"intake": intake.empty_intake()},
        "intake": intake.empty_intake(),
    }
    stored_intake = intake.empty_intake()

    def fake_get_task(_task_id):
        return {**task, "meta": {"intake": stored_intake}, "intake": stored_intake}

    def fake_merge_meta(_task_id, patch):
        new_intake = dict(patch["intake"])
        stored_intake.clear()
        stored_intake.update(new_intake)
        return fake_get_task(_task_id)

    monkeypatch.setattr(intake, "get_task", fake_get_task)
    monkeypatch.setattr(intake, "merge_meta", fake_merge_meta)
    monkeypatch.setattr(intake, "update_task", lambda *_args, **_kwargs: None)
    retrieve = Mock()
    monkeypatch.setattr(intake, "_prioritized_retrieve", retrieve)
    model = AsyncMock()
    monkeypatch.setattr(intake, "chat_turn", model)

    result = await intake.start_intake("wt-auto")

    assert result["intake"]["status"] == "done"
    assert result["intake"]["mode"] == "auto_skipped"
    assert result["intake"]["diagnostics"]["latest"]["model_called"] is False
    retrieve.assert_not_called()
    model.assert_not_awaited()


def test_confirm_and_skip_preserve_diagnostics(monkeypatch):
    diagnostics = {
        "latest": {"parse_error": "invalid JSON", "duration_ms": 1234},
        "attempts": [{"parse_error": "invalid JSON", "duration_ms": 1234}],
    }
    stored_intake = {
        **intake.empty_intake(),
        "status": "await_answers",
        "questions": [
            {
                "id": "q1",
                "field": "scope",
                "prompt": "范围？",
                "answer": "天然气",
                "skipped": False,
            }
        ],
        "diagnostics": diagnostics,
    }
    task = {"id": "wt-1", "meta": {"intake": stored_intake}, "intake": stored_intake}

    def fake_get_task(_task_id):
        return {**task, "meta": {"intake": stored_intake}, "intake": stored_intake}

    def fake_merge_meta(_task_id, patch):
        new_intake = dict(patch["intake"])
        stored_intake.clear()
        stored_intake.update(new_intake)
        return fake_get_task(_task_id)

    monkeypatch.setattr(intake, "get_task", fake_get_task)
    monkeypatch.setattr(intake, "merge_meta", fake_merge_meta)
    monkeypatch.setattr(intake, "update_task", lambda *_args, **_kwargs: None)

    confirmed = intake.confirm_intake("wt-1")
    assert confirmed["intake"]["diagnostics"] == diagnostics

    stored_intake["status"] = "await_answers"
    skipped = intake.skip_intake("wt-1")
    assert skipped["intake"]["status"] == "done"
    assert skipped["intake"]["mode"] == "user_skipped"
    assert skipped["intake"]["diagnostics"]["latest"]["parse_error"] == "invalid JSON"
