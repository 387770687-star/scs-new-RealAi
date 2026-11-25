"""SQLite graph index rebuilt from vault [[wikilinks]] and entity pages."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import yaml

from realai.meta.db import get_db, init_db
from realai.vault.service import SKIP_DIRS, ensure_vault
from realai.vault.wiki.linkify import extract_wikilinks

GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_nodes (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  path TEXT,
  type TEXT,
  props_json TEXT,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_edges (
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  rel TEXT NOT NULL DEFAULT 'link',
  weight REAL NOT NULL DEFAULT 1,
  PRIMARY KEY (src, dst, rel)
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON graph_edges(src);
CREATE INDEX IF NOT EXISTS idx_graph_edges_dst ON graph_edges(dst);
"""


def ensure_graph_tables() -> None:
    init_db()
    con = get_db()
    try:
        con.executescript(GRAPH_SCHEMA)
        con.commit()
    finally:
        con.close()


def _node_id(kind: str, title: str, path: str | None = None) -> str:
    if path:
        return f"path:{path}"
    return f"{kind}:{title}"


def rebuild_graph_index() -> dict[str, Any]:
    ensure_graph_tables()
    root = ensure_vault()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str, str, float]] = []
    title_to_id: dict[str, str] = {}
    path_to_id: dict[str, str] = {}

    # Only index knowledge surfaces — avoid scanning polluted/huge trees
    scan_roots = [
        root / "entities",
        root / "wiki",
        root / "new_energy",
        root / "05_Metrics",
        root / "pipelines",
    ]
    md_files: list[Path] = []
    for base in scan_roots:
        if not base.is_dir():
            continue
        for p in base.rglob("*.md"):
            if p.is_file():
                md_files.append(p)

    for p in md_files:
        rel = p.relative_to(root).as_posix()
        try:
            # Cap read size for safety
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(300_000)
        except OSError:
            continue
        title = p.stem
        kind = "entity" if rel.startswith("entities/") else "document"
        etype = None
        props: dict[str, Any] = {}
        if text.startswith("---"):
            m = re.match(r"^---\n([\s\S]*?)\n---", text)
            if m:
                try:
                    meta = yaml.safe_load(m.group(1)) or {}
                    title = str(meta.get("name") or title)
                    etype = meta.get("type")
                    props = {
                        "metrics": meta.get("metrics") or {},
                        "source_files": meta.get("source_files") or [],
                    }
                except Exception:
                    pass
        nid = _node_id(kind, title, rel)
        nodes[nid] = {
            "id": nid,
            "kind": kind,
            "title": title,
            "path": rel,
            "type": etype or ("document" if kind == "document" else "entity"),
            "props_json": json.dumps(props, ensure_ascii=False),
        }
        title_to_id[title] = nid
        path_to_id[rel] = nid

    # second pass: edges from wikilinks (reuse text from first pass where possible)
    for p in md_files:
        rel = p.relative_to(root).as_posix()
        src = path_to_id.get(rel)
        if not src:
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(300_000)
        except OSError:
            continue
        for link in extract_wikilinks(text):
            link = link.strip()
            if not link:
                continue
            dst = title_to_id.get(link)
            if not dst:
                dst = _node_id("stub", link)
                if dst not in nodes:
                    nodes[dst] = {
                        "id": dst,
                        "kind": "stub",
                        "title": link,
                        "path": None,
                        "type": "stub",
                        "props_json": "{}",
                    }
                title_to_id[link] = dst
            edges.append((src, dst, "wikilink", 1.0))
            edges.append((dst, src, "backlink", 0.5))

    now = time.time()
    con = get_db()
    try:
        con.execute("DELETE FROM graph_edges")
        con.execute("DELETE FROM graph_nodes")
        con.executemany(
            """
            INSERT INTO graph_nodes(id, kind, title, path, type, props_json, updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (
                    n["id"],
                    n["kind"],
                    n["title"],
                    n["path"],
                    n["type"],
                    n["props_json"],
                    now,
                )
                for n in nodes.values()
            ],
        )
        con.executemany(
            """
            INSERT OR IGNORE INTO graph_edges(src, dst, rel, weight)
            VALUES (?,?,?,?)
            """,
            edges,
        )
        con.commit()
    finally:
        con.close()

    return {"nodes": len(nodes), "edges": len(edges), "updated_at": now}


def query_graph(
    *,
    seed: str | None = None,
    depth: int = 1,
    types: list[str] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    ensure_graph_tables()
    con = get_db()
    try:
        if not seed:
            rows = con.execute(
                "SELECT * FROM graph_nodes ORDER BY title LIMIT ?",
                (limit,),
            ).fetchall()
            node_ids = {r["id"] for r in rows}
        else:
            # find seed by title or path
            row = con.execute(
                "SELECT * FROM graph_nodes WHERE title=? OR path=? OR id=? LIMIT 1",
                (seed, seed, seed),
            ).fetchone()
            if not row:
                # fuzzy
                row = con.execute(
                    "SELECT * FROM graph_nodes WHERE title LIKE ? LIMIT 1",
                    (f"%{seed}%",),
                ).fetchone()
            if not row:
                return {"nodes": [], "edges": []}
            node_ids = {row["id"]}
            frontier = {row["id"]}
            for _ in range(max(0, depth)):
                nxt: set[str] = set()
                for nid in frontier:
                    for er in con.execute(
                        "SELECT dst FROM graph_edges WHERE src=?",
                        (nid,),
                    ).fetchall():
                        nxt.add(er["dst"])
                node_ids |= nxt
                frontier = nxt
            rows = []
            for nid in list(node_ids)[:limit]:
                r = con.execute("SELECT * FROM graph_nodes WHERE id=?", (nid,)).fetchone()
                if r:
                    rows.append(r)

        if types:
            tset = set(types)
            rows = [r for r in rows if (r["type"] or "") in tset]
            node_ids = {r["id"] for r in rows}

        nodes = [
            {
                "id": r["id"],
                "kind": r["kind"],
                "title": r["title"],
                "path": r["path"],
                "type": r["type"],
                "props": json.loads(r["props_json"] or "{}"),
            }
            for r in rows
        ]
        edges = []
        for r in con.execute("SELECT * FROM graph_edges").fetchall():
            if r["src"] in node_ids and r["dst"] in node_ids:
                edges.append(
                    {"source": r["src"], "target": r["dst"], "rel": r["rel"], "weight": r["weight"]}
                )
        return {"nodes": nodes, "edges": edges}
    finally:
        con.close()


def backlinks_for_path(path: str) -> list[dict[str, Any]]:
    ensure_graph_tables()
    con = get_db()
    try:
        row = con.execute("SELECT id FROM graph_nodes WHERE path=?", (path,)).fetchone()
        if not row:
            return []
        nid = row["id"]
        out = []
        for er in con.execute(
            "SELECT src FROM graph_edges WHERE dst=? AND rel IN ('wikilink','backlink')",
            (nid,),
        ).fetchall():
            n = con.execute("SELECT * FROM graph_nodes WHERE id=?", (er["src"],)).fetchone()
            if n:
                out.append({"id": n["id"], "title": n["title"], "path": n["path"], "type": n["type"]})
        return out
    finally:
        con.close()


def neighbor_titles(seed: str, *, limit: int = 8) -> list[str]:
    g = query_graph(seed=seed, depth=1, limit=50)
    titles = []
    for n in g.get("nodes") or []:
        t = n.get("title")
        if t and t != seed and t not in titles:
            titles.append(t)
        if len(titles) >= limit:
            break
    return titles
