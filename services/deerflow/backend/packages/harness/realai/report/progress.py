"""Report pipeline agent progress tracking (strategic intake + 6-step)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

AgentStatus = Literal["pending", "running", "completed", "skipped", "failed"]

REPORT_AGENTS: list[tuple[str, str]] = [
    ("intake", "智能补缺"),
    ("researcher", "战略研究"),
    ("architect", "报告架构"),
    ("writer", "逐章写作"),
    ("citer", "引用审核"),
    ("reviewer", "质量评审"),
    ("optimizer", "迭代优化"),
]

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

# Soft cap per text field to keep SQLite task rows manageable (~200KB).
_TRACE_FIELD_MAX = 200_000


def _clip_field(text: str | None, *, label: str) -> tuple[str, str | None]:
    """Return (possibly truncated text, optional summary note)."""
    if text is None:
        return "", None
    s = str(text)
    if len(s) <= _TRACE_FIELD_MAX:
        return s, None
    note = f"{label}已截断（原文 {len(s)} 字符，保留前 {_TRACE_FIELD_MAX}）"
    return s[:_TRACE_FIELD_MAX], note


def make_action_trace(
    title: str,
    *,
    summary: str = "",
    detail: str = "",
) -> dict[str, Any]:
    detail_c, note = _clip_field(detail, label="详情")
    summary_parts = [summary] if summary else []
    if note:
        summary_parts.append(note)
    return {
        "kind": "action",
        "at": time.time(),
        "title": title,
        "summary": "；".join(summary_parts),
        "detail": detail_c,
    }


def make_llm_trace(
    title: str,
    *,
    system: str | None = None,
    prompt: str,
    reply: str,
    reasoning: str | None = None,
) -> dict[str, Any]:
    notes: list[str] = []
    system_c, n1 = _clip_field(system or "", label="系统提示")
    prompt_c, n2 = _clip_field(prompt, label="提示词")
    reply_c, n3 = _clip_field(reply, label="回复")
    reasoning_c, n4 = _clip_field(reasoning, label="思考过程") if reasoning else ("", None)
    for n in (n1, n2, n3, n4):
        if n:
            notes.append(n)
    item: dict[str, Any] = {
        "kind": "llm",
        "at": time.time(),
        "title": title,
        "system": system_c,
        "prompt": prompt_c,
        "reply": reply_c,
        "reasoning": reasoning_c or None,
    }
    if notes:
        item["summary"] = "；".join(notes)
    return item


def initial_agent_progress(
    skill_bindings: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Create progress rows; optional per-agent skill meta (skill_id/name/assets/tools)."""
    out: list[dict[str, Any]] = []
    for aid, label in REPORT_AGENTS:
        meta = (skill_bindings or {}).get(aid) or {}
        out.append(
            {
                "id": aid,
                "label": label,
                "status": "pending",
                "message": "",
                "started_at": None,
                "finished_at": None,
                "skill_id": meta.get("skill_id") or "",
                "skill_name": meta.get("skill_name") or "",
                "skill_valid": bool(meta.get("skill_valid")),
                "references": list(meta.get("references") or []),
                "scripts": list(meta.get("scripts") or []),
                "tools": list(meta.get("tools") or []),
                "trace": [],
            }
        )
    return out


