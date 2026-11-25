from __future__ import annotations

import pytest


@pytest.fixture
def isolated_writing_store(tmp_path, monkeypatch):
    monkeypatch.setenv("REALAI_APP_ROOT", str(tmp_path))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))

    from realai.meta import db

    db._initialized = False
    yield
    db._initialized = False


def _outline():
    return {
        "title": "测试规划报告",
        "strategic_main_line": "以高质量发展为主线",
        "sections": [
            {"id": "sec-1", "heading": "第一章", "word_budget": 1200},
            {"id": "sec-2", "heading": "第二章", "word_budget": 1200},
        ],
    }


def test_writer_requires_a_real_outline_before_generating_chapters():
    from realai.report.strategic_pipeline import _outline_ready_for_writing

    assert _outline_ready_for_writing({}) is False
    assert _outline_ready_for_writing({"title": "只有标题"}) is False
    assert _outline_ready_for_writing({"sections": [{"id": "sec-1", "heading": ""}]}) is False
    assert _outline_ready_for_writing(_outline()) is True


def test_writer_resume_is_pinned_to_the_first_missing_chapter():
    from realai.report.strategic_pipeline import _first_missing_chapter_index

    outline = _outline()
    only_second = [{"id": "sec-2", "heading": "第二章", "body": "第二章正文。"}]
    first_only = [{"id": "sec-1", "heading": "第一章", "body": "第一章正文。"}]
    all_done = [*first_only, *only_second]

    assert _first_missing_chapter_index(outline, []) == 0
    assert _first_missing_chapter_index(outline, only_second) == 0
    assert _first_missing_chapter_index(outline, first_only) == 1
    assert _first_missing_chapter_index(outline, all_done) == 2


def test_resume_metadata_cannot_bypass_outline_confirmation():
    from realai.report.strategic_pipeline import _needs_outline_confirmation

    assert (
        _needs_outline_confirmation(
            step_confirm=False,
            outline_confirm_required=True,
            confirmed=False,
            resume_chapter_index=4,
            resume_from="writer",
        )
        is True
    )


@pytest.mark.asyncio
async def test_malformed_resume_checkpoint_returns_to_outline_confirmation():
    from realai.report.strategic_pipeline import run_report_pipeline

    result = await run_report_pipeline(
        "损坏断点恢复测试",
        outline_confirm_required=True,
        confirmed=True,
        resume_from="writer",
        checkpoint={
            "resume_from": "writer",
            "resume_chapter_index": 4,
            "outline": {"title": "只有标题"},
            "chapter_drafts": [{"id": "sec-5", "heading": "第五章", "body": "不应提前展示的正文"}],
        },
    )

    assert result["phase"] == "await_outline_confirm"
    assert result["outline_confirm_required"] is True
    assert len(result["outline"]["sections"]) > 0
    assert result["chapter_drafts"] == []


def test_completed_chapters_are_checkpointed_in_outline_order(isolated_writing_store):
    from realai.meta.writing import (
        create_task,
        get_task,
        merge_meta,
        update_task,
    )

    from app.gateway.routers.realai_ext import _persist_writing_chapter

    task = create_task("测试规划报告")
    update_task(task["id"], status="running", outline_json=_outline())
    merge_meta(
        task["id"],
        {
            "checkpoint": {
                "resume_from": "writer",
                "outline": _outline(),
                "evidence": {"items": [{"id": "kb:1", "source": "doc.md"}]},
                "chapter_drafts": [],
            }
        },
    )

    _persist_writing_chapter(
        task["id"],
        {
            "type": "chapter",
            "chapter_index": 1,
            "chapter": {
                "id": "sec-2",
                "heading": "第二章",
                "body": "第二章正文。",
                "word_budget": 1200,
            },
        },
    )
    after_second = get_task(task["id"])
    assert after_second["meta"]["resume_chapter_index"] == 0

    _persist_writing_chapter(
        task["id"],
        {
            "type": "chapter",
            "chapter_index": 0,
            "chapter": {
                "id": "sec-1",
                "heading": "第一章",
                "body": "第一章正文。",
                "word_budget": 1200,
            },
        },
    )

    saved = get_task(task["id"])
    drafts = saved["outline"]["chapter_drafts"]
    assert [draft["id"] for draft in drafts] == ["sec-1", "sec-2"]
    assert saved["meta"]["resume_from"] == "writer"
    assert saved["meta"]["resume_chapter_index"] == 2
    assert saved["result"]["evidence"]["items"][0]["id"] == "kb:1"
    assert "第一章正文" in saved["result"]["preview_markdown"]
    assert "第二章正文" in saved["result"]["preview_markdown"]


