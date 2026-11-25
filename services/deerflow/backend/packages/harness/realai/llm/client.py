"""Protocol-aware chat client with role routing and fallback."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from realai.llm.schema import normalize_llm, role_api_model
from realai.meta.routing import log_model_call

logger = logging.getLogger(__name__)

RoleName = Literal["primary", "fast", "vision", "fallback"]
TextDeltaCallback = Callable[[str], Awaitable[None] | None]
StreamResetCallback = Callable[[], Awaitable[None] | None]
_model_override: ContextVar[str | None] = ContextVar("realai_model_override", default=None)

# MiniMax OpenAI-compatible multimodal limits (approx).
_VISION_MAX_IMAGES = 2
_VISION_MAX_BYTES = 10 * 1024 * 1024
_VISION_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    if settings is None:
        from realai.config import load_settings

        settings = load_settings()
    override = (_model_override.get() or "").strip()
    if not override:
        return settings

    # Never mutate the process-wide settings cache. The override is scoped to the
    # current evaluation coroutine and therefore remains safe under concurrent runs.
    copied = dict(settings)
    llm = normalize_llm(dict(settings.get("llm") or {}))
    models = [dict(m) for m in (llm.get("models") or [])]
    selected = next(
        (
            m
            for m in models
            if override in {
                str(m.get("id") or ""),
                str(m.get("apiModel") or ""),
                str(m.get("label") or ""),
            }
        ),
        None,
    )
    if selected is None:
        selected = {"id": f"eval-{override}", "label": override, "apiModel": override}
        models.append(selected)
    roles = dict(llm.get("roles") or {})
    roles["primary"] = selected["id"]
    roles["fast"] = selected["id"]
    llm["models"] = models
    llm["roles"] = roles
    llm["modelId"] = selected["id"]
    llm["model"] = selected["apiModel"]
    copied["llm"] = llm
    return copied


@contextmanager
def model_override_context(model: str | None):
    """Temporarily route all LLM calls in this async context to one catalog model."""
    token = _model_override.set((model or "").strip() or None)
    try:
        yield
    finally:
        _model_override.reset(token)


@dataclass
class ResolvedModel:
    role: str
    catalog_id: str
    api_model: str
    protocol: str
    provider: str
    base_url: str
    api_key: str


@dataclass
class ChatResult:
    content: str
    reasoning: str | None = None
    model: str = ""
    degraded: bool = False
    fallback_model: str | None = None
    usage: dict[str, Any] | None = None


def _pack_chat_result(
    content: str,
    reasoning: str | None,
    *,
    model: str,
    usage: dict[str, Any] | None = None,
    degraded: bool = False,
    fallback_model: str | None = None,
    reasoning_max_chars: int | None = None,
) -> ChatResult:
    from realai.llm.sanitize import finalize_llm_text

    visible, merged_reasoning = finalize_llm_text(content, reasoning)
    if merged_reasoning and reasoning_max_chars is not None:
        merged_reasoning = merged_reasoning[: max(0, reasoning_max_chars)] or None
    return ChatResult(
        content=visible,
        reasoning=merged_reasoning,
        model=model,
        degraded=degraded,
        fallback_model=fallback_model,
        usage=usage,
    )


def get_api_key(settings: dict[str, Any] | None = None) -> str:
    settings = _settings(settings)
    llm = normalize_llm(settings.get("llm") or {})
    key = str(llm.get("apiKey") or "").strip()
    if key:
        return key
    protocol = str(llm.get("protocol") or "openai_compatible")
    provider = str(llm.get("provider") or "minimax").lower()
    if protocol == "anthropic":
        return (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("REALAI_LLM_API_KEY") or "").strip()
    if provider == "minimax":
        return (os.environ.get("MINIMAX_API_KEY") or os.environ.get("REALAI_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    return (os.environ.get("OPENAI_API_KEY") or os.environ.get("REALAI_LLM_API_KEY") or os.environ.get("MINIMAX_API_KEY") or "").strip()


def has_api_key(settings: dict[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def resolve_role_model(
    role: RoleName | str = "primary",
    settings: dict[str, Any] | None = None,
) -> ResolvedModel:
    settings = _settings(settings)
    llm = normalize_llm(settings.get("llm") or {})
    roles = llm.get("roles") or {}
    models = llm.get("models") or []

    rid = str(roles.get(role) or "").strip()
    if role != "primary" and not rid:
        rid = str(roles.get("primary") or "").strip()

    entry = None
    for m in models:
        if m.get("id") == rid:
            entry = m
            break
    if entry is None and models:
        entry = models[0]
        rid = str(entry.get("id") or "")

    api_model = str((entry or {}).get("apiModel") or role_api_model(llm, str(role)))
    catalog_id = str((entry or {}).get("id") or rid or "primary")
    protocol = str(llm.get("protocol") or "openai_compatible")
    provider = str(llm.get("provider") or "minimax")
    base_url = str(llm.get("baseUrl") or "").strip()
    if not base_url:
        if protocol == "anthropic":
            base_url = "https://api.anthropic.com"
        else:
            base_url = "https://api.minimaxi.com/v1"

    return ResolvedModel(
        role=str(role),
        catalog_id=catalog_id,
        api_model=api_model,
        protocol=protocol,
        provider=provider,
        base_url=base_url.rstrip("/"),
        api_key=get_api_key(settings),
    )


def _extract_reasoning_openai(message: dict[str, Any], payload: dict[str, Any]) -> str | None:
    for key in ("reasoning_content", "reasoning", "thinking", "reasoning_text"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    choice0 = (payload.get("choices") or [{}])[0]
    for key in ("reasoning_content", "reasoning", "thinking"):
        val = choice0.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _stream_text(value: Any) -> str:
    """Normalize OpenAI-compatible streamed text fields."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _parse_openai_stream_event(
    payload: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None]:
    """Return visible delta, reasoning delta, and optional usage."""
    choice = (payload.get("choices") or [{}])[0]
    delta = choice.get("delta") if isinstance(choice, dict) else {}
    if not isinstance(delta, dict):
        delta = {}
    content = _stream_text(delta.get("content"))
    reasoning = ""
    for key in ("reasoning_content", "reasoning", "thinking", "reasoning_text"):
        reasoning = _stream_text(delta.get(key))
        if reasoning:
            break
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    return content, reasoning, usage