class ReportProgressTracker:
    """Track sub-agent status for report pipeline UI."""

    def __init__(
        self,
        *,
        on_step: ProgressCallback | None = None,
        on_event: EventCallback | None = None,
        skill_bindings: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.steps = initial_agent_progress(skill_bindings)
        self._index = {s["id"]: i for i, s in enumerate(self.steps)}
        self.on_step = on_step
        self.on_event = on_event

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.steps]

    async def _emit(self, agent_id: str) -> None:
        if not self.on_step:
            return
        step = dict(self.steps[self._index[agent_id]])
        result = self.on_step(step)
        if result is not None:
            await result

    async def emit_event(self, event: dict[str, Any]) -> None:
        if not self.on_event:
            return
        result = self.on_event(event)
        if result is not None:
            await result

    async def append_trace(self, agent_id: str, item: dict[str, Any]) -> None:
        """Append a trace item and push progress so the UI can refresh mid-step."""
        idx = self._index[agent_id]
        step = self.steps[idx]
        # Drop matching llm_pending when a real llm turn arrives
        if item.get("kind") == "llm":
            title = item.get("title") or ""
            trace = [t for t in (step.get("trace") or []) if not (t.get("kind") == "llm_pending" and (t.get("title") or "") == title)]
        else:
            trace = list(step.get("trace") or [])
        trace.append(item)
        step["trace"] = trace
        await self._emit(agent_id)

    async def mark_llm_pending(self, agent_id: str, title: str) -> None:
        """Show a live placeholder while waiting for chat_turn to finish."""
        idx = self._index[agent_id]
        step = self.steps[idx]
        trace = list(step.get("trace") or [])
        # Avoid duplicate pending for same title
        if any(t.get("kind") == "llm_pending" and t.get("title") == title for t in trace):
            await self._emit(agent_id)
            return
        trace.append(
            {
                "kind": "llm_pending",
                "at": time.time(),
                "title": title,
                "summary": "模型生成中…",
            }
        )
        step["trace"] = trace
        await self._emit(agent_id)

    async def clear_llm_pending(self, agent_id: str, title: str | None = None) -> None:
        """Remove pending placeholder(s); used on LLM failure without a formal llm turn."""
        idx = self._index[agent_id]
        step = self.steps[idx]
        before = list(step.get("trace") or [])
        if title is None:
            after = [t for t in before if t.get("kind") != "llm_pending"]
        else:
            after = [t for t in before if not (t.get("kind") == "llm_pending" and (t.get("title") or "") == title)]
        if len(after) == len(before):
            return
        step["trace"] = after
        await self._emit(agent_id)

    def update_meta(
        self,
        agent_id: str,
        *,
        skill_id: str | None = None,
        skill_name: str | None = None,
        skill_valid: bool | None = None,
        references: list[str] | None = None,
        scripts: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> None:
        idx = self._index[agent_id]
        step = self.steps[idx]
        if skill_id is not None:
            step["skill_id"] = skill_id
        if skill_name is not None:
            step["skill_name"] = skill_name
        if skill_valid is not None:
            step["skill_valid"] = skill_valid
        if references is not None:
            step["references"] = list(references)
        if scripts is not None:
            step["scripts"] = list(scripts)
        if tools is not None:
            step["tools"] = list(tools)

    async def start(self, agent_id: str, message: str = "", **meta: Any) -> None:
        idx = self._index[agent_id]
        now = time.time()
        if meta:
            self.update_meta(agent_id, **{k: v for k, v in meta.items() if k in {"skill_id", "skill_name", "skill_valid", "references", "scripts", "tools"}})
        # Fresh run of a step: keep existing trace only if already has items (resume mid-step).
        if not self.steps[idx].get("trace"):
            self.steps[idx]["trace"] = []
        self.steps[idx].update({"status": "running", "message": message, "started_at": now, "finished_at": None})
        await self._emit(agent_id)

    async def complete(self, agent_id: str, message: str = "", **meta: Any) -> None:
        idx = self._index[agent_id]
        if meta:
            self.update_meta(agent_id, **{k: v for k, v in meta.items() if k in {"skill_id", "skill_name", "skill_valid", "references", "scripts", "tools"}})
        self.steps[idx].update({"status": "completed", "message": message, "finished_at": time.time()})
        await self._emit(agent_id)

    async def skip(self, agent_id: str, message: str = "") -> None:
        idx = self._index[agent_id]
        self.steps[idx].update({"status": "skipped", "message": message, "finished_at": time.time()})
        await self._emit(agent_id)

    async def fail(self, agent_id: str, message: str = "") -> None:
        idx = self._index[agent_id]
        self.steps[idx].update({"status": "failed", "message": message, "finished_at": time.time()})
        await self._emit(agent_id)
