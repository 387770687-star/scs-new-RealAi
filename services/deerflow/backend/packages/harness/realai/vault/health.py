"""Vault health snapshot (usable for Q&A / writing readiness)."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from realai.meta.evaluation import latest_pass_rate
from realai.vault.content_quality import MIN_BODY_CHARS, is_shell_or_thin_text
from realai.vault.index import query_vault_files
from realai.vault.service import SKIP_DIRS, ensure_vault, vault_snapshot_mtime


def vault_health() -> dict[str, Any]:
    root = ensure_vault()
    page, total = query_vault_files(limit=500, offset=0, force=False)
    by_ext: dict[str, int] = {}
    text_ok = 0
    for f in page:
        ext = (f.extension or "").lower() or "other"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        if ext in {".md", ".txt", ".csv"}:
            text_ok += 1

    names: dict[str, int] = {}
    for f in page:
        names[f.name] = names.get(f.name, 0) + 1
    conflict_candidates = sum(1 for n, c in names.items() if c > 1)

    wiki_cards = 0
    raw_sources = 0
    entity_lq = 0
    thin_docs = 0
    content_hashes: dict[str, list[str]] = {}

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        # Content-dupe: hash only small/medium files (skip multi‑MB tables)
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size <= 2_000_000:
            try:
                data = p.read_bytes()
            except OSError:
                continue
            digest = hashlib.sha1(data).hexdigest()
            content_hashes.setdefault(digest, []).append(rel)

        if rel.startswith("wiki/") and p.suffix.lower() == ".md" and p.name.lower() != "readme.md":
            wiki_cards += 1
        if rel.startswith("raw/") and p.name.lower() != "readme.md":
            raw_sources += 1
        if rel.startswith("entities/") and p.suffix.lower() == ".md":
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:1200]
            except OSError:
                head = ""
            if "low_quality: true" in head or "low_quality: True" in head:
                entity_lq += 1
        if p.suffix.lower() == ".md" and not rel.startswith("entities/"):
            if p.name.lower() == "readme.md":
                continue
            if size > 500_000:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if is_shell_or_thin_text(text, min_chars=MIN_BODY_CHARS)[0]:
                thin_docs += 1

    content_dupes = sum(1 for paths in content_hashes.values() if len(paths) > 1)

    pass_rate = latest_pass_rate()

    writing_ready = wiki_cards > 0 and thin_docs < max(3, wiki_cards)
    qa_ready = any(
        (root / d).is_dir() and any((root / d).glob("*"))
        for d in ("pipelines", "dataqa", "new_energy")
    )

    return {
        "vault_path": str(root),
        "vault_mtime": vault_snapshot_mtime(),
        "checked_at": time.time(),
        "file_total": total,
        "indexed_sample": len(page),
        "by_extension": by_ext,
        "parse_ok_estimate": text_ok,
        "parse_fail_estimate": None,
        "parse_ok_note": "按扩展名 .md/.txt/.csv 计数，非真实解析成功数",
        "conflict_name_dupes": conflict_candidates,
        "content_dupes": content_dupes,
        "wiki_doc_cards": wiki_cards,
        "raw_source_files": raw_sources,
        "entity_low_quality": entity_lq,
        "thin_docs": thin_docs,
        "qa_ready": qa_ready,
        "writing_ready": writing_ready,
        "eval_pass_rate": pass_rate,
        "skip_dirs": sorted(SKIP_DIRS),
    }
