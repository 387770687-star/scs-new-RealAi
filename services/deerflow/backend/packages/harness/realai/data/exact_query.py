"""Deterministic exact lookup for uploaded tabular data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import duckdb

from realai.data.sql_engine import _register_file, _safe_alias
from realai.data.table_catalog import list_catalog_schemas
from realai.evidence.types import EvidenceItem, EvidencePack, make_data_id
from realai.vault.service import ensure_vault

_NUMERIC_TYPES = (
    "INT",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "HUGEINT",
)
_DIMENSION_HINTS = ("年", "日期", "时间", "项目", "名称", "类型", "类别", "编号", "地区", "区域")
_MEASURE_HINTS = (
    "成本",
    "费用",
    "金额",
    "数量",
    "总量",
    "收入",
    "利润",
    "率",
    "占比",
    "价格",
    "单价",
    "长度",
    "压力",
    "输量",
    "人口",
    "gdp",
)


@dataclass
class ExactQueryResult:
    pack: EvidencePack = field(default_factory=EvidencePack)
    sql: str | None = None
    candidates: int = 0
    error: str | None = None


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _column_base(value: str) -> str:
    base = re.sub(r"[_（(].*$", "", value).strip().lower()
    return re.sub(r"^(综合|累计|总体|全量)", "", base)


def _measure_score(question: str, column: str, column_type: str) -> int:
    q = question.lower()
    base = _column_base(column)
    score = 0
    if column.lower() in q:
        score += 30
    if len(base) >= 2 and base in q:
        score += 24
    for hint in _MEASURE_HINTS:
        if hint in q and hint in base:
            score += 12
    if any(token in column_type.upper() for token in _NUMERIC_TYPES):
        score += 4
    if any(hint in base for hint in _DIMENSION_HINTS):
        score -= 12
    return score


def _candidate_measures(question: str, schema: dict[str, Any]) -> list[str]:
    types = schema.get("types") or {}
    scored = [(_measure_score(question, str(column), str(types.get(column) or "")), str(column)) for column in (schema.get("columns") or [])]
    scored = [item for item in scored if item[0] >= 12]
    scored.sort(reverse=True)
    if not scored:
        return []
    threshold = max(12, scored[0][0] - 8)
    return [column for score, column in scored[:3] if score >= threshold]


def _dimension_columns(schema: dict[str, Any], measures: list[str]) -> list[str]:
    types = schema.get("types") or {}
    dimensions: list[str] = []
    for raw in schema.get("columns") or []:
        column = str(raw)
        if column in measures:
            continue
        column_type = str(types.get(column) or "").upper()
        if "CHAR" in column_type or "TEXT" in column_type or any(hint in column.lower() for hint in _DIMENSION_HINTS):
            dimensions.append(column)
    return dimensions[:12]


def _wide_year_columns(schema: dict[str, Any]) -> list[str]:
    return [
        str(column)
        for column in (schema.get("columns") or [])
        if re.fullmatch(r"(?:19|20)\d{2}年?", str(column).strip())
    ]


def _year_dimension_columns(schema: dict[str, Any]) -> list[str]:
    return [
        str(column)
        for column in (schema.get("columns") or [])
        if str(column).strip().lower() in {"year", "yr", "年份", "年度"}
    ][:2]


def _year_label(column: str) -> str | None:
    matched = re.fullmatch(r"((?:19|20)\d{2})年?", column.strip())
    return matched.group(1) if matched else None


def _rows_from_frame(frame: Any, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for _, row in frame.head(limit).iterrows():
        item: dict[str, str] = {}
        for column in frame.columns:
            value = row[column]
            item[str(column)] = "" if value is None or (isinstance(value, float) and value != value) else str(value)
        rows.append(item)
    return rows


def _query_candidate(
    question: str,
    schema: dict[str, Any],
    *,
    limit: int,
) -> tuple[Any | None, str | None, list[Any]]:
    path = ensure_vault() / str(schema["path"])
    if not path.is_file():
        return None, None, []
    year_values = list(dict.fromkeys(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", question)))
    wide_years = _wide_year_columns(schema)
    requested_wide = [
        column
        for column in wide_years
        if _year_label(column) in year_values
    ]
    wants_year_series = bool(
        re.search(r"(趋势|变化|走势|折线|图表|可视化|逐年|历年)", question)
    )
    series_measures = wide_years if wants_year_series and len(wide_years) >= 2 else []
    measures = requested_wide or series_measures or _candidate_measures(question, schema)
    if not measures:
        return None, None, []

    year_dimensions = _year_dimension_columns(schema)
    dimensions = [
        column
        for column in _dimension_columns(schema, measures)
        if column not in year_dimensions and column not in wide_years
    ]
    if requested_wide or series_measures:
        selected = list(dict.fromkeys([*dimensions[:4], *measures]))
    else:
        selected = list(dict.fromkeys([*year_dimensions, *dimensions[:4], *measures]))
    select_sql = ", ".join(_quote_identifier(column) for column in selected)

    fixed_conditions: list[str] = []
    fixed_params: list[Any] = []
    if year_values and year_dimensions:
        fixed_conditions.append(f"TRY_CAST({_quote_identifier(year_dimensions[0])} AS BIGINT) = ?")
        fixed_params.append(int(year_values[0]))

    text_conditions = [(f"LENGTH(TRIM(CAST({_quote_identifier(column)} AS VARCHAR))) >= 2 AND STRPOS(?, TRIM(CAST({_quote_identifier(column)} AS VARCHAR))) > 0") for column in dimensions]
    attempts: list[tuple[list[str], list[Any]]] = []
    if text_conditions:
        attempts.append(
            (
                [*fixed_conditions, "(" + " OR ".join(text_conditions) + ")"],
                [*fixed_params, *([question] * len(text_conditions))],
            )
        )
    if fixed_conditions:
        attempts.append((fixed_conditions, fixed_params))
    if not attempts:
        return None, None, []

    alias = _safe_alias(str(schema["path"]))
    con = duckdb.connect(database=":memory:")
    try:
        _register_file(con, path, alias)
        for conditions, params in attempts:
            sql = f"SELECT {select_sql} FROM {alias} WHERE " + " AND ".join(conditions) + f" LIMIT {int(limit)}"
            frame = con.execute(sql, params).fetchdf()
            if frame is not None and not frame.empty:
                return frame, sql, params
    except Exception:
        return None, None, []
    finally:
        con.close()
    return None, None, []


def run_exact_query(
    question: str,
    *,
    scope_paths: list[str] | None = None,
    limit: int = 20,
) -> ExactQueryResult:
    """Answer direct table lookups without requiring an LLM-generated SQL query."""
    schemas = list_catalog_schemas(
        scope_paths=scope_paths,
        limit=20,
        query_hint=question,
    )
    for schema in schemas:
        frame, sql, params = _query_candidate(question, schema, limit=limit)
        if frame is None or frame.empty or not sql:
            continue
        rows = _rows_from_frame(frame, limit)
        columns = [str(column) for column in frame.columns]
        path = str(schema["path"])
        semantic = schema.get("semantic") or {}
        excerpt = "; ".join(" | ".join(row.values()) for row in rows[:5])[:500]
        return ExactQueryResult(
            pack=EvidencePack(
                items=[
                    EvidenceItem(
                        id=make_data_id(path, "exact_lookup"),
                        type="data",
                        source=path,
                        excerpt=excerpt,
                        meta={
                            "engine": "duckdb",
                            "mode": "exact",
                            "query_strategy": "deterministic",
                            "sql": sql,
                            "sql_params": params,
                            "path": path,
                            "source_paths": [path],
                            "tables_used": [path],
                            "locator": "exact_lookup",
                            "confidence": "computed",
                            "columns": columns,
                            "rows": rows,
                            "title": semantic.get("title"),
                            "sheet_name": semantic.get("sheet_name"),
                            "unit": semantic.get("unit"),
                            "layout": semantic.get("layout"),
                            "口径": "按上传表字段和行值进行确定性精确匹配",
                        },
                    )
                ]
            ),
            sql=sql,
            candidates=len(schemas),
        )
    return ExactQueryResult(candidates=len(schemas), error="no_exact_match")
