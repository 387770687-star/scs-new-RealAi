"""Regression tests for strategic-report token streaming and writer batching."""

from __future__ import annotations

import asyncio
import time

import pytest
from realai.evidence.types import EvidencePack
from realai.llm import client as llm_client
from realai.llm.client import (
    ResolvedModel,
    _call_openai_compatible_stream_async,
    _parse_anthropic_stream_event,
    _parse_openai_stream_event,
    _VisibleStreamFilter,
)
from realai.report import strategic_pipeline
from realai.report.run_control import PipelineCancelled, clear_control, request_cancel, reset_to_run
from realai.report.strategic_pipeline import (
    _bounded_sync_evidence,
    _chapter_batches,
    _writer_concurrency,
    _writer_token_limit,
    iter_report_pipeline_events,
    run_report_pipeline,
)


def test_parse_openai_stream_event_separates_visible_and_reasoning_delta() -> None:
    content, reasoning, usage = _parse_openai_stream_event(
        {
            "choices": [
                {
                    "delta": {
                        "content": "第一段",
                        "reasoning_content": "简短思考",
                    }
                }
            ],
            "usage": {"completion_tokens": 12},
        }
    )

    assert content == "第一段"
    assert reasoning == "简短思考"
    assert usage == {"completion_tokens": 12}


def test_parse_openai_stream_event_accepts_structured_text_parts() -> None:
    content, reasoning, _ = _parse_openai_stream_event(
        {
            "choices": [
                {
                    "delta": {
                        "content": [
                            {"type": "text", "text": "发展"},
                            {"type": "output_text", "text": "基础"},
                        ]
                    }
                }
            ]
        }
    )

    assert content == "发展基础"
    assert reasoning == ""


def test_parse_anthropic_stream_event_handles_text_thinking_and_usage() -> None:
    assert _parse_anthropic_stream_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "正文"}}) == ("正文", "", None)
    assert _parse_anthropic_stream_event(
        {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "思考"},
        }
    ) == ("", "思考", None)
    assert _parse_anthropic_stream_event({"type": "message_delta", "usage": {"output_tokens": 88}}) == ("", "", {"output_tokens": 88})


def test_visible_stream_filter_hides_split_inline_thinking() -> None:
    visible = _VisibleStreamFilter()
    chunks = ["<thi", "nk>内部推理", "过程</th", "ink>正式", "正文"]

    output = "".join(visible.feed(chunk) for chunk in chunks) + visible.finish()

    assert output == "正式正文"


def test_writer_uses_three_chapter_batches_but_step_confirm_stays_serial() -> None:
    assert _writer_concurrency(False, 3) == 3
    assert _writer_concurrency(False, 99) == 3
    assert _writer_concurrency(True, 3) == 1
    assert _chapter_batches(0, 8, 3) == [[0, 1, 2], [3, 4, 5], [6, 7]]
    assert _chapter_batches(2, 5, 2) == [[2, 3], [4]]


def test_writer_token_limit_is_dynamic_and_never_exceeds_cap() -> None:
    assert _writer_token_limit(800, 4096) == 1800
    assert 1800 < _writer_token_limit(2000, 4096) <= 4096
    assert _writer_token_limit(8000, 4096) == 4096
    assert _writer_token_limit(8000, 2500) == 2500


@pytest.mark.asyncio
async def test_pipeline_progress_is_yielded_before_blocking_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_report_pipeline(*_args, **kwargs):
        await kwargs["on_progress"](
            {
                "id": "researcher",
                "label": "战略研究",
                "status": "running",
                "message": "正在检索",
            }
        )
        # Simulate a legacy synchronous Vault scan. The iterator must let the
        # SSE consumer paint the progress event before this finishes.
        time.sleep(0.12)
        return {"agent_progress": []}

    monkeypatch.setattr(
        strategic_pipeline,
        "run_report_pipeline",
        fake_run_report_pipeline,
    )
    stream = iter_report_pipeline_events("测试进度即时反馈")
    started = time.perf_counter()
    first = await anext(stream)
    first_event_seconds = time.perf_counter() - started
    await stream.aclose()

    assert first["type"] == "progress"
    assert first["agent_progress"][1]["status"] == "running"
    assert first_event_seconds < 0.08


