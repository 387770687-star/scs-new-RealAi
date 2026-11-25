"""Metric definitions (口径)."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from realai.meta.db import get_db, init_db
from realai.vault.service import ensure_vault


def _slug_id(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff\-]+", "-", name).strip("-").lower()
    return f"metric-{base[:40] or uuid.uuid4().hex[:8]}"


def create_metric(body: dict[str, Any]) -> dict[str, Any]:
    init_db()
    mid = str(body.get("id") or _slug_id(str(body.get("name") or "metric")))
    now = time.time()
    con = get_db()
    try:
        con.execute(
            """
            INSERT INTO metrics(
              id, created_at, updated_at, name, aliases_json, formula, unit,
              dimensions_json, authority_table, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                mid,
                now,
                now,
                str(body.get("name") or "").strip(),
                json.dumps(body.get("aliases") or [], ensure_ascii=False),
                body.get("formula"),
                body.get("unit"),
                json.dumps(body.get("dimensions") or [], ensure_ascii=False),
                body.get("authority_table"),
                body.get("notes"),
            ),
        )
        con.commit()
    finally:
        con.close()
    _sync_vault_card(get_metric(mid) or {})
    return get_metric(mid)  # type: ignore[return-value]


def update_metric(metric_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    cur = get_metric(metric_id)
    if not cur:
        return None
    merged = {**cur, **{k: v for k, v in body.items() if v is not None}}
    con = get_db()
    try:
        con.execute(
            """
            UPDATE metrics SET updated_at=?, name=?, aliases_json=?, formula=?, unit=?,
              dimensions_json=?, authority_table=?, notes=?
            WHERE id=?
            """,
            (
                time.time(),
                merged.get("name"),
                json.dumps(merged.get("aliases") or [], ensure_ascii=False),
                merged.get("formula"),
                merged.get("unit"),
                json.dumps(merged.get("dimensions") or [], ensure_ascii=False),
                merged.get("authority_table"),
                merged.get("notes"),
                metric_id,
            ),
        )
        con.commit()
    finally:
        con.close()
    out = get_metric(metric_id)
    if out:
        _sync_vault_card(out)
    return out


def delete_metric(metric_id: str) -> bool:
    init_db()
    con = get_db()
    try:
        cur = con.execute("DELETE FROM metrics WHERE id=?", (metric_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def list_metrics() -> list[dict[str, Any]]:
    init_db()
    con = get_db()
    try:
        rows = con.execute("SELECT * FROM metrics ORDER BY updated_at DESC").fetchall()
        return [_row(r) for r in rows]
    finally:
        con.close()


def get_metric(metric_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM metrics WHERE id=?", (metric_id,)).fetchone()
        return _row(r) if r else None
    finally:
        con.close()


def _sync_vault_card(m: dict[str, Any]) -> None:
    if not m.get("id"):
        return
    try:
        root = ensure_vault()
        d = root / "05_Metrics"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{m['id']}.md").write_text(
            f"---\nid: {m['id']}\nname: {m.get('name')}\nunit: {m.get('unit') or ''}\n---\n\n"
            f"# {m.get('name')}\n\n"
            f"- 公式：{m.get('formula') or '—'}\n"
            f"- 单位：{m.get('unit') or '—'}\n"
            f"- 权威表：{m.get('authority_table') or '—'}\n"
            f"- 别名：{', '.join(m.get('aliases') or []) or '—'}\n\n"
            f"{m.get('notes') or ''}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


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
        "updated_at": r["updated_at"],
        "name": r["name"],
        "aliases": loads(r["aliases_json"], []),
        "formula": r["formula"],
        "unit": r["unit"],
        "dimensions": loads(r["dimensions_json"], []),
        "authority_table": r["authority_table"],
        "notes": r["notes"],
    }