def test_writing_task_persists_customer_skill_profile_snapshot(isolated_writing_store):
    from realai.meta.writing import create_task, get_task

    profile = {
        "id": "customer-strategy",
        "name": "客户战略方法",
        "version": "v1",
        "body": "客户写作规则正文",
    }
    task = create_task("客户方法写作测试", skill_profile=profile)
    profile["body"] = "调用方后来修改的内容"

    saved = get_task(task["id"])
    assert saved["skill_profile"]["id"] == "customer-strategy"
    assert saved["skill_profile"]["body"] == "客户写作规则正文"
    assert saved["meta"]["skill_profile"]["version"] == "v1"


def test_gateway_restart_marks_running_writing_task_resumable(isolated_writing_store):
    from realai.meta.writing import (
        create_task,
        get_task,
        merge_meta,
        pause_interrupted_running_tasks,
        update_task,
    )

    task = create_task("中断恢复测试")
    checkpoint = {
        "resume_from": "writer",
        "resume_chapter_index": 1,
        "outline": {**_outline(), "chapter_drafts": [{"id": "sec-1", "heading": "第一章", "body": "已保存正文"}]},
        "chapter_drafts": [{"id": "sec-1", "heading": "第一章", "body": "已保存正文"}],
        "preview_markdown": "# 测试规划报告\n\n## 第一章\n\n已保存正文",
    }
    update_task(
        task["id"],
        status="running",
        outline_json=checkpoint["outline"],
        result_json={"run_mode": "report", "phase": "running", **checkpoint},
    )
    merge_meta(
        task["id"],
        {
            "checkpoint": checkpoint,
            "resume_from": "writer",
            "resume_chapter_index": 1,
        },
    )

    assert pause_interrupted_running_tasks("Gateway 已重启") == 1

    saved = get_task(task["id"])
    assert saved["status"] == "paused"
    assert saved["result"]["phase"] == "paused"
    assert saved["result"]["resume_chapter_index"] == 1
    assert saved["outline"]["chapter_drafts"][0]["body"] == "已保存正文"
    assert "Gateway 已重启" in saved["error"]


@pytest.mark.asyncio
async def test_background_writer_keeps_pumping_without_an_sse_subscriber(monkeypatch):
    from app.gateway.routers import realai_ext

    emitted = [
        {"type": "chapter", "chapter": {"id": "sec-1", "body": "后台正文"}},
        {
            "type": "result",
            "result": {
                "phase": "completed",
                "outline": {},
                "agent_progress": [],
            },
        },
    ]
    persisted = []

    async def fake_events(*_args, **_kwargs):
        for event in emitted:
            yield event

    monkeypatch.setattr(realai_ext, "iter_report_pipeline_events", fake_events)
    monkeypatch.setattr(
        realai_ext,
        "_persist_writing_stream_event",
        lambda _task_id, event: persisted.append(event),
    )
    session = realai_ext._WritingRunSession("wt-background")

    await realai_ext._pump_writing_run(
        session,
        task={
            "id": "wt-background",
            "goal": "后台写作",
            "step_confirm": False,
            "outline_confirm_required": False,
            "outline": {},
        },
        body=realai_ext.WritingRun(),
        mode="off",
        scope=None,
        report_type="regional",
        audience="",
        resume_kwargs={
            "resume_chapter_index": None,
            "resume_from": None,
            "checkpoint": None,
        },
    )

    assert session.done is True
    assert persisted == emitted
    replayed = [event async for event in session.subscribe(0)]
    assert replayed == emitted