@pytest.mark.asyncio
async def test_blocking_research_call_has_a_hard_time_budget() -> None:
    def slow_retrieve() -> EvidencePack:
        time.sleep(0.08)
        return EvidencePack()

    started = time.perf_counter()
    pack, error = await _bounded_sync_evidence(
        slow_retrieve,
        timeout=0.01,
    )

    assert pack.items == []
    assert error and "超过" in error
    assert time.perf_counter() - started < 0.06


@pytest.mark.asyncio
async def test_openai_stream_request_forwards_visible_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"战略"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"规划"}}],"usage":{"completion_tokens":9}}'
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, *, timeout: float):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, method: str, url: str, **kwargs):
            captured.update({"method": method, "url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeClient)
    deltas: list[str] = []
    resolved = ResolvedModel(
        role="primary",
        catalog_id="test",
        api_model="test-model",
        protocol="openai_compatible",
        provider="test",
        base_url="https://example.test/v1",
        api_key="secret",
    )

    content, reasoning, usage = await _call_openai_compatible_stream_async(
        resolved=resolved,
        messages=[{"role": "user", "content": "写报告"}],
        max_tokens=2048,
        temperature=0.2,
        timeout=30,
        on_text_delta=lambda delta: deltas.append(delta),
        reasoning_max_chars=100,
    )

    assert captured["method"] == "POST"
    assert captured["json"]["stream"] is True  # type: ignore[index]
    assert captured["json"]["max_tokens"] == 2048  # type: ignore[index]
    assert deltas == ["战略", "规划"]
    assert content == "战略规划"
    assert reasoning == "思考"
    assert usage == {"completion_tokens": 9}


@pytest.mark.asyncio
async def test_report_writer_streams_three_chapters_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = "stream-concurrency-test"
    active = 0
    max_active = 0
    events: list[dict[str, object]] = []
    completed = 0

    async def fake_chat_turn_stream(_prompt: str, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        on_delta = kwargs["on_text_delta"]
        await on_delta("这是用于验证流式并发写作的正式章节正文，")
        await asyncio.sleep(0.01)
        await on_delta("内容完整、结构清晰，并且能够被前端立即显示。")
        active -= 1
        return {
            "content": "这是用于验证流式并发写作的正式章节正文，内容完整、结构清晰，并且能够被前端立即显示。",
            "reasoning": "简短思考",
        }

    async def on_event(event: dict[str, object]) -> None:
        nonlocal completed
        events.append(event)
        if event.get("type") == "chapter":
            completed += 1
            if completed == 3:
                request_cancel(task_id, "测试在首批完成后停止")

    monkeypatch.setattr(strategic_pipeline, "chat_turn_stream", fake_chat_turn_stream)
    monkeypatch.setattr(strategic_pipeline, "_load_skill_body", lambda *_args, **_kwargs: "")
    outline = {
        "title": "并发流式测试报告",
        "report_type": "regional",
        "report_type_label": "测试规划",
        "min_chars": 120,
        "strategic_main_line": "验证三个章节能够并发生成并独立推送正文增量。",
        "sections": [
            {"id": "one", "heading": "第一章", "word_budget": 20},
            {"id": "two", "heading": "第二章", "word_budget": 20},
            {"id": "three", "heading": "第三章", "word_budget": 20},
        ],
    }
    checkpoint = {
        "resume_from": "writer",
        "outline": outline,
        "evidence": {"items": []},
        "chapter_drafts": [],
    }

    reset_to_run(task_id)
    try:
        with pytest.raises(PipelineCancelled):
            await run_report_pipeline(
                "并发流式测试",
                task_id=task_id,
                resume_from="writer",
                checkpoint=checkpoint,
                outline_override=outline,
                on_event=on_event,
            )
    finally:
        clear_control(task_id)

    assert max_active == 3
    assert {event.get("chapter_id") for event in events if event.get("type") == "chapter_delta"} == {"one", "two", "three"}
    assert completed == 3
