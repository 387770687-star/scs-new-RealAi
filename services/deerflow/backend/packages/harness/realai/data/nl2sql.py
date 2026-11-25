"""Read-only NL2SQL over Vault tables via LLM + DuckDB."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import duckdb

from realai.config import load_settings
from realai.data.sql_engine import (
    _FORBIDDEN_SQL,
    _list_data_files,
    _register_file,
    _safe_alias,
)
from realai.data.table_catalog import list_catalog_schemas
from realai.evidence.types import EvidenceItem, EvidencePack, make_data_id
from realai.vault.service import ensure_vault

logger = logging.getLogger(__name__)

_SQL_BLOCK_RE = re.compile(r"```(?:sql)?\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass
class Nl2SqlResult:
    pack: EvidencePack = field(default_factory=EvidencePack)
    sql: str | None = None
    candidates: int = 0
    error: str | None = None


def run_nl2sql(
    question: str,
    *,
    scope_paths: list[str] | None = None,
    limit: int = 20,
) -> Nl2SqlResult:
    schemas = list_catalog_schemas(scope_paths=scope_paths, limit=10, query_hint=question)
    if not schemas:
        return Nl2SqlResult(error="no_tables")

    alias_map: dict[str, str] = {}
    schema_lines = []
    for s in schemas:
        alias = _safe_alias(s["path"])
        alias_map[alias] = s["path"]
        types = s.get("types") or {}
        cols = ", ".join(f"{column} {types.get(column, '')}".strip() for column in s["columns"][:24])
        samples = s.get("samples") or []
        sample_text = ""
        if samples:
            pairs = [", ".join(f"{key}={value}" for key, value in sample.items()) for sample in samples[:2] if isinstance(sample, dict)]
            if pairs:
                sample_text = f"; examples: {'; '.join(pairs)[:500]}"
        semantic = s.get("semantic") or {}
        semantic_text = ", ".join(
            str(value)
            for value in (
                f"title={semantic.get('title')}" if semantic.get("title") else None,
                f"sheet={semantic.get('sheet_name')}" if semantic.get("sheet_name") else None,
                f"unit={semantic.get('unit')}" if semantic.get("unit") else None,
                f"layout={semantic.get('layout')}" if semantic.get("layout") else None,
            )
            if value
        )
        schema_lines.append(
            f"- VIEW `{alias}` ← file `{s['path']}` ({s.get('row_count') or '?'} rows)"
            f"{'; ' + semantic_text if semantic_text else ''}; columns: {cols}{sample_text}"
        )

    sql = _generate_sql(question, "\n".join(schema_lines), list(alias_map.keys()))
    if not sql:
        return Nl2SqlResult(candidates=len(schemas), error="sql_gen_failed")

    sql = sql.strip().rstrip(";")
    if _FORBIDDEN_SQL.search(sql) or not sql.lower().startswith("select"):
        return Nl2SqlResult(candidates=len(schemas), sql=sql, error="sql_rejected")

    root = ensure_vault()
    con = duckdb.connect(database=":memory:")
    try:
        registered = 0
        for s in schemas:
            path = root / s["path"]
            if not path.is_file():
                continue
            alias = _safe_alias(s["path"])
            try:
                _register_file(con, path, alias)
                registered += 1
            except Exception:
                continue
        if registered == 0:
            # fallback register first files
            for path in _list_data_files(root)[:8]:
                rel = path.relative_to(root).as_posix()
                try:
                    _register_file(con, path, _safe_alias(rel))
                    alias_map[_safe_alias(rel)] = rel
                    registered += 1
                except Exception:
                    continue
        if registered == 0:
            return Nl2SqlResult(candidates=len(schemas), sql=sql, error="register_failed")

        exec_sql = sql if " limit " in sql.lower() else f"{sql} LIMIT {int(limit)}"
        df = con.execute(exec_sql).fetchdf()
        if df is None or df.empty:
            return Nl2SqlResult(
                pack=EvidencePack(),
                sql=exec_sql,
                candidates=len(schemas),
                error="empty",
            )
        cols = [str(c) for c in df.columns]
        rows: list[dict[str, Any]] = []
        for _, row in df.head(limit).iterrows():
            item = {}
            for c in cols:
                v = row[c]
                if v is None or (isinstance(v, float) and v != v):
                    item[c] = ""
                else:
                    item[c] = str(v)
            rows.append(item)
        excerpt = "; ".join(" | ".join(str(v) for v in list(r.values())[:8]) for r in rows[:5])[:500]
        source_paths = [path for alias, path in alias_map.items() if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", exec_sql)]
        source_paths = list(dict.fromkeys(source_paths))
        alignment_error = _validate_result_alignment(
            question,
            exec_sql,
            source_paths=source_paths,
            schemas=schemas,
            columns=cols,
            rows=rows,
        )
        if alignment_error:
            return Nl2SqlResult(
                sql=exec_sql,
                candidates=len(schemas),
                error=alignment_error,
            )
        source = source_paths[0] if len(source_paths) == 1 else "sql:nl2sql"
        selected_semantic = next(
            (
                schema.get("semantic") or {}
                for schema in schemas
                if schema.get("path") in source_paths
            ),
            {},
        )
        return Nl2SqlResult(
            pack=EvidencePack(
                items=[
                    EvidenceItem(
                        id=make_data_id(source, "query_result"),
                        type="data",
                        source=source,
                        excerpt=excerpt,
                        meta={
                            "engine": "duckdb",
                            "mode": "nl2sql",
                            "sql": exec_sql,
                            "path": source,
                            "locator": "nl2sql",
                            "confidence": "computed",
                            "columns": cols,
                            "rows": rows,
                            "title": selected_semantic.get("title"),
                            "sheet_name": selected_semantic.get("sheet_name"),
                            "unit": selected_semantic.get("unit"),
                            "layout": selected_semantic.get("layout"),
                            "口径": "由模型根据表目录生成只读 SQL，请核对口径",
                            "source_paths": source_paths,
                            "tables_used": source_paths,
                        },
                    )
                ]
            ),
            sql=exec_sql,
            candidates=len(schemas),
        )
    except Exception as exc:
        logger.debug("nl2sql exec failed: %s", exc, exc_info=True)
        return Nl2SqlResult(candidates=len(schemas), sql=sql, error=str(exc))
    finally:
        con.close()


def _generate_sql(question: str, schema_text: str, aliases: list[str]) -> str | None:
    from realai.llm import chat_text_sync, has_api_key

    settings = load_settings()
    if not has_api_key(settings):
        return _heuristic_sql(question, aliases)
    system = (
        "你是 DuckDB SQL 助手。只输出一条只读 SELECT 语句（可含 JOIN），不要解释。"
        "禁止 INSERT/UPDATE/DELETE/DROP/CREATE/ATTACH。只能使用给出的 VIEW 别名与列名。"
        "中文列名用双引号包裹。若年份作为多列横向展开（如“2026年”“2027年”），"
        "用户问某一年时应直接 SELECT 对应年份列，不要把该列自身 CAST 后与年份比较。"
        "优先选择标题、工作表、列名、样例值与问题实体和年份同时匹配的表。"
    )
    user = f"可用表：\n{schema_text}\n\n问题：{question}\n\n请生成 SQL："
    try:
        content = chat_text_sync(
            user,
            system=system,
            role="fast",
            temperature=0.1,
            max_tokens=512,
            timeout=45.0,
            purpose="nl2sql",
        )
        return _extract_sql(content)
    except Exception:
        logger.debug("nl2sql llm failed", exc_info=True)
        return _heuristic_sql(question, aliases)


def _extract_sql(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    m = _SQL_BLOCK_RE.search(t)
    if m:
        t = m.group(1).strip()
    # take first select...
    lower = t.lower()
    idx = lower.find("select")
    if idx < 0:
        return None
    t = t[idx:]
    # cut trailing prose
    for stop in ("\n\n", "；\n", "。\n"):
        cut = t.find(stop)
        if cut > 10:
            t = t[:cut]
    return t.strip().rstrip(";")


def _validate_result_alignment(
    question: str,
    sql: str,
    *,
    source_paths: list[str],
    schemas: list[dict[str, Any]],
    columns: list[str],
    rows: list[dict[str, Any]],
) -> str | None:
    if not source_paths:
        return "missing_lineage"

    selected_scores = [
        int(schema.get("score") or 0)
        for schema in schemas
        if schema.get("path") in source_paths
    ]
    best_score = max((int(schema.get("score") or 0) for schema in schemas), default=0)
    if best_score >= 8 and (not selected_scores or max(selected_scores) < max(4, best_score - 8)):
        return "low_table_alignment"

    result_blob = " ".join(
        [
            sql,
            *columns,
            *[
                str(value)
                for row in rows[:5]
                for value in row.values()
            ],
        ]
    )
    requested_years = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", question)
    if any(year not in result_blob for year in requested_years):
        return "year_not_aligned"
    return None


def _heuristic_sql(question: str, aliases: list[str]) -> str | None:
    if not aliases:
        return None
    a = aliases[0]
    if any(k in question for k in ("成本", "费用")):
        return f"SELECT * FROM {a} LIMIT 20"
    if any(k in question for k in ("合计", "总和", "sum")):
        return f"SELECT * FROM {a} LIMIT 20"
    return None