def _parse_anthropic_stream_event(
    payload: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None]:
    """Return visible delta, thinking delta, and optional Anthropic usage."""
    delta = payload.get("delta") if isinstance(payload.get("delta"), dict) else {}
    dtype = str(delta.get("type") or "")
    content = str(delta.get("text") or "") if dtype == "text_delta" else ""
    reasoning = str(delta.get("thinking") or delta.get("text") or "") if dtype in {"thinking_delta", "reasoning_delta"} else ""
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    if usage is None and isinstance(message.get("usage"), dict):
        usage = message["usage"]
    return content, reasoning, usage


async def _call_delta(callback: TextDeltaCallback | None, delta: str) -> None:
    if not callback or not delta:
        return
    result = callback(delta)
    if result is not None:
        await result


def _merge_stream_usage(
    current: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not incoming:
        return current
    return {**(current or {}), **incoming}


class _VisibleStreamFilter:
    """Remove inline ``<think>`` blocks even when tags span SSE chunks."""

    _OPEN = "<think"
    _CLOSE = "</think"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    @staticmethod
    def _partial_tag_suffix(text: str, tag: str) -> int:
        lower = text.lower()
        for size in range(min(len(lower), len(tag) - 1), 0, -1):
            if lower.endswith(tag[:size]):
                return size
        return 0

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        visible: list[str] = []
        while self._buffer:
            tag = self._CLOSE if self._inside else self._OPEN
            lower = self._buffer.lower()
            index = lower.find(tag)
            if index < 0:
                keep = self._partial_tag_suffix(self._buffer, tag)
                stable = self._buffer[:-keep] if keep else self._buffer
                if not self._inside:
                    visible.append(stable)
                self._buffer = self._buffer[-keep:] if keep else ""
                break

            if not self._inside:
                visible.append(self._buffer[:index])
            tag_end = self._buffer.find(">", index + len(tag))
            if tag_end < 0:
                # Keep only the incomplete tag; text before a closing tag is reasoning.
                self._buffer = self._buffer[index:]
                break
            self._buffer = self._buffer[tag_end + 1 :]
            self._inside = not self._inside
        return "".join(visible)

    def finish(self) -> str:
        if self._inside:
            self._buffer = ""
            return ""
        visible = self._buffer
        self._buffer = ""
        return visible


def _openai_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    return f"{root}/chat/completions"


def _anthropic_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1/messages") or root.endswith("/messages"):
        return root
    if root.endswith("/v1"):
        return f"{root}/messages"
    return f"{root}/v1/messages"


def _call_openai_compatible(
    *,
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[str, str | None, dict[str, Any] | None]:
    url = _openai_url(resolved.base_url)
    with httpx.Client(timeout=timeout) as client:
        res = client.post(
            url,
            headers={"Authorization": f"Bearer {resolved.api_key}"},
            json={
                "model": resolved.api_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        res.raise_for_status()
        payload = res.json()
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        content = str(message.get("content") or "").strip()
        reasoning = _extract_reasoning_openai(message, payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return content, reasoning, usage


async def _call_openai_compatible_async(
    *,
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[str, str | None, dict[str, Any] | None]:
    url = _openai_url(resolved.base_url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(
            url,
            headers={"Authorization": f"Bearer {resolved.api_key}"},
            json={
                "model": resolved.api_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        res.raise_for_status()
        payload = res.json()
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        content = str(message.get("content") or "").strip()
        reasoning = _extract_reasoning_openai(message, payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return content, reasoning, usage


async def _call_openai_compatible_stream_async(
    *,
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
    on_text_delta: TextDeltaCallback | None,
    reasoning_max_chars: int,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Consume an OpenAI-compatible SSE response and forward visible deltas."""
    url = _openai_url(resolved.base_url)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_chars = 0
    usage: dict[str, Any] | None = None
    visible_filter = _VisibleStreamFilter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {resolved.api_key}"},
            json={
                "model": resolved.api_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    continue
                content, reasoning, event_usage = _parse_openai_stream_event(payload)
                if content:
                    content_parts.append(content)
                    await _call_delta(on_text_delta, visible_filter.feed(content))
                if reasoning and reasoning_chars < reasoning_max_chars:
                    kept = reasoning[: max(0, reasoning_max_chars - reasoning_chars)]
                    reasoning_parts.append(kept)
                    reasoning_chars += len(kept)
                usage = _merge_stream_usage(usage, event_usage)
    await _call_delta(on_text_delta, visible_filter.finish())
    content = "".join(content_parts).strip()
    reasoning = "".join(reasoning_parts).strip() or None
    return content, reasoning, usage


def _anthropic_messages_payload(
    messages: list[dict[str, Any]],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    system_parts: list[str] = []
    anth_messages: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content") or ""
        if role == "system":
            if isinstance(content, list):
                system_parts.append("\n".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text"))
            else:
                system_parts.append(str(content))
            continue
        if role not in ("user", "assistant"):
            role = "user"
        if isinstance(content, list):
            # Vision over Anthropic is not supported in this product path.
            raise RuntimeError("当前视觉请使用 OpenAI 兼容协议的 MiniMax M3（模型协议勿选 Anthropic）。")
        anth_messages.append({"role": role, "content": str(content)})
    if not anth_messages:
        anth_messages = [{"role": "user", "content": ""}]
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": anth_messages,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    return payload


def _extract_anthropic_text(payload: dict[str, Any]) -> tuple[str, str | None]:
    blocks = payload.get("content") or []
    texts: list[str] = []
    reasoning: str | None = None
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                texts.append(str(block.get("text") or ""))
            elif btype in ("thinking", "reasoning") and not reasoning:
                reasoning = str(block.get("thinking") or block.get("text") or "").strip() or None
    return "\n".join(t for t in texts if t).strip(), reasoning


def _call_anthropic(
    *,
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[str, str | None, dict[str, Any] | None]:
    url = _anthropic_url(resolved.base_url)
    payload = _anthropic_messages_payload(messages, model=resolved.api_model, max_tokens=max_tokens, temperature=temperature)
    with httpx.Client(timeout=timeout) as client:
        res = client.post(
            url,
            headers={
                "x-api-key": resolved.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        res.raise_for_status()
        body = res.json()
        content, reasoning = _extract_anthropic_text(body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
        return content, reasoning, usage


async def _call_anthropic_async(
    *,
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[str, str | None, dict[str, Any] | None]:
    url = _anthropic_url(resolved.base_url)
    payload = _anthropic_messages_payload(messages, model=resolved.api_model, max_tokens=max_tokens, temperature=temperature)
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(
            url,
            headers={
                "x-api-key": resolved.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        res.raise_for_status()
        body = res.json()
        content, reasoning = _extract_anthropic_text(body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
        return content, reasoning, usage


async def _call_anthropic_stream_async(
    *,
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
    on_text_delta: TextDeltaCallback | None,
    reasoning_max_chars: int,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Consume an Anthropic SSE response and forward visible text deltas."""
    url = _anthropic_url(resolved.base_url)
    payload = _anthropic_messages_payload(messages, model=resolved.api_model, max_tokens=max_tokens, temperature=temperature)
    payload["stream"] = True
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_chars = 0
    usage: dict[str, Any] | None = None
    visible_filter = _VisibleStreamFilter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            url,
            headers={
                "x-api-key": resolved.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        ) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                event = json.loads(raw)
                if not isinstance(event, dict):
                    continue
                content, reasoning, event_usage = _parse_anthropic_stream_event(event)
                if content:
                    content_parts.append(content)
                    await _call_delta(on_text_delta, visible_filter.feed(content))
                if reasoning and reasoning_chars < reasoning_max_chars:
                    kept = reasoning[: max(0, reasoning_max_chars - reasoning_chars)]
                    reasoning_parts.append(kept)
                    reasoning_chars += len(kept)
                usage = _merge_stream_usage(usage, event_usage)
    await _call_delta(on_text_delta, visible_filter.finish())
    content = "".join(content_parts).strip()
    reasoning = "".join(reasoning_parts).strip() or None
    return content, reasoning, usage


def _dispatch_sync(
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if resolved.protocol == "anthropic":
        return _call_anthropic(
            resolved=resolved,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    return _call_openai_compatible(
        resolved=resolved,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )


async def _dispatch_async(
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if resolved.protocol == "anthropic":
        return await _call_anthropic_async(
            resolved=resolved,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    return await _call_openai_compatible_async(
        resolved=resolved,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )


async def _dispatch_stream_async(
    resolved: ResolvedModel,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
    on_text_delta: TextDeltaCallback | None,
    reasoning_max_chars: int,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if resolved.protocol == "anthropic":
        return await _call_anthropic_stream_async(
            resolved=resolved,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            on_text_delta=on_text_delta,
            reasoning_max_chars=reasoning_max_chars,
        )
    return await _call_openai_compatible_stream_async(
        resolved=resolved,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        on_text_delta=on_text_delta,
        reasoning_max_chars=reasoning_max_chars,
    )


def _build_messages(
    prompt: str,
    *,
    system: str | None,
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    from realai.org_identity import ensure_messages_org_identity

    if messages is not None:
        return ensure_messages_org_identity(list(messages))
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    out.append({"role": "user", "content": prompt})
    return ensure_messages_org_identity(out)


def _mime_for_path(path: Path) -> str:
    return _VISION_MIME.get(path.suffix.lower(), "image/jpeg")


def _shrink_image_bytes(raw: bytes, *, mime: str) -> tuple[bytes, str]:
    """Optionally shrink oversized images via Pillow; otherwise return as-is."""
    if len(raw) <= _VISION_MAX_BYTES:
        return raw, mime
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        raise RuntimeError(f"图片超过 {_VISION_MAX_BYTES // (1024 * 1024)}MB，且未安装 Pillow 无法压缩。请缩小图片后重试。") from None

    img = Image.open(BytesIO(raw))
    img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    for scale in (0.75, 0.5, 0.35, 0.25, 0.15):
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        resized = img.resize((w, h))
        buf = BytesIO()
        resized.save(buf, format="JPEG", quality=85, optimize=True)
        out = buf.getvalue()
        if len(out) <= _VISION_MAX_BYTES:
            return out, "image/jpeg"
    raise RuntimeError("图片过大，压缩后仍超过限制，请缩小后重试。")


def encode_image_data_url(
    path: str | Path | None = None,
    *,
    raw: bytes | None = None,
    mime: str | None = None,
    detail: str = "high",
) -> dict[str, Any]:
    """Build an OpenAI-compatible image_url content part from path or bytes."""
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"图片不存在：{p}")
        data = p.read_bytes()
        mime = mime or _mime_for_path(p)
    elif raw is not None:
        data = raw
        mime = mime or "image/jpeg"
    else:
        raise ValueError("encode_image_data_url 需要 path 或 raw")

    data, mime = _shrink_image_bytes(data, mime=mime)
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{b64}",
            "detail": detail if detail in ("low", "default", "high") else "high",
        },
    }


def build_vision_user_content(
    prompt: str,
    images: Sequence[str | Path | bytes | dict[str, Any]],
    *,
    detail: str = "high",
) -> list[dict[str, Any]]:
    """Assemble multimodal user content: text + up to 2 images."""
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    count = 0
    for img in images:
        if count >= _VISION_MAX_IMAGES:
            break
        if isinstance(img, (str, Path)):
            parts.append(encode_image_data_url(img, detail=detail))
            count += 1
        elif isinstance(img, (bytes, bytearray)):
            parts.append(encode_image_data_url(raw=bytes(img), detail=detail))
            count += 1
        elif isinstance(img, dict) and img.get("path"):
            parts.append(encode_image_data_url(img["path"], detail=detail))
            count += 1
        elif isinstance(img, dict) and img.get("raw") is not None:
            parts.append(
                encode_image_data_url(
                    raw=bytes(img["raw"]),
                    mime=img.get("mime"),
                    detail=detail,
                )
            )
            count += 1
    if count == 0:
        raise ValueError("视觉调用至少需要一张有效图片")
    return parts


def _fallback_resolved(
    settings: dict[str, Any],
    primary: ResolvedModel,
) -> ResolvedModel | None:
    llm = normalize_llm(settings.get("llm") or {})
    roles = llm.get("roles") or {}
    fid = str(roles.get("fallback") or "").strip()
    if not fid or fid == primary.catalog_id:
        return None
    fb = resolve_role_model("fallback", settings)
    if fb.api_model == primary.api_model and fb.catalog_id == primary.catalog_id:
        return None
    return fb


def chat_turn_sync(
    prompt: str = "",
    *,
    system: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    role: RoleName | str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.5,
    timeout: float = 120.0,
    purpose: str = "chat",
    task_id: str | None = None,
    allow_fallback: bool = True,
    settings: dict[str, Any] | None = None,
) -> ChatResult:
    settings = _settings(settings)
    resolved = resolve_role_model(role, settings)
    if not resolved.api_key:
        raise RuntimeError("未配置 API Key，请在「模型」页填写后再试。")

    msg_list = _build_messages(prompt, system=system, messages=messages)
    t0 = time.perf_counter()
    try:
        content, reasoning, usage = _dispatch_sync(resolved, msg_list, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        log_model_call(
            purpose=purpose,
            model=resolved.api_model,
            provider=resolved.provider,
            latency_ms=(time.perf_counter() - t0) * 1000,
            prompt_tokens=(usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
            completion_tokens=(usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
            success=True,
            task_id=task_id,
        )
        return _pack_chat_result(content, reasoning, model=resolved.api_model, usage=usage)
    except Exception as primary_exc:
        logger.warning("LLM call failed role=%s model=%s: %s", role, resolved.api_model, primary_exc)
        fb = _fallback_resolved(settings, resolved) if allow_fallback else None
        if fb is None:
            log_model_call(
                purpose=purpose,
                model=resolved.api_model,
                provider=resolved.provider,
                latency_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                error=str(primary_exc)[:400],
                task_id=task_id,
            )
            raise RuntimeError(f"模型调用失败：{primary_exc}") from primary_exc

        t1 = time.perf_counter()
        try:
            content, reasoning, usage = _dispatch_sync(fb, msg_list, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            log_model_call(
                purpose=purpose,
                model=fb.api_model,
                provider=fb.provider,
                latency_ms=(time.perf_counter() - t1) * 1000,
                prompt_tokens=(usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
                completion_tokens=(usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
                success=True,
                degraded=True,
                fallback_model=fb.api_model,
                error=str(primary_exc)[:200],
                task_id=task_id,
            )
            return _pack_chat_result(
                content,
                reasoning,
                model=fb.api_model,
                usage=usage,
                degraded=True,
                fallback_model=fb.api_model,
            )
        except Exception as fb_exc:
            log_model_call(
                purpose=purpose,
                model=resolved.api_model,
                provider=resolved.provider,
                latency_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                degraded=True,
                fallback_model=fb.api_model,
                error=f"{primary_exc} | fallback: {fb_exc}"[:400],
                task_id=task_id,
            )
            raise RuntimeError(f"模型调用失败（含备用）：{fb_exc}") from fb_exc


async def chat_turn(
    prompt: str = "",
    *,
    system: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    role: RoleName | str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.5,
    timeout: float = 120.0,
    purpose: str = "chat",
    task_id: str | None = None,
    allow_fallback: bool = True,
    reasoning_max_chars: int | None = None,
    settings: dict[str, Any] | None = None,
) -> ChatResult:
    settings = _settings(settings)
    resolved = resolve_role_model(role, settings)
    if not resolved.api_key:
        raise RuntimeError("未配置 API Key，请在「模型」页填写后再试。")

    msg_list = _build_messages(prompt, system=system, messages=messages)
    t0 = time.perf_counter()
    try:
        content, reasoning, usage = await _dispatch_async(resolved, msg_list, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        log_model_call(
            purpose=purpose,
            model=resolved.api_model,
            provider=resolved.provider,
            latency_ms=(time.perf_counter() - t0) * 1000,
            prompt_tokens=(usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
            completion_tokens=(usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
            success=True,
            task_id=task_id,
        )
        return _pack_chat_result(
            content,
            reasoning,
            model=resolved.api_model,
            usage=usage,
            reasoning_max_chars=reasoning_max_chars,
        )
    except Exception as primary_exc:
        logger.warning("LLM call failed role=%s model=%s: %s", role, resolved.api_model, primary_exc)
        fb = _fallback_resolved(settings, resolved) if allow_fallback else None
        if fb is None:
            log_model_call(
                purpose=purpose,
                model=resolved.api_model,
                provider=resolved.provider,
                latency_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                error=str(primary_exc)[:400],
                task_id=task_id,
            )
            raise RuntimeError(f"模型调用失败：{primary_exc}") from primary_exc

        t1 = time.perf_counter()
        try:
            content, reasoning, usage = await _dispatch_async(fb, msg_list, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            log_model_call(
                purpose=purpose,
                model=fb.api_model,
                provider=fb.provider,
                latency_ms=(time.perf_counter() - t1) * 1000,
                prompt_tokens=(usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
                completion_tokens=(usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
                success=True,
                degraded=True,
                fallback_model=fb.api_model,
                error=str(primary_exc)[:200],
                task_id=task_id,
            )
            return _pack_chat_result(
                content,
                reasoning,
                model=fb.api_model,
                usage=usage,
                degraded=True,
                fallback_model=fb.api_model,
                reasoning_max_chars=reasoning_max_chars,
            )
        except Exception as fb_exc:
            log_model_call(
                purpose=purpose,
                model=resolved.api_model,
                provider=resolved.provider,
                latency_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                degraded=True,
                fallback_model=fb.api_model,
                error=f"{primary_exc} | fallback: {fb_exc}"[:400],
                task_id=task_id,
            )
            raise RuntimeError(f"模型调用失败（含备用）：{fb_exc}") from fb_exc


async def chat_turn_stream(
    prompt: str = "",
    *,
    system: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    role: RoleName | str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.5,
    timeout: float = 120.0,
    purpose: str = "chat",
    task_id: str | None = None,
    allow_fallback: bool = True,
    reasoning_max_chars: int = 6000,
    on_text_delta: TextDeltaCallback | None = None,
    on_reset: StreamResetCallback | None = None,
    settings: dict[str, Any] | None = None,
) -> ChatResult:
    """Stream visible model text while retaining the normal routing/audit contract."""
    settings = _settings(settings)
    resolved = resolve_role_model(role, settings)
    if not resolved.api_key:
        raise RuntimeError("未配置 API Key，请在「模型」页填写后再试。")

    msg_list = _build_messages(prompt, system=system, messages=messages)
    emitted = False

    async def forward(delta: str) -> None:
        nonlocal emitted
        emitted = True
        await _call_delta(on_text_delta, delta)

    t0 = time.perf_counter()
    try:
        content, reasoning, usage = await _dispatch_stream_async(
            resolved,
            msg_list,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            on_text_delta=forward,
            reasoning_max_chars=max(0, int(reasoning_max_chars)),
        )
        log_model_call(
            purpose=purpose,
            model=resolved.api_model,
            provider=resolved.provider,
            latency_ms=(time.perf_counter() - t0) * 1000,
            prompt_tokens=(usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
            completion_tokens=(usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
            success=True,
            task_id=task_id,
        )
        return _pack_chat_result(
            content,
            reasoning,
            model=resolved.api_model,
            usage=usage,
            reasoning_max_chars=reasoning_max_chars,
        )
    except Exception as primary_exc:
        logger.warning(
            "Streaming LLM call failed role=%s model=%s: %s",
            role,
            resolved.api_model,
            primary_exc,
        )
        fb = _fallback_resolved(settings, resolved) if allow_fallback else None
        if fb is None:
            log_model_call(
                purpose=purpose,
                model=resolved.api_model,
                provider=resolved.provider,
                latency_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                error=str(primary_exc)[:400],
                task_id=task_id,
            )
            raise RuntimeError(f"模型流式调用失败：{primary_exc}") from primary_exc

        if emitted and on_reset:
            reset_result = on_reset()
            if reset_result is not None:
                await reset_result
            emitted = False

        t1 = time.perf_counter()
        try:
            content, reasoning, usage = await _dispatch_stream_async(
                fb,
                msg_list,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                on_text_delta=forward,
                reasoning_max_chars=max(0, int(reasoning_max_chars)),
            )
            log_model_call(
                purpose=purpose,
                model=fb.api_model,
                provider=fb.provider,
                latency_ms=(time.perf_counter() - t1) * 1000,
                prompt_tokens=(usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
                completion_tokens=(usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
                success=True,
                degraded=True,
                fallback_model=fb.api_model,
                error=str(primary_exc)[:200],
                task_id=task_id,
            )
            return _pack_chat_result(
                content,
                reasoning,
                model=fb.api_model,
                usage=usage,
                degraded=True,
                fallback_model=fb.api_model,
                reasoning_max_chars=reasoning_max_chars,
            )
        except Exception as fb_exc:
            log_model_call(
                purpose=purpose,
                model=resolved.api_model,
                provider=resolved.provider,
                latency_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                degraded=True,
                fallback_model=fb.api_model,
                error=f"{primary_exc} | fallback: {fb_exc}"[:400],
                task_id=task_id,
            )
            raise RuntimeError(f"模型流式调用失败（含备用）：{fb_exc}") from fb_exc


async def chat_text(
    prompt: str,
    *,
    system: str | None = None,
    role: RoleName | str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.5,
    timeout: float = 120.0,
    purpose: str = "chat",
    task_id: str | None = None,
    allow_fallback: bool = True,
) -> str:
    turn = await chat_turn(
        prompt,
        system=system,
        role=role,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        purpose=purpose,
        task_id=task_id,
        allow_fallback=allow_fallback,
    )
    return turn.content


def chat_text_sync(
    prompt: str,
    *,
    system: str | None = None,
    role: RoleName | str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.5,
    timeout: float = 120.0,
    purpose: str = "chat",
    task_id: str | None = None,
    allow_fallback: bool = True,
) -> str:
    turn = chat_turn_sync(
        prompt,
        system=system,
        role=role,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        purpose=purpose,
        task_id=task_id,
        allow_fallback=allow_fallback,
    )
    return turn.content


_VISION_SYSTEM = "你是国家管网集团知识助手的视觉分析模块。请仔细阅读图片，输出结构化中文：图类型、标题/图例、关键结论、可读数字列表；看不清的数字必须写「看不清」，禁止臆造。"


async def chat_vision(
    prompt: str,
    images: Sequence[str | Path | bytes | dict[str, Any]],
    *,
    system: str | None = None,
    role: RoleName | str = "vision",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 180.0,
    purpose: str = "vision",
    task_id: str | None = None,
    allow_fallback: bool = True,
    detail: str = "high",
    settings: dict[str, Any] | None = None,
) -> ChatResult:
    """Multimodal chat via vision role (falls back to primary when vision unset)."""
    settings = _settings(settings)
    resolved = resolve_role_model(role, settings)
    if resolved.protocol == "anthropic":
        raise RuntimeError("当前视觉请使用 OpenAI 兼容协议的 MiniMax M3（模型协议勿选 Anthropic）。")
    content_parts = build_vision_user_content(prompt, images, detail=detail)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system or _VISION_SYSTEM},
        {"role": "user", "content": content_parts},
    ]
    return await chat_turn(
        messages=messages,
        role=role,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        purpose=purpose,
        task_id=task_id,
        allow_fallback=allow_fallback,
        settings=settings,
    )


def chat_vision_sync(
    prompt: str,
    images: Sequence[str | Path | bytes | dict[str, Any]],
    *,
    system: str | None = None,
    role: RoleName | str = "vision",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 180.0,
    purpose: str = "vision",
    task_id: str | None = None,
    allow_fallback: bool = True,
    detail: str = "high",
    settings: dict[str, Any] | None = None,
) -> ChatResult:
    settings = _settings(settings)
    resolved = resolve_role_model(role, settings)
    if resolved.protocol == "anthropic":
        raise RuntimeError("当前视觉请使用 OpenAI 兼容协议的 MiniMax M3（模型协议勿选 Anthropic）。")
    content_parts = build_vision_user_content(prompt, images, detail=detail)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system or _VISION_SYSTEM},
        {"role": "user", "content": content_parts},
    ]
    return chat_turn_sync(
        messages=messages,
        role=role,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        purpose=purpose,
        task_id=task_id,
        allow_fallback=allow_fallback,
        settings=settings,
    )
