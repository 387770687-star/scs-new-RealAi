"""Excel/CSV read-only query: entity row-match, catalog, NL2SQL fallback."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import duckdb

from realai.data.external_db import query_external_databases
from realai.data.sql_engine import query_multi_table
from realai.evidence.types import EvidenceItem, EvidencePack, make_data_id
from realai.vault.clean_table import is_geometry_column
from realai.vault.paths import sql_string_literal
from realai.vault.scope import matches_scope
from realai.vault.service import SKIP_DIRS, ensure_vault

logger = logging.getLogger(__name__)

DATA_EXTENSIONS = {".csv", ".xlsx", ".xls"}

_DATA_KEYS = (
    "成本",
    "费用",
    "金额",
    "指标",
    "多少",
    "降低",
    "增长",
    "excel",
    "表",
    "数据",
    "率",
    "%",
    "里程",
    "管径",
    "压力",
    "输量",
    "介绍",
    "概况",
    "合计",
    "平均",
    "统计",
)
_SECTION_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9#]{2,40}_[\u4e00-\u9fffA-Za-z0-9#]{2,40}")
_STATION_HINT = re.compile(r"[\u4e00-\u9fff]{2,20}(?:压气站|分输清管站|分输站|清管站|分输压气站|接收站|储气库|阀室|联络站)")
# Bigrams that appear in almost every pipeline CSV — do not use for table scoring.
_GENERIC_TOKENS = frozenset(
    {
        "压气",
        "气站",
        "分输",
        "清管",
        "管道",
        "天然",
        "然气",
        "气管道",
        "管线",
        "站场",
        "工程",
        "公司",
        "集团",
        "介绍",
        "概况",
        "数据",
        "多少",
    }
)

DataIntent = Literal["entity", "metric_stats", "free_query"]
RowMatchLimit = 50


@dataclass
class DataQueryResult:
    pack: EvidencePack = field(default_factory=EvidencePack)
    mode: str = "none"  # entity_match | nl2sql | multi_table | preview | none
    match_terms: list[str] = field(default_factory=list)
    candidates: int = 0
    hits: int = 0
    entity_name: str | None = None
    entity_type: str | None = None  # station | pipe_section | pipeline
    sql: str | None = None
    intent: DataIntent = "free_query"
    error: str | None = None


@dataclass
class TablePreviewResult:
    pack: EvidencePack = field(default_factory=EvidencePack)
    candidates: int = 0
    best_score: int = 0
    reason: str | None = None


def _tokenize(query: str) -> list[str]:
    raw = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_#]+", query.lower())
    tokens: list[str] = []
    for part in raw:
        if len(part) >= 2 and part not in tokens:
            tokens.append(part)
        if re.fullmatch(r"[\u4e00-\u9fff]+", part) and len(part) > 3:
            for i in range(len(part) - 1):
                bi = part[i : i + 2]
                if bi not in tokens and bi not in _GENERIC_TOKENS:
                    tokens.append(bi)
    return tokens[:32]


def needs_data_query(query: str, *, force: bool = False) -> bool:
    if force:
        return True
    if any(k in query for k in _DATA_KEYS):
        return True
    if _SECTION_RE.search(query) or _STATION_HINT.search(query):
        return True
    return False


_needs_data_query = needs_data_query


def _in_scope(rel: str, scope_paths: list[str] | None) -> bool:
    return matches_scope(rel, scope_paths)


def extract_entity_terms(query: str) -> tuple[list[str], str | None, str | None]:
    """Return (match_terms, primary_name, entity_type)."""
    q = (query or "").strip()
    terms: list[str] = []
    primary: str | None = None
    etype: str | None = None

    sections = _SECTION_RE.findall(q)
    for m in re.finditer(r"[\u4e00-\u9fffA-Za-z0-9#]{4,40}(?:_[\u4e00-\u9fffA-Za-z0-9#]{2,40})+", q):
        if m.group(0) not in sections:
            sections.append(m.group(0))
    stations = _STATION_HINT.findall(q)

    if sections:
        primary = sections[0]
        etype = "pipe_section"
        terms.extend(sections)
    if stations:
        if not primary:
            primary = stations[0]
            etype = "station"
        for s in stations:
            if s not in terms:
                terms.append(s)

    # Entity title dictionary (wiki)
    try:
        from realai.vault.wiki.entity_pages import list_entity_titles

        titles = list_entity_titles()
        for t in titles:
            if t and t in q and t not in terms:
                terms.append(t)
                if not primary:
                    primary = t
                    path = titles[t]
                    if "/station/" in path.replace("\\", "/"):
                        etype = "station"
                    elif "/pipe_section/" in path.replace("\\", "/"):
                        etype = "pipe_section"
                    elif "/pipeline/" in path.replace("\\", "/"):
                        etype = "pipeline"
    except Exception:
        logger.debug("entity titles skipped", exc_info=True)

    # Graph one-hop for recall
    if primary:
        try:
            from realai.vault.wiki.graph_index import neighbor_titles

            for n in neighbor_titles(primary, limit=12):
                if n and n not in terms:
                    terms.append(n)
        except Exception:
            logger.debug("neighbor titles skipped", exc_info=True)

    # Prefer longer terms first (more specific matches)
    terms = sorted(dict.fromkeys(terms), key=len, reverse=True)
    return terms[:24], primary, etype


def classify_data_intent(query: str, match_terms: list[str]) -> DataIntent:
    if match_terms:
        return "entity"
    if any(k in query for k in ("成本", "费用", "降低", "增长", "合计", "平均", "统计", "多少", "率", "%")):
        return "metric_stats"
    return "free_query"


def run_structured_data_query(
    query: str,
    *,
    limit: int = 8,
    force: bool = False,
    scope_paths: list[str] | None = None,
) -> DataQueryResult:
    if not needs_data_query(query, force=force):
        return DataQueryResult()

    match_terms, primary, etype = extract_entity_terms(query)
    intent = classify_data_intent(query, match_terms)

    if intent == "entity" and match_terms:
        return _query_entity_rows(
            query,
            match_terms=match_terms,
            primary=primary,
            etype=etype,
            limit=limit,
            scope_paths=scope_paths,
        )

    # metric / free: deterministic lookup first, then catalog-assisted NL2SQL.
    try:
        from realai.data.exact_query import run_exact_query

        exact = run_exact_query(query, scope_paths=scope_paths, limit=20)
        if exact.pack.items:
            return DataQueryResult(
                pack=exact.pack,
                mode="exact",
                match_terms=match_terms,
                candidates=exact.candidates,
                hits=len(exact.pack.items),
                entity_name=primary,
                entity_type=etype,
                sql=exact.sql,
                intent=intent,
            )
    except Exception:
        logger.debug("exact query skipped", exc_info=True)

    # LLM-generated SQL, then multi-table, then soft preview.
    try:
        from realai.data.nl2sql import run_nl2sql

        nl = run_nl2sql(query, scope_paths=scope_paths, limit=20)
        if nl.pack.items:
            return DataQueryResult(
                pack=nl.pack,
                mode="nl2sql",
                match_terms=match_terms,
                candidates=nl.candidates,
                hits=len(nl.pack.items),
                entity_name=primary,
                entity_type=etype,
                sql=nl.sql,
                intent=intent,
            )
    except Exception:
        logger.debug("nl2sql skipped", exc_info=True)

    multi = query_multi_table(query, limit=limit, scope_paths=scope_paths)
    if multi.items:
        return DataQueryResult(
            pack=multi,
            mode="multi_table",
            match_terms=match_terms,
            candidates=len(multi.items),
            hits=len(multi.items),
            entity_name=primary,
            entity_type=etype,
            intent=intent,
        )

    ext = query_external_databases(query, limit=limit)
    if ext.items:
        return DataQueryResult(
            pack=ext,
            mode="external",
            hits=len(ext.items),
            intent=intent,
        )

    # Last resort preview only for non-entity (and only if forced/metric)
    if intent != "entity":
        preview = _preview_top_tables(query, limit=min(limit, 2), scope_paths=scope_paths)
        if preview.pack.items:
            return DataQueryResult(
                pack=preview.pack,
                mode="preview",
                candidates=preview.candidates,
                hits=len(preview.pack.items),
                intent=intent,
            )

    return DataQueryResult(
        intent=intent,
        match_terms=match_terms,
        entity_name=primary,
        entity_type=etype,
        candidates=preview.candidates if intent != "entity" else 0,
        error=preview.reason if intent != "entity" else "no_match",
    )


def query_vault_data(
    query: str,
    *,
    limit: int = 3,
    force: bool = False,
    scope_paths: list[str] | None = None,
) -> EvidencePack:
    return run_structured_data_query(query, limit=limit, force=force, scope_paths=scope_paths).pack


def _query_entity_rows(
    query: str,
    *,
    match_terms: list[str],
    primary: str | None,
    etype: str | None,
    limit: int,
    scope_paths: list[str] | None,
) -> DataQueryResult:
    root = ensure_vault()
    tokens = _tokenize(query)
    # Prefer catalog paths when available
    files: list[tuple[Path, str]] = []
    try:
        from realai.data.table_catalog import list_catalog_paths

        for rel in list_catalog_paths(scope_paths=scope_paths):
            p = root / rel
            if p.is_file():
                files.append((p, rel))
    except Exception:
        logger.debug("catalog list skipped", exc_info=True)

    if not files:
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in DATA_EXTENSIONS:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            rel = p.relative_to(root).as_posix()
            if not _in_scope(rel, scope_paths):
                continue
            files.append((p, rel))

    candidates = 0
    scored: list[tuple[int, EvidenceItem]] = []
    for path, rel in files:
        candidates += 1
        # Cheap prefilter: skip file if none of the match terms appear in sample/path
        if not _file_might_match(path, rel, match_terms):
            continue
        try:
            item = _match_rows(path, rel, match_terms, tokens, row_limit=RowMatchLimit)
        except Exception:
            continue
        if not item:
            continue
        hit_n = int(item.meta.get("match_rows") or 0)
        path_score = _score_table_path(path, rel, tokens, match_terms)
        score = hit_n * 100 + path_score
        item.meta["table_score"] = score
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    items = [it for _, it in scored[:limit]]
    return DataQueryResult(
        pack=EvidencePack(items=items),
        mode="entity_match",
        match_terms=match_terms,
        candidates=candidates,
        hits=len(items),
        entity_name=primary,
        entity_type=etype,
        intent="entity",
    )


def _file_might_match(path: Path, rel: str, match_terms: list[str]) -> bool:
    blob = rel.lower()
    for t in match_terms:
        if t.lower() in blob:
            return True
    if path.suffix.lower() != ".csv":
        return True  # try excel; costlier but rare
    try:
        sample = path.read_text(encoding="utf-8", errors="replace")[:200000].lower()
    except OSError:
        return True
    return any(t.lower() in sample for t in match_terms)


def _score_table_path(
    path: Path,
    rel: str,
    tokens: list[str],
    match_terms: list[str],
    *,
    query: str = "",
) -> int:
    blob = rel.lower()
    score = 0
    for t in tokens:
        if t in _GENERIC_TOKENS:
            continue
        if t in blob:
            score += 3
    for sn in match_terms:
        if sn.lower() in blob:
            score += 25
    if path.suffix.lower() == ".csv":
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:12000].lower()
        except OSError:
            sample = ""
        for t in tokens:
            if t in _GENERIC_TOKENS:
                continue
            if t in sample:
                score += 2
        for sn in match_terms:
            if sn.lower() in sample:
                score += 60
        query_lower = query.lower()
        metric_question = bool(
            re.search(
                r"(预测|统计|成本|费用|金额|数量|总量|人口|gdp|多少|趋势|年度|20\d{2}年?)",
                query_lower,
            )
        )
        pipeline_question = bool(re.search(r"(管段|管线|站场|压气站|管径|设计压力|里程)", query_lower))
        category = rel.replace("\\", "/").split("/", 1)[0]
        if category == "dataqa" and metric_question:
            score += 6
        if category == "pipelines":
            if pipeline_question:
                score += 6
            elif metric_question:
                score -= 8
        requested_years = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", query_lower)
        for year in requested_years:
            if year in sample or year in blob:
                score += 8
            else:
                score -= 6
    return score


def _business_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if not is_geometry_column(c)]


def _df_rows_as_dicts(rows, columns: list[str], limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, row in rows.head(limit).iterrows():
        item: dict[str, Any] = {}
        for c in columns:
            v = row[c] if c in row.index else None
            if v is None or (isinstance(v, float) and v != v):
                item[c] = ""
            else:
                item[c] = str(v)
        out.append(item)
    return out


def _preview_top_tables(
    query: str,
    *,
    limit: int,
    scope_paths: list[str] | None,
) -> TablePreviewResult:
    root = ensure_vault()
    tokens = _tokenize(query)
    scored: list[tuple[int, Path, str]] = []
    candidates = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in DATA_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        if not _in_scope(rel, scope_paths):
            continue
        candidates += 1
        score = _score_table_path(p, rel, tokens, [], query=query)
        if score > 0:
            scored.append((score, p, rel))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0] if scored else 0
    if best_score < 8:
        return TablePreviewResult(
            candidates=candidates,
            best_score=best_score,
            reason="low_confidence",
        )
    items: list[EvidenceItem] = []
    for score, path, rel in scored[:limit]:
        try:
            item = _summarize_table(path, rel, tokens)
        except Exception:
            continue
        if item:
            item.meta["table_score"] = score
            items.append(item)
    return TablePreviewResult(
        pack=EvidencePack(items=items),
        candidates=candidates,
        best_score=best_score,
        reason=None if items else "preview_failed",
    )


def _summarize_table(path: Path, rel: str, tokens: list[str] | None = None) -> EvidenceItem | None:
    con = duckdb.connect(database=":memory:")
    safe = sql_string_literal(path.as_posix())
    try:
        if path.suffix.lower() == ".csv":
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_csv_auto('{safe}')")
        else:
            try:
                con.execute("INSTALL excel")
                con.execute("LOAD excel")
                con.execute(f"CREATE TABLE t AS SELECT * FROM read_xlsx('{safe}')")
            except Exception:
                return None
        cols = [r[0] for r in con.execute("DESCRIBE t").fetchall()]
        cols = _business_columns(cols)
        if not cols:
            return None
        show_cols = cols[:12]
        col_sql = ", ".join(f'"{c}"' for c in show_cols)
        rows = con.execute(f"SELECT {col_sql} FROM t LIMIT 5").fetchdf()
        if rows.empty:
            return None
        table_rows = _df_rows_as_dicts(rows, show_cols, limit=5)
        excerpt_parts = []
        for item in table_rows:
            excerpt_parts.append(" | ".join(item.get(c, "") for c in show_cols[:8]))
        excerpt = "; ".join(excerpt_parts)[:500]
        cell_ref = "preview:rows1-5"
        return EvidenceItem(
            id=make_data_id(rel, cell_ref),
            type="data",
            source=rel,
            excerpt=excerpt,
            meta={
                "engine": "duckdb",
                "preview_rows": min(5, len(rows)),
                "path": rel,
                "locator": cell_ref,
                "confidence": "computed",
                "columns": show_cols,
                "rows": table_rows,
            },
        )
    finally:
        con.close()


def _match_rows(
    path: Path,
    rel: str,
    match_terms: list[str],
    tokens: list[str],
    *,
    row_limit: int = RowMatchLimit,
) -> EvidenceItem | None:
    if not match_terms:
        return None
    con = duckdb.connect(database=":memory:")
    safe = sql_string_literal(path.as_posix())
    try:
        if path.suffix.lower() == ".csv":
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_csv_auto('{safe}')")
        else:
            try:
                con.execute("INSTALL excel")
                con.execute("LOAD excel")
                con.execute(f"CREATE TABLE t AS SELECT * FROM read_xlsx('{safe}')")
            except Exception:
                return None
        cols = [r[0] for r in con.execute("DESCRIBE t").fetchall()]
        cols = _business_columns(cols)
        prefer = [
            c
            for c in cols
            if c
            in (
                "pipe_section_name",
                "pipeline_name",
                "start_station_name",
                "end_station_name",
                "管段名称",
                "管线名称",
                "起点站",
                "终点站",
            )
            or "name" in c.lower()
            or "站" in c
        ]
        search_cols = prefer or [c for c in cols if c.lower() not in ("id", "code")][:8]
        if not search_cols:
            return None

        clauses = []
        for sn in match_terms:
            lit = sn.replace("'", "''")
            for c in search_cols:
                clauses.append(f"CAST(\"{c}\" AS VARCHAR) ILIKE '%{lit}%'")
        if not clauses:
            return None
        where = " OR ".join(clauses)
        show_cols = [
            c
            for c in (
                "pipe_section_name",
                "pipeline_name",
                "start_station_name",
                "end_station_name",
                "pipe_section_length",
                "pipe_diameter",
                "design_pressure",
                "design_trans_flow_rate",
                "medium_tran",
                "use_status",
                "owner_company",
            )
            if c in cols
        ] or cols[:10]
        col_sql = ", ".join(f'"{c}"' for c in show_cols)
        try:
            rows = con.execute(f"SELECT {col_sql} FROM t WHERE {where} LIMIT {int(row_limit)}").fetchdf()
        except Exception:
            return None
        if rows.empty:
            return None
        table_rows = _df_rows_as_dicts(rows, show_cols, limit=row_limit)
        parts = []
        for item in table_rows:
            parts.append("；".join(f"{c}={item[c]}" for c in show_cols if item.get(c) not in ("", "None", "nan")))
        excerpt = " || ".join(parts)[:600]
        locator = f"rowmatch:{match_terms[0]}"
        return EvidenceItem(
            id=make_data_id(rel, locator),
            type="data",
            source=rel,
            excerpt=excerpt,
            meta={
                "engine": "duckdb",
                "path": rel,
                "locator": locator,
                "confidence": "computed",
                "columns": show_cols,
                "rows": table_rows,
                "matched": match_terms[:8],
                "match_rows": len(table_rows),
            },
        )
    finally:
        con.close()


def build_entity_profile(
    *,
    name: str | None,
    entity_type: str | None,
    data: EvidencePack,
    match_terms: list[str],
) -> dict[str, Any] | None:
    if not name:
        return None
    related: list[str] = []
    try:
        from realai.vault.wiki.entity_pages import list_entity_titles
        from realai.vault.wiki.graph_index import neighbor_titles

        related = neighbor_titles(name, limit=10)
        titles = list_entity_titles()
        source_hint = titles.get(name)
    except Exception:
        source_hint = None

    pipelines: set[str] = set()
    sections: set[str] = set()
    length_sum = 0.0
    length_n = 0
    for it in data.items:
        rows = it.meta.get("rows") or []
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            pn = str(r.get("pipeline_name") or r.get("管线名称") or "").strip()
            sn = str(r.get("pipe_section_name") or r.get("管段名称") or "").strip()
            if pn:
                pipelines.add(pn)
            if sn:
                sections.add(sn)
            raw_len = r.get("pipe_section_length") or r.get("管段长度")
            try:
                if raw_len not in (None, ""):
                    length_sum += float(str(raw_len).replace(",", ""))
                    length_n += 1
            except ValueError:
                pass

    bullets = [
        f"实体类型：{entity_type or '未知'}",
        f"命中数据文件：{len(data.items)} 个",
        f"相关管段（明细行）：{len(sections)} 条",
        f"涉及管线：{len(pipelines)} 条",
    ]
    if length_n:
        bullets.append(f"管段长度合计（可解析）：{length_sum:.2f}")
    if related:
        bullets.append("图谱相关：" + "、".join(related[:6]))

    return {
        "name": name,
        "type": entity_type or "entity",
        "summary_bullets": bullets,
        "related": related[:12],
        "metrics": {
            "files": len(data.items),
            "sections": len(sections),
            "pipelines": len(pipelines),
            "length_sum": round(length_sum, 2) if length_n else None,
        },
        "source_entity_path": source_hint,
        "match_terms": match_terms[:12],
        "pipelines": sorted(pipelines)[:20],
        "sections": sorted(sections)[:30],
    }
