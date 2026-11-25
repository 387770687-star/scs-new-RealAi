"""Insert [[wikilinks]] into markdown documents safely."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from realai.vault.content_quality import is_linkable_entity_title
from realai.vault.service import ensure_vault, write_vault_file
from realai.vault.wiki.entity_pages import WIKI_BLOCK_END, WIKI_BLOCK_START

_CODE_FENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`]+`")
_EXISTING_LINK = re.compile(r"\[\[[^\]]+\]\]")


def linkify_markdown_file(rel_path: str, titles: list[str], *, related_docs: list[str] | None = None) -> bool:
    """Replace bare entity names with [[name]]. Returns True if file changed."""
    if not rel_path.endswith(".md"):
        return False
    root = ensure_vault()
    path = root / rel_path
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    if rel_path.replace("\\", "/").startswith("entities/"):
        return False

    titles_sorted = sorted(
        {t for t in titles if t and is_linkable_entity_title(t)},
        key=len,
        reverse=True,
    )
    if not titles_sorted and not related_docs:
        return False

    protected: list[str] = []

    def _protect(m: re.Match[str]) -> str:
        protected.append(m.group(0))
        return f"\x00P{len(protected) - 1}\x00"

    work = _CODE_FENCE.sub(_protect, text)
    work = _INLINE_CODE.sub(_protect, work)
    work = _EXISTING_LINK.sub(_protect, work)

    for title in titles_sorted:
        pattern = re.compile(re.escape(title))

        def _repl(m: re.Match[str], t: str = title) -> str:
            return f"[[{t}]]"

        work = pattern.sub(_repl, work)

    for i, frag in enumerate(protected):
        work = work.replace(f"\x00P{i}\x00", frag)

    if related_docs:
        links = "\n".join(f"- [[{d}]]" for d in related_docs if d)
        block = (
            f"\n\n{WIKI_BLOCK_START}\n"
            f"## 相关文档\n{links}\n"
            f"\n<!-- wiki_linked_at: {datetime.now(timezone.utc).isoformat()} -->\n"
            f"{WIKI_BLOCK_END}\n"
        )
        pattern = re.compile(
            re.escape(WIKI_BLOCK_START) + r"[\s\S]*?" + re.escape(WIKI_BLOCK_END),
            re.MULTILINE,
        )
        if pattern.search(work):
            work = pattern.sub(block.strip(), work)
        else:
            work = work.rstrip() + block

    if work == text:
        return False
    write_vault_file(rel_path, work)
    return True


def extract_wikilinks(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", text)
