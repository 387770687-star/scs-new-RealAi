"""Orchestrate entity extraction, wiki doc cards, linkify, graph rebuild."""

from __future__ import annotations

import logging
from typing import Any

from realai.vault.service import ensure_vault
from realai.vault.wiki.doc_cards import generate_doc_cards_for_paths
from realai.vault.wiki.entity_pages import list_entity_titles, purge_generic_entity_pages, write_entity_page
from realai.vault.wiki.extract import extract_from_csv_text, extract_from_markdown
from realai.vault.wiki.graph_index import rebuild_graph_index
from realai.vault.wiki.linkify import linkify_markdown_file

logger = logging.getLogger(__name__)


def _category_from_path(rel: str) -> str:
    part = rel.replace("\\", "/").split("/", 1)[0]
    if part in ("pipelines", "new_energy", "dataqa"):
        return part
    return "pipelines"


async def process_imported_paths(paths: list[str]) -> dict[str, Any]:
    root = ensure_vault()
    drafts_all = []
    md_targets: list[str] = []
    card_paths: list[str] = []

    for rel in paths:
        rel = rel.replace("\\", "/")
        path = root / rel
        if not path.is_file():
            continue
        cat = _category_from_path(rel)
        try:
            if rel.endswith(".csv"):
                if cat == "dataqa":
                    # Avoid loading multi‑MB tables for entity extract (skipped anyway)
                    card_paths.append(rel)
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    drafts_all.extend(extract_from_csv_text(text, rel, category=cat))
                    card_paths.append(rel)
            elif rel.endswith(".md"):
                text = path.read_text(encoding="utf-8", errors="replace")
                drafts_all.extend(extract_from_markdown(text, rel))
                md_targets.append(rel)
                card_paths.append(rel)
        except Exception:
            logger.exception("extract failed for %s", rel)

    purged = purge_generic_entity_pages()

    entity_paths = []
    for d in drafts_all:
        try:
            written = write_entity_page(d)
            if written:
                entity_paths.append(written)
        except Exception:
            logger.exception("write entity failed: %s", d.name)

    wiki_info = generate_doc_cards_for_paths(card_paths)

    titles = list(list_entity_titles().keys())
    titles = list(dict.fromkeys([*titles, *[d.name for d in drafts_all if not d.low_quality]]))

    linked = 0
    for md in md_targets:
        try:
            if linkify_markdown_file(md, titles):
                linked += 1
        except Exception:
            logger.exception("linkify failed %s", md)

    # Also linkify newly written wiki cards
    for wrel in wiki_info.get("paths") or []:
        try:
            if linkify_markdown_file(wrel, titles):
                linked += 1
        except Exception:
            logger.exception("linkify wiki card failed %s", wrel)

    graph = rebuild_graph_index()
    return {
        "entities_written": len(entity_paths),
        "docs_linked": linked,
        "wiki_cards": wiki_info.get("wiki_cards", 0),
        "purged_generic": purged,
        "graph": graph,
    }


async def rebuild_wiki(*, linkify_all: bool = True) -> dict[str, Any]:
    """Full vault wiki rebuild: extract from all csv/md, rewrite entities, wiki cards, linkify, reindex."""
    root = ensure_vault()
    paths: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(x in rel.split("/") for x in (".obsidian", ".git", "reports", "_raw_archive")):
            continue
        if rel.startswith("entities/") or rel.startswith("wiki/"):
            continue
        if p.suffix.lower() in {".csv", ".md"}:
            paths.append(rel)

    result = await process_imported_paths(paths)

    if linkify_all:
        titles = list(list_entity_titles().keys())
        extra = 0
        for p in root.rglob("*.md"):
            rel = p.relative_to(root).as_posix()
            if rel.startswith("entities/"):
                continue
            if any(x in rel.split("/") for x in (".obsidian", "reports")):
                continue
            try:
                if linkify_markdown_file(rel, titles):
                    extra += 1
            except Exception:
                logger.exception("linkify_all failed %s", rel)
        result["docs_linked_extra"] = extra
        result["graph"] = rebuild_graph_index()

    return result
