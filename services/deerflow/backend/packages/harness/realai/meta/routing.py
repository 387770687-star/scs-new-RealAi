"""Model call routing / audit log."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from realai.meta.db import get_db, init_db

_task_context: ContextVar[str | None] = ContextVar("realai_model_call_task", default=None)


@contextmanager
def model_call_task(task_id: str | None):
    """Attach model calls made in the current async context to an auditable task."""
    token = _task_context.set(task_id)
    try:
        yield
    finally:
        _task_context.reset(token)


def log_model_call(
    *,
    purpose: str,
    model: str,
    provider: str = "minimax",
    latency_ms: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    success: bool = True,
    degraded: bool = False,
    fallback_model: str | None = None,
    error: str | None = None,
    task_id: str | None = None,
) -> str:
    init_db()
    task_id = task_id or _task_context.get()
    call_id = f"mc-{uuid.uuid4().hex[:12]}"
    con = get_db()
    try:
        con.execute(
            """
            INSERT INTO model_calls(
              id, created_at, task_id, purpose, model, provider,
              latency_ms, prompt_tokens, completion_tokens,
              success, degraded, fallback_model, error
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                call_id,
                time.time(),
                task_id,
                purpose,
                model,
                provider,
                latency_ms,
                prompt_tokens,
                completion_tokens,
                1 if success else 0,
                1 if degraded else 0,
                fallback_model,
                error,
            ),
        )
        con.commit()
    finally:
        con.close()
    return call_id


def list_routing(limit: int = 50, *, task_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    con = get_db()
    try:
        if task_id:
            rows = con.execute(
                """
                SELECT id, created_at, task_id, purpose, model, provider,
                       latency_ms, prompt_tokens, completion_tokens,
                       success, degraded, fallback_model, error
                FROM model_calls
                WHERE task_id=?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (task_id, max(1, min(limit, 500))),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT id, created_at, task_id, purpose, model, provider,
                       latency_ms, prompt_tokens, completion_tokens,
                       success, degraded, fallback_model, error
                FROM model_calls
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "task_id": r["task_id"],
                "purpose": r["purpose"],
                "model": r["model"],
                "provider": r["provider"],
                "latency_ms": r["latency_ms"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "success": bool(r["success"]),
                "degraded": bool(r["degraded"]),
                "fallback_model": r["fallback_model"],
                "error": r["error"],
            }
            for r in rows
        ]
    finally:
        con.close()
