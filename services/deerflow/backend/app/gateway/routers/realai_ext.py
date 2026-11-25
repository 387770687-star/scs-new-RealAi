"""RealAi extended APIs: models, writing, artifacts, metrics, evaluation, vault health."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from realai.config import load_settings, public_settings, resolve_request_web_search_mode
from realai.meta.artifacts import create_artifact, get_artifact, list_artifacts
from realai.meta.chat import (
    append_message,
    create_session,
    delete_session,
    get_session,
    list_sessions,
    rename_session,
)
from realai.meta.evaluation import (
    add_case,
    cancel_run,
    compare_runs,
    create_suite,
    delete_case,
    delete_suite,
    duplicate_case,
    evaluation_overview,
    export_suite,
    get_run,
    get_suite,
    import_suite,
    list_runs,
    list_suites,
    retry_failed_run,
    seed_suites,
    start_run,
    update_case,
    validate_suite,
)
from realai.meta.import_jobs import create_job, get_job, list_jobs, schedule_job
from realai.meta.metrics import (
    create_metric,
    delete_metric,
    get_metric,
    list_metrics,
    update_metric,
)
from realai.meta.routing import list_routing
from realai.meta.writing import (
    append_artifact,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    merge_meta,
    update_task,
)
from realai.report.export_service import apply_preview_to_result, build_export_bytes
from realai.report.intake import (
    confirm_intake,
    intake_blocks_run,
    save_intake_answers,
    skip_intake,
    start_intake,
)
from realai.report.pipeline import iter_report_pipeline_events, run_report_pipeline
from realai.report.run_control import (
    PipelineCancelled,
    PipelinePaused,
    clear_control,
    request_cancel,
    request_pause,
    reset_to_run,
)
from realai.report.strategic_pipeline import assemble_report_markdown, control_result
from realai.report.strategic_types import REPORT_TYPES
from realai.skills.runtime import snapshot_skill_profile
from realai.vault.catalog import invalidate_vault_catalog
from realai.vault.health import vault_health
from realai.vault.import_service import import_from_raw_tree
from realai.vault.index import invalidate_vault_index
from realai.vault.wiki.graph_index import backlinks_for_path, query_graph
from realai.vault.wiki.pipeline import rebuild_wiki

router = APIRouter(prefix="/api/realai", tags=["realai-ext"])


# ----- models -----


@router.get("/models")
async def models_list():
    from realai.llm.schema import catalog_for_api

    settings = load_settings()
    llm = settings.get("llm") or {}
    catalog = catalog_for_api(llm)
    return {
        "models": catalog.get("resolved") or [],
        "catalog": catalog.get("catalog") or [],
        "roles": catalog.get("roles") or {},
        "protocol": catalog.get("protocol"),
        "provider": catalog.get("provider"),
        "settings": public_settings(settings).get("llm"),
    }


@router.get("/models/routing")
async def models_routing(limit: int = 50):
    calls = list_routing(limit=limit)
    return {"calls": calls, "count": len(calls)}


# ----- light ask extras live in realai.py; writing -----


class WritingCreate(BaseModel):
    goal: str = Field(min_length=1)
    step_confirm: bool = False
    # None = 不选模板，由架构阶段生成大纲并强制确认。
    report_type: str | None = None
    audience: str = ""
    scope_paths: list[str] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    skill_profile_id: str | None = None


class WritingPatch(BaseModel):
    goal: str | None = None
    step_confirm: bool | None = None
    outline: dict[str, Any] | None = None
    status: str | None = None
    report_type: str | None = None
    audience: str | None = None
    scope_paths: list[str] | None = None
    skill_profile_id: str | None = None
    preview_markdown: str | None = None
    rewrite_exports: bool = True


class WritingRun(BaseModel):
    confirmed: bool = False
    confirmed_chapter: bool = False
    resume_chapter_index: int | None = None
    outline: dict[str, Any] | None = None
    scope_paths: list[str] | None = None
    report_type: str | None = None
    audience: str | None = None
    web_search_enabled: bool | None = None
    web_search_mode: str | None = None
    resume: bool | None = None
    """True=从暂停点继续；False=从头跑；None=paused 状态自动继续。"""


class IntakeAnswersBody(BaseModel):
    answers: list[dict[str, Any]] = Field(default_factory=list)


def _resume_kwargs(task: dict[str, Any], body: WritingRun) -> dict[str, Any]:
    """Decide checkpoint / resume_from for pause-continue."""
    result = task.get("result") or {}
    meta = task.get("meta") or {}
    want_resume = body.resume
    if want_resume is None:
        want_resume = task.get("status") == "paused" and bool(result.get("resume_from") or meta.get("resume_from"))
    if not want_resume:
        return {
            "resume_from": None,
            "checkpoint": None,
            "resume_chapter_index": body.resume_chapter_index,
        }
    checkpoint = dict(result)
    if meta.get("checkpoint") and isinstance(meta["checkpoint"], dict):
        # meta checkpoint fills missing fields
        for k, v in meta["checkpoint"].items():
            checkpoint.setdefault(k, v)
    resume_from = str(result.get("resume_from") or meta.get("resume_from") or "") or None
    chapter_idx = body.resume_chapter_index
    if chapter_idx is None:
        chapter_idx = result.get("resume_chapter_index")
        if chapter_idx is None:
            chapter_idx = meta.get("resume_chapter_index")
    return {
        "resume_from": resume_from,
        "checkpoint": checkpoint,
        "resume_chapter_index": chapter_idx,
    }


def _ensure_intake_done(task: dict[str, Any]) -> None:
    msg = intake_blocks_run(task)
    if msg:
        raise HTTPException(400, msg)


class WritingExportBody(BaseModel):
    format: str = Field(description="md | docx | pdf")
    markdown: str | None = None


class InsertArtifact(BaseModel):
    artifact_id: str


@router.get("/writing/tasks")
async def writing_list(limit: int = 50):
    return {"tasks": list_tasks(limit=limit)}


@router.get("/writing/report-types")
async def writing_report_types():
    return {"types": [{"id": k, "label": v["label"], "min_chars": v["min_chars"]} for k, v in REPORT_TYPES.items()]}


@router.post("/writing/tasks")
async def writing_create(body: WritingCreate):
    try:
        skill_profile = snapshot_skill_profile(body.skill_profile_id) if body.skill_profile_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return create_task(
        body.goal,
        step_confirm=body.step_confirm,
        report_type=body.report_type or "regional",
        template_id=body.report_type,
        outline_confirm_required=body.report_type is None,
        audience=body.audience,
        scope_paths=body.scope_paths,
        attachments=body.attachments,
        skill_profile=skill_profile,
    )


@router.get("/writing/tasks/{task_id}")
async def writing_get(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


@router.patch("/writing/tasks/{task_id}")
async def writing_patch(task_id: str, body: WritingPatch):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    fields: dict[str, Any] = {}
    if body.goal is not None:
        fields["goal"] = body.goal
    if body.step_confirm is not None:
        fields["step_confirm"] = body.step_confirm
    if body.status is not None:
        fields["status"] = body.status
    if body.outline is not None:
        fields["outline_json"] = body.outline
    if body.preview_markdown is not None:
        try:
            fields["result_json"] = apply_preview_to_result(
                task.get("result"),
                body.preview_markdown,
                goal=body.goal or task.get("goal") or "report",
                rewrite_files=body.rewrite_exports,
            )
        except Exception as e:
            raise HTTPException(500, f"保存预览失败：{e}") from e
    meta_patch: dict[str, Any] = {}
    if body.report_type is not None:
        meta_patch["report_type"] = body.report_type
    if body.audience is not None:
        meta_patch["audience"] = body.audience
    if body.scope_paths is not None:
        meta_patch["scope_paths"] = body.scope_paths
    if body.skill_profile_id is not None:
        try:
            meta_patch["skill_profile"] = snapshot_skill_profile(body.skill_profile_id) if body.skill_profile_id else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if fields:
        update_task(task_id, **fields)
    if meta_patch:
        merge_meta(task_id, meta_patch)
    return get_task(task_id)


@router.post("/writing/tasks/{task_id}/export")
async def writing_export(task_id: str, body: WritingExportBody):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    fmt = (body.format or "").strip().lower()
    if fmt not in {"md", "docx", "pdf"}:
        raise HTTPException(400, "format 仅支持 md / docx / pdf")
    md = body.markdown
    if md is None:
        md = ((task.get("result") or {}).get("preview_markdown") or "").strip()
    if not md:
        raise HTTPException(400, "暂无预览正文可导出")
    goal = task.get("goal") or "report"
    try:
        content, media, filename = build_export_bytes(md, goal=goal, fmt=fmt)  # type: ignore[arg-type]
    except Exception as e:
        raise HTTPException(500, f"导出失败：{e}") from e
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/writing/tasks/{task_id}")
async def writing_delete(task_id: str):
    if not delete_task(task_id):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.post("/writing/tasks/{task_id}/intake/start")
async def writing_intake_start(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    try:
        return await start_intake(task_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        update_task(task_id, status="failed", error=str(e))
        raise HTTPException(500, f"摸底问答失败：{e}") from e


@router.patch("/writing/tasks/{task_id}/intake/answers")
async def writing_intake_answers(task_id: str, body: IntakeAnswersBody):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    try:
        return save_intake_answers(task_id, body.answers)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/writing/tasks/{task_id}/intake/confirm")
async def writing_intake_confirm(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    try:
        return confirm_intake(task_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/writing/tasks/{task_id}/intake/skip")
async def writing_intake_skip(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    try:
        return skip_intake(task_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _task_checkpoint(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result")
    checkpoint = dict(result) if isinstance(result, dict) else {}
    meta_checkpoint = (task.get("meta") or {}).get("checkpoint")
    if isinstance(meta_checkpoint, dict):
        checkpoint.update(meta_checkpoint)
    return checkpoint


def _ordered_chapter_drafts(
    outline: dict[str, Any],
    existing: list[dict[str, Any]],
    incoming: dict[str, Any],
) -> list[dict[str, Any]]:
    chapter_id = str(incoming.get("id") or "")
    heading = str(incoming.get("heading") or "")
    merged = [dict(item) for item in existing if isinstance(item, dict)]
    match = next(
        (index for index, item in enumerate(merged) if (chapter_id and str(item.get("id") or "") == chapter_id) or (not chapter_id and heading and str(item.get("heading") or "") == heading)),
        None,
    )
    if match is None:
        merged.append(dict(incoming))
    else:
        merged[match] = dict(incoming)

    order = {str(section.get("id") or f"sec-{index + 1}"): index for index, section in enumerate(outline.get("sections") or []) if isinstance(section, dict)}
    merged.sort(key=lambda item: order.get(str(item.get("id") or ""), len(order) + 1))
    return merged


def _next_resume_chapter_index(outline: dict[str, Any], drafts: list[dict[str, Any]]) -> int:
    completed = {str(item.get("id") or "") for item in drafts if str(item.get("body") or "").strip()}
    next_index = 0
    for index, section in enumerate(outline.get("sections") or []):
        if not isinstance(section, dict):
            break
        chapter_id = str(section.get("id") or f"sec-{index + 1}")
        if chapter_id not in completed:
            break
        next_index = index + 1
    return next_index


def _persist_writing_checkpoint(task_id: str, checkpoint: dict[str, Any]) -> None:
    """Persist one durable pipeline boundary without marking the run complete."""

    task = get_task(task_id)
    if not task:
        return
    current_checkpoint = _task_checkpoint(task)
    current_checkpoint.update(checkpoint)
    outline = dict(current_checkpoint.get("outline") or task.get("outline") or {})
    drafts = list(current_checkpoint.get("chapter_drafts") or outline.get("chapter_drafts") or [])
    if drafts:
        outline["chapter_drafts"] = drafts
    preview = str(current_checkpoint.get("preview_markdown") or "")
    if drafts and not preview:
        preview = assemble_report_markdown(task["goal"], outline, drafts)
    current_checkpoint.update(
        {
            "outline": outline,
            "chapter_drafts": drafts,
            "preview_markdown": preview,
        }
    )

    result = dict(task.get("result") or {})
    result.update(current_checkpoint)
    result.update(
        {
            "run_mode": "report",
            "phase": "running",
            "outline": outline,
            "chapter_drafts": drafts,
            "preview_markdown": preview,
            "checkpoint": True,
        }
    )
    progress = current_checkpoint.get("agent_progress")
    if not isinstance(progress, list):
        progress = task.get("progress") or []
    meta = dict(task.get("meta") or {})
    meta.update(
        {
            "checkpoint": current_checkpoint,
            "resume_from": current_checkpoint.get("resume_from"),
            "resume_chapter_index": int(current_checkpoint.get("resume_chapter_index") or 0),
        }
    )
    update_task(
        task_id,
        status="running",
        outline_json=outline,
        progress_json=progress,
        result_json=result,
        meta_json=meta,
        error=None,
    )


def _persist_writing_chapter(task_id: str, event: dict[str, Any]) -> None:
    """Upsert a completed chapter and advance the resumable writer checkpoint."""

    chapter = event.get("chapter")
    if not isinstance(chapter, dict):
        return
    task = get_task(task_id)
    if not task:
        return
    checkpoint = _task_checkpoint(task)
    outline = dict(checkpoint.get("outline") or task.get("outline") or {})
    existing = list(checkpoint.get("chapter_drafts") or outline.get("chapter_drafts") or [])
    drafts = _ordered_chapter_drafts(outline, existing, chapter)
    outline["chapter_drafts"] = drafts
    resume_index = _next_resume_chapter_index(outline, drafts)
    checkpoint.update(
        {
            "resume_from": "writer",
            "resume_chapter_index": resume_index,
            "outline": outline,
            "chapter_drafts": drafts,
            "preview_markdown": assemble_report_markdown(task["goal"], outline, drafts),
            "agent_progress": task.get("progress") or checkpoint.get("agent_progress") or [],
        }
    )
    _persist_writing_checkpoint(task_id, checkpoint)


def _persist_writing_result(task_id: str, result: dict[str, Any]) -> None:
    phase = result.get("phase")
    status = "completed"
    if phase == "await_outline_confirm":
        status = "await_confirm"
    elif phase == "await_chapter_confirm":
        status = "await_chapter"
    elif phase == "paused":
        status = "paused"
    elif phase == "cancelled":
        status = "cancelled"
    cards = result.get("knowledge_cards") or []
    scorecards = result.get("scorecards") or []
    meta_patch: dict[str, Any] = {
        "knowledge_cards": cards,
        "scorecards": scorecards,
        "report_type": (result.get("outline") or {}).get("report_type"),
    }
    if phase != "completed":
        meta_patch["resume_from"] = result.get("resume_from")
        meta_patch["resume_chapter_index"] = result.get("resume_chapter_index") or 0
        meta_patch["checkpoint"] = {
            "resume_from": result.get("resume_from"),
            "resume_chapter_index": result.get("resume_chapter_index") or 0,
            "outline": result.get("outline") or {},
            "chapter_drafts": result.get("chapter_drafts") or [],
            "evidence": result.get("evidence") or {"items": []},
            "knowledge_cards": cards,
            "fact_pack": result.get("fact_pack") or {},
            "preview_markdown": result.get("preview_markdown") or "",
            "cited_md": result.get("cited_md") or "",
            "citation_ledger": result.get("citation_ledger") or [],
            "scorecard": result.get("scorecard"),
            "scorecards": scorecards,
            "agent_progress": result.get("agent_progress") or [],
            "skills": result.get("skills") or {},
        }
    else:
        meta_patch["resume_from"] = None
        meta_patch["resume_chapter_index"] = None
        meta_patch["checkpoint"] = None
    merge_meta(task_id, meta_patch)
    update_task(
        task_id,
        status=status,
        outline_json=result.get("outline") or {},
        progress_json=result.get("agent_progress") or [],
        result_json=result,
        error=None,
    )


def _persist_writing_stream_event(task_id: str, event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "progress" and isinstance(event.get("agent_progress"), list):
        update_task(task_id, progress_json=event["agent_progress"])
    elif event_type == "outline" and isinstance(event.get("outline"), dict):
        update_task(task_id, outline_json=event["outline"])
    elif event_type == "checkpoint" and isinstance(event.get("checkpoint"), dict):
        _persist_writing_checkpoint(task_id, event["checkpoint"])
    elif event_type == "chapter":
        _persist_writing_chapter(task_id, event)
    elif event_type == "card" and isinstance(event.get("cards"), list):
        task = get_task(task_id) or {}
        cards = list(task.get("knowledge_cards") or [])
        known = {str(card.get("id") or "") for card in cards if isinstance(card, dict)}
        for card in event["cards"]:
            if not isinstance(card, dict):
                continue
            card_id = str(card.get("id") or "")
            if card_id and card_id in known:
                continue
            cards.append(card)
            if card_id:
                known.add(card_id)
        merge_meta(task_id, {"knowledge_cards": cards})
    elif event_type == "scorecard" and isinstance(event.get("scorecard"), dict):
        task = get_task(task_id) or {}
        scorecards = list(task.get("scorecards") or [])
        scorecards.append(event["scorecard"])
        merge_meta(task_id, {"scorecards": scorecards})
    elif event_type == "result" and isinstance(event.get("result"), dict):
        _persist_writing_result(task_id, event["result"])
    elif event_type == "error":
        update_task(
            task_id,
            status="failed",
            error=str(event.get("message") or "报告生成失败"),
        )


def _pause_writing_after_worker_interruption(task_id: str, message: str) -> None:
    task = get_task(task_id)
    if not task or task.get("status") != "running":
        return
    checkpoint = _task_checkpoint(task)
    outline = dict(checkpoint.get("outline") or task.get("outline") or {})
    drafts = list(checkpoint.get("chapter_drafts") or outline.get("chapter_drafts") or [])
    if drafts:
        outline["chapter_drafts"] = drafts
    result = dict(task.get("result") or {})
    result.update(checkpoint)
    result.update(
        {
            "run_mode": "report",
            "phase": "paused",
            "message": message,
            "outline": outline,
            "chapter_drafts": drafts,
            "resume_from": checkpoint.get("resume_from"),
            "resume_chapter_index": int(checkpoint.get("resume_chapter_index") or 0),
            "checkpoint": True,
        }
    )
    update_task(
        task_id,
        status="paused",
        outline_json=outline,
        result_json=result,
        error=message,
    )


class _WritingRunSession:
    """A process-local writer worker with reconnectable SSE subscribers."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=4096)
        self.sequence = 0
        self.done = False
        self.condition = asyncio.Condition()
        self.worker: asyncio.Task[None] | None = None

    async def publish(self, event: dict[str, Any]) -> None:
        async with self.condition:
            self.sequence += 1
            self.events.append((self.sequence, event))
            self.condition.notify_all()

    async def finish(self) -> None:
        async with self.condition:
            self.done = True
            self.condition.notify_all()

    async def subscribe(self, after_sequence: int = 0) -> AsyncIterator[dict[str, Any]]:
        cursor = after_sequence
        while True:
            async with self.condition:
                pending = [(seq, event) for seq, event in self.events if seq > cursor]
                while not pending and not self.done:
                    await self.condition.wait()
                    pending = [(seq, event) for seq, event in self.events if seq > cursor]
                finished = self.done and not pending
            if finished:
                break
            for sequence, event in pending:
                cursor = sequence
                yield event


