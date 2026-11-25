"""RealAi product APIs (Vault, light Q&A, report pipeline)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from realai.agents.light_qa import run_light_qa, run_light_qa_filter_confirm
from realai.config import (
    load_settings,
    public_settings,
    resolve_request_vision_mode,
    resolve_request_web_search_mode,
    resolve_vault_path,
    save_settings,
)
from realai.config_sync import sync_deerflow_config, sync_from_disk
from realai.data.sql_engine import run_vault_sql
from realai.onboarding import complete_onboarding, health_snapshot, onboarding_needed
from realai.report.pipeline import iter_report_pipeline_events, run_report_pipeline
from realai.vault.catalog import invalidate_vault_catalog, query_vault_catalog
from realai.vault.import_service import import_file_to_vault
from realai.vault.index import invalidate_vault_index, query_vault_files
from realai.vault.service import resolve_vault_file, vault_file_preview, vault_snapshot_mtime

router = APIRouter(prefix="/api/realai", tags=["realai"])


class LightAskRequest(BaseModel):
    query: str = Field(min_length=1)
    web_search_enabled: bool | None = None
    web_search_mode: str | None = None
    vision_mode: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    intent: str = "ask"
    scope_paths: list[str] = Field(default_factory=list)
    session_id: str | None = None
    skill_id: str | None = None


class LightAskConfirmRequest(BaseModel):
    query: str = Field(min_length=1)
    confirm_kind: str = "filter"
    filter: dict[str, Any] = Field(default_factory=dict)
    web_search_enabled: bool | None = None
    web_search_mode: str | None = None
    vision_mode: str | None = None
    intent: str = "ask"
    scope_paths: list[str] = Field(default_factory=list)
    session_id: str | None = None
    message_id: str | None = None
    skill_id: str | None = None


class ReportRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    step_confirm: bool | None = None
    confirmed: bool = False
    outline: dict[str, Any] | None = None
    scope_paths: list[str] | None = None
    web_search_enabled: bool | None = None
    web_search_mode: str | None = None


class DataSqlRequest(BaseModel):
    sql: str = Field(min_length=8)


class RealAiSettingsUpdate(BaseModel):
    obsidianVaultPath: str | None = None
    llm: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    search: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    onboarding: dict[str, Any] | None = None


class OnboardingCompleteRequest(BaseModel):
    api_key: str = Field(min_length=1)
    web_search_enabled: bool | None = None
    web_search_mode: str | None = None
    import_demo: bool = True
    vault_path: str | None = None


@router.get("/config")
async def get_realai_config():
    settings = load_settings()
    vault = resolve_vault_path(settings)
    llm = settings.get("llm") or {}
    from realai.llm.client import has_api_key

    has_key = has_api_key(settings)
    return {
        "vault_path": str(vault),
        "settings": public_settings(settings),
        "deerflow": {
            "linked": True,
            "has_api_key": has_key,
            "model_id": llm.get("modelId") or "minimax-m3",
            "protocol": llm.get("protocol") or "openai_compatible",
        },
    }


@router.put("/config")
async def put_realai_config(body: RealAiSettingsUpdate):
    try:
        saved = save_settings(body.model_dump(exclude_none=True))
        deerflow = sync_deerflow_config(saved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {exc}") from exc
    vault = resolve_vault_path(saved)
    return {
        "ok": True,
        "vault_path": str(vault),
        "settings": public_settings(saved),
        "deerflow": deerflow,
        "message": "已保存并同步到 DeerFlow（Key 不会提交到 git）",
    }


@router.post("/config/sync")
async def post_realai_config_sync():
    try:
        deerflow = sync_from_disk()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "deerflow": deerflow}


@router.get("/vault/files")
async def vault_files(limit: int = 50, offset: int = 0, q: str = "", refresh: bool = False):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit 须在 1–500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset 不能为负")
    page, total = query_vault_files(limit=limit, offset=offset, q=q, force=refresh)
    return {
        "files": [asdict(f) for f in page],
        "count": len(page),
        "total": total,
        "offset": offset,
        "limit": limit,
        "vault_mtime": vault_snapshot_mtime(),
    }


@router.get("/vault/catalog")
def vault_catalog(
    limit: int = 500,
    offset: int = 0,
    q: str = "",
    knowledge_type: str = "",
    source_status: str = "",
    quality_status: str = "",
    business_tag: str = "",
    refresh: bool = False,
):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit 须在 1–500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset 不能为负")
    return query_vault_catalog(
        knowledge_type=knowledge_type,
        source_status=source_status,
        quality_status=quality_status,
        business_tag=business_tag,
        q=q,
        limit=limit,
        offset=offset,
        force=refresh,
    )


@router.post("/vault/index/rebuild")
async def vault_index_rebuild():
    invalidate_vault_index()
    invalidate_vault_catalog()
    page, total = query_vault_files(limit=1, offset=0, force=True)
    return {"ok": True, "total": total, "vault_mtime": vault_snapshot_mtime()}


@router.get("/vault/file")
async def vault_file_meta(path: str, max_chars: int = 12000):
    if not path.strip():
        raise HTTPException(status_code=400, detail="缺少 path")
    try:
        preview = vault_file_preview(path.strip(), max_chars=max_chars)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    return preview


@router.get("/vault/file/download")
async def vault_file_download(path: str):
    if not path.strip():
        raise HTTPException(status_code=400, detail="缺少 path")
    try:
        target = resolve_vault_file(path.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    media = "application/octet-stream"
    ext = target.suffix.lower()
    if ext in {".md", ".txt"}:
        media = "text/plain; charset=utf-8"
    elif ext == ".json":
        media = "application/json"
    elif ext == ".csv":
        media = "text/csv"
    elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        media = f"image/{ext.lstrip('.').replace('jpg', 'jpeg')}"
    elif ext == ".docx":
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".pdf":
        media = "application/pdf"
    elif ext == ".xlsx":
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ext == ".xls":
        media = "application/vnd.ms-excel"
    elif ext == ".pptx":
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif ext == ".ppt":
        media = "application/vnd.ms-powerpoint"
    return FileResponse(
        path=target,
        filename=target.name,
        media_type=media,
    )


@router.get("/vault/status")
async def vault_status():
    return {"vault_mtime": vault_snapshot_mtime(), "vault_path": str(resolve_vault_path())}


@router.post("/vault/import")
async def vault_import(
    file: UploadFile = File(...),
    target_dir: str | None = None,
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    result = await import_file_to_vault(
        file.filename or "upload.bin",
        data,
        target_dir=target_dir,
    )
    if not result.success:
        raise HTTPException(status_code=422, detail=result.message)
    invalidate_vault_index()
    invalidate_vault_catalog()
    return result.to_dict()


@router.post("/vault/upload-image")
async def vault_upload_image(
    file: UploadFile = File(...),
    session_id: str | None = None,
):
    """Workbench image upload → vault/uploads/<session|date>/…"""
    from datetime import datetime

    from realai.agents.vision import IMAGE_EXTENSIONS
    from realai.vault.service import write_vault_file

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    name = file.filename or "image.png"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ".png"
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型：{ext}")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片过大（上限约 12MB）")
    day = datetime.now(UTC).strftime("%Y%m%d")
    folder = (session_id or "anon").replace("/", "_").replace("\\", "_")[:64]
    stem = Path(name).stem[:80] or "image"
    digest = __import__("hashlib").sha1(data).hexdigest()[:8]
    rel = f"uploads/{folder or day}/{stem}-{digest}{ext}".replace("\\", "/")
    write_vault_file(rel, data)
    invalidate_vault_index()
    invalidate_vault_catalog()
    return {"ok": True, "path": rel, "size": len(data)}


def _persist_light_ask_session(
    body: LightAskRequest,
    intent: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Append user/assistant messages when session_id is provided."""
    if not body.session_id:
        return result
    try:
        from realai.meta.chat import append_message, create_session, get_session

        sid = body.session_id
        if not get_session(sid):
            created = create_session(title=body.query[:40], intent=intent)
            sid = created["id"]
        append_message(sid, role="user", content={"text": body.query, "query": body.query})
        assistant_content = {
            "text": result.get("answer"),
            "answer": result.get("answer"),
            "conclusion": result.get("conclusion"),
            "evidence": result.get("evidence"),
            "trajectory": result.get("trajectory"),
            "tables": result.get("tables"),
            "chart_spec": result.get("chart_spec"),
            "entity_profile": result.get("entity_profile"),
            "data_query": result.get("data_query"),
            "awaiting_confirm": result.get("awaiting_confirm"),
            "confirm_kind": result.get("confirm_kind"),
            "filter_draft": result.get("filter_draft"),
            "skill_used": result.get("skill_used"),
        }
        append_message(sid, role="assistant", content=assistant_content, auto_title=False)
        result["session_id"] = sid
        # expose last assistant id for confirm patch
        sess = get_session(sid)
        if sess and sess.get("messages"):
            last = sess["messages"][-1]
            if last.get("role") == "assistant":
                result["message_id"] = last.get("id")
    except Exception:
        pass
    return result


