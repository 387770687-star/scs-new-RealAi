"""Web search for RealAi — MiniMax Coding Plan HTTP API (portable, no uvx)."""

from __future__ import annotations

import logging
from typing import Literal, overload

from realai.evidence.types import EvidencePack

logger = logging.getLogger(__name__)


@overload
async def search_web(
    query: str,
    *,
    limit: int = 3,
    return_error: Literal[False] = False,
) -> EvidencePack: ...


@overload
async def search_web(
    query: str,
    *,
    limit: int = 3,
    return_error: Literal[True],
) -> tuple[EvidencePack, str | None]: ...


async def search_web(
    query: str,
    *,
    limit: int = 3,
    return_error: bool = False,
) -> EvidencePack | tuple[EvidencePack, str | None]:
    """Run MiniMax HTTP web search and map results to web: evidence."""
    from realai.agents.minimax_web_search import call_minimax_web_search

    pack, err = await call_minimax_web_search(query, limit=limit)
    if err:
        logger.warning("web search failed: %s", err)
    if return_error:
        return pack, err
    return pack
