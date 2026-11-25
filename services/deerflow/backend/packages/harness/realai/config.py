"""Load RealAi settings from RealAiData/config/settings.json (or repo config/ in dev)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from realai.llm.schema import DEFAULT_LLM, normalize_llm, validate_llm
from realai.paths import ensure_data_layout, get_data_root, get_repo_root, resolve_data_path

WebSearchMode = Literal["off", "auto", "force"]
VisionMode = Literal["off", "auto", "force"]
WEB_SEARCH_MODES: frozenset[str] = frozenset({"off", "auto", "force"})
VISION_MODES: frozenset[str] = frozenset({"off", "auto", "force"})

DEFAULTS: dict[str, Any] = {
    "obsidianVaultPath": "./vault",
    "onboarding": {"completed": False},
    "llm": dict(DEFAULT_LLM),
    "search": {
        "webSearchMode": "auto",
        "webSearchEnabled": False,
        "webSearchSkillId": "web-search",
        "visionMode": "auto",
    },
    "data": {"excelRoots": ["./vault"], "databases": []},
    "report": {
        "outputDir": "./vault/reports",
        "stepConfirm": False,
        "intakeSkillId": "strategic-planning-intake",
        "researcherSkillId": "strategic-planning-researcher",
        "architectSkillId": "strategic-planning-architect",
        "writerSkillId": "strategic-planning-writer",
        "citerSkillId": "strategic-planning-citer",
        "reviewSkillId": "strategic-planning-reviewer",
        "optimizerSkillId": "strategic-planning-optimizer",
        "optimizerMaxRounds": 5,
        "optimizerPassScore": 85,
    },
}


def normalize_web_search_mode(
    mode: str | None = None,
    *,
    enabled: bool | None = None,
) -> WebSearchMode:
    """Resolve off|auto|force from mode string and/or legacy boolean."""
    raw = (mode or "").strip().lower()
    if raw in WEB_SEARCH_MODES:
        return raw  # type: ignore[return-value]
    if enabled is True:
        return "force"
    if enabled is False and mode is None:
        return "off"
    return "auto"


def get_web_search_mode(settings: dict[str, Any] | None = None) -> WebSearchMode:
    """Read web search mode from settings with legacy webSearchEnabled compat."""
    settings = settings or load_settings()
    search = settings.get("search") or {}
    mode = search.get("webSearchMode")
    if mode is None and "webSearchEnabled" in search:
        return normalize_web_search_mode(None, enabled=bool(search.get("webSearchEnabled")))
    if mode is None:
        return "auto"
    return normalize_web_search_mode(str(mode), enabled=None)


def resolve_request_web_search_mode(
    mode: str | None = None,
    enabled: bool | None = None,
    *,
    fallback_settings: bool = False,
) -> WebSearchMode:
    """Resolve per-request mode; optional fallback to settings default."""
    raw = (mode or "").strip().lower()
    if raw in WEB_SEARCH_MODES:
        return raw  # type: ignore[return-value]
    if enabled is True:
        return "force"
    if enabled is False:
        return "off"
    if fallback_settings:
        return get_web_search_mode()
    return "auto"


def normalize_vision_mode(
    mode: str | None = None,
    *,
    enabled: bool | None = None,
) -> VisionMode:
    """Resolve off|auto|force for vision (mirrors web search)."""
    raw = (mode or "").strip().lower()
    if raw in VISION_MODES:
        return raw  # type: ignore[return-value]
    if enabled is True:
        return "force"
    if enabled is False and mode is None:
        return "off"
    return "auto"


def get_vision_mode(settings: dict[str, Any] | None = None) -> VisionMode:
    settings = settings or load_settings()
    search = settings.get("search") or {}
    mode = search.get("visionMode")
    if mode is None:
        return "auto"
    return normalize_vision_mode(str(mode))


def resolve_request_vision_mode(
    mode: str | None = None,
    enabled: bool | None = None,
    *,
    fallback_settings: bool = False,
) -> VisionMode:
    raw = (mode or "").strip().lower()
    if raw in VISION_MODES:
        return raw  # type: ignore[return-value]
    if enabled is True:
        return "force"
    if enabled is False:
        return "off"
    if fallback_settings:
        return get_vision_mode()
    return "auto"


def _normalize_search_settings(
    search: dict[str, Any],
    *,
    user_search: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize search block. Legacy: explicit true→force; else default auto."""
    out = dict(search)
    user = user_search if user_search is not None else search
    if "webSearchMode" in user and user.get("webSearchMode") is not None:
        mode = normalize_web_search_mode(str(user.get("webSearchMode")))
    elif user.get("webSearchEnabled") is True:
        mode = "force"
    else:
        # false / missing / only defaults → smart default
        mode = "auto"
    out["webSearchMode"] = mode
    out["webSearchEnabled"] = mode != "off"
    skill_id = str(out.get("webSearchSkillId") or DEFAULTS["search"]["webSearchSkillId"]).strip()
    out["webSearchSkillId"] = skill_id or "web-search"
    if "visionMode" in user and user.get("visionMode") is not None:
        out["visionMode"] = normalize_vision_mode(str(user.get("visionMode")))
    else:
        out["visionMode"] = normalize_vision_mode(str(out.get("visionMode") or "auto"))
    return out

def get_web_search_skill_id(settings: dict[str, Any] | None = None) -> str:
    settings = settings or load_settings()
    search = settings.get("search") or {}
    sid = str(search.get("webSearchSkillId") or DEFAULTS["search"]["webSearchSkillId"]).strip()
    return sid or "web-search"


