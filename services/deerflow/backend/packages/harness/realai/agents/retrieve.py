"""Lightweight knowledge retrieval over Vault."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from realai.evidence.types import EvidenceItem, EvidencePack, make_kb_id
from realai.vault.clean_table import is_geometry_column
from realai.vault.scope import matches_scope
from realai.vault.service import SKIP_DIRS, TEXT_EXTENSIONS, ensure_vault


def _tokenize(query: str) -> list[str]:
    raw = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", query.lower())
    tokens: list[str] = []
    for part in raw:
        if len(part) >= 2 and part not in tokens:
            tokens.append(part)
        if re.fullmatch(r"[\u4e00-\u9fff]+", part) and len(part) > 3:
            for i in range(len(part) - 1):
                bi = part[i : i + 2]
                if bi not in tokens:
                    tokens.append(bi)
    return tokens[:24]


def _read_for_search(path: Path) -> str:
    """Read text; for CSV drop geometry columns to avoid poisoning excerpts."""
    if path.suffix.lower() != ".csv":
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            return ""
        header = rows[0]
        keep = [i for i, c in enumerate(header) if not is_geometry_column(c)]
        if not keep:
            keep = list(range(len(header)))
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([header[i] for i in keep])
        for row in rows[1:]:
            w.writerow([(row[i] if i < len(row) else "")[:200] for i in keep])
        return out.getvalue()
    except Exception:
        return path.read_text(encoding="utf-8", errors="replace")[:50000]


def _in_scope(rel: str, scope_paths: list[str] | None) -> bool:
    return matches_scope(rel, scope_paths)


def _entity_is_low_quality(text: str) -> bool:
    return "low_quality: true" in text[:800] or "low_quality: True" in text[:800]


def search_vault(
    query: str,
    *,
    limit: int = 5,
    boost_paths: list[str] | None = None,
    scope_paths: list[str] | None = None,
) -> EvidencePack:
    root = ensure_vault()
    tokens = _tokenize(query)
    if not tokens:
        return EvidencePack()

    boost = {p.replace("\\", "/") for p in (boost_paths or [])}
    scored: list[tuple[int, Path, str]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        if not _in_scope(rel, scope_paths):
            continue
        try:
            text = _read_for_search(p)
        except OSError:
            continue
        if rel.startswith("entities/") and _entity_is_low_quality(text):
            continue
        lower = text.lower()
        score = sum(lower.count(t) for t in tokens)
        # prefer entity cards and wiki digests
        if rel.startswith("entities/"):
            score = int(score * 1.5) + 2
        if rel.startswith("wiki/"):
            score = int(score * 1.35) + 2
        if rel in boost:
            score += 30
        if score <= 0:
            continue
        scored.append((score, p, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    items: list[EvidenceItem] = []
    for score, path, text in scored[:limit]:
        rel = path.relative_to(root).as_posix()
        excerpt, line_no = _best_excerpt(text, tokens, is_csv=path.suffix.lower() == ".csv")
        items.append(
            EvidenceItem(
                id=make_kb_id(rel, excerpt),
                type="kb",
                source=rel,
                excerpt=excerpt,
                meta={
                    "score": score,
                    "mtime": path.stat().st_mtime,
                    "path": rel,
                    "locator": f"line≈{line_no}",
                    "confidence": "retrieved",
                },
            )
        )
    return EvidencePack(items=items)


def _best_excerpt(text: str, tokens: list[str], *, is_csv: bool = False, window: int = 480) -> tuple[str, int]:
    """Return (excerpt, approx line number). Prefer whole-line / CSV-row snippets."""
    lines = text.splitlines()
    if not lines:
        return "", 1

    lower_tokens = [t.lower() for t in tokens]
    best_idx = -1
    best_score = -1
    for i, line in enumerate(lines):
        low = line.lower()
        sc = sum(1 for t in lower_tokens if t in low)
        if sc > best_score:
            best_score = sc
            best_idx = i
    if best_idx < 0 or best_score <= 0:
        best_idx = 0

    line_no = best_idx + 1
    if is_csv and len(lines) >= 2:
        header = lines[0]
        # Prefer a data row that matched; if header itself matched, take first data hit.
        data_idx = (
            best_idx
            if best_idx > 0
            else next(
                (i for i, line in enumerate(lines[1:], start=1) if any(t in line.lower() for t in lower_tokens)),
                1,
            )
        )
        formatted = _format_csv_row_excerpt(header, lines[data_idx])
        if formatted:
            return formatted, data_idx + 1

    # Whole-line excerpt (snap to line, not mid-token char window)
    line = lines[best_idx].strip()
    if len(line) <= window:
        return line, line_no
    # Keep match neighborhood inside the long line
    low = line.lower()
    hit = 0
    for t in lower_tokens:
        j = low.find(t)
        if j >= 0:
            hit = j
            break
    start = max(0, hit - window // 3)
    end = min(len(line), start + window)
    snippet = line[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(line):
        snippet = snippet + "…"
    return snippet, line_no


def _format_csv_row_excerpt(header_line: str, row_line: str, max_fields: int = 14) -> str:
    """Turn a CSV header+row into readable「列: 值」pairs (skip empties)."""
    try:
        headers = next(csv.reader(io.StringIO(header_line)))
        values = next(csv.reader(io.StringIO(row_line)))
    except Exception:
        return ""
    parts: list[str] = []
    for i, h in enumerate(headers):
        if not h or is_geometry_column(h):
            continue
        v = values[i].strip() if i < len(values) else ""
        if not v or v.lower() in ("nan", "none", "null"):
            continue
        if len(v) > 80:
            v = v[:77] + "…"
        parts.append(f"{h}: {v}")
        if len(parts) >= max_fields:
            break
    if not parts:
        return row_line.strip()[:480]
    text = "；".join(parts)
    if len(text) > 900:
        text = text[:897] + "…"
    return text