_active_writing_runs: dict[str, _WritingRunSession] = {}


async def _pump_writing_run(
    session: _WritingRunSession,
    *,
    task: dict[str, Any],
    body: WritingRun,
    mode: str,
    scope: list[str] | None,
    report_type: str | None,
    audience: str | None,
    resume_kwargs: dict[str, Any],
) -> None:
    last_heartbeat = time.monotonic()
    try:
        async for event in iter_report_pipeline_events(
            task["goal"],
            step_confirm=task["step_confirm"],
            outline_confirm_required=bool(task.get("outline_confirm_required")),
            confirmed=body.confirmed,
            outline_override=body.outline or (task.get("outline") or None),
            scope_paths=scope,
            report_type=report_type,
            audience=audience,
            skill_profile=task.get("skill_profile"),
            web_search_mode=mode,
            resume_chapter_index=resume_kwargs["resume_chapter_index"],
            confirmed_chapter=body.confirmed_chapter,
            task_id=task["id"],
            resume_from=resume_kwargs["resume_from"],
            checkpoint=resume_kwargs["checkpoint"],
        ):
            await asyncio.to_thread(
                _persist_writing_stream_event,
                task["id"],
                event,
            )
            await session.publish(event)
            now = time.monotonic()
            if now - last_heartbeat >= 10:
                await asyncio.to_thread(
                    update_task,
                    task["id"],
                    status="running",
                    error=None,
                )
                last_heartbeat = now
    except asyncio.CancelledError:
        await asyncio.shield(
            asyncio.to_thread(
                _pause_writing_after_worker_interruption,
                task["id"],
                "生成服务已停止，任务已在最近检查点暂停",
            )
        )
        raise
    except Exception as exc:
        await asyncio.to_thread(
            update_task,
            task["id"],
            status="failed",
            error=str(exc),
        )
        await session.publish({"type": "error", "message": str(exc)})
    finally:
        await session.finish()
        if _active_writing_runs.get(task["id"]) is session:
            _active_writing_runs.pop(task["id"], None)


