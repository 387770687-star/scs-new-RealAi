"""Server-side writing tasks."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from realai.meta.db import get_db, init_db


def create_task(
    goal: str,
    *,
    step_confirm: bool = False,
    report_type: str | None = None,
    template_id: str | None = None,
    outline_confirm_required: bool = False,
    audience: str | None = None,
    scope_paths: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    skill_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    init_db()
    tid = f"wt-{uuid.uuid4().hex[:12]}"
    now = time.time()
    meta = {
        "report_type": report_type or "regional",
        # template_id=None 表示用户未选模板；与内部 report_type 回退值分开保存。
        "template_id": template_id,
        "outline_confirm_required": bool(outline_confirm_required),
        "audience": audience or "",
        "scope_paths": scope_paths or [],
        "attachments": attachments or [],
        # Immutable task-level copy. A later edit/deletion of the source Skill
        # must not change the method used halfway through an existing report.
        "skill_profile": dict(skill_profile) if skill_profile else None,
        "knowledge_cards": [],
        "scorecards": [],
        "intake": {
            "status": "pending",
            "mode": "smart_gap_fill",
            "local_context": {},
            "missing_fields": [],
            "evidence_brief": [],
            "questions": [],
            "user_provided_facts": [],
            "diagnostics": {"attempts": [], "latest": {}},
            "skill_id": "strategic-planning-intake",
        },
    }
    con = get_db()
    try:
        con.execute(
            """
            INSERT INTO writing_tasks(
              id, created_at, updated_at, goal, status, step_confirm,
              outline_json, progress_json, result_json, error, artifact_ids_json, meta_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tid,
                now,
                now,
                goal.strip(),
                "draft",
                1 if step_confirm else 0,
                None,
                "[]",
                None,
                None,
                "[]",
                json.dumps(meta, ensure_ascii=False),
            ),
        )
        con.commit()
    finally:
        con.close()
    return get_task(tid)  # type: ignore[return-value]


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    con = get_db()
    try:
        rows = con.execute(
            "SELECT * FROM writing_tasks ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        con.close()


def get_task(task_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM writing_tasks WHERE id=?", (task_id,)).fetchone()
        return _row(r) if r else None
    finally:
        con.close()


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    init_db()
    allowed = {
        "goal",
        "status",
        "step_confirm",
        "outline_json",
        "progress_json",
        "result_json",
        "error",
        "artifact_ids_json",
        "meta_json",
    }
    # Convenience: merge meta dict
    if "meta" in fields and "meta_json" not in fields:
        fields["meta_json"] = fields.pop("meta")
    sets = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "step_confirm":
            v = 1 if v else 0
        if k.endswith("_json") and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return get_task(task_id)
    sets.append("updated_at=?")
    vals.append(time.time())
    vals.append(task_id)
    con = get_db()
    try:
        con.execute(f"UPDATE writing_tasks SET {', '.join(sets)} WHERE id=?", vals)
        con.commit()
    finally:
        con.close()
    return get_task(task_id)


def merge_meta(task_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    task = get_task(task_id)
    if not task:
        return None
    meta = dict(task.get("meta") or {})
    meta.update(patch)
    return update_task(task_id, meta_json=meta)


def pause_interrupted_running_tasks(reason: str = "Gateway 重启，任务已在最近检查点暂停") -> int:
    """Turn orphaned request-time runs into resumable paused tasks.

    Writing workers are process-local. Any row still marked ``running`` during
    Gateway startup belongs to a worker that no longer exists. Preserve its
    latest checkpoint and expose a normal "continue" action instead of leaving
    the UI in a permanent ghost-running state.
    """

    init_db()
    con = get_db()
    try:
        rows = con.execute("SELECT id FROM writing_tasks WHERE status='running'").fetchall()
    finally:
        con.close()

    recovered = 0
    for row in rows:
        task_id = row["id"]
        task = get_task(task_id)
        if not task or task.get("status") != "running":
            continue
        meta = dict(task.get("meta") or {})
        result = dict(task.get("result") or {})
        checkpoint = dict(meta.get("checkpoint") or result)
        outline = dict(checkpoint.get("outline") or task.get("outline") or {})
        drafts = list(checkpoint.get("chapter_drafts") or outline.get("chapter_drafts") or [])
        if drafts:
            outline["chapter_drafts"] = drafts
        resume_from = checkpoint.get("resume_from") or meta.get("resume_from")
        resume_chapter_index = checkpoint.get("resume_chapter_index")
        if resume_chapter_index is None:
            resume_chapter_index = meta.get("resume_chapter_index") or 0
        result.update(checkpoint)
        result.update(
            {
                "run_mode": "report",
                "phase": "paused",
                "message": reason,
                "resume_from": resume_from,
                "resume_chapter_index": int(resume_chapter_index or 0),
                "outline": outline,
                "chapter_drafts": drafts,
                "checkpoint": True,
            }
        )
        meta.update(
            {
                "checkpoint": checkpoint or result,
                "resume_from": resume_from,
                "resume_chapter_index": int(resume_chapter_index or 0),
            }
        )
        update_task(
            task_id,
            status="paused",
            outline_json=outline,
            result_json=result,
            meta_json=meta,
            error=reason,
        )
        recovered += 1
    return recovered


def delete_task(task_id: str) -> bool:
    init_db()
    con = get_db()
    try:
        cur = con.execute("DELETE FROM writing_tasks WHERE id=?", (task_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def append_artifact(task_id: str, artifact_id: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    if not task:
        return None
    ids = list(task.get("artifact_ids") or [])
    if artifact_id not in ids:
        ids.append(artifact_id)
    return update_task(task_id, artifact_ids_json=ids)


def _row(r: Any) -> dict[str, Any]:
    def loads(s: str | None, default: Any):
        if not s:
            return default
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return default

    keys = set(r.keys()) if hasattr(r, "keys") else set()
    meta = loads(r["meta_json"] if "meta_json" in keys else None, {})
    # 旧任务没有 template_id，按原 report_type 模板处理，避免历史行为改变。
    template_id = meta.get("template_id") if "template_id" in meta else (meta.get("report_type") or "regional")
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "goal": r["goal"],
        "status": r["status"],
        "step_confirm": bool(r["step_confirm"]),
        "outline": loads(r["outline_json"], {}),
        "progress": loads(r["progress_json"], []),
        "result": loads(r["result_json"], None),
        "error": r["error"],
        "artifact_ids": loads(r["artifact_ids_json"], []),
        "meta": meta,
        "report_type": meta.get("report_type") or "regional",
        "template_id": template_id,
        "outline_confirm_required": bool(meta.get("outline_confirm_required")),
        "audience": meta.get("audience") or "",
        "scope_paths": meta.get("scope_paths") or [],
        "knowledge_cards": meta.get("knowledge_cards") or ((loads(r["result_json"], None) or {}).get("knowledge_cards") if r["result_json"] else []) or [],
        "scorecards": meta.get("scorecards") or ((loads(r["result_json"], None) or {}).get("scorecards") if r["result_json"] else []) or [],
        "intake": meta.get("intake"),
        "skill_profile": meta.get("skill_profile"),
    }
