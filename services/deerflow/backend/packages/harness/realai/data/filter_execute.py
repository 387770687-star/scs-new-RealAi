"""Execute confirmed column filters across Vault tables (UNION ALL merge)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb

from realai.data.column_semantics import is_numeric_field
from realai.data.sql_engine import _register_file, _safe_alias
from realai.data.table_catalog import list_catalog_paths, list_catalog_schemas
from realai.evidence.types import EvidenceItem, EvidencePack, make_data_id
from realai.vault.paths import sql_string_literal
from realai.vault.service import ensure_vault

logger = logging.getLogger(__name__)

_SHOW_COLS = (
    "pipe_section_name",
    "pipeline_name",
    "start_station_name",
    "end_station_name",
    "pipe_section_length",
    "pipe_diameter",
    "design_pressure",
    "design_trans_flow_rate",
    "use_status",
    "owner_company",
)


def execute_filter(
    draft: dict[str, Any],
    *,
    scope_paths: list[str] | None = None,
    limit: int = 500,
) -> tuple[EvidencePack, dict[str, Any]]:
    """Return (pack with one merged table item, stats)."""
    conditions = list(draft.get("conditions") or [])
    if not conditions:
        return EvidencePack(), {"candidates": 0, "hits": 0, "sql": None}

    field_keys = [str(c["field_key"]) for c in conditions]
    tables = _pick_tables(field_keys, scope_paths=scope_paths)
    stats = {"candidates": len(tables), "hits": 0, "sql": None, "files": [t[0] for t in tables]}
    if not tables:
        empty = _empty_item(draft, "未找到包含全部筛选字段的数据表")
        return EvidencePack(items=[empty]), stats

    root = ensure_vault()
    con = duckdb.connect(database=":memory:")
    try:
        parts: list[str] = []
        aliases_ok: list[str] = []
        for rel, cols in tables:
            path = root / rel
            if not path.is_file():
                continue
            alias = _safe_alias(rel)
            try:
                _register_file(con, path, alias)
            except Exception:
                logger.debug("register failed %s", rel, exc_info=True)
                continue
            show = [c for c in _SHOW_COLS if c in cols] or [c for c in cols if c in field_keys][:8]
            for fk in field_keys:
                if fk in cols and fk not in show:
                    show.append(fk)
            rel_lit = rel.replace("'", "''")
            select_cols = ", ".join([f"'{rel_lit}' AS source_file"] + [f'"{c}"' for c in show])
            where = _where_sql(conditions, cols)
            if not where:
                continue
            parts.append(f"SELECT {select_cols} FROM {alias} WHERE {where}")
            aliases_ok.append(rel)

        if not parts:
            empty = _empty_item(draft, "无法在候选表上构造筛选条件")
            return EvidencePack(items=[empty]), stats

        sql = " UNION ALL ".join(parts) + f" LIMIT {int(limit)}"
        stats["sql"] = sql
        df = con.execute(sql).fetchdf()
        cols = [str(c) for c in df.columns]
        rows: list[dict[str, Any]] = []
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                item: dict[str, Any] = {}
                for c in cols:
                    v = row[c]
                    if v is None or (isinstance(v, float) and v != v):
                        item[c] = ""
                    else:
                        item[c] = str(v)
                rows.append(item)
        stats["hits"] = len(rows)
        stats["files"] = aliases_ok

        title_hint = draft.get("title_hint") or "筛选结果"
        excerpt = (
            f"命中 {len(rows)} 行（{len(aliases_ok)} 个文件）；条件：{title_hint}"
            if rows
            else f"无命中行；条件：{title_hint}"
        )
        # Prefer Chinese header for source_file in UI via columns as-is; FE can label
        display_cols = cols
        item = EvidenceItem(
            id=make_data_id("filter:union", "filter:union"),
            type="data",
            source="filter:union",
            excerpt=excerpt[:600],
            meta={
                "engine": "duckdb",
                "mode": "filter_union",
                "path": "filter:union",
                "locator": "filter:union",
                "confidence": "computed",
                "columns": display_cols,
                "rows": rows,
                "sql": sql,
                "口径": f"跨表 AND 筛选：{title_hint}",
                "match_rows": len(rows),
                "title": f"筛选结果 · {title_hint}",
                "files": aliases_ok,
            },
        )
        return EvidencePack(items=[item]), stats
    except Exception as exc:
        logger.exception("execute_filter failed")
        empty = _empty_item(draft, f"筛选执行失败：{exc}")
        return EvidencePack(items=[empty]), stats
    finally:
        con.close()


def _pick_tables(
    field_keys: list[str],
    *,
    scope_paths: list[str] | None,
) -> list[tuple[str, list[str]]]:
    """Return (rel_path, columns) that contain all field_keys; prefer pipelines/."""
    try:
        schemas = list_catalog_schemas(scope_paths=scope_paths, limit=80, query_hint=" ".join(field_keys))
    except Exception:
        schemas = []

    out: list[tuple[str, list[str], int]] = []
    if schemas:
        for s in schemas:
            cols = [str(c) for c in (s.get("columns") or [])]
            colset = set(cols)
            if all(k in colset for k in field_keys):
                rel = str(s["path"])
                score = 10 if rel.startswith("pipelines/") else 0
                score += int(s.get("score") or 0)
                out.append((rel, cols, score))
    else:
        # fallback filesystem via catalog paths or vault walk
        root = ensure_vault()
        try:
            paths = list_catalog_paths(scope_paths=scope_paths)
        except Exception:
            paths = []
        if not paths:
            from realai.vault.service import SKIP_DIRS

            for p in root.rglob("*.csv"):
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                paths.append(p.relative_to(root).as_posix())
        for rel in paths:
            path = root / rel
            if not path.is_file():
                continue
            cols = _peek_columns(path)
            if cols and all(k in cols for k in field_keys):
                score = 10 if rel.startswith("pipelines/") else 0
                out.append((rel, cols, score))

    out.sort(key=lambda x: x[2], reverse=True)
    return [(r, c) for r, c, _ in out[:40]]


def _peek_columns(path: Path) -> list[str]:
    safe = sql_string_literal(path.as_posix())
    con = duckdb.connect(database=":memory:")
    try:
        if path.suffix.lower() == ".csv":
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_csv_auto('{safe}') LIMIT 0")
        else:
            return []
        return [r[0] for r in con.execute("DESCRIBE t").fetchall()]
    except Exception:
        return []
    finally:
        con.close()


def _where_sql(conditions: list[dict[str, Any]], cols: list[str]) -> str:
    clauses: list[str] = []
    colset = set(cols)
    for c in conditions:
        key = str(c.get("field_key") or "")
        if key not in colset:
            return ""  # table missing a required column
        op = str(c.get("op") or "eq")
        norm = c.get("value_normalized")
        raw = str(c.get("value") or "")
        col_ref = f'CAST("{key}" AS VARCHAR)'
        if op == "contains":
            lit = raw.replace("'", "''")
            clauses.append(f"{col_ref} ILIKE '%{lit}%'")
            continue
        if is_numeric_field(key) and isinstance(norm, (int, float)):
            num = float(norm)
            casted = f'TRY_CAST("{key}" AS DOUBLE)'
            if op == "eq":
                clauses.append(f"{casted} = {num}")
            elif op == "ne":
                clauses.append(f"({casted} IS NULL OR {casted} <> {num})")
            elif op == "gt":
                clauses.append(f"{casted} > {num}")
            elif op == "gte":
                clauses.append(f"{casted} >= {num}")
            elif op == "lt":
                clauses.append(f"{casted} < {num}")
            elif op == "lte":
                clauses.append(f"{casted} <= {num}")
            else:
                clauses.append(f"{casted} = {num}")
        else:
            lit = str(norm if norm is not None else raw).replace("'", "''")
            if op == "eq":
                clauses.append(f"{col_ref} = '{lit}'")
            elif op == "ne":
                clauses.append(f"{col_ref} <> '{lit}'")
            else:
                # fallback compare as double if possible
                try:
                    num = float(lit)
                    casted = f'TRY_CAST("{key}" AS DOUBLE)'
                    sql_op = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(op, "=")
                    clauses.append(f"{casted} {sql_op} {num}")
                except ValueError:
                    clauses.append(f"{col_ref} ILIKE '%{lit}%'")
    return " AND ".join(clauses) if clauses else ""


def _empty_item(draft: dict[str, Any], message: str) -> EvidenceItem:
    hint = draft.get("title_hint") or ""
    cols = ["source_file"] + [str(c.get("field_key")) for c in (draft.get("conditions") or [])]
    return EvidenceItem(
        id=make_data_id("filter:union", "filter:empty"),
        type="data",
        source="filter:union",
        excerpt=f"{message}；条件：{hint}"[:600],
        meta={
            "engine": "duckdb",
            "mode": "filter_union",
            "path": "filter:union",
            "locator": "filter:union",
            "columns": cols,
            "rows": [],
            "match_rows": 0,
            "title": f"筛选结果 · {hint}" if hint else "筛选结果",
            "口径": message,
        },
    )
