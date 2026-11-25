"""Batch vault import jobs with progress."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from realai.meta.db import get_db, init_db
from realai.vault.import_service import import_file_to_vault
from realai.vault.index import invalidate_vault_index

_jobs_running: set[str] = set()
_job_tasks: set[asyncio.Task[None]] = set()


def create_job(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    init_db()
    jid = f"imp-{uuid.uuid4().hex[:10]}"
    now = time.time()
    items = [
        {
            "name": name,
            "size": len(data),
            "status": "pending",
            "stage": "queued",
            "progress": 0,
            "message": "等待处理",
            "outputs": [],
        }
        for name, data in files
    ]
    con = get_db()
    try:
        con.execute(
            """
            INSERT INTO import_jobs(
              id, created_at, updated_at, status, total, done, failed,
              stage, progress, current_file, message, error, items_json
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                jid,
                now,
                now,
                "queued",
                len(files),
                0,
                0,
                "queued",
                0,
                None,
                "文件已接收，等待处理",
                None,
                json.dumps(items, ensure_ascii=False),
            ),
        )
        con.commit()
    finally:
        con.close()
    # stash payloads in memory keyed by job (dev-scale)
    _PAYLOADS[jid] = files
    return get_job(jid)  # type: ignore[return-value]


_PAYLOADS: dict[str, list[tuple[str, bytes]]] = {}


def get_job(job_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM import_jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return None
        return {
            "id": r["id"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "status": r["status"],
            "total": r["total"],
            "done": r["done"],
            "failed": r["failed"],
            "stage": r["stage"] or "queued",
            "progress": int(r["progress"] or 0),
            "current_file": r["current_file"],
            "message": r["message"] or "",
            "error": r["error"],
            "items": json.loads(r["items_json"] or "[]"),
        }
    finally:
        con.close()


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(int(limit), 100))
    con = get_db()
    try:
        rows = con.execute(
            "SELECT id FROM import_jobs ORDER BY created_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    finally:
        con.close()
    return [job for row in rows if (job := get_job(str(row["id"]))) is not None]


async def run_job(job_id: str) -> None:
    if job_id in _jobs_running:
        return
    _jobs_running.add(job_id)
    try:
        payloads = _PAYLOADS.get(job_id) or []
        job = get_job(job_id)
        if not job:
            return
        if not payloads:
            _update(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                message="导入服务已重启，临时上传内容不可恢复，请重新上传",
                error="missing_upload_payload",
            )
            return
        _update(
            job_id,
            status="running",
            stage="preparing",
            progress=2,
            message="正在准备导入任务",
        )
        items = list(job["items"])
        done = 0
        failed = 0
        written_paths: list[str] = []
        for i, (name, data) in enumerate(payloads):
            item_base = (i / max(len(payloads), 1)) * 88

            async def on_progress(stage: str, progress: int, message: str) -> None:
                item_progress = max(0, min(100, int(progress)))
                items[i] = {
                    **items[i],
                    "status": "running",
                    "stage": stage,
                    "progress": item_progress,
                    "message": message,
                }
                overall = 3 + round(item_base + (item_progress / 100) * (88 / max(len(payloads), 1)))
                _update(
                    job_id,
                    status="running",
                    stage=stage,
                    progress=min(overall, 91),
                    current_file=name,
                    message=message,
                    items=items,
                )

            try:
                await on_progress("validating", 1, "正在校验文件")
                result = await import_file_to_vault(
                    name,
                    data,
                    run_wiki=False,
                    on_progress=on_progress,
                )
                if result.success:
                    outputs = list(
                        dict.fromkeys(
                            [
                                *result.table_paths,
                                *[
                                    path
                                    for path in (
                                        result.markdown_path,
                                        result.vault_path,
                                        result.source_path,
                                    )
                                    if path
                                ],
                            ]
                        )
                    )
                    items[i] = {
                        **items[i],
                        "status": "completed",
                        "stage": "completed",
                        "progress": 100,
                        "message": result.message,
                        "outputs": outputs,
                        "category": result.category,
                    }
                    done += 1
                    if not result.skipped_duplicate:
                        for key in (
                            *result.table_paths,
                            result.markdown_path,
                            result.vault_path,
                        ):
                            if key:
                                written_paths.append(key)
                else:
                    items[i] = {
                        **items[i],
                        "status": "failed",
                        "stage": "failed",
                        "progress": 100,
                        "message": result.message,
                    }
                    failed += 1
            except Exception as exc:
                items[i] = {
                    **items[i],
                    "status": "failed",
                    "stage": "failed",
                    "progress": 100,
                    "message": str(exc),
                }
                failed += 1
            completed_items = done + failed
            _update(
                job_id,
                done=done,
                failed=failed,
                progress=min(91, 3 + round((completed_items / max(len(payloads), 1)) * 88)),
                items=items,
            )
            await asyncio.sleep(0)
        if written_paths:
            try:
                from realai.vault.import_service import finalize_batch_wiki

                _update(
                    job_id,
                    stage="knowledge_processing",
                    progress=93,
                    current_file=None,
                    message="正在生成知识卡片、实体和关系",
                    items=items,
                )
                await finalize_batch_wiki(written_paths)
            except Exception as exc:
                _update(job_id, error=f"知识加工失败：{exc}")
        invalidate_vault_index()
        from realai.vault.catalog import invalidate_vault_catalog

        _update(
            job_id,
            stage="indexing",
            progress=98,
            current_file=None,
            message="正在刷新知识目录和检索索引",
            items=items,
        )
        invalidate_vault_catalog()
        final_status = "failed" if failed and not done else "completed"
        final_message = (
            f"导入完成：成功 {done} 个，失败 {failed} 个"
            if failed
            else f"导入完成：共 {done} 个文件"
        )
        _update(
            job_id,
            status=final_status,
            stage="completed" if final_status == "completed" else "failed",
            progress=100,
            current_file=None,
            message=final_message,
            done=done,
            failed=failed,
            items=items,
        )
    except Exception as exc:
        _update(
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            current_file=None,
            message="导入任务异常终止",
            error=str(exc),
        )
    finally:
        _jobs_running.discard(job_id)
        _PAYLOADS.pop(job_id, None)


def schedule_job(job_id: str) -> None:
    """Start an import independently of the HTTP response lifecycle."""
    # Conversion and third-party parsers contain synchronous work. Running the
    # job on the API event loop can therefore delay the HTTP response until the
    # whole import is finished, which prevents the client from polling progress.
    task = asyncio.create_task(
        asyncio.to_thread(_run_job_in_thread, job_id),
        name=f"vault-import-{job_id}",
    )
    _job_tasks.add(task)
    task.add_done_callback(_job_tasks.discard)


def _run_job_in_thread(job_id: str) -> None:
    asyncio.run(run_job(job_id))


def _update(job_id: str, **fields: Any) -> None:
    sets = ["updated_at=?"]
    vals: list[Any] = [time.time()]
    for k, v in fields.items():
        if k == "items":
            sets.append("items_json=?")
            vals.append(json.dumps(v, ensure_ascii=False))
        elif k in (
            "status",
            "done",
            "failed",
            "total",
            "stage",
            "progress",
            "current_file",
            "message",
            "error",
        ):
            sets.append(f"{k}=?")
            vals.append(v)
    vals.append(job_id)
    con = get_db()
    try:
        con.execute(f"UPDATE import_jobs SET {', '.join(sets)} WHERE id=?", vals)
        con.commit()
    finally:
        con.close()