@router.post("/writing/tasks/{task_id}/run")
async def writing_run(task_id: str, body: WritingRun):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    _ensure_intake_done(task)
    update_task(task_id, status="running", error=None)
    reset_to_run(task_id)

    async def on_progress(step: dict[str, Any]) -> None:
        # refresh full progress from last result later; append step snapshot
        cur = get_task(task_id) or {}
        prog = list(cur.get("progress") or [])
        # replace by id
        found = False
        for i, p in enumerate(prog):
            if p.get("id") == step.get("id"):
                prog[i] = step
                found = True
                break
        if not found:
            prog.append(step)
        update_task(task_id, progress_json=prog)

    mode = resolve_request_web_search_mode(body.web_search_mode, body.web_search_enabled, fallback_settings=True)
    scope = body.scope_paths if body.scope_paths is not None else (task.get("scope_paths") or None)
    rt = body.report_type or task.get("report_type")
    audience = body.audience if body.audience is not None else task.get("audience")
    resume_kw = _resume_kwargs(task, body)
    try:
        result = await run_report_pipeline(
            task["goal"],
            step_confirm=task["step_confirm"],
            outline_confirm_required=bool(task.get("outline_confirm_required")),
            confirmed=body.confirmed,
            on_progress=on_progress,
            outline_override=body.outline or (task.get("outline") or None),
            scope_paths=scope,
            report_type=rt,
            audience=audience,
            skill_profile=task.get("skill_profile"),
            web_search_mode=mode,
            resume_chapter_index=resume_kw["resume_chapter_index"],
            confirmed_chapter=body.confirmed_chapter,
            task_id=task_id,
            resume_from=resume_kw["resume_from"],
            checkpoint=resume_kw["checkpoint"],
        )
        _persist_writing_result(task_id, result)
        return get_task(task_id)
    except PipelinePaused as exc:
        _persist_writing_result(task_id, control_result("paused", exc.snapshot, exc.reason))
        return get_task(task_id)
    except PipelineCancelled as exc:
        _persist_writing_result(task_id, control_result("cancelled", exc.snapshot, exc.reason))
        return get_task(task_id)
    except Exception as exc:
        update_task(task_id, status="failed", error=str(exc))
        raise HTTPException(500, str(exc)) from exc
    finally:
        clear_control(task_id)