@router.post("/light/ask")
async def light_ask(body: LightAskRequest):
    intent = body.intent if body.intent in ("ask", "data", "research") else "ask"
    mode = resolve_request_web_search_mode(body.web_search_mode, body.web_search_enabled, fallback_settings=True)
    vmode = resolve_request_vision_mode(body.vision_mode, fallback_settings=True)
    try:
        result = await run_light_qa(
            body.query,
            web_search_mode=mode,
            vision_mode=vmode,
            image_paths=body.image_paths or None,
            intent=intent,  # type: ignore[arg-type]
            scope_paths=body.scope_paths or None,
            session_id=body.session_id,
            skill_id=body.skill_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _persist_light_ask_session(body, intent, result)


@router.post("/light/ask/confirm")
async def light_ask_confirm(body: LightAskConfirmRequest):
    if body.confirm_kind != "filter":
        raise HTTPException(status_code=400, detail="暂仅支持 confirm_kind=filter")
    intent = body.intent if body.intent in ("ask", "data", "research") else "ask"
    mode = resolve_request_web_search_mode(body.web_search_mode, body.web_search_enabled, fallback_settings=True)
    try:
        result = await run_light_qa_filter_confirm(
            body.query,
            body.filter,
            web_search_mode=mode,
            intent=intent,  # type: ignore[arg-type]
            scope_paths=body.scope_paths or None,
            skill_id=body.skill_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.session_id:
        try:
            from realai.meta.chat import (
                find_last_assistant_awaiting_confirm,
                get_session,
                update_message,
            )

            sid = body.session_id
            mid = body.message_id
            target = None
            if mid:
                sess = get_session(sid)
                if sess:
                    for m in sess.get("messages") or []:
                        if m.get("id") == mid:
                            target = m
                            break
            if not target:
                target = find_last_assistant_awaiting_confirm(sid)
            content = {
                "text": result.get("answer"),
                "answer": result.get("answer"),
                "conclusion": result.get("conclusion"),
                "evidence": result.get("evidence"),
                "trajectory": result.get("trajectory"),
                "tables": result.get("tables"),
                "chart_spec": result.get("chart_spec"),
                "entity_profile": result.get("entity_profile"),
                "data_query": result.get("data_query"),
                "awaiting_confirm": False,
                "confirm_kind": "filter",
                "filter_draft": result.get("filter_draft"),
                "filter_status": "confirmed",
                "skill_used": result.get("skill_used"),
            }
            if target:
                update_message(sid, target["id"], content)
                result["message_id"] = target["id"]
            result["session_id"] = sid
        except Exception:
            pass
    return result


@router.post("/light/ask/stream")
async def light_ask_stream(body: LightAskRequest):
    """SSE: progress (trajectory) then result or error. Answer is not token-streamed."""
    import asyncio

    intent = body.intent if body.intent in ("ask", "data", "research") else "ask"
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_progress(trajectory: list[str]) -> None:
        await queue.put({"type": "progress", "trajectory": trajectory})

    mode = resolve_request_web_search_mode(body.web_search_mode, body.web_search_enabled, fallback_settings=True)
    vmode = resolve_request_vision_mode(body.vision_mode, fallback_settings=True)

    async def runner() -> None:
        try:
            result = await run_light_qa(
                body.query,
                web_search_mode=mode,
                vision_mode=vmode,
                image_paths=body.image_paths or None,
                intent=intent,  # type: ignore[arg-type]
                scope_paths=body.scope_paths or None,
                session_id=body.session_id,
                skill_id=body.skill_id,
                on_progress=on_progress,
            )
            result = _persist_light_ask_session(body, intent, result)
            await queue.put({"type": "result", "result": result})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(runner())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await task

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/data/sql")
async def data_sql(body: DataSqlRequest):
    try:
        pack = run_vault_sql(body.sql)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"evidence": pack.to_dict()}


@router.post("/report/run")
async def report_run(body: ReportRunRequest):
    mode = resolve_request_web_search_mode(body.web_search_mode, body.web_search_enabled, fallback_settings=True)
    return await run_report_pipeline(
        body.goal,
        step_confirm=body.step_confirm,
        confirmed=body.confirmed,
        outline_override=body.outline,
        scope_paths=body.scope_paths,
        web_search_mode=mode,
    )


@router.post("/report/run/stream")
async def report_run_stream(body: ReportRunRequest):
    mode = resolve_request_web_search_mode(body.web_search_mode, body.web_search_enabled, fallback_settings=True)

    async def event_stream():
        async for event in iter_report_pipeline_events(
            body.goal,
            step_confirm=body.step_confirm,
            confirmed=body.confirmed,
            outline_override=body.outline,
            scope_paths=body.scope_paths,
            web_search_mode=mode,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/onboarding/status")
async def get_onboarding_status():
    return {
        "needed": onboarding_needed(),
        "health": health_snapshot(),
    }


@router.post("/onboarding/complete")
async def post_onboarding_complete(body: OnboardingCompleteRequest):
    try:
        return complete_onboarding(
            api_key=body.api_key,
            web_search_enabled=body.web_search_enabled,
            web_search_mode=body.web_search_mode,
            import_demo=body.import_demo,
            vault_path=body.vault_path,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"向导完成失败: {exc}") from exc


@router.get("/health")
async def realai_health():
    return health_snapshot()