def get_settings_path() -> Path:
    ensure_data_layout()
    return get_data_root() / "config" / "settings.json"


def _default_settings() -> dict[str, Any]:
    out = dict(DEFAULTS)
    out["llm"] = normalize_llm(dict(DEFAULT_LLM))
    out["search"] = _normalize_search_settings(dict(DEFAULTS["search"]))
    return out


def load_settings() -> dict[str, Any]:
    path = get_settings_path()
    if not path.is_file():
        return _default_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_settings()
    merged = dict(DEFAULTS)
    merged.update(data)
    if isinstance(data.get("llm"), dict):
        user_llm = data["llm"]
        base = {**DEFAULTS["llm"], **user_llm}
        # Don't let DEFAULTS.models block flat-field migration for legacy files
        if "models" not in user_llm:
            base.pop("models", None)
        if "roles" not in user_llm:
            base.pop("roles", None)
        merged["llm"] = normalize_llm(base)
    else:
        merged["llm"] = normalize_llm(dict(DEFAULT_LLM))
    if isinstance(data.get("search"), dict):
        user_search = data["search"]
        merged["search"] = _normalize_search_settings(
            {**DEFAULTS["search"], **user_search},
            user_search=user_search,
        )
    else:
        merged["search"] = _normalize_search_settings(dict(DEFAULTS["search"]))
    if isinstance(data.get("report"), dict):
        merged["report"] = {**DEFAULTS["report"], **data["report"]}
    if isinstance(data.get("data"), dict):
        merged["data"] = {**DEFAULTS["data"], **data["data"]}
    if isinstance(data.get("onboarding"), dict):
        merged["onboarding"] = {**DEFAULTS["onboarding"], **data["onboarding"]}
    return merged


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Persist settings.json (merge with defaults)."""
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    merged = _merge_settings(current, settings)
    errors = validate_llm(merged.get("llm") or {})
    if errors:
        raise ValueError("；".join(errors))
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def _merge_settings(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    merged.update(current)
    merged.update({k: v for k, v in incoming.items() if v is not None})

    for key in ("llm", "search", "report", "data", "onboarding"):
        if isinstance(incoming.get(key), dict):
            base = dict(merged.get(key) or DEFAULTS.get(key) or {})
            base.update(incoming[key])
            merged[key] = base

    if isinstance(merged.get("search"), dict):
        user_search = incoming["search"] if isinstance(incoming.get("search"), dict) else None
        merged["search"] = _normalize_search_settings(merged["search"], user_search=user_search)

    llm_in = incoming.get("llm") if isinstance(incoming.get("llm"), dict) else {}
    if not str(llm_in.get("apiKey") or "").strip():
        prev_key = (current.get("llm") or {}).get("apiKey") or ""
        if prev_key:
            merged.setdefault("llm", {})["apiKey"] = prev_key

    # If caller didn't send models/roles, keep current catalog (don't re-migrate from defaults)
    if llm_in:
        if "models" not in llm_in and isinstance((current.get("llm") or {}).get("models"), list):
            merged.setdefault("llm", {})["models"] = (current.get("llm") or {}).get("models")
        if "roles" not in llm_in and isinstance((current.get("llm") or {}).get("roles"), dict):
            merged.setdefault("llm", {})["roles"] = (current.get("llm") or {}).get("roles")

    merged["llm"] = normalize_llm(merged.get("llm") or {})
    return merged


def public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strip secrets for API responses."""
    settings = settings or load_settings()
    out = dict(settings)
    llm = normalize_llm(dict(out.get("llm") or {}))
    raw_key = str(llm.get("apiKey") or "").strip()
    from realai.llm.client import has_api_key

    has_key = has_api_key(settings)
    llm.pop("apiKey", None)
    llm["hasApiKey"] = has_key
    if has_key and raw_key and len(raw_key) >= 8:
        llm["apiKeyPreview"] = f"{raw_key[:4]}…{raw_key[-4:]}"
    elif has_key:
        llm["apiKeyPreview"] = "已配置"
    else:
        llm["apiKeyPreview"] = ""
    out["llm"] = llm
    return out


def resolve_vault_path(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_settings()
    raw = settings.get("obsidianVaultPath") or DEFAULTS["obsidianVaultPath"]
    return resolve_data_path(str(raw))


def resolve_report_output_dir(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_settings()
    raw = (settings.get("report") or {}).get("outputDir") or DEFAULTS["report"]["outputDir"]
    return resolve_data_path(str(raw))


def light_tool_groups(web_search_enabled: bool | str | None = None) -> list[str]:
    groups = ["file:read"]
    if isinstance(web_search_enabled, str):
        allow = normalize_web_search_mode(web_search_enabled) != "off"
    else:
        allow = bool(web_search_enabled)
    if allow:
        groups.append("web")
    return groups


def resolve_chat_model_name(settings: dict[str, Any] | None = None) -> str:
    """Resolve provider API model id (e.g. MiniMax-M3) from settings + DeerFlow config."""
    settings = settings or load_settings()
    llm = normalize_llm(settings.get("llm") or {})
    model_id = llm.get("modelId") or "minimax-m3"
    try:
        from deerflow.config import get_app_config

        cfg = get_app_config().get_model_config(str(model_id))
        if cfg and cfg.model:
            return str(cfg.model)
    except Exception:
        pass
    raw = llm.get("model") or "MiniMax-M3"
    return str(raw).replace(" ", "-")


# Backward-compatible re-exports
from realai.paths import get_app_root, get_repo_root  # noqa: E402,F401
