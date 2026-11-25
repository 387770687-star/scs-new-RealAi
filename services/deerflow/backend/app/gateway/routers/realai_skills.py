"""RealAi Skill product APIs (P3: 查看/维护/执行/导入 + 工坊)."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from realai.agents.skill_optimize import publish_skill_draft, run_skill_optimize
from realai.skills.deerflow_bridge import ensure_skills_layout, is_deerflow_builtin, list_deerflow_skills
from realai.skills.executor import execute_skill, execute_skill_draft
from realai.skills.importer import import_skill_zip
from realai.skills.registry import (
    delete_skill,
    get_skill,
    list_skill_history,
    list_skill_package_files,
    list_skills,
    read_skill_package_file,
    save_skill,
    set_skill_enabled,
)

router = APIRouter(prefix="/api/realai/skills", tags=["realai-skills"])


class SkillUpsertRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    body: str = Field(min_length=1)


class SkillExecuteRequest(BaseModel):
    input: str = Field(min_length=1)


class SkillPreviewExecuteRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    body: str = Field(min_length=1)
    input: str = Field(min_length=1)


class SkillEnabledRequest(BaseModel):
    enabled: bool


class SkillOptimizeChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class SkillOptimizeRequest(BaseModel):
    skill_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    history: list[SkillOptimizeChatMessage] = Field(default_factory=list)
    current_draft: dict[str, str] | None = None


class SkillOptimizePublishRequest(BaseModel):
    publish_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    body: str = Field(min_length=1)
    source_skill_id: str | None = None


class SkillOptimizeTurnRequest(BaseModel):
    message: str = Field(min_length=1)
    current_draft: dict[str, str] | None = None


def _history_from_session(sess: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in sess.get("messages") or []:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or {}
        text = ""
        if isinstance(content, dict):
            text = str(content.get("text") or content.get("answer") or "").strip()
        elif isinstance(content, str):
            text = content.strip()
        if text:
            out.append({"role": role, "content": text})
    return out


def _latest_draft_from_session(sess: dict) -> dict[str, str] | None:
    for m in reversed(sess.get("messages") or []):
        if m.get("role") != "assistant":
            continue
        content = m.get("content") or {}
        draft = content.get("draft") if isinstance(content, dict) else None
        if isinstance(draft, dict) and (draft.get("body") or draft.get("raw")):
            return {str(k): str(v) for k, v in draft.items() if v is not None}
    return None


def _skill_summary(s) -> dict:
    category = getattr(s, "category", "public")
    # 以 is_deerflow_builtin 为准，避免 list_deerflow 补录时 read_only 默认 False
    builtin = is_deerflow_builtin(s.id, category=category) or bool(getattr(s, "read_only", False)) or getattr(s, "source", "") == "deerflow"
    read_only = bool(builtin)
    editable = not read_only
    source = "deerflow" if read_only else "realai"
    # 前端分组：系统内置 vs 业务场景（含 RealAi 预置与用户 custom）
    group = "deerflow_builtin" if read_only else "business"
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "valid": s.valid,
        "errors": s.errors,
        "category": category,
        "enabled": s.enabled,
        "version": s.version,
        "source": source,
        "editable": editable,
        "read_only": read_only,
        "group": group,
    }


@router.get("")
async def skills_list(include_deerflow: bool = False):
    ensure_skills_layout()
    items = list_skills(include_deerflow=include_deerflow)
    return {
        "skills": [_skill_summary(s) for s in items],
        "count": len(items),
    }


@router.get("/workshop")
async def skills_workshop():
    """Unified Skill 工坊列表：RealAi 管理 + 系统内置 public/custom。"""
    ensure_skills_layout()
    items = list_skills(include_deerflow=True)
    realai_count = sum(1 for s in items if not getattr(s, "read_only", s.source == "deerflow"))
    deerflow_count = sum(1 for s in items if getattr(s, "read_only", s.source == "deerflow"))
    return {
        "skills": [_skill_summary(s) for s in items],
        "count": len(items),
        "realai_count": realai_count,
        "deerflow_count": deerflow_count,
        "note": "Agent 对话内激活 Skill 走 DeerFlow（/skill-name）；工坊「试跑」走 RealAi execute。",
    }


@router.post("/optimize")
async def skills_optimize(body: SkillOptimizeRequest):
    """兼容：客户端自带 history 的优化（Skill 页主路径用 /{id}/optimize）。"""
    try:
        return await run_skill_optimize(
            body.skill_id,
            body.message,
            history=[h.model_dump() for h in body.history],
            current_draft=body.current_draft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/optimize/publish")
async def skills_optimize_publish(body: SkillOptimizePublishRequest):
    """发布技能优化草案到 skills/。"""
    try:
        return publish_skill_draft(
            publish_id=body.publish_id,
            name=body.name,
            description=body.description,
            body=body.body,
            source_skill_id=body.source_skill_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{skill_id}/optimize/session")
async def skills_optimize_session_get(skill_id: str):
    """取或建本 Skill 的永久优化对话。"""
    from realai.agents.skill_optimize import _assert_optimizable
    from realai.meta.chat import get_or_create_skill_optimize_session

    try:
        _assert_optimizable(skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sess = get_or_create_skill_optimize_session(skill_id)
    return {"session": sess, "latest_draft": _latest_draft_from_session(sess)}


@router.post("/{skill_id}/optimize")
async def skills_optimize_turn(skill_id: str, body: SkillOptimizeTurnRequest):
    """发送一轮优化：服务端读会话历史并落库。"""
    from realai.meta.chat import append_message, get_or_create_skill_optimize_session, get_session

    try:
        sess = get_or_create_skill_optimize_session(skill_id)
        history = _history_from_session(sess)
        draft = body.current_draft or _latest_draft_from_session(sess)
        result = await run_skill_optimize(
            skill_id,
            body.message,
            history=history,
            current_draft=draft,
        )
        append_message(
            sess["id"],
            role="user",
            content={"text": body.message.strip()},
            auto_title=True,
        )
        append_message(
            sess["id"],
            role="assistant",
            content={
                "text": result.get("answer"),
                "answer": result.get("answer"),
                "draft": result.get("draft"),
                "trajectory": result.get("trajectory"),
                "publish_hint": result.get("publish_hint"),
            },
            auto_title=False,
        )
        updated = get_session(sess["id"])
        return {
            **result,
            "session": updated,
            "session_id": sess["id"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{skill_id}/optimize/messages/{message_id}")
async def skills_optimize_delete_message(skill_id: str, message_id: str):
    from realai.agents.skill_optimize import _assert_optimizable
    from realai.meta.chat import delete_message, get_or_create_skill_optimize_session

    try:
        _assert_optimizable(skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sess = get_or_create_skill_optimize_session(skill_id)
    updated = delete_message(sess["id"], message_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True, "session": updated}


@router.delete("/{skill_id}/optimize/session")
async def skills_optimize_clear_session(skill_id: str):
    from realai.agents.skill_optimize import _assert_optimizable
    from realai.meta.chat import clear_session_messages, get_or_create_skill_optimize_session

    try:
        _assert_optimizable(skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sess = get_or_create_skill_optimize_session(skill_id)
    updated = clear_session_messages(sess["id"])
    return {"ok": True, "session": updated}


@router.post("/preview-execute")
async def skills_preview_execute(body: SkillPreviewExecuteRequest):
    try:
        return await execute_skill_draft(
            name=body.name,
            description=body.description,
            body=body.body,
            user_input=body.input,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import")
async def skills_import(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        imported = import_skill_zip(data)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "imported": imported}


@router.get("/{skill_id}")
async def skills_get(skill_id: str):
    skill = get_skill(skill_id)
    files = list_skill_package_files(skill_id)
    if skill is None:
        deerflow = next((s for s in list_deerflow_skills() if s["id"] == skill_id), None)
        if deerflow is None:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {
            "id": deerflow["id"],
            "name": deerflow["name"],
            "description": deerflow["description"],
            "body": "",
            "valid": True,
            "errors": [],
            "raw": "",
            "category": deerflow["category"],
            "enabled": deerflow["enabled"],
            "version": deerflow.get("version"),
            "source": "deerflow",
            "editable": deerflow["editable"],
            "read_only": True,
            "files": files,
        }
    return {
        **_skill_summary(skill),
        "body": skill.body,
        "raw": skill.raw,
        "files": files,
    }


@router.get("/{skill_id}/files")
async def skills_list_files(skill_id: str):
    if get_skill(skill_id) is None and not list_skill_package_files(skill_id):
        deerflow = next((s for s in list_deerflow_skills() if s["id"] == skill_id), None)
        if deerflow is None:
            raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"skill_id": skill_id, "files": list_skill_package_files(skill_id)}


@router.get("/{skill_id}/file")
async def skills_read_file(skill_id: str, path: str = Query(..., min_length=1)):
    try:
        return read_skill_package_file(skill_id, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件不存在") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{skill_id}/history")
async def skills_history(skill_id: str, limit: int = 20):
    if get_skill(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill 不存在或无版本历史")
    return {"skill_id": skill_id, "history": list_skill_history(skill_id, limit=limit)}


@router.post("/{skill_id}")
async def skills_create(skill_id: str, body: SkillUpsertRequest):
    from realai.skills.deerflow_bridge import is_deerflow_builtin

    if is_deerflow_builtin(skill_id):
        raise HTTPException(status_code=400, detail="系统内置 Skill 只读，不可覆盖")
    if get_skill(skill_id) is not None:
        raise HTTPException(status_code=409, detail=f"Skill '{skill_id}' 已存在，请修改系统标识")
    try:
        rec = save_skill(
            skill_id,
            name=body.name,
            description=body.description,
            body=body.body,
            overwrite=False,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "skill": _skill_summary(rec)}


@router.put("/{skill_id}")
async def skills_update(skill_id: str, body: SkillUpsertRequest):
    from realai.skills.deerflow_bridge import is_deerflow_builtin

    if is_deerflow_builtin(skill_id):
        raise HTTPException(status_code=400, detail="系统内置 Skill 只读，不可修改")
    if get_skill(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    try:
        rec = save_skill(skill_id, name=body.name, description=body.description, body=body.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "skill": _skill_summary(rec)}


@router.patch("/{skill_id}/enabled")
async def skills_set_enabled(skill_id: str, body: SkillEnabledRequest):
    try:
        set_skill_enabled(skill_id, body.enabled)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "id": skill_id, "enabled": body.enabled}


@router.delete("/{skill_id}")
async def skills_delete(skill_id: str):
    try:
        delete_skill(skill_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/{skill_id}/execute")
async def skills_execute(skill_id: str, body: SkillExecuteRequest):
    try:
        return await execute_skill(skill_id, body.input)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
