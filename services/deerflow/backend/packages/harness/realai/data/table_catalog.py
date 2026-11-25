"""Vault table catalog cached in realai_meta.sqlite for ask-data routing."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import duckdb

from realai.meta.db import get_db, init_db
from realai.vault.clean_table import is_geometry_column
from realai.vault.paths import sql_string_literal
from realai.vault.scope import matches_scope
from realai.vault.service import SKIP_DIRS, ensure_vault

logger = logging.getLogger(__name__)

DATA_EXTENSIONS = {".csv", ".xlsx", ".xls"}

_ENSURED = False


def _ensure_catalog_table() -> None:
    global _ENSURED
    if _ENSURED:
        return
    init_db()
    con = get_db()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS table_catalog (
              path TEXT PRIMARY KEY,
              category TEXT,
              columns_json TEXT NOT NULL,
              types_json TEXT,
              row_count INTEGER,
              sample_json TEXT,
              semantic_json TEXT,
              mtime REAL,
              updated_at REAL NOT NULL
            )
            """
        )
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(table_catalog)").fetchall()}
        if "types_json" not in columns:
            con.execute("ALTER TABLE table_catalog ADD COLUMN types_json TEXT")
        if "semantic_json" not in columns:
            con.execute("ALTER TABLE table_catalog ADD COLUMN semantic_json TEXT")
        con.commit()
    finally:
        con.close()
    _ENSURED = True


def _category_of(rel: str) -> str:
    top = rel.replace("\\", "/").split("/", 1)[0]
    return top


def _inspect_file(path: Path) -> dict[str, Any] | None:
    safe = sql_string_literal(path.as_posix())
    con = duckdb.connect(database=":memory:")
    try:
        if path.suffix.lower() == ".csv":
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_csv_auto('{safe}', strict_mode=false, ignore_errors=true, null_padding=true)")
        else:
            try:
                con.execute("INSTALL excel")
                con.execute("LOAD excel")
                con.execute(f"CREATE TABLE t AS SELECT * FROM read_xlsx('{safe}')")
            except Exception:
                return None
        described = con.execute("DESCRIBE t").fetchall()
        cols = [r[0] for r in described]
        types = {str(r[0]): str(r[1]) for r in described}
        cols = [c for c in cols if not is_geometry_column(c)]
        types = {column: types[column] for column in cols}
        if not cols:
            return None
        show = cols[:16]
        col_sql = ", ".join(f'"{c}"' for c in show)
        sample_df = con.execute(f"SELECT {col_sql} FROM t LIMIT 3").fetchdf()
        row_count = int(con.execute("SELECT COUNT(*) FROM t").fetchone()[0])
        sample: list[dict[str, str]] = []
        for _, row in sample_df.iterrows():
            sample.append({c: "" if row.get(c) is None else str(row[c]) for c in show})
        return {
            "columns": cols,
            "types": types,
            "row_count": row_count,
            "sample": sample,
        }
    except Exception:
        logger.debug("inspect failed %s", path, exc_info=True)
        return None
    finally:
        con.close()


def _default_semantic(rel: str, info: dict[str, Any]) -> dict[str, Any]:
    columns = [str(column) for column in (info.get("columns") or [])]
    year_columns = [column for column in columns if re.fullmatch(r"(?:19|20)\d{2}年?", column.strip())]
    long_year_columns = [column for column in columns if column.strip().lower() in {"year", "yr", "年份", "年度"}]
    stem = Path(rel).stem
    stem = re.sub(r"-[0-9a-f]{8}$", "", stem, flags=re.IGNORECASE)
    stem = stem.split("__", 1)[0]
    return {
        "title": stem,
        "sheet_name": None,
        "unit": None,
        "layout": ("wide_year" if len(year_columns) >= 2 else "long_year" if long_year_columns else "tabular"),
        "year_columns": year_columns,
        "dimension_columns": [
            column
            for column in columns
            if column not in year_columns
            and any(
                token in column.lower()
                for token in (
                    "地区",
                    "省",
                    "市",
                    "名称",
                    "项目",
                    "类别",
                    "类型",
                    "region",
                    "name",
                )
            )
        ],
        "aliases": [stem],
    }


