"""MiniMax Coding Plan web search via official HTTP API (no uvx/MCP)."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from realai.evidence.types import EvidenceItem, EvidencePack, make_web_id

logger = logging.getLogger(__name__)


def _api_host_from_base_url(base_url: str) -> str:
    raw = (base_url or "").strip() or "https://api.minimaxi.com/v1"
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://api.minimaxi.com"


def _resolve_api_key(settings: dict[str, Any] | None = None) -> str:
    if settings is None:
        try:
            from realai.config import load_settings

            settings = load_settings()
        except Exception:
            settings = {}
    llm = settings.get("llm") or {}
    key = str(llm.get("apiKey") or "").strip()
    if key:
        return key
    for env_name in (
        "MINIMAX_API_KEY",
        "MINIMAX_CODE_PLAN_KEY",
        "MINIMAX_CODING_API_KEY",
    ):
        v = os.environ.get(env_name, "").strip()
        if v:
            return v
    return ""


def _resolve_host(settings: dict[str, Any] | None = None) -> str:
    if settings is None:
        try:
            from realai.config import load_settings

            settings = load_settings()
        except Exception:
            settings = {}
    llm = settings.get("llm") or {}
    host_env = os.environ.get("MINIMAX_API_HOST", "").strip()
    if host_env:
        return _api_host_from_base_url(host_env)
    return _api_host_from_base_url(str(llm.get("baseUrl") or ""))


def _search_url(host: str) -> str:
    return f"{host.rstrip('/')}/v1/coding_plan/search"


def _parse_organic(data: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return rows
    organic = data.get("organic") or data.get("results") or data.get("data") or []
    if isinstance(organic, dict):
        organic = organic.get("results") or organic.get("items") or []
    if not isinstance(organic, list):
        return rows
    for r in organic:
        if not isinstance(r, dict):
            continue
        url = str(r.get("link") or r.get("url") or r.get("href") or "").strip()
        title = str(r.get("title") or "").strip()
        body = str(
            r.get("snippet") or r.get("body") or r.get("description") or r.get("content") or ""
        ).strip()
        if url or title or body:
            rows.append({"url": url, "title": title, "body": body})
    return rows


def _friendly_http_error(status: int, body: str) -> str:
    low = (body or "").lower()
    if status in (401, 403) or "invalid" in low and "key" in low:
        return (
            f"MiniMax 搜索鉴权失败（HTTP {status}）。"
            "请确认模型中心 Key 与 Base URL 同区（国内 api.minimaxi.com），"
            "且 Key 已开通 Coding Plan / Token Plan 网络搜索。"
        )
    if status == 429 or "quota" in low or "额度" in body:
        return f"MiniMax 搜索额度不足或限流（HTTP {status}）"
    return f"MiniMax 搜索失败（HTTP {status}）：{(body or '')[:240]}"


async def call_minimax_web_search(
    query: str,
    *,
    limit: int = 5,
    settings: dict[str, Any] | None = None,
) -> tuple[EvidencePack, str | None]:
    """POST /v1/coding_plan/search and map organic results to web: evidence."""
    q = (query or "").strip()
    if not q:
        return EvidencePack(), "搜索词为空"

    key = _resolve_api_key(settings)
    if not key:
        return EvidencePack(), "未配置 MiniMax API Key，无法联网搜索"

    host = _resolve_host(settings)
    url = _search_url(host)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    # Official MCP client sends {"q": query}; some docs also mention query/count
    payloads = (
        {"q": q},
        {"query": q},
        {"q": q, "count": max(1, min(int(limit), 10))},
    )

    last_err: str | None = None
    data: Any = None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for payload in payloads:
                try:
                    resp = await client.post(url, headers=headers, json=payload)
                except httpx.RequestError as exc:
                    last_err = f"无法连接 MiniMax 搜索接口（{host}）：{exc}"
                    continue
                text = resp.text or ""
                if resp.status_code >= 400:
                    last_err = _friendly_http_error(resp.status_code, text)
                    # 400 on unknown field → try next payload shape
                    if resp.status_code in (400, 422) and payload is not payloads[-1]:
                        continue
                    return EvidencePack(), last_err
                try:
                    data = resp.json()
                except Exception:
                    last_err = f"MiniMax 搜索返回非 JSON：{text[:200]}"
                    return EvidencePack(), last_err
                break
    except Exception as exc:
        logger.exception("minimax web search failed")
        return EvidencePack(), f"MiniMax 搜索异常：{exc}"

    if data is None:
        return EvidencePack(), last_err or "MiniMax 搜索无响应"

    # API-level base_resp / error envelope (MiniMax style)
    if isinstance(data, dict):
        base = data.get("base_resp") or data.get("base_response")
        if isinstance(base, dict):
            code = base.get("status_code", base.get("statusCode", 0))
            if code not in (0, "0", None, ""):
                msg = str(base.get("status_msg") or base.get("statusMsg") or base)
                return EvidencePack(), _friendly_http_error(int(code) if str(code).isdigit() else 400, msg)

    rows = _parse_organic(data)
    items: list[EvidenceItem] = []
    for row in rows[: max(1, limit)]:
        link = str(row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        body = str(row.get("body") or "").strip()
        if not link:
            continue
        excerpt = f"{title} — {body}".strip(" —")[:400]
        items.append(
            EvidenceItem(
                id=make_web_id(link),
                type="web",
                source=link,
                excerpt=excerpt or title or link,
                meta={"title": title, "provider": "minimax_http"},
            )
        )

    if not items:
        return EvidencePack(), "MiniMax 搜索完成，但未解析到带链接的结果"

    return EvidencePack(items=items), None


def minimax_web_search_health() -> dict[str, Any]:
    """Settings/health snapshot — no network call."""
    key = _resolve_api_key()
    host = _resolve_host()
    return {
        "provider": "minimax_http",
        "endpoint": _search_url(host),
        "has_api_key": bool(key),
        "detail": (
            f"直调 {_search_url(host)}（无需 uvx/MCP）"
            if key
            else "未配置 API Key；配置后可直调 MiniMax 搜索接口"
        ),
        "hint": "便携包无需安装 uvx；Key 需开通 Coding Plan / Token Plan 网络搜索，且与 Base URL 同区。",
    }


# Back-compat aliases used by older imports
async def call_minimax_web_search_mcp(query: str, *, limit: int = 5) -> tuple[EvidencePack, str | None]:
    return await call_minimax_web_search(query, limit=limit)


def mcp_web_search_health() -> dict[str, Any]:
    return minimax_web_search_health()


def sync_minimax_mcp_config(*, api_key: str, base_url: str) -> dict[str, Any]:
    """No-op: web search no longer uses MCP/uvx (kept for config_sync compatibility)."""
    host = _api_host_from_base_url(base_url)
    if api_key:
        os.environ["MINIMAX_API_KEY"] = api_key.strip()
    return {
        "ok": True,
        "mode": "http",
        "endpoint": _search_url(host),
        "enabled": bool(api_key or os.environ.get("MINIMAX_API_KEY")),
        "uvx_required": False,
    }