@router.post("/writing/tasks/{task_id}/pause")
async def writing_pause(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.get("status") != "running":
        raise HTTPException(400, "仅运行中的任务可暂停（将在当前步骤/章节边界生效）")
    request_pause(task_id, "用户暂停")
    return {"ok": True, "action": "pause", "message": "已请求暂停，将在当前步骤或章节结束后停下"}


@router.post("/writing/tasks/{task_id}/cancel")
async def writing_cancel(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.get("status") != "running":
        raise HTTPException(400, "仅运行中的任务可终止（将在当前步骤/章节边界生效）")
    request_cancel(task_id, "用户终止")
    return {"ok": True, "action": "cancel", "message": "已请求终止，将保留已生成预览与知识卡片"}


@router.post("/writing/tasks/{task_id}/run/stream")
async def writing_run_stream(task_id: str, body: WritingRun):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    _ensure_intake_done(task)
    session = _active_writing_runs.get(task_id)
    if session and not session.done:
        # Reconnection sends one current database snapshot, then follows the
        # live edge. Replaying historical deltas would duplicate text before
        # the final chapter replacement arrives.
        after_sequence = session.sequence
        reconnect_snapshot = get_task(task_id) or task
    else:
        reconnect_snapshot = None
        recovering_orphan = task.get("status") == "running"
        run_body = body.model_copy(deep=True)
        if recovering_orphan:
            run_body.resume = True
        mode = resolve_request_web_search_mode(
            run_body.web_search_mode,
            run_body.web_search_enabled,
            fallback_settings=True,
        )
        scope = run_body.scope_paths if run_body.scope_paths is not None else (task.get("scope_paths") or None)
        report_type = run_body.report_type or task.get("report_type")
        audience = run_body.audience if run_body.audience is not None else task.get("audience")
        resume_kwargs = _resume_kwargs(task, run_body)
        update_task(task_id, status="running", error=None)
        session = _WritingRunSession(task_id)
        _active_writing_runs[task_id] = session
        session.worker = asyncio.create_task(
            _pump_writing_run(
                session,
                task=task,
                body=run_body,
                mode=mode,
                scope=scope,
                report_type=report_type,
                audience=audience,
                resume_kwargs=resume_kwargs,
            ),
            name=f"realai-writing-{task_id}",
        )
        after_sequence = 0

    async def event_stream():
        if reconnect_snapshot:
            progress = reconnect_snapshot.get("progress") or []
            if progress:
                yield (f"data: {json.dumps({'type': 'progress', 'agent_progress': progress}, ensure_ascii=False)}\n\n")
            outline = reconnect_snapshot.get("outline") or {}
            if outline:
                yield (f"data: {json.dumps({'type': 'outline', 'outline': outline}, ensure_ascii=False)}\n\n")
            drafts = list(outline.get("chapter_drafts") or (reconnect_snapshot.get("result") or {}).get("chapter_drafts") or [])
            for chapter_index, chapter in enumerate(drafts):
                yield (f"data: {json.dumps({'type': 'chapter', 'chapter': chapter, 'chapter_index': chapter_index}, ensure_ascii=False)}\n\n")
        async for event in session.subscribe(after_sequence):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/writing/tasks/{task_id}/confirm-outline")
async def writing_confirm(task_id: str, body: WritingRun):
    body.confirmed = True
    return await writing_run(task_id, body)


@router.post("/writing/tasks/{task_id}/confirm-chapter")
async def writing_confirm_chapter(task_id: str, body: WritingRun):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    result = task.get("result") or {}
    body.confirmed = True
    body.confirmed_chapter = True
    body.resume_chapter_index = body.resume_chapter_index or result.get("next_chapter_index") or 0
    body.outline = body.outline or task.get("outline")
    return await writing_run(task_id, body)


@router.post("/writing/tasks/{task_id}/insert-artifact")
async def writing_insert_artifact(task_id: str, body: InsertArtifact):
    if not get_task(task_id):
        raise HTTPException(404, "任务不存在")
    if not get_artifact(body.artifact_id):
        raise HTTPException(404, "Artifact 不存在")
    return append_artifact(task_id, body.artifact_id)


# ----- artifacts -----


class ArtifactCreate(BaseModel):
    kind: str = "conclusion"
    title: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    source_task: str | None = None


@router.get("/artifacts")
async def artifacts_list(limit: int = 50):
    return {"artifacts": list_artifacts(limit=limit)}


@router.post("/artifacts")
async def artifacts_create(body: ArtifactCreate):
    return create_artifact(
        kind=body.kind,
        title=body.title or body.kind,
        content=body.content,
        evidence_ids=body.evidence_ids,
        source_task=body.source_task,
    )


@router.get("/artifacts/{artifact_id}")
async def artifacts_get(artifact_id: str):
    a = get_artifact(artifact_id)
    if not a:
        raise HTTPException(404, "不存在")
    return a


# ----- metrics -----


class MetricBody(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    formula: str | None = None
    unit: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    authority_table: str | None = None
    notes: str | None = None


@router.get("/metrics")
async def metrics_list():
    return {"metrics": list_metrics()}


@router.post("/metrics/seed")
async def metrics_seed():
    from realai.shared_retrieve import seed_default_metrics

    created = seed_default_metrics()
    return {"ok": True, "created": len(created), "metrics": list_metrics()}


@router.post("/metrics")
async def metrics_create(body: MetricBody):
    return create_metric(body.model_dump())


@router.get("/metrics/{metric_id}")
async def metrics_get(metric_id: str):
    m = get_metric(metric_id)
    if not m:
        raise HTTPException(404, "不存在")
    return m


@router.put("/metrics/{metric_id}")
async def metrics_put(metric_id: str, body: MetricBody):
    m = update_metric(metric_id, body.model_dump())
    if not m:
        raise HTTPException(404, "不存在")
    return m


@router.delete("/metrics/{metric_id}")
async def metrics_delete(metric_id: str):
    if not delete_metric(metric_id):
        raise HTTPException(404, "不存在")
    return {"ok": True}


# ----- evaluation -----


class SuiteCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


class CaseCreate(BaseModel):
    question: str = Field(min_length=1)
    expect_keywords: list[str] = Field(default_factory=list)
    expect_evidence: bool = True
    expect_number: float | None = None
    number_tolerance: float | None = None
    expect_answer: str | None = None
    answer_match_mode: str = "contains"
    expect_unit: str | None = None
    expect_table: dict[str, Any] = Field(default_factory=dict)
    expect_source_paths: list[str] = Field(default_factory=list)
    rubric: dict[str, Any] = Field(default_factory=dict)
    fixture: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    intent: str = "ask"
    category: str = "general"
    mode: str = "light"
    expect_evidence_kinds: list[str] = Field(default_factory=list)
    expect_min_rows: int | None = None
    skip_if: str | None = None
    notes: str = ""


class CaseUpdate(BaseModel):
    question: str | None = None
    expect_keywords: list[str] | None = None
    expect_evidence: bool | None = None
    expect_number: float | None = None
    number_tolerance: float | None = None
    expect_answer: str | None = None
    answer_match_mode: str | None = None
    expect_unit: str | None = None
    expect_table: dict[str, Any] | None = None
    expect_source_paths: list[str] | None = None
    rubric: dict[str, Any] | None = None
    fixture: dict[str, Any] | None = None
    tags: list[str] | None = None
    difficulty: str | None = None
    intent: str | None = None
    category: str | None = None
    mode: str | None = None
    expect_evidence_kinds: list[str] | None = None
    expect_min_rows: int | None = None
    skip_if: str | None = None
    notes: str | None = None


class RunCreate(BaseModel):
    suite_id: str
    web_search_enabled: bool = False
    mode: str = "auto"
    model_override: str | None = None
    skill_overrides: dict[str, str] = Field(default_factory=dict)
    compare_base_run_id: str | None = None
    case_ids: list[str] = Field(default_factory=list)
    concurrency: int = Field(default=3, ge=1, le=6)
    light_timeout_seconds: int = Field(default=180, ge=30, le=1800)
    report_timeout_seconds: int = Field(default=900, ge=60, le=3600)
    judge_enabled: bool = False
    judge_model_override: str | None = None
    wait: bool = False


class SeedBody(BaseModel):
    recreate: bool = False


class ImportSuiteBody(BaseModel):
    version: int = 2
    name: str = Field(min_length=1)
    description: str = ""
    kind: str | None = None
    cases: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/evaluation/suites")
async def eval_suites():
    return {"suites": list_suites()}


@router.post("/evaluation/suites")
async def eval_suite_create(body: SuiteCreate):
    return create_suite(body.name, body.description)


@router.post("/evaluation/suites/seed")
async def eval_suites_seed(body: SeedBody | None = None):
    recreate = bool(body and body.recreate)
    return seed_suites(recreate=recreate)


@router.get("/evaluation/suites/{suite_id}")
async def eval_suite_get(suite_id: str):
    s = get_suite(suite_id)
    if not s:
        raise HTTPException(404, "不存在")
    return s


@router.get("/evaluation/suites/{suite_id}/export")
async def eval_suite_export(suite_id: str):
    payload = export_suite(suite_id)
    if not payload:
        raise HTTPException(404, "不存在")
    return payload


@router.get("/evaluation/suites/{suite_id}/validate")
async def eval_suite_validate(suite_id: str):
    try:
        return validate_suite(suite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/evaluation/suites/import")
async def eval_suite_import(body: ImportSuiteBody):
    return import_suite(body.model_dump())


@router.delete("/evaluation/suites/{suite_id}")
async def eval_suite_delete(suite_id: str):
    if not delete_suite(suite_id):
        raise HTTPException(404, "不存在")
    return {"ok": True}


@router.get("/evaluation/suites/{suite_id}/cases")
async def eval_cases(suite_id: str, category: str | None = None):
    if not get_suite(suite_id):
        raise HTTPException(404, "套件不存在")
    from realai.meta.evaluation import list_cases

    return {"cases": list_cases(suite_id, category=category)}


@router.post("/evaluation/suites/{suite_id}/cases")
async def eval_case_create(suite_id: str, body: CaseCreate):
    c = add_case(suite_id, body.model_dump())
    if not c:
        raise HTTPException(404, "套件不存在")
    return c


@router.put("/evaluation/cases/{case_id}")
async def eval_case_update(case_id: str, body: CaseUpdate):
    c = update_case(case_id, body.model_dump(exclude_unset=True))
    if not c:
        raise HTTPException(404, "不存在")
    return c


@router.post("/evaluation/cases/{case_id}/duplicate")
async def eval_case_duplicate(case_id: str):
    c = duplicate_case(case_id)
    if not c:
        raise HTTPException(404, "不存在")
    return c


@router.delete("/evaluation/cases/{case_id}")
async def eval_case_delete(case_id: str):
    if not delete_case(case_id):
        raise HTTPException(404, "不存在")
    return {"ok": True}


@router.post("/evaluation/runs")
async def eval_run_create(body: RunCreate):
    try:
        run = start_run(
            body.suite_id,
            web_search_enabled=body.web_search_enabled,
            mode=body.mode,
            model_override=body.model_override,
            skill_overrides=body.skill_overrides or None,
            compare_base_run_id=body.compare_base_run_id,
            case_ids=body.case_ids or None,
            concurrency=body.concurrency,
            light_timeout_seconds=body.light_timeout_seconds,
            report_timeout_seconds=body.report_timeout_seconds,
            judge_enabled=body.judge_enabled,
            judge_model_override=body.judge_model_override,
        )
        if not body.wait:
            return run
        import asyncio

        rid = run["id"]
        for _ in range(3600):
            cur = get_run(rid)
            if cur and cur.get("status") in ("completed", "failed", "empty", "cancelled"):
                return cur
            await asyncio.sleep(0.5)
        return get_run(rid) or run
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/evaluation/runs")
async def eval_runs(suite_id: str | None = None, limit: int = 30):
    return {"runs": list_runs(suite_id=suite_id, limit=limit)}


@router.get("/evaluation/overview")
async def eval_overview(suite_id: str | None = None, limit: int = 20):
    return evaluation_overview(suite_id=suite_id, limit=limit)


@router.get("/evaluation/runs/{run_id}")
async def eval_run_get(run_id: str):
    r = get_run(run_id)
    if not r:
        raise HTTPException(404, "不存在")
    return r


@router.post("/evaluation/runs/{run_id}/cancel")
async def eval_run_cancel(run_id: str):
    r = cancel_run(run_id)
    if not r:
        raise HTTPException(404, "不存在")
    return r


@router.post("/evaluation/runs/{run_id}/retry-failed")
async def eval_run_retry_failed(run_id: str):
    try:
        return retry_failed_run(run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/evaluation/runs/{run_id}/compare/{base_run_id}")
async def eval_run_compare(run_id: str, base_run_id: str):
    if not get_run(run_id) or not get_run(base_run_id):
        raise HTTPException(404, "跑批记录不存在")
    return compare_runs(base_run_id, run_id)


# ----- vault health / batch import -----


@router.get("/vault/health")
async def vault_health_api():
    return vault_health()


@router.post("/vault/import/batch")
async def vault_import_batch(
    files: list[UploadFile] = File(...),
):
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if data:
            payloads.append((f.filename or "upload.bin", data))
    if not payloads:
        raise HTTPException(400, "无有效文件")
    job = create_job(payloads)
    schedule_job(job["id"])
    return job


@router.get("/vault/import/jobs/{job_id}")
async def vault_import_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@router.get("/vault/import/jobs")
async def vault_import_jobs(limit: int = 20):
    return {"jobs": list_jobs(limit=limit)}


@router.post("/vault/import/from-raw")
async def vault_import_from_raw():
    """Scan repo raw/raw/{pipelines,new_energy,dataqa} into classified vault."""
    result = await import_from_raw_tree(run_wiki=True)
    invalidate_vault_index()
    invalidate_vault_catalog()
    return result


@router.post("/vault/wiki/rebuild")
async def vault_wiki_rebuild():
    result = await rebuild_wiki(linkify_all=True)
    invalidate_vault_index()
    invalidate_vault_catalog()
    return {"success": True, **result}


@router.get("/vault/graph")
async def vault_graph(
    seed: str | None = None,
    depth: int = 1,
    types: str | None = None,
    limit: int = 200,
):
    type_list = [t.strip() for t in (types or "").split(",") if t.strip()] or None
    return query_graph(seed=seed, depth=depth, types=type_list, limit=limit)


@router.get("/vault/graph/backlinks")
async def vault_graph_backlinks(path: str):
    return {"path": path, "backlinks": backlinks_for_path(path)}


# ----- chat sessions (permanent) -----


class ChatCreateBody(BaseModel):
    title: str = "新对话"
    intent: str | None = None


class ChatRenameBody(BaseModel):
    title: str = Field(min_length=1)


class ChatAppendBody(BaseModel):
    role: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)


@router.get("/chat/sessions")
async def chat_sessions_list(limit: int = 100):
    return {"sessions": list_sessions(limit=limit)}


@router.post("/chat/sessions")
async def chat_sessions_create(body: ChatCreateBody):
    return create_session(title=body.title, intent=body.intent)


@router.get("/chat/sessions/{session_id}")
async def chat_sessions_get(session_id: str):
    s = get_session(session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@router.patch("/chat/sessions/{session_id}")
async def chat_sessions_rename(session_id: str, body: ChatRenameBody):
    s = rename_session(session_id, body.title)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@router.delete("/chat/sessions/{session_id}")
async def chat_sessions_delete(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


@router.post("/chat/sessions/{session_id}/messages")
async def chat_sessions_append(session_id: str, body: ChatAppendBody):
    s = append_message(session_id, role=body.role, content=body.content)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s
