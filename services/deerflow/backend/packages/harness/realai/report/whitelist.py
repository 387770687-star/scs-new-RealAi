"""Writing-path web search whitelist (config/web_whitelist.json)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from realai.config import get_repo_root
from realai.paths import get_data_root

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_web_whitelist() -> dict:
    candidates = [
        get_data_root() / "config" / "web_whitelist.json",
        get_repo_root() / "config" / "web_whitelist.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {
                    "domains": [str(d).lower().lstrip(".") for d in (data.get("domains") or [])],
                    "allow_suffixes": [str(s).lower() for s in (data.get("allow_suffixes") or [])],
                }
            except Exception:
                logger.exception("failed to load web whitelist from %s", path)
    return {
        "domains": [],
        "allow_suffixes": [".gov.cn", "pipechina.com.cn", "cnpc.com.cn", "sinopec.com", "cnooc.com.cn"],
    }


def url_allowed(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    wl = load_web_whitelist()
    for suf in wl["allow_suffixes"]:
        s = suf.lstrip(".")
        if host == s or host.endswith("." + s) or host.endswith(s if s.startswith(".") else "." + s):
            return True
        if host.endswith(suf) or host == suf.lstrip("."):
            return True
    for d in wl["domains"]:
        if host == d or host.endswith("." + d):
            return True
    return False


def filter_web_items(items: list) -> list:
    """Keep only EvidenceItem-like objects whose source URL is whitelisted."""
    kept = []
    for item in items:
        url = getattr(item, "source", None) or (item.get("source") if isinstance(item, dict) else "")
        if url_allowed(str(url)):
            kept.append(item)
    return kept


def clear_whitelist_cache() -> None:
    load_web_whitelist.cache_clear()
