"""Deprecated shim: MiniMax web search is HTTP-based (see minimax_web_search)."""

from __future__ import annotations

from realai.agents.minimax_web_search import (  # noqa: F401
    call_minimax_web_search,
    mcp_web_search_health,
    minimax_web_search_health,
    sync_minimax_mcp_config,
)
