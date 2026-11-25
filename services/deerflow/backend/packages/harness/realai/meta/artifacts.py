"""Reusable artifacts (conclusions / tables / charts)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from realai.meta.db import get_db, init_db
from realai.vault.service import ensure_vault


def create_artifact(
    *,
    kind: str,
    title: str,
    content: dict[str, Any],
    evidence_ids: list[str] | None = None,
    source_task: str | None = None,
    persist_vault: bool = True,
) -> dict[str, Any]:
    init_db()
    aid = f"art-{uuid.uuid4().hex[:12]}"
    now = time.time()
    con = get_db()
    try:
        con.execute(
            """
            INSERT INTO artifacts(id, created_at, kind, title, content_json, evidence_ids_json, source_task)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                aid,
                now,
                kind,
                title,
                json.dumps(content, ensure_ascii=False),
                json.dumps(evidence_ids or [], ensure_ascii=False),
                source_task,
            ),
        )
        con.commit()
    finally:
        con.close()

    if persist_vault:
        try:
            root = ensure_vault()
            out_dir = root / "10_Outputs" / "artifacts"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{aid}.md").write_text(
                f"---\nid: {aid}\nkind: {kind}\ntitle: {title}\n---\n\n"
                f"# {title}\n\n```json\n{json.dumps(content, ensure_ascii=False, indent=2)}\n```\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    return get_artifact(aid)  # type: ignore[return-value]


def list_artifacts(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    con = get_db()
    try:
        rows = con.execute(
            "SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        con.close()


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        return _row(r) if r else None
    finally:
        con.close()


def _row(r: Any) -> dict[str, Any]:
    def loads(s: str | None, default: Any):
        if not s:
            return default
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return default

    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "kind": r["kind"],
        "title": r["title"],
        "content": loads(r["content_json"], {}),
        "evidence_ids": loads(r["evidence_ids_json"], []),
        "source_task": r["source_task"],
    }
