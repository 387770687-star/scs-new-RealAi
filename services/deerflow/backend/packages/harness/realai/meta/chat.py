"""Persistent chat sessions (no TTL)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from realai.meta.db import get_db, init_db


def list_sessions(*, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    con = get_db()
    try:
        rows = con.execute(
            """
            SELECT id, title, created_at, updated_at, intent, meta_json
            FROM chat_sessions
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "intent": r["intent"],
                    "meta": json.loads(r["meta_json"] or "{}"),
                }
            )
        return out
    finally:
        con.close()


def create_session(
    *,
    title: str = "新对话",
    intent: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    init_db()
    sid = f"chat-{uuid.uuid4().hex[:12]}"
    now = time.time()
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    con = get_db()
    try:
        con.execute(
            """
            INSERT INTO chat_sessions(id, title, created_at, updated_at, intent, meta_json)
            VALUES (?,?,?,?,?,?)
            """,
            (sid, title.strip() or "新对话", now, now, intent, meta_json),
        )
        con.commit()
    finally:
        con.close()
    return get_session(sid)  # type: ignore[return-value]


def delete_message(session_id: str, message_id: str) -> dict[str, Any] | None:
    """Delete one message; return updated session or None if session missing."""
    init_db()
    con = get_db()
    try:
        exists = con.execute("SELECT id FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not exists:
            return None
        cur = con.execute(
            "DELETE FROM chat_messages WHERE id=? AND session_id=?",
            (message_id, session_id),
        )
        if cur.rowcount <= 0:
            return get_session(session_id)
        con.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE id=?",
            (time.time(), session_id),
        )
        con.commit()
    finally:
        con.close()
    return get_session(session_id)


def clear_session_messages(session_id: str) -> dict[str, Any] | None:
    """Remove all messages in a session; keep the session row."""
    init_db()
    con = get_db()
    try:
        exists = con.execute("SELECT id FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not exists:
            return None
        con.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        con.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE id=?",
            (time.time(), session_id),
        )
        con.commit()
    finally:
        con.close()
    return get_session(session_id)


SKILL_OPTIMIZE_INTENT = "skill_optimize"


def get_or_create_skill_optimize_session(skill_id: str) -> dict[str, Any]:
    """One permanent optimize chat per skill_id (intent=skill_optimize)."""
    sid_key = (skill_id or "").strip()
    if not sid_key:
        raise ValueError("skill_id 不能为空")
    init_db()
    con = get_db()
    try:
        rows = con.execute(
            """
            SELECT id, meta_json FROM chat_sessions
            WHERE intent=?
            ORDER BY updated_at DESC
            """,
            (SKILL_OPTIMIZE_INTENT,),
        ).fetchall()
        for r in rows:
            meta = json.loads(r["meta_json"] or "{}")
            if str(meta.get("skill_id") or "") == sid_key:
                found = get_session(r["id"])
                if found:
                    return found
    finally:
        con.close()

    return create_session(
        title=f"优化·{sid_key}",
        intent=SKILL_OPTIMIZE_INTENT,
        meta={"skill_id": sid_key},
    )


def get_session(session_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not r:
            return None
        msgs = con.execute(
            """
            SELECT id, role, content_json, created_at
            FROM chat_messages WHERE session_id=?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
        return {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "intent": r["intent"],
            "meta": json.loads(r["meta_json"] or "{}"),
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": json.loads(m["content_json"] or "{}"),
                    "created_at": m["created_at"],
                }
                for m in msgs
            ],
        }
    finally:
        con.close()


def rename_session(session_id: str, title: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        con.execute(
            "UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?",
            (title.strip() or "未命名", time.time(), session_id),
        )
        con.commit()
    finally:
        con.close()
    return get_session(session_id)


def delete_session(session_id: str) -> bool:
    init_db()
    con = get_db()
    try:
        cur = con.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def update_message(
    session_id: str,
    message_id: str,
    content: dict[str, Any],
) -> dict[str, Any] | None:
    """Replace content_json of an existing message (e.g. filter confirm patch)."""
    init_db()
    con = get_db()
    try:
        cur = con.execute(
            """
            UPDATE chat_messages
            SET content_json=?
            WHERE id=? AND session_id=?
            """,
            (json.dumps(content, ensure_ascii=False), message_id, session_id),
        )
        if cur.rowcount <= 0:
            return None
        con.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE id=?",
            (time.time(), session_id),
        )
        con.commit()
    finally:
        con.close()
    return get_session(session_id)


def find_last_assistant_awaiting_confirm(session_id: str) -> dict[str, Any] | None:
    sess = get_session(session_id)
    if not sess:
        return None
    for m in reversed(sess.get("messages") or []):
        if m.get("role") != "assistant":
            continue
        c = m.get("content") or {}
        if c.get("awaiting_confirm"):
            return m
    return None


def append_message(
    session_id: str,
    *,
    role: str,
    content: dict[str, Any],
    auto_title: bool = True,
) -> dict[str, Any] | None:
    init_db()
    mid = f"msg-{uuid.uuid4().hex[:12]}"
    now = time.time()
    con = get_db()
    try:
        exists = con.execute("SELECT id, title FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not exists:
            return None
        con.execute(
            """
            INSERT INTO chat_messages(id, session_id, role, content_json, created_at)
            VALUES (?,?,?,?,?)
            """,
            (mid, session_id, role, json.dumps(content, ensure_ascii=False), now),
        )
        title = exists["title"]
        if auto_title and role == "user" and (not title or title in ("新对话", "未命名")):
            text = str(content.get("text") or content.get("query") or "")[:40]
            if text:
                title = text
        con.execute(
            "UPDATE chat_sessions SET updated_at=?, title=? WHERE id=?",
            (now, title, session_id),
        )
        con.commit()
    finally:
        con.close()
    return get_session(session_id)
