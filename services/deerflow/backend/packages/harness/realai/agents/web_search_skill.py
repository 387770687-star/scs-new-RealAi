"""Web-search decision via Skill + LLM (shared by light QA and writing)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from realai.agents.web_decision import wants_explicit_web
from realai.config import (
    WebSearchMode,
    get_web_search_skill_id,
    load_settings,
    normalize_web_search_mode,
)
from realai.evidence.types import EvidencePack

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{[\s\S]*\}")


@dataclass
class WebSearchSkillDecision:
    should_search: bool
    reason: str
    search_query: str
    trajectory: list[str] = field(default_factory=list)
    error: str | None = None


def _load_skill_body(skill_id: str, max_len: int = 4000) -> str:
    try:
        from realai.skills.executor import skill_prompt_excerpt
        from realai.skills.registry import get_skill

        sk = get_skill(skill_id)
        if sk and not sk.enabled:
            return ""
        if sk and sk.valid:
            return skill_prompt_excerpt(sk, max_len=max_len) or (sk.body[:max_len] if sk.body else "")
    except Exception:
        logger.debug("load web-search skill from registry failed", exc_info=True)

    # Fallback: bundled preset on disk (before first skills sync)
    try:
        from realai.paths import get_app_root, get_repo_root

        for root in (get_app_root(), get_repo_root()):
            path = root / "skills" / "public" / skill_id / "SKILL.md"
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                # strip simple frontmatter
                if text.startswith("---"):
                    end = text.find("\n---", 3)
                    if end > 0:
                        text = text[end + 4 :]
                return text.strip()[:max_len]
    except Exception:
        logger.debug("load bundled web-search skill failed", exc_info=True)
    return ""


def _parse_decision_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def decide_web_search_with_skill(
    query: str,
    mode: str | WebSearchMode,
    *,
    local_pack: EvidencePack | None = None,
    history_text: str = "",
    settings: dict[str, Any] | None = None,
) -> WebSearchSkillDecision:
    """Decide whether to search using hard guards + web-search Skill LLM."""
    settings = settings or load_settings()
    m = normalize_web_search_mode(str(mode))
    q = (query or "").strip()
    explicit = wants_explicit_web(q)
    skill_id = get_web_search_skill_id(settings)

    if m == "off":
        return WebSearchSkillDecision(
            should_search=False,
            reason="已关闭联网",
            search_query=q,
            trajectory=["联网跳过（已关闭）"],
        )

    # Hard force / explicit: must search without waiting on Skill LLM
    if m == "force" or explicit:
        label = "联网：强制检索" if m == "force" else "联网：用户要求搜索"
        return WebSearchSkillDecision(
            should_search=True,
            reason="强制检索" if m == "force" else "用户要求搜索",
            search_query=q,
            trajectory=[label],
        )

    from realai.agents.session_context import evidence_digest
    from realai.llm import chat_turn, has_api_key

    skill_body = _load_skill_body(skill_id)
    if not skill_body:
        return WebSearchSkillDecision(
            should_search=False,
            reason="联网 Skill 不可用，智能模式保守跳过",
            search_query=q,
            trajectory=[f"联网：智能跳过（Skill「{skill_id}」不可用）"],
            error=f"Skill {skill_id} 不可用",
        )

    if not has_api_key(settings):
        return WebSearchSkillDecision(
            should_search=False,
            reason="未配置 API Key，无法做智能联网判断",
            search_query=q,
            trajectory=["联网：智能跳过（未配置 API Key）"],
            error="未配置 API Key",
        )

    local_text = evidence_digest(local_pack)
    system = (
        "你是联网决策助手。严格遵守给定 Skill。"
        "只输出一个 JSON 对象，字段：should_search(boolean)、reason(string)、search_query(string)。"
        "不要输出 Markdown 代码围栏以外的解释。"
    )
    user = (
        f"【Skill】\n{skill_body}\n\n"
        f"【mode】{m}\n"
        f"【explicit_web】false\n"
        f"【query】{q}\n"
        f"【history】\n{history_text or '（无）'}\n\n"
        f"【local_evidence】\n{local_text}\n"
    )
    try:
        turn = await chat_turn(
            user,
            system=system,
            role="fast",
            temperature=0.2,
            max_tokens=512,
            purpose="web_search_decide",
            settings=settings,
        )
        parsed = _parse_decision_json(turn.content)
    except Exception as exc:
        logger.exception("web-search skill LLM failed")
        return WebSearchSkillDecision(
            should_search=False,
            reason="Skill 决策失败，智能模式保守跳过",
            search_query=q,
            trajectory=[f"联网：智能跳过（Skill 决策失败：{exc}）"],
            error=str(exc),
        )

    if not parsed:
        return WebSearchSkillDecision(
            should_search=False,
            reason="Skill 返回无法解析，保守跳过",
            search_query=q,
            trajectory=["联网：智能跳过（Skill 返回无法解析）"],
            error="unparseable skill output",
        )

    should = bool(parsed.get("should_search"))
    reason = str(parsed.get("reason") or "").strip() or ("需要联网" if should else "本地已足够")
    search_query = str(parsed.get("search_query") or q).strip() or q

    if should:
        traj = [
            f"联网 Skill「{skill_id}」：建议搜索",
            f"联网：将搜索（{reason}）",
            f"搜词：{search_query}",
        ]
    else:
        traj = [f"联网：智能跳过（{reason}）", f"联网 Skill「{skill_id}」：不搜索"]

    return WebSearchSkillDecision(
        should_search=should,
        reason=reason,
        search_query=search_query,
        trajectory=traj,
    )


async def run_web_search_pipeline(
    query: str,
    mode: str | WebSearchMode,
    *,
    local_pack: EvidencePack | None = None,
    history_text: str = "",
    limit: int = 3,
    apply_whitelist: bool = False,
    settings: dict[str, Any] | None = None,
) -> tuple[EvidencePack, list[str], str | None]:
    """Decide then (optionally) execute MiniMax MCP web search.

    Returns ``(pack, trajectory_lines, error_message)``.
    """
    decision = await decide_web_search_with_skill(
        query,
        mode,
        local_pack=local_pack,
        history_text=history_text,
        settings=settings,
    )
    traj = list(decision.trajectory)
    if not decision.should_search:
        return EvidencePack(), traj, decision.error

    from realai.agents.web import search_web

    pack, err = await search_web(
        decision.search_query or query,
        limit=limit,
        return_error=True,
    )
    if err:
        traj.append(f"联网搜索失败：{err}")
    elif not pack.items:
        traj.append("联网搜索完成，但无可用结果")
    else:
        traj.append(f"联网命中 {len(pack.items)} 条")

    if apply_whitelist and pack.items:
        from realai.report.whitelist import filter_web_items

        kept = filter_web_items(pack.items)
        if len(kept) < len(pack.items):
            traj.append(f"白名单过滤：{len(pack.items)} → {len(kept)}")
        pack = EvidencePack(items=kept)

    return pack, traj, err or decision.error