def _semantic_for_upsert(
    con: Any,
    rel: str,
    info: dict[str, Any],
    supplied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if supplied:
        return supplied
    existing = con.execute(
        "SELECT semantic_json FROM table_catalog WHERE path=?",
        (rel,),
    ).fetchone()
    if existing and existing["semantic_json"]:
        try:
            parsed = json.loads(existing["semantic_json"])
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            pass
    return _default_semantic(rel, info)


def rebuild_table_catalog(*, scope_paths: list[str] | None = None) -> dict[str, Any]:
    """Full rescan of Vault data files into table_catalog."""
    _ensure_catalog_table()
    root = ensure_vault()
    now = time.time()
    upserted = 0
    con = get_db()
    try:
        seen: list[str] = []
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in DATA_EXTENSIONS:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            rel = p.relative_to(root).as_posix()
            if not matches_scope(rel, scope_paths):
                continue
            info = _inspect_file(p)
            if not info:
                continue
            mtime = p.stat().st_mtime
            con.execute(
                """
                INSERT INTO table_catalog(path, category, columns_json, types_json, row_count, sample_json, semantic_json, mtime, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                  category=excluded.category,
                  columns_json=excluded.columns_json,
                  types_json=excluded.types_json,
                  row_count=excluded.row_count,
                  sample_json=excluded.sample_json,
                  semantic_json=excluded.semantic_json,
                  mtime=excluded.mtime,
                  updated_at=excluded.updated_at
                """,
                (
                    rel,
                    _category_of(rel),
                    json.dumps(info["columns"], ensure_ascii=False),
                    json.dumps(info["types"], ensure_ascii=False),
                    info["row_count"],
                    json.dumps(info["sample"], ensure_ascii=False),
                    json.dumps(_semantic_for_upsert(con, rel, info), ensure_ascii=False),
                    mtime,
                    now,
                ),
            )
            seen.append(rel)
            upserted += 1
        # drop stale
        if seen:
            placeholders = ",".join("?" * len(seen))
            con.execute(f"DELETE FROM table_catalog WHERE path NOT IN ({placeholders})", seen)
        else:
            con.execute("DELETE FROM table_catalog")
        con.commit()
    finally:
        con.close()
    return {"upserted": upserted}


def refresh_catalog_paths(
    paths: list[str],
    *,
    metadata_by_path: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Incremental refresh for imported paths (and csv sidecars)."""
    _ensure_catalog_table()
    root = ensure_vault()
    now = time.time()
    con = get_db()
    try:
        for rel in paths:
            rel = rel.replace("\\", "/")
            p = root / rel
            if not p.is_file() or p.suffix.lower() not in DATA_EXTENSIONS:
                continue
            info = _inspect_file(p)
            if not info:
                continue
            con.execute(
                """
                INSERT INTO table_catalog(path, category, columns_json, types_json, row_count, sample_json, semantic_json, mtime, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                  category=excluded.category,
                  columns_json=excluded.columns_json,
                  types_json=excluded.types_json,
                  row_count=excluded.row_count,
                  sample_json=excluded.sample_json,
                  semantic_json=excluded.semantic_json,
                  mtime=excluded.mtime,
                  updated_at=excluded.updated_at
                """,
                (
                    rel,
                    _category_of(rel),
                    json.dumps(info["columns"], ensure_ascii=False),
                    json.dumps(info["types"], ensure_ascii=False),
                    info["row_count"],
                    json.dumps(info["sample"], ensure_ascii=False),
                    json.dumps(
                        _semantic_for_upsert(
                            con,
                            rel,
                            info,
                            (metadata_by_path or {}).get(rel),
                        ),
                        ensure_ascii=False,
                    ),
                    p.stat().st_mtime,
                    now,
                ),
            )
        con.commit()
    finally:
        con.close()


def list_catalog_paths(*, scope_paths: list[str] | None = None) -> list[str]:
    _ensure_catalog_table()
    con = get_db()
    try:
        rows = con.execute("SELECT path FROM table_catalog ORDER BY updated_at DESC").fetchall()
        paths = [str(r["path"]) for r in rows]
    finally:
        con.close()
    if not paths:
        # lazy rebuild once
        rebuild_table_catalog(scope_paths=scope_paths)
        con = get_db()
        try:
            rows = con.execute("SELECT path FROM table_catalog ORDER BY updated_at DESC").fetchall()
            paths = [str(r["path"]) for r in rows]
        finally:
            con.close()
    return [rel for rel in paths if matches_scope(rel, scope_paths)]


def list_catalog_schemas(
    *,
    scope_paths: list[str] | None = None,
    limit: int = 12,
    query_hint: str = "",
) -> list[dict[str, Any]]:
    """Schemas for NL2SQL prompt; prefer paths matching query tokens."""
    _ensure_catalog_table()
    paths = list_catalog_paths(scope_paths=scope_paths)
    con = get_db()
    try:
        entries: list[dict[str, Any]] = []
        for rel in paths:
            row = con.execute(
                "SELECT path, category, columns_json, types_json, row_count, sample_json, semantic_json FROM table_catalog WHERE path=?",
                (rel,),
            ).fetchone()
            if not row:
                continue
            cols = json.loads(row["columns_json"] or "[]")
            types = json.loads(row["types_json"] or "{}")
            samples = json.loads(row["sample_json"] or "[]")
            semantic = json.loads(row["semantic_json"] or "{}")
            score = 0
            sample_blob = " ".join(str(value) for sample in samples[:3] for value in (sample.values() if isinstance(sample, dict) else []))
            semantic_blob = " ".join(
                str(value)
                for value in (
                    semantic.get("title"),
                    semantic.get("sheet_name"),
                    semantic.get("unit"),
                    *(semantic.get("aliases") or []),
                )
                if value
            )
            blob = (rel + " " + " ".join(cols) + " " + sample_blob + " " + semantic_blob).lower()
            for tok in re_findall_tokens(query_hint):
                if tok in blob:
                    score += 2
            stem = Path(rel).stem.split("__", 1)[0]
            stem = re.sub(r"-[0-9a-f]{8}$", "", stem, flags=re.IGNORECASE)
            if stem and stem.lower() in (query_hint or "").lower():
                score += 12
            for column in cols:
                base = re.sub(r"[_（(].*$", "", str(column)).strip().lower()
                if len(base) >= 2 and base in (query_hint or "").lower():
                    score += 8
            for sample in samples[:3]:
                if not isinstance(sample, dict):
                    continue
                for value in sample.values():
                    text = str(value).strip().lower()
                    if len(text) >= 2 and text in (query_hint or "").lower():
                        score += 6
            query_lower = (query_hint or "").lower()
            category = str(row["category"] or "")
            metric_question = bool(
                re.search(
                    r"(预测|统计|成本|费用|金额|数量|总量|人口|gdp|多少|趋势|年度|20\d{2}年?)",
                    query_lower,
                )
            )
            pipeline_question = bool(re.search(r"(管段|管线|站场|压气站|管径|设计压力|里程)", query_lower))
            requested_years = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", query_lower)
            if category == "dataqa" and metric_question:
                score += 8
            if category == "pipelines":
                if pipeline_question:
                    score += 8
                elif metric_question:
                    score -= 8
            for year in requested_years:
                if any(year in str(column) for column in cols) or year in sample_blob:
                    score += 10
                else:
                    score -= 4
            entries.append(
                {
                    "path": row["path"],
                    "category": row["category"],
                    "columns": cols,
                    "types": types,
                    "samples": samples,
                    "row_count": row["row_count"],
                    "semantic": semantic
                    or _default_semantic(
                        rel,
                        {"columns": cols},
                    ),
                    "score": score,
                }
            )
        entries.sort(key=lambda e: e["score"], reverse=True)
        return entries[:limit]
    finally:
        con.close()


def re_findall_tokens(text: str) -> list[str]:
    import re

    raw = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", (text or "").lower())
    tokens: list[str] = []
    for value in raw:
        if len(value) >= 2 and value not in tokens:
            tokens.append(value)
        if re.fullmatch(r"[\u4e00-\u9fff]+", value) and len(value) > 2:
            for index in range(len(value) - 1):
                token = value[index : index + 2]
                if token not in tokens:
                    tokens.append(token)
    return tokens[:48]
