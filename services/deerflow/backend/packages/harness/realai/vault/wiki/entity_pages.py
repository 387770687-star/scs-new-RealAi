"""Write / update entity markdown pages under vault/entities/."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from realai.vault.content_quality import is_generic_org_name, is_linkable_entity_title
from realai.vault.service import ensure_vault, write_vault_file
from realai.vault.wiki.extract import EntityDraft, safe_entity_filename

WIKI_BLOCK_START = "<!-- realai:wiki -->"
WIKI_BLOCK_END = "<!-- /realai:wiki -->"


def entity_rel_path(draft: EntityDraft) -> str:
    return f"entities/{draft.type}/{safe_entity_filename(draft.name)}.md"


def write_entity_page(draft: EntityDraft) -> str | None:
    """Write or merge an entity page. Returns rel path, or None if rejected."""
    if draft.type == "org" and is_generic_org_name(draft.name):
        return None
    if draft.low_quality and draft.type in ("org", "metric"):
        return None
    if draft.type == "metric" and not is_linkable_entity_title(draft.name, low_quality=False):
        # short metric topics blocked unless already long whitelist names
        from realai.vault.content_quality import SHORT_METRIC_TOPICS

        if draft.name in SHORT_METRIC_TOPICS:
            return None

    rel = entity_rel_path(draft)
    root = ensure_vault()
    target = root / rel
    existing_body = ""
    existing_fm: dict = {}
    if target.is_file():
        raw = target.read_text(encoding="utf-8", errors="replace")
        existing_fm, existing_body = _parse_existing(raw)

    # Merge sources / metrics / related / aliases
    old_sources = list(existing_fm.get("source_files") or [])
    sources = list(dict.fromkeys([*old_sources, *(draft.source_files or [])]))
    old_metrics = dict(existing_fm.get("metrics") or {})
    metrics = {**old_metrics, **(draft.metrics or {})}
    old_related = list(existing_fm.get("related") or [])
    # related may live only in body; keep draft.related
    related = list(dict.fromkeys([*old_related, *(draft.related or [])]))
    aliases = list(dict.fromkeys([*(existing_fm.get("aliases") or []), *(draft.aliases or [])]))
    low_quality = bool(draft.low_quality or existing_fm.get("low_quality"))

    fm = {
        "type": draft.type,
        "name": draft.name,
        "aliases": aliases,
        "source_files": sources,
        "metrics": metrics,
        "related": related,
        "low_quality": low_quality,
        "wiki_linked_at": datetime.now(timezone.utc).isoformat(),
    }
    points = []
    for k, v in metrics.items():
        points.append(f"- **{k}**：{v}")
    if not points:
        points.append("- （暂无结构化指标，见来源文件）")

    related_links = [f"- [[{r}]]" for r in related if r and r != draft.name]
    source_lines = [f"- `{s}`" for s in sources]

    wiki_block = "\n".join(
        [
            WIKI_BLOCK_START,
            f"# {draft.name}",
            "",
            "## 要点",
            *points,
            "",
            "## 相关",
            *(related_links or ["- （暂无）"]),
            "",
            "## 来源",
            *(source_lines or ["- （无）"]),
            WIKI_BLOCK_END,
            "",
        ]
    )

    user_part = existing_body.strip()
    if user_part and WIKI_BLOCK_START not in user_part:
        body = wiki_block + "\n## 备注\n\n" + user_part + "\n"
    else:
        body = wiki_block

    front = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    content = f"---\n{front}\n---\n\n{body}"
    write_vault_file(rel, content)
    return rel


def _parse_existing(raw: str) -> tuple[dict, str]:
    fm: dict = {}
    text = raw
    if text.startswith("---"):
        m = re.match(r"^---\n([\s\S]*?)\n---\n?", text)
        if m:
            try:
                loaded = yaml.safe_load(m.group(1))
                if isinstance(loaded, dict):
                    fm = loaded
            except Exception:
                fm = {}
            text = text[m.end() :]
    text = _strip_wiki_block(text)
    return fm, text


def _strip_wiki_block(text: str) -> str:
    pattern = re.compile(
        re.escape(WIKI_BLOCK_START) + r"[\s\S]*?" + re.escape(WIKI_BLOCK_END),
        re.MULTILINE,
    )
    text = pattern.sub("", text)
    text = re.sub(r"^## 备注\s*\n*", "", text.strip())
    return text.strip()


def _strip_frontmatter_and_wiki_block(raw: str) -> str:
    text = raw
    if text.startswith("---"):
        m = re.match(r"^---\n[\s\S]*?\n---\n?", text)
        if m:
            text = text[m.end() :]
    return _strip_wiki_block(text)


def list_entity_titles(*, include_low_quality: bool = False) -> dict[str, str]:
    """Map entity title / alias -> relative path."""
    root = ensure_vault()
    ent = root / "entities"
    mapping: dict[str, str] = {}
    if not ent.is_dir():
        return mapping
    for p in ent.rglob("*.md"):
        rel = p.relative_to(root).as_posix()
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, _ = _parse_existing(raw)
        name = str(fm.get("name") or p.stem)
        if fm.get("low_quality") and not include_low_quality:
            continue
        if not is_linkable_entity_title(name, low_quality=bool(fm.get("low_quality"))):
            continue
        mapping[name] = rel
        for a in fm.get("aliases") or []:
            if a and is_linkable_entity_title(str(a)):
                mapping[str(a)] = rel
    return mapping


def purge_generic_entity_pages() -> int:
    """Delete known-bad org/metric pages (e.g. 有限公司). Returns count removed."""
    root = ensure_vault()
    ent = root / "entities"
    removed = 0
    if not ent.is_dir():
        return 0
    for p in list(ent.rglob("*.md")):
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, _ = _parse_existing(raw)
        name = str(fm.get("name") or p.stem)
        etype = str(fm.get("type") or p.parent.name)
        drop = False
        if etype == "org" and is_generic_org_name(name):
            drop = True
        if etype == "metric" and name in __import__(
            "realai.vault.content_quality", fromlist=["SHORT_METRIC_TOPICS"]
        ).SHORT_METRIC_TOPICS:
            drop = True
        if drop:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed
