"""P2: optional external read-only database connections."""

from __future__ import annotations

import logging
from typing import Any

from realai.config import load_settings
from realai.evidence.types import EvidenceItem, EvidencePack, make_data_id

logger = logging.getLogger(__name__)


def query_external_databases(question: str, *, limit: int = 5) -> EvidencePack:
    settings = load_settings()
    dbs: list[dict[str, Any]] = (settings.get("data") or {}).get("databases") or []
    if not dbs:
        return EvidencePack()

    items: list[EvidenceItem] = []
    for cfg in dbs[:3]:
        if not cfg.get("enabled", True):
            continue
        url = cfg.get("url") or ""
        name = cfg.get("name") or "external"
        if not url.startswith(("postgresql://", "postgres://", "mysql://")):
            continue
        try:
            row_text = _sample_readonly(url, limit=limit)
        except Exception as exc:
            logger.warning("external db %s failed: %s", name, exc)
            continue
        if row_text:
            items.append(
                EvidenceItem(
                    id=make_data_id(f"db:{name}", "sample"),
                    type="data",
                    source=f"db:{name}",
                    excerpt=row_text[:400],
                    meta={"connection": name, "readonly": True},
                )
            )
    return EvidencePack(items=items)


def _sample_readonly(url: str, *, limit: int) -> str:
    try:
        import sqlalchemy as sa
        from sqlalchemy import text
    except ImportError as exc:
        raise RuntimeError("sqlalchemy required for external DB") from exc

    engine = sa.create_engine(url, connect_args={"connect_timeout": 5})
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return f"外接库连接成功（只读），请在 P2 配置具体 SELECT 模板。limit={limit}"
