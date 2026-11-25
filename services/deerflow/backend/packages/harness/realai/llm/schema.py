"""LLM settings schema: protocol, model catalog, role assignment, legacy migration."""

from __future__ import annotations

import re
from typing import Any, Literal

LlmProtocol = Literal["openai_compatible", "anthropic"]
LlmRole = Literal["primary", "fast", "vision", "fallback"]

PROTOCOLS: frozenset[str] = frozenset({"openai_compatible", "anthropic"})
ROLES: tuple[str, ...] = ("primary", "fast", "vision", "fallback")

DEFAULT_LLM: dict[str, Any] = {
    "protocol": "openai_compatible",
    "provider": "minimax",
    "apiKey": "",
    "baseUrl": "https://api.minimaxi.com/v1",
    "models": [
        {
            "id": "minimax-m3",
            "label": "MiniMax M3",
            "apiModel": "MiniMax-M3",
        }
    ],
    "roles": {
        "primary": "minimax-m3",
        "fast": "",
        "vision": "",
        "fallback": "",
    },
    # Flat fields kept for backward compatibility / DeerFlow modelId
    "modelId": "minimax-m3",
    "model": "MiniMax-M3",
    "fastModel": "",
    "visionModel": "",
    "fallbackModel": "",
}


def _slug_id(raw: str, *, fallback: str = "model") -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(raw or "").strip()).strip("-").lower()
    return s or fallback


def _normalize_model_entry(raw: Any, *, index: int = 0) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    api_model = str(raw.get("apiModel") or raw.get("model") or "").strip()
    if not api_model:
        return None
    mid = str(raw.get("id") or "").strip() or _slug_id(api_model, fallback=f"model-{index + 1}")
    label = str(raw.get("label") or raw.get("name") or api_model).strip() or api_model
    return {"id": mid, "label": label, "apiModel": api_model}


def _find_model(models: list[dict[str, str]], model_id: str) -> dict[str, str] | None:
    for m in models:
        if m.get("id") == model_id:
            return m
    return None


def _find_by_api_model(models: list[dict[str, str]], api_model: str) -> dict[str, str] | None:
    target = api_model.strip()
    for m in models:
        if m.get("apiModel") == target:
            return m
    return None


def _ensure_catalog_entry(
    models: list[dict[str, str]],
    *,
    mid: str,
    label: str,
    api_model: str,
) -> str:
    existing = _find_model(models, mid)
    if existing:
        if api_model and existing.get("apiModel") != api_model:
            # Same id, refresh api model / label
            existing["apiModel"] = api_model
            if label:
                existing["label"] = label
        return mid
    by_api = _find_by_api_model(models, api_model)
    if by_api:
        return str(by_api["id"])
    models.append({"id": mid, "label": label or api_model, "apiModel": api_model})
    return mid


def _migrate_from_flat(llm: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, str]]:
    models: list[dict[str, str]] = []
    roles = {"primary": "", "fast": "", "vision": "", "fallback": ""}

    primary_api = str(llm.get("model") or "MiniMax-M3").replace(" ", "-").strip() or "MiniMax-M3"
    primary_id = str(llm.get("modelId") or "").strip() or _slug_id(primary_api, fallback="minimax-m3")
    primary_label = str(llm.get("model") or primary_api).strip() or primary_api
    roles["primary"] = _ensure_catalog_entry(
        models, mid=primary_id, label=primary_label, api_model=primary_api
    )

    for role, flat_key in (
        ("fast", "fastModel"),
        ("vision", "visionModel"),
        ("fallback", "fallbackModel"),
    ):
        raw = str(llm.get(flat_key) or "").strip()
        if not raw:
            continue
        mid = _slug_id(raw, fallback=f"{role}-model")
        roles[role] = _ensure_catalog_entry(models, mid=mid, label=raw, api_model=raw)

    return models, roles


