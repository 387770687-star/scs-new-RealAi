"""Generate vault/wiki document digest cards from classified business files."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from pathlib import Path
from typing import Any

from realai.vault.service import ensure_vault, write_vault_file
from realai.vault.wiki.entity_pages import WIKI_BLOCK_END, WIKI_BLOCK_START

_DOC_NO_RE = re.compile(r"[（(]?[\u4e00-\u9fff]{0,8}(?:发改|国能|自然资|工信部|发改办)[^\s，。；]{0,40}号[）)]?")
_DATE_RE = re.compile(r"20\d{2}[-年./]?\d{1,2}[-月./]?\d{0,2}日?")


def _safe_stem(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    s = re.sub(r"\s+", "_", s)
    # drop content-hash suffix like -a1b2c3d4
    s = re.sub(r"-[a-f0-9]{8}$", "", s, flags=re.I)
    return (s or "doc")[:100]


def write_wiki_doc_card(
    *,
    category: str,
    title: str,
    source_rel: str,
    body_lines: list[str],
) -> str:
    rel = f"wiki/{category}/{_safe_stem(title)}.md"
    points = [ln if ln.startswith("-") else f"- {ln}" for ln in body_lines if ln.strip()]
    if not points:
        points = ["- （摘要待补充，见来源文件）"]
    block = "\n".join(
        [
            WIKI_BLOCK_START,
            f"# {title}",
            "",
            "## 要点",
            *points,
            "",
            "## 来源",
            f"- `{source_rel}`",
            WIKI_BLOCK_END,
            "",
        ]
    )
    content = (
        f"---\n"
        f"type: wiki_card\n"
        f"category: {category}\n"
        f"title: {title}\n"
        f"source: {source_rel}\n"
        f"---\n\n{block}"
    )
    write_vault_file(rel, content)
    return rel


def card_from_policy_markdown(text: str, source_rel: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = Path(source_rel).stem
    title = re.sub(r"-[a-f0-9]{8}$", "", title, flags=re.I)
    # Prefer first markdown heading
    for ln in lines[:30]:
        if ln.startswith("#"):
            title = ln.lstrip("#").strip() or title
            break
    doc_no = ""
    for ln in lines[:40]:
        m = _DOC_NO_RE.search(ln)
        if m:
            doc_no = m.group(0)
            break
    date = ""
    for ln in lines[:40]:
        m = _DATE_RE.search(ln)
        if m:
            date = m.group(0)
            break
    # Excerpt: first substantial paragraphs (skip nav-ish short lines)
    excerpts: list[str] = []
    for ln in lines:
        if ln.startswith("#") or ln.startswith("!") or ln.startswith("* ["):
            continue
        if len(re.findall(r"[\u4e00-\u9fff]", ln)) < 12:
            continue
        excerpts.append(ln[:180])
        if len(excerpts) >= 5:
            break
    body = []
    if doc_no:
        body.append(f"**文号**：{doc_no}")
    if date:
        body.append(f"**日期线索**：{date}")
    body.extend(excerpts)
    return write_wiki_doc_card(
        category="new_energy",
        title=title,
        source_rel=source_rel,
        body_lines=body,
    )


def card_from_pipeline_csv(csv_text: str, source_rel: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        return []
    rows = list(reader)
    if not rows:
        return []
    by_pipe: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        pn = (row.get("pipeline_name") or row.get("管线名称") or Path(source_rel).stem).strip()
        by_pipe.setdefault(pn or Path(source_rel).stem, []).append(row)

    written: list[str] = []
    for pname, prows in by_pipe.items():
        lengths: list[float] = []
        diameters: Counter[str] = Counter()
        pressures: Counter[str] = Counter()
        stations: list[str] = []
        for r in prows:
            raw_len = (r.get("pipe_section_length") or r.get("线路长度") or "").strip()
            try:
                lengths.append(float(raw_len))
            except ValueError:
                pass
            d = (r.get("pipe_diameter") or "").strip()
            if d:
                diameters[d] += 1
            p = (r.get("design_pressure") or "").strip()
            if p:
                pressures[p] += 1
            for col in ("start_station_name", "end_station_name"):
                sn = (r.get(col) or "").strip()
                if sn and sn not in stations:
                    stations.append(sn)
        body = [
            f"**管段数**：{len(prows)}",
            f"**里程合计(表内)**：{round(sum(lengths), 2) if lengths else '—'}",
            f"**管径分布**：{', '.join(f'{k}×{v}' for k, v in diameters.most_common(5)) or '—'}",
            f"**设计压力分布**：{', '.join(f'{k}×{v}' for k, v in pressures.most_common(5)) or '—'}",
            f"**关联站场（节选）**：{'、'.join(stations[:12]) or '—'}",
        ]
        written.append(
            write_wiki_doc_card(
                category="pipelines",
                title=pname,
                source_rel=source_rel,
                body_lines=body,
            )
        )
    return written


def card_from_dataqa_csv(csv_text: str, source_rel: str) -> str | None:
    # Cap parse cost on multi‑MB tables
    sample = csv_text if len(csv_text) < 400_000 else csv_text[:400_000]
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        return None
    fields = [c for c in reader.fieldnames if c]
    years: list[str] = []
    year_col = next((c for c in fields if c.lower() in ("year", "年份", "yr")), None)
    sample_rows = 0
    for i, row in enumerate(reader):
        sample_rows = i + 1
        if year_col and row.get(year_col):
            years.append(str(row[year_col]).strip())
        if i >= 800:
            break
    year_span = ""
    if years:
        try:
            nums = sorted({int(float(y)) for y in years if str(y).replace(".", "", 1).isdigit()})
            if nums:
                year_span = f"{nums[0]}–{nums[-1]}"
        except Exception:
            year_span = f"{years[0]}…"
    title = Path(source_rel).stem
    title = re.sub(r"-[a-f0-9]{8}$", "", title, flags=re.I)
    body = [
        f"**字段数**：{len(fields)}",
        f"**抽样行数**：约 {sample_rows}+",
        f"**年份范围**：{year_span or '—'}",
        f"**主要字段**：{', '.join(fields[:16])}",
        "**适用**：统计问数 / 区域与年份对比",
    ]
    return write_wiki_doc_card(
        category="dataqa",
        title=title,
        source_rel=source_rel,
        body_lines=body,
    )


def generate_doc_cards_for_paths(paths: list[str]) -> dict[str, Any]:
    root = ensure_vault()
    cards: list[str] = []
    for rel in paths:
        rel = rel.replace("\\", "/")
        path = root / rel
        if not path.is_file():
            continue
        top = rel.split("/", 1)[0]
        try:
            if rel.endswith(".md") and top == "new_energy":
                text = path.read_text(encoding="utf-8", errors="replace")
                c = card_from_policy_markdown(text, rel)
                if c:
                    cards.append(c)
            elif rel.endswith(".csv") and top == "pipelines":
                text = path.read_text(encoding="utf-8", errors="replace")
                cards.extend(card_from_pipeline_csv(text, rel))
            elif rel.endswith(".csv") and top == "dataqa":
                # Read only a head slice for catalog cards (tables can be multi‑MB)
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(400_000)
                c = card_from_dataqa_csv(text, rel)
                if c:
                    cards.append(c)
            elif rel.endswith(".md") and top in ("pipelines", "dataqa"):
                # optional narrative beside tables
                text = path.read_text(encoding="utf-8", errors="replace")
                c = card_from_policy_markdown(text, rel)
                if c:
                    # rewrite category via path
                    pass
        except Exception:
            continue
    return {"wiki_cards": len(cards), "paths": cards}
