"""Unified RealAi LLM package."""

from __future__ import annotations

from typing import Any

from realai.llm.schema import (
    DEFAULT_LLM,
    catalog_for_api,
    normalize_llm,
    role_api_model,
    validate_llm,
)

__all__ = [
    "DEFAULT_LLM",
    "ChatResult",
    "ResolvedModel",
    "catalog_for_api",
    "chat_text",
    "chat_text_sync",
    "chat_turn",
    "chat_turn_stream",
    "chat_turn_sync",
    "chat_vision",
    "chat_vision_sync",
    "get_api_key",
    "has_api_key",
    "model_override_context",
    "normalize_llm",
    "resolve_role_model",
    "role_api_model",
    "validate_llm",
]


def __getattr__(name: str) -> Any:
    if name in {
        "ChatResult",
        "ResolvedModel",
        "chat_text",
        "chat_text_sync",
        "chat_turn",
        "chat_turn_stream",
        "chat_turn_sync",
        "chat_vision",
        "chat_vision_sync",
        "get_api_key",
        "has_api_key",
        "model_override_context",
        "resolve_role_model",
    }:
        from realai.llm import client as _client

        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