def normalize_llm(llm: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize llm block: protocol, models[], roles, and flat compat fields."""
    src: dict[str, Any] = {}
    if isinstance(llm, dict):
        src.update(llm)

    protocol = str(src.get("protocol") or DEFAULT_LLM["protocol"]).strip().lower()
    if protocol not in PROTOCOLS:
        protocol = "openai_compatible"
    provider = str(src.get("provider") or DEFAULT_LLM["provider"]).strip() or "minimax"
    base_url = str(src.get("baseUrl") or DEFAULT_LLM["baseUrl"]).strip() or DEFAULT_LLM["baseUrl"]
    api_key = str(src.get("apiKey") or "")

    raw_models = src.get("models")
    models: list[dict[str, str]] = []
    if isinstance(raw_models, list) and raw_models:
        for i, item in enumerate(raw_models):
            entry = _normalize_model_entry(item, index=i)
            if entry and not _find_model(models, entry["id"]):
                models.append(entry)

    raw_roles = src.get("roles") if isinstance(src.get("roles"), dict) else {}
    roles = {
        "primary": str(raw_roles.get("primary") or "").strip(),
        "fast": str(raw_roles.get("fast") or "").strip(),
        "vision": str(raw_roles.get("vision") or "").strip(),
        "fallback": str(raw_roles.get("fallback") or "").strip(),
    }

    if not models:
        # Fill missing connection defaults for migration input
        if "model" not in src and "modelId" not in src:
            src = {**DEFAULT_LLM, **src}
            src.pop("models", None)
            src.pop("roles", None)
        models, migrated_roles = _migrate_from_flat(src)
        for k, v in migrated_roles.items():
            if v and not roles.get(k):
                roles[k] = v

    if not roles.get("primary") and models:
        roles["primary"] = models[0]["id"]

    # Drop role refs that point nowhere
    for role in ROLES:
        rid = roles.get(role) or ""
        if rid and not _find_model(models, rid):
            roles[role] = ""

    if not roles.get("primary") and models:
        roles["primary"] = models[0]["id"]
    if not roles.get("primary"):
        # Last resort defaults
        models = [dict(DEFAULT_LLM["models"][0])]
        roles = dict(DEFAULT_LLM["roles"])

    primary = _find_model(models, roles["primary"]) or models[0]
    roles["primary"] = primary["id"]

    flat_fast = ""
    flat_vision = ""
    flat_fallback = ""
    if roles.get("fast"):
        m = _find_model(models, roles["fast"])
        flat_fast = (m or {}).get("apiModel") or ""
    if roles.get("vision"):
        m = _find_model(models, roles["vision"])
        flat_vision = (m or {}).get("apiModel") or ""
    if roles.get("fallback"):
        m = _find_model(models, roles["fallback"])
        flat_fallback = (m or {}).get("apiModel") or ""

    out: dict[str, Any] = {
        "protocol": protocol,
        "provider": provider,
        "apiKey": api_key,
        "baseUrl": base_url,
        "models": models,
        "roles": roles,
        "modelId": primary["id"],
        "model": primary["apiModel"],
        "fastModel": flat_fast,
        "visionModel": flat_vision,
        "fallbackModel": flat_fallback,
    }
    # Preserve unknown keys (e.g. future fields) except ones we own
    for k, v in src.items():
        if k not in out and k not in ("hasApiKey", "apiKeyPreview"):
            out[k] = v
    return out


def validate_llm(llm: dict[str, Any]) -> list[str]:
    """Return human-readable validation errors (empty = ok)."""
    errors: list[str] = []
    norm = normalize_llm(llm)
    models = norm.get("models") or []
    if not models:
        errors.append("至少登记一个模型")
    roles = norm.get("roles") or {}
    if not roles.get("primary"):
        errors.append("必须指定主模型")
    for role in ROLES:
        rid = roles.get(role) or ""
        if rid and not _find_model(models, rid):
            errors.append(f"角色 {role} 引用了不存在的模型 id：{rid}")
    protocol = norm.get("protocol")
    if protocol not in PROTOCOLS:
        errors.append(f"不支持的协议：{protocol}")
    return errors


def role_api_model(llm: dict[str, Any], role: str) -> str:
    """Resolve API model name for a role (fast/vision empty → primary)."""
    norm = normalize_llm(llm)
    roles = norm.get("roles") or {}
    models = norm.get("models") or []
    rid = str(roles.get(role) or "").strip()
    if role != "primary" and not rid:
        rid = str(roles.get("primary") or "")
    entry = _find_model(models, rid) if rid else None
    if entry:
        return str(entry["apiModel"])
    return str(norm.get("model") or "MiniMax-M3")


def catalog_for_api(llm: dict[str, Any]) -> dict[str, Any]:
    """Public catalog + resolved role api models for GET /models."""
    norm = normalize_llm(llm)
    roles = norm.get("roles") or {}
    models = norm.get("models") or []
    resolved = []
    for role in ROLES:
        rid = str(roles.get(role) or "").strip()
        entry = _find_model(models, rid) if rid else None
        if role != "primary" and not entry:
            resolved.append(
                {
                    "role": role,
                    "modelId": None,
                    "apiModel": None,
                    "label": None,
                    "enabled": False,
                }
            )
            continue
        if not entry and role == "primary":
            entry = models[0] if models else None
        resolved.append(
            {
                "role": role,
                "modelId": (entry or {}).get("id"),
                "apiModel": (entry or {}).get("apiModel"),
                "label": (entry or {}).get("label"),
                "enabled": bool(entry),
            }
        )
    return {
        "protocol": norm.get("protocol"),
        "provider": norm.get("provider"),
        "baseUrl": norm.get("baseUrl"),
        "catalog": models,
        "roles": roles,
        "resolved": resolved,
    }
