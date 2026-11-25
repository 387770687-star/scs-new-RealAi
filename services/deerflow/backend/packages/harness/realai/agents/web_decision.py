"""Decide whether to run web search (shared by light QA and report writing)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from realai.config import WebSearchMode, normalize_web_search_mode
from realai.evidence.types import EvidencePack

WebPhase = Literal["immediate", "after_local", "skip"]

# Explicit user asks to go online
_EXPLICIT_WEB_RE = re.compile(
    r"(上网|联网|搜一下|搜下|搜索一下|网上查|网上搜|百度|谷歌|google|搜索引擎|"
    r"查最新新闻|搜新闻|网页搜索|外部搜索|用搜索)",
    re.IGNORECASE,
)

# Timeliness / external-info hints → prefer search when local evidence is thin
_TEMPORAL_RE = re.compile(
    r"(最新|近期|今年|去年|本月|今日|昨天|刚刚|动态|新闻|行情|股价|"
    r"政策更新|新规|修订|颁布|发布会|官网|公开信息)",
)

# Strong local / structured-data intent — prefer vault unless evidence is weak
_STRONG_LOCAL_RE = re.compile(
    r"(管径|设计压力|管段长度|站场|压气站|分输|清管站|阀室|联络站|末站|"
    r"管段|管线|问数|excel|csv|列表|筛选|大于|小于|等于|"
    r"介绍一下|介绍下|概况|基本情况)",
    re.IGNORECASE,
)

_SECTION_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,40}_[\u4e00-\u9fffA-Za-z0-9]{2,40}"
)


@dataclass(frozen=True)
class WebSearchDecision:
    should_search: bool
    phase: WebPhase
    reason: str
    trajectory: str

    @property
    def mode_allows(self) -> bool:
        return self.phase != "skip" or self.should_search


def wants_explicit_web(query: str) -> bool:
    return bool(_EXPLICIT_WEB_RE.search(query or ""))


def has_temporal_hint(query: str) -> bool:
    return bool(_TEMPORAL_RE.search(query or ""))


def has_strong_local_intent(query: str) -> bool:
    q = query or ""
    if _SECTION_RE.search(q):
        return True
    return bool(_STRONG_LOCAL_RE.search(q))


def local_evidence_weak(pack: EvidencePack | None, *, min_items: int = 2) -> bool:
    """True when local kb/data/viz evidence is insufficient."""
    if pack is None or not pack.items:
        return True
    solid = [
        i
        for i in pack.items
        if i.type in ("kb", "data", "viz") and (i.excerpt or "").strip()
    ]
    if not solid:
        return True
    # Single thin hit still counts as weak
    if len(solid) < min_items:
        total_len = sum(len((i.excerpt or "").strip()) for i in solid)
        if total_len < 80:
            return True
        # One solid data/entity hit can be enough for structured asks
        if len(solid) == 1 and solid[0].type == "data" and total_len >= 40:
            return False
        if len(solid) < min_items:
            return True
    return False


def decide_web_search_pre(query: str, mode: str | WebSearchMode) -> WebSearchDecision:
    """First-pass decision before / while local retrieval runs."""
    m = normalize_web_search_mode(str(mode))
    if m == "off":
        return WebSearchDecision(
            should_search=False,
            phase="skip",
            reason="未开启",
            trajectory="联网跳过（已关闭）",
        )
    if m == "force":
        return WebSearchDecision(
            should_search=True,
            phase="immediate",
            reason="强制检索",
            trajectory="联网：强制检索",
        )
    if wants_explicit_web(query):
        return WebSearchDecision(
            should_search=True,
            phase="immediate",
            reason="用户要求搜索",
            trajectory="联网：用户要求搜索",
        )
    # Defer to post-local for auto
    return WebSearchDecision(
        should_search=False,
        phase="after_local",
        reason="待本地证据评估",
        trajectory="",
    )


def decide_web_search_post(
    query: str,
    mode: str | WebSearchMode,
    pack: EvidencePack | None,
) -> WebSearchDecision:
    """Second-pass after local kb/data (auto mode only)."""
    m = normalize_web_search_mode(str(mode))
    if m == "off":
        return WebSearchDecision(
            should_search=False,
            phase="skip",
            reason="未开启",
            trajectory="联网跳过（已关闭）",
        )
    if m == "force" or wants_explicit_web(query):
        # Should have been handled as immediate; still search if called.
        reason = "强制检索" if m == "force" else "用户要求搜索"
        label = "联网：强制检索" if m == "force" else "联网：用户要求搜索"
        return WebSearchDecision(
            should_search=True,
            phase="immediate",
            reason=reason,
            trajectory=label,
        )

    weak = local_evidence_weak(pack)
    temporal = has_temporal_hint(query)
    strong_local = has_strong_local_intent(query)

    if weak:
        reason = "本地证据不足"
        if temporal:
            reason = "时效/外部信息且本地不足"
        return WebSearchDecision(
            should_search=True,
            phase="after_local",
            reason=reason,
            trajectory=f"联网：智能补搜（{reason}）",
        )

    if temporal and not strong_local:
        return WebSearchDecision(
            should_search=True,
            phase="after_local",
            reason="时效/外部信息",
            trajectory="联网：智能检索（时效/外部信息）",
        )

    if strong_local and not weak:
        return WebSearchDecision(
            should_search=False,
            phase="skip",
            reason="知识库/问数已足够",
            trajectory="联网：智能跳过（知识库/问数已足够）",
        )

    # Uncertain → prefer search (product bias: fear missing needed search)
    return WebSearchDecision(
        should_search=True,
        phase="after_local",
        reason="不确定，倾向检索",
        trajectory="联网：智能检索（不确定，倾向检索）",
    )


def decide_web_search(
    query: str,
    mode: str | WebSearchMode,
    pack: EvidencePack | None = None,
    *,
    stage: Literal["pre", "post", "auto"] = "auto",
) -> WebSearchDecision:
    """Unified entry: pre / post / auto (post if pack given else pre)."""
    if stage == "pre":
        return decide_web_search_pre(query, mode)
    if stage == "post":
        return decide_web_search_post(query, mode, pack)
    if pack is not None:
        pre = decide_web_search_pre(query, mode)
        if pre.phase != "after_local":
            return pre
        return decide_web_search_post(query, mode, pack)
    return decide_web_search_pre(query, mode)
