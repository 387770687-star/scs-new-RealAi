"""First-run onboarding status and completion."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from realai.bootstrap import bootstrap_data_dir
from realai.config import (
    get_settings_path,
    load_settings,
    public_settings,
    resolve_vault_path,
    save_settings,
)
from realai.config_sync import sync_deerflow_config
from realai.paths import ensure_data_layout, get_data_root


def onboarding_needed(settings: dict[str, Any] | None = None) -> bool:
    settings = settings or load_settings()
    if (settings.get("onboarding") or {}).get("completed"):
        return False
    if not get_settings_path().is_file():
        return True
    llm = settings.get("llm") or {}
    has_key = bool(str(llm.get("apiKey") or "").strip() or os.environ.get("MINIMAX_API_KEY"))
    return not has_key


def health_snapshot() -> dict[str, Any]:
    ensure_data_layout()
    settings = load_settings()
    vault = resolve_vault_path(settings)
    llm = settings.get("llm") or {}
    has_key = bool(str(llm.get("apiKey") or "").strip() or os.environ.get("MINIMAX_API_KEY"))
    vault_exists = vault.is_dir()
    file_count = 0
    if vault_exists:
        try:
            from realai.vault.index import get_vault_index

            file_count = len(get_vault_index())
        except Exception:
            file_count = 0
    web_search_health: dict[str, Any] = {}
    try:
        from realai.agents.minimax_web_search import minimax_web_search_health

        web_search_health = minimax_web_search_health()
    except Exception as exc:
        web_search_health = {"detail": f"联网健康检查失败：{exc}"}
    search = settings.get("search") or {}
    return {
        "data_root": str(get_data_root()),
        "settings_exists": get_settings_path().is_file(),
        "vault_path": str(vault),
        "vault_exists": vault_exists,
        "vault_file_count": file_count,
        "has_api_key": has_key,
        "web_search_default": search.get("webSearchMode") or "auto",
        "web_search_enabled": bool((search.get("webSearchMode") or "auto") != "off"),
        "web_search_skill_id": search.get("webSearchSkillId") or "web-search",
        "minimax_web_search": web_search_health,
        "minimax_mcp_web_search": web_search_health,
        "onboarding_needed": onboarding_needed(settings),
    }


def complete_onboarding(
    *,
    api_key: str,
    web_search_enabled: bool | None = None,
    web_search_mode: str | None = None,
    import_demo: bool = True,
    vault_path: str | None = None,
) -> dict[str, Any]:
    from realai.config import resolve_request_web_search_mode

    ensure_data_layout()
    bootstrap = bootstrap_data_dir(demo_vault=import_demo)
    mode = resolve_request_web_search_mode(
        web_search_mode,
        web_search_enabled,
        fallback_settings=False,
    )
    # Onboarding: unset → default smart (auto)
    if web_search_mode is None and web_search_enabled is None:
        mode = "auto"
    patch: dict[str, Any] = {
        "llm": {"apiKey": api_key.strip()},
        "search": {"webSearchMode": mode, "webSearchEnabled": mode != "off"},
        "onboarding": {
            "completed": True,
            "completedAt": datetime.now(UTC).isoformat(),
        },
    }
    if vault_path:
        patch["obsidianVaultPath"] = vault_path
    saved = save_settings(patch)
    deerflow = sync_deerflow_config(saved)
    return {
        "ok": True,
        "bootstrap": bootstrap,
        "settings": public_settings(saved),
        "deerflow": deerflow,
        "onboarding_needed": False,
    }
