"""P2: DuckDB multi-file read-only SQL over Vault tables."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from realai.evidence.types import EvidenceItem, EvidencePack, make_data_id
from realai.vault.paths import sql_string_literal
from realai.vault.scope import matches_scope
from realai.vault.service import SKIP_DIRS, ensure_vault

DATA_EXTENSIONS = {".csv", ".xlsx", ".xls"}

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|truncate|grant|revoke)\b",
    re.IGNORECASE,
)


def _list_data_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in DATA_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        files.append(p)
    return files


def _in_scope(rel: str, scope_paths: list[str] | None) -> bool:
    return matches_scope(rel, scope_paths)


def _register_file(con: duckdb.DuckDBPyConnection, path: Path, alias: str) -> None:
    safe = sql_string_literal(path.as_posix())
    if path.suffix.lower() == ".csv":
        con.execute(f"CREATE OR REPLACE VIEW {alias} AS SELECT * FROM read_csv_auto('{safe}', strict_mode=false, ignore_errors=true, null_padding=true)")
        return
    con.execute("INSTALL excel")
    con.execute("LOAD excel")
    con.execute(f"CREATE OR REPLACE VIEW {alias} AS SELECT * FROM read_xlsx('{safe}')")


def _safe_alias(rel: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "_", Path(rel).stem)
    if not base or base[0].isdigit():
        base = f"t_{base}"
    return base[:48]


def run_vault_sql(sql: str, *, limit: int = 20) -> EvidencePack:
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN_SQL.search(sql):
        raise ValueError("仅允许只读 SELECT 查询")
    if not sql.lower().startswith("select"):
        raise ValueError("问数 SQL 必须以 SELECT 开头")

    root = ensure_vault()
    files = _list_data_files(root)
    if not files:
        return EvidencePack()

    con = duckdb.connect(database=":memory:")
    try:
        for path in files:
            rel = path.relative_to(root).as_posix()
            _register_file(con, path, _safe_alias(rel))
        if " limit " not in sql.lower():
            sql = f"{sql} LIMIT {limit}"
        rows = con.execute(sql).fetchdf()
        if rows.empty:
            return EvidencePack()
        cols = [str(c) for c in rows.columns]
        table_rows = []
        for _, row in rows.head(limit).iterrows():
            table_rows.append({c: "" if row[c] is None or (isinstance(row[c], float) and row[c] != row[c]) else str(row[c]) for c in cols})
        excerpt_parts = []
        for r in table_rows[:5]:
            excerpt_parts.append(" | ".join(str(v) for v in list(r.values())[:8]))
        rel = "sql:multi"
        excerpt = "; ".join(excerpt_parts)[:500]
        return EvidencePack(
            items=[
                EvidenceItem(
                    id=make_data_id(rel, "query_result"),
                    type="data",
                    source=rel,
                    excerpt=excerpt,
                    meta={
                        "sql": sql,
                        "rows": table_rows,
                        "columns": cols,
                        "engine": "duckdb",
                        "path": rel,
                        "locator": "sql",
                    },
                )
            ]
        )
    finally:
        con.close()


def _pick_tables_by_keywords(files: list[Path], root: Path, keywords: tuple[str, ...]) -> list[tuple[str, str, Path]]:
    """Return (alias, rel, path) scored by filename keywords."""
    scored: list[tuple[int, str, str, Path]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        blob = rel.lower()
        score = sum(3 for k in keywords if k.lower() in blob)
        if score <= 0 and any(k in ("成本", "费用", "year", "年") for k in keywords):
            # soft include examples/dataqa
            if any(p in rel for p in ("dataqa", "examples", "成本", "cost")):
                score = 1
        if score > 0:
            scored.append((score, _safe_alias(rel), rel, path))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(a, r, p) for _, a, r, p in scored[:6]]


def query_multi_table(
    question: str,
    *,
    limit: int = 3,
    scope_paths: list[str] | None = None,
) -> EvidencePack:
    """Heuristic multi-table: year+region stats join, or cost tables."""
    root = ensure_vault()
    files = [path for path in _list_data_files(root) if _in_scope(path.relative_to(root).as_posix(), scope_paths)]
    if len(files) < 1:
        return EvidencePack()

    year_m = re.search(r"(20\d{2})", question)
    year = year_m.group(1) if year_m else None
    wants_cost = any(k in question for k in ("成本", "费用", "降低", "率"))
    wants_pop = any(k in question for k in ("人口", "GDP", "地区", "省市"))

    con = duckdb.connect(database=":memory:")
    try:
        if wants_cost:
            picked = _pick_tables_by_keywords(files, root, ("成本", "费用", "cost", "examples"))
            if not picked:
                picked = [(_safe_alias(f.relative_to(root).as_posix()), f.relative_to(root).as_posix(), f) for f in files[:2]]
            for alias, rel, path in picked[:3]:
                try:
                    _register_file(con, path, alias)
                except Exception:
                    continue
            alias = picked[0][0]
            rel = picked[0][1]
            # Prefer filtering by year column when present
            cols = [r[0] for r in con.execute(f"DESCRIBE {alias}").fetchall()]
            year_cols = [c for c in cols if "年" in c or c.lower() in ("year", "yr")]
            if year and year_cols:
                yc = year_cols[0]
                sql = f"SELECT * FROM {alias} WHERE CAST(\"{yc}\" AS VARCHAR) LIKE '%{year}%' LIMIT 15"
            else:
                sql = f"SELECT * FROM {alias} LIMIT 15"
            rows = con.execute(sql).fetchdf()
            if rows.empty:
                return EvidencePack()
            cols = [str(c) for c in rows.columns]
            table_rows = []
            for _, row in rows.head(15).iterrows():
                table_rows.append({c: "" if row[c] is None or (isinstance(row[c], float) and row[c] != row[c]) else str(row[c]) for c in cols})
            excerpt = "; ".join(" | ".join(str(v) for v in list(r.values())[:6]) for r in table_rows[:5])[:400]
            return EvidencePack(
                items=[
                    EvidenceItem(
                        id=make_data_id(rel, "multi:cost"),
                        type="data",
                        source=rel,
                        excerpt=excerpt,
                        meta={
                            "engine": "duckdb",
                            "mode": "multi_table_cost",
                            "sql": sql,
                            "path": rel,
                            "locator": "multi:cost",
                            "columns": cols,
                            "rows": table_rows,
                            "口径": "成本相关表启发式查询",
                        },
                    )
                ]
            )

        # Do not treat a bare year as sufficient evidence for a statistics-table
        # fallback. Exact query/NL2SQL own year lookups; this branch is only for
        # explicit population/GDP/region statistics intent.
        if wants_pop:
            picked = _pick_tables_by_keywords(files, root, ("population", "人口", "gdp", "dataqa", "统计"))
            if not picked:
                return EvidencePack()
            for alias, rel, path in picked[:2]:
                try:
                    _register_file(con, path, alias)
                except Exception:
                    continue
            a0, r0, _ = picked[0]
            cols = [r[0] for r in con.execute(f"DESCRIBE {a0}").fetchall()]
            year_cols = [c for c in cols if "年" in c or c.lower() in ("year", "yr")]
            region_cols = [c for c in cols if any(x in c for x in ("市", "省", "区", "region", "name", "地区"))]
            select_cols = (year_cols[:1] + region_cols[:2] + cols[:6])[:8]
            # dedupe preserve order
            seen = set()
            sc = []
            for c in select_cols:
                if c not in seen:
                    seen.add(c)
                    sc.append(c)
            col_sql = ", ".join(f'"{c}"' for c in sc) if sc else "*"
            if len(picked) >= 2 and year_cols:
                a1 = picked[1][0]
                cols2 = [r[0] for r in con.execute(f"DESCRIBE {a1}").fetchall()]
                y2 = next((c for c in cols2 if "年" in c or c.lower() in ("year", "yr")), None)
                if y2 and year:
                    sql = f'SELECT * FROM {a0} a LEFT JOIN {a1} b ON CAST(a."{year_cols[0]}" AS VARCHAR)=CAST(b."{y2}" AS VARCHAR) WHERE CAST(a."{year_cols[0]}" AS VARCHAR) LIKE \'%{year}%\' LIMIT 20'
                elif y2:
                    sql = f'SELECT * FROM {a0} a LEFT JOIN {a1} b ON CAST(a."{year_cols[0]}" AS VARCHAR)=CAST(b."{y2}" AS VARCHAR) LIMIT 20'
                elif year:
                    sql = f"SELECT {col_sql} FROM {a0} WHERE CAST(\"{year_cols[0]}\" AS VARCHAR) LIKE '%{year}%' LIMIT 20"
                else:
                    sql = f"SELECT {col_sql} FROM {a0} LIMIT 20"
            elif year and year_cols:
                sql = f"SELECT {col_sql} FROM {a0} WHERE CAST(\"{year_cols[0]}\" AS VARCHAR) LIKE '%{year}%' LIMIT 20"
            else:
                sql = f"SELECT {col_sql} FROM {a0} LIMIT 20"
            try:
                rows = con.execute(sql).fetchdf()
            except Exception:
                sql = f"SELECT * FROM {a0} LIMIT 15"
                rows = con.execute(sql).fetchdf()
            if rows.empty:
                return EvidencePack()
            cols = [str(c) for c in rows.columns][:12]
            table_rows = []
            for _, row in rows.head(15).iterrows():
                table_rows.append({c: "" if c not in row.index or row[c] is None or (isinstance(row[c], float) and row[c] != row[c]) else str(row[c]) for c in cols})
            excerpt = "; ".join(" | ".join(str(v) for v in list(r.values())[:6]) for r in table_rows[:5])[:400]
            return EvidencePack(
                items=[
                    EvidenceItem(
                        id=make_data_id(r0, "multi:stats"),
                        type="data",
                        source=r0,
                        excerpt=excerpt,
                        meta={
                            "engine": "duckdb",
                            "mode": "multi_table_stats",
                            "sql": sql,
                            "path": r0,
                            "locator": "multi:stats",
                            "columns": cols,
                            "rows": table_rows,
                            "口径": "统计表启发式/年关联查询",
                        },
                    )
                ]
            )
    finally:
        con.close()
    return EvidencePack()
