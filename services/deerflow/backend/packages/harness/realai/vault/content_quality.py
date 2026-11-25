"""Import / document content quality gates for shared Vault."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from realai.vault.service import SKIP_DIRS, ensure_vault

# Minimum CJK / letter characters in converted markdown before accepting into Vault.
MIN_BODY_CHARS = 200

_SHELL_MARKERS = (
    "gtrs_logo",
    "gtrs_newsearch",
    "无障碍",
    "个人中心",
    "No content available",
    "未能提取正文",
    "big5.www.gov.cn",
)

_GENERIC_ORG_NAMES = frozenset(
    {
        "有限公司",
        "股份有限公司",
        "有限责任公司",
        "集团公司",
        "集团有限公司",
        "分公司",
        "总公司",
        "本公司",
        "该公司",
        "公司",
        "作业区",
        "维抢修中心",
        "维抢修队",
    }
)

# Short metric topic names that must not become standalone entity pages from bare substring hits.
SHORT_METRIC_TOPICS = frozenset(
    {
        "管径",
        "罐容",
        "起止点",
        "储罐数",
        "总库容",
        "组织机构",
        "编制人数",
        "线路长度",
        "设计压力",
        "设计输量",
        "在役里程",
        "封存里程",
    }
)


def content_sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def count_meaningful_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text or ""))


def is_shell_or_thin_text(text: str, *, min_chars: int = MIN_BODY_CHARS) -> tuple[bool, str]:
    """Return (reject, reason). Reject empty HTML shells and near-empty conversions."""
    body = (text or "").strip()
    if not body:
        return True, "正文为空"
    lower = body.lower()
    shell_hits = sum(1 for m in _SHELL_MARKERS if m.lower() in lower)
    meaningful = count_meaningful_chars(body)
    if shell_hits >= 2 and meaningful < min_chars * 2:
        return True, "疑似网页导航壳，正文过短"
    if meaningful < min_chars:
        return True, f"有效正文不足 {min_chars} 字（当前 {meaningful}）"
    return False, ""


def find_existing_by_content_hash(digest: str) -> str | None:
    """Find a vault *business* file whose name embeds this sha1[:8] digest.

    Skips ``raw/`` staging so staged sources named ``stem-<oldhash>.ext`` do not
    block a fresh import of the same bytes into classified folders.
    """
    if not digest or len(digest) < 8:
        return None
    short = digest[:8].lower()
    root = ensure_vault()
    # Match only RealAi import naming: stem-<sha8>.ext
    needle = f"-{short}."
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        top = rel.split("/", 1)[0]
        if top in {"raw", "wiki", "entities", "reports", "05_Metrics", "10_Outputs", "examples"}:
            continue
        name = p.name.lower()
        if needle in name:
            return rel
    return None


def is_generic_org_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    if n in _GENERIC_ORG_NAMES:
        return True
    if len(n) < 4:
        return True
    # 「有限」+「公司」without a proper proper-noun prefix of length >= 2 beyond the suffix glue
    if n in ("有限公司", "有限责任公司", "股份有限公司"):
        return True
    # Reject if stripping common legal suffix leaves < 2 chars
    stripped = re.sub(
        r"(股份)?有限(责任)?公司$|集团有限公司$|集团公司$|分公司$|总公司$",
        "",
        n,
    )
    if len(stripped) < 2:
        return True
    return False


def is_linkable_entity_title(name: str, *, low_quality: bool = False) -> bool:
    if low_quality:
        return False
    n = (name or "").strip()
    if len(n) < 4:
        return False
    if n in _GENERIC_ORG_NAMES or is_generic_org_name(n):
        return False
    if n in SHORT_METRIC_TOPICS:
        return False
    return True
