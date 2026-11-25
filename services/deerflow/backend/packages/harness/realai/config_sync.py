"""Sync RealAi settings.json into DeerFlow runtime (.env, config.yaml)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from realai.config import load_settings
from realai.llm.schema import normalize_llm
from realai.paths import get_app_root, get_data_root

logger = logging.getLogger(__name__)

REALAI_MODELS_START = "# === REALAI_MANAGED_MODELS_START ==="
REALAI_MODELS_END = "# === REALAI_MANAGED_MODELS_END ==="


def deerflow_root() -> Path:
    env = os.environ.get("DEER_FLOW_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return get_app_root() / "services" / "deerflow"


def sync_from_disk() -> dict[str, Any]:
    """Load settings.json and push into DeerFlow."""
    return sync_deerflow_config(load_settings())


def _env_var_name(protocol: str, provider: str) -> str:
    if protocol == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider.lower() == "minimax":
        return "MINIMAX_API_KEY"
    return "OPENAI_API_KEY"


def _adapter_use(protocol: str, provider: str) -> str:
    if protocol == "anthropic":
        return "langchain_anthropic:ChatAnthropic"
    if provider.lower() == "minimax":
        return "deerflow.models.patched_minimax:PatchedChatMiniMax"
    return "langchain_openai:ChatOpenAI"


def sync_deerflow_config(settings: dict[str, Any]) -> dict[str, Any]:
    """Write API key / model endpoint into DeerFlow env + config.yaml."""
    deer = deerflow_root()
    llm = normalize_llm(settings.get("llm") or {})
    api_key = str(llm.get("apiKey") or "").strip()
    base_url = str(llm.get("baseUrl") or "https://api.minimaxi.com/v1").strip()
    protocol = str(llm.get("protocol") or "openai_compatible")
    provider = str(llm.get("provider") or "minimax")
    env_var = _env_var_name(protocol, provider)

    env_path = deer / ".env"
    existing = _read_env_value(env_path, env_var)
    # Also try legacy MiniMax key when migrating
    if not existing and env_var != "MINIMAX_API_KEY":
        existing = _read_env_value(env_path, "MINIMAX_API_KEY")
    effective_key = api_key or existing or os.environ.get(env_var, "") or os.environ.get(
        "MINIMAX_API_KEY", ""
    )
    _write_env_keys(env_path, {env_var: effective_key})
    if effective_key:
        os.environ[env_var] = effective_key
        # Keep MiniMax env populated for older code paths when using MiniMax
        if env_var == "MINIMAX_API_KEY":
            os.environ["MINIMAX_API_KEY"] = effective_key

    cfg_path = deer / "config.yaml"
    if not cfg_path.is_file():
        example = deer / "config.example.yaml"
        if example.is_file():
            cfg_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    if cfg_path.is_file():
        text = cfg_path.read_text(encoding="utf-8")
        text = _upsert_managed_models(text, llm, env_var=env_var, base_url=base_url)
        cfg_path.write_text(text, encoding="utf-8")

    runtime_path = get_data_root() / "config" / "realai.runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        json.dumps(
            {
                "obsidianVaultPath": settings.get("obsidianVaultPath"),
                "report": settings.get("report"),
                "search": settings.get("search"),
                "data": settings.get("data"),
                "llm": {
                    "modelId": llm.get("modelId") or "minimax-m3",
                    "protocol": protocol,
                    "provider": provider,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    reloaded = False
    try:
        from deerflow.config.app_config import reload_app_config

        reload_app_config(str(cfg_path))
        reloaded = True
    except Exception:
        logger.debug("reload_app_config skipped", exc_info=True)

    memory_seed: dict[str, Any] = {"ok": False, "reason": "not_attempted"}
    try:
        from realai.org_identity import ensure_org_identity_in_deerflow_memory

        memory_seed = ensure_org_identity_in_deerflow_memory(user_id="default")
    except Exception:
        logger.debug("org identity memory seed skipped", exc_info=True)
        memory_seed = {"ok": False, "reason": "exception"}

    mcp_sync: dict[str, Any] = {"ok": False, "reason": "not_attempted"}
    try:
        from realai.agents.minimax_web_search import sync_minimax_mcp_config

        mcp_key = effective_key
        if provider.lower() != "minimax":
            mcp_key = os.environ.get("MINIMAX_API_KEY", "") or mcp_key
        # Ensure env has Key for search; no uvx/MCP process required
        mcp_sync = sync_minimax_mcp_config(api_key=mcp_key, base_url=base_url)
    except Exception:
        logger.debug("MiniMax web search env sync skipped", exc_info=True)
        mcp_sync = {"ok": False, "reason": "exception"}

    return {
        "ok": True,
        "deerflow_env": str(env_path),
        "deerflow_config": str(cfg_path),
        "model_id": llm.get("modelId") or "minimax-m3",
        "protocol": protocol,
        "provider": provider,
        "base_url": base_url,
        "env_var": env_var,
        "has_api_key": bool(effective_key),
        "config_reloaded": reloaded,
        "org_identity_memory": memory_seed,
        "web_search_sync": mcp_sync,
        "mcp_sync": mcp_sync,
    }


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.is_file():
        return ""
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    return ""


def _write_env_keys(env_path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    keys_done: set[str] = set()
    out: list[str] = []
    for line in lines:
        matched = False
        for key, value in updates.items():
            if line.startswith(f"{key}="):
                out.append(f"{key}={value}")
                keys_done.add(key)
                matched = True
                break
        if not matched:
            out.append(line)
    for key, value in updates.items():
        if key not in keys_done:
            out.append(f"{key}={value}")
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _yaml_escape(value: str) -> str:
    if any(c in value for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "\n", '"', "'")):
        return json.dumps(value, ensure_ascii=False)
    return value


def _build_model_yaml_block(
    *,
    name: str,
    label: str,
    api_model: str,
    use: str,
    env_var: str,
    base_url: str,
    protocol: str,
    provider: str,
) -> str:
    lines = [
        f"  - name: {_yaml_escape(name)}",
        f"    display_name: {_yaml_escape(label or api_model)}",
        f"    use: {use}",
        f"    model: {_yaml_escape(api_model)}",
        f"    api_key: ${env_var}",
    ]
    # Anthropic ChatAnthropic uses base_url optionally; OpenAI-compat needs it
    if protocol != "anthropic" or base_url:
        lines.append(f"    base_url: {_yaml_escape(base_url)}")
    lines.extend(
        [
            "    request_timeout: 600.0",
            "    max_retries: 2",
            "    max_tokens: 4096",
            "    supports_vision: true",
        ]
    )
    if protocol == "openai_compatible" and provider.lower() == "minimax":
        lines.extend(
            [
                "    supports_thinking: true",
                "    when_thinking_enabled:",
                "      extra_body:",
                "        thinking:",
                "          type: adaptive",
                "    when_thinking_disabled:",
                "      extra_body:",
                "        thinking:",
                "          type: disabled",
            ]
        )
    return "\n".join(lines) + "\n"


def _models_to_sync(llm: dict[str, Any]) -> list[dict[str, str]]:
    catalog = list(llm.get("models") or [])
    roles = llm.get("roles") or {}
    needed_ids = {str(roles.get(r) or "").strip() for r in ("primary", "fast", "vision", "fallback")}
    needed_ids.discard("")
    if not needed_ids:
        return catalog
    by_id = {m["id"]: m for m in catalog if m.get("id")}
    out = []
    seen: set[str] = set()
    for mid in needed_ids:
        if mid in by_id and mid not in seen:
            out.append(by_id[mid])
            seen.add(mid)
    # Include full catalog so user-registered models are available in DeerFlow
    for m in catalog:
        mid = m.get("id")
        if mid and mid not in seen:
            out.append(m)
            seen.add(mid)
    return out or catalog


def _upsert_managed_models(
    text: str,
    llm: dict[str, Any],
    *,
    env_var: str,
    base_url: str,
) -> str:
    protocol = str(llm.get("protocol") or "openai_compatible")
    provider = str(llm.get("provider") or "minimax")
    use = _adapter_use(protocol, provider)
    blocks: list[str] = []
    for m in _models_to_sync(llm):
        blocks.append(
            _build_model_yaml_block(
                name=str(m.get("id") or "model"),
                label=str(m.get("label") or m.get("apiModel") or ""),
                api_model=str(m.get("apiModel") or ""),
                use=use,
                env_var=env_var,
                base_url=base_url,
                protocol=protocol,
                provider=provider,
            )
        )
    managed = REALAI_MODELS_START + "\n" + "".join(blocks) + REALAI_MODELS_END + "\n"

    if REALAI_MODELS_START in text and REALAI_MODELS_END in text:
        pattern = re.compile(
            re.escape(REALAI_MODELS_START) + r"[\s\S]*?" + re.escape(REALAI_MODELS_END) + r"\n?",
            re.MULTILINE,
        )
        return pattern.sub(managed, text, count=1)

    # First sync: insert managed block under models:
    if re.search(r"^models:\s*$", text, re.MULTILINE):
        return re.sub(
            r"^models:\s*$",
            "models:\n" + managed.rstrip() + "\n",
            text,
            count=1,
            flags=re.MULTILINE,
        )

    # If an old minimax-m3 block exists without markers, prepend markers around generated set
    # after models: and leave historical commented examples intact.
    m = re.search(r"^models:\s*\n", text, re.MULTILINE)
    if m:
        insert_at = m.end()
        return text[:insert_at] + managed + text[insert_at:]

    return text + "\nmodels:\n" + managed


if __name__ == "__main__":
    import sys

    result = sync_from_disk()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
