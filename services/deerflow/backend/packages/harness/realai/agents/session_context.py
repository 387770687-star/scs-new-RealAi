"""Session transcript helpers for multi-turn light QA."""

from __future__ import annotations

from typing import Any


def format_session_history(
    session_id: str | None,
    *,
    max_chars: int = 12000,
    exclude_pending_query: str | None = None,
) -> tuple[str, int]:
    """Load same-session dialogue as plain text (newest rounds kept if truncated).

    Returns ``(text, turn_count)`` where turn_count is number of user/assistant
    messages included (not counting system).
    """
    if not session_id:
        return "", 0
    try:
        from realai.meta.chat import get_session

        sess = get_session(session_id)
    except Exception:
        return "", 0
    if not sess:
        return "", 0

    lines: list[str] = []
    turns = 0
    for m in sess.get("messages") or []:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        text = ""
        if isinstance(content, dict):
            text = str(content.get("text") or content.get("answer") or "").strip()
        elif isinstance(content, str):
            text = content.strip()
        if not text:
            continue
        # Current user query is passed separately; skip duplicate last user turn
        if (
            exclude_pending_query
            and role == "user"
            and text.strip() == exclude_pending_query.strip()
            and m is (sess.get("messages") or [])[-1]
        ):
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}：{text}")
        turns += 1

    if not lines:
        return "", 0

    # Drop oldest lines until under max_chars (keep complete turns from the end)
    while lines and sum(len(x) + 1 for x in lines) > max_chars:
        lines.pop(0)
        turns = max(0, turns - 1)

    return "\n".join(lines), turns


def evidence_digest(pack: Any, *, max_items: int = 8, max_excerpt: int = 180) -> str:
    """Compact local evidence summary for the web-search decision Skill."""
    items = getattr(pack, "items", None) or []
    if not items:
        return "（无本地证据）"
    parts: list[str] = []
    for it in items[:max_items]:
        typ = getattr(it, "type", "") or ""
        eid = getattr(it, "id", "") or ""
        excerpt = (getattr(it, "excerpt", None) or "")[:max_excerpt]
        parts.append(f"- [{typ}] {eid}: {excerpt}")
    return "\n".join(parts)
