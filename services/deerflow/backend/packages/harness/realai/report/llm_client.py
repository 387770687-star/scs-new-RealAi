"""Shared chat helper for report agents (via unified RealAi LLM client)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from realai.llm import chat_text as _chat_text
from realai.llm import chat_turn as _chat_turn
from realai.llm import chat_turn_stream as _chat_turn_stream

TextDeltaCallback = Callable[[str], Awaitable[None] | None]
StreamResetCallback = Callable[[], Awaitable[None] | None]


async def chat_turn(
    prompt: str,
    *,
    system: str | None = None,
    role: str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.5,
    timeout: float = 300.0,
    purpose: str = "report",
    reasoning_max_chars: int | None = None,
    allow_fallback: bool = True,
) -> dict[str, str | None]:
    """Call chat; return {content, reasoning} (reasoning may be None)."""
    result = await _chat_turn(
        prompt,
        system=system,
        role=role,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        purpose=purpose,
        reasoning_max_chars=reasoning_max_chars,
        allow_fallback=allow_fallback,
    )
    return {"content": result.content, "reasoning": result.reasoning}


async def chat_turn_stream(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.5,
    task_id: str | None = None,
    reasoning_max_chars: int = 6000,
    on_text_delta: TextDeltaCallback | None = None,
    on_reset: StreamResetCallback | None = None,
) -> dict[str, str | None]:
    """Stream report正文 deltas through the unified protocol-aware client."""
    result = await _chat_turn_stream(
        prompt,
        system=system,
        role="primary",
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=300.0,
        purpose="report",
        task_id=task_id,
        reasoning_max_chars=reasoning_max_chars,
        on_text_delta=on_text_delta,
        on_reset=on_reset,
    )
    return {"content": result.content, "reasoning": result.reasoning}


async def chat_text(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.5,
) -> str:
    return await _chat_text(
        prompt,
        system=system,
        role="primary",
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=300.0,
        purpose="report",
    )


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters + Chinese punctuation (approx Skill word budget)."""
    n = 0
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:
            n += 1
    return n
