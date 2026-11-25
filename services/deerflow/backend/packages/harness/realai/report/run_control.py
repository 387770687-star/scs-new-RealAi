"""In-process writing run control: pause / cancel between pipeline steps."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

ControlAction = Literal["run", "pause", "cancel"]


@dataclass
class RunControl:
    action: ControlAction = "run"
    reason: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_CONTROLS: dict[str, RunControl] = {}


def ensure_control(task_id: str) -> RunControl:
    ctrl = _CONTROLS.get(task_id)
    if ctrl is None:
        ctrl = RunControl()
        _CONTROLS[task_id] = ctrl
    return ctrl


def clear_control(task_id: str) -> None:
    _CONTROLS.pop(task_id, None)


def request_pause(task_id: str, reason: str = "用户暂停") -> RunControl:
    ctrl = ensure_control(task_id)
    ctrl.action = "pause"
    ctrl.reason = reason
    return ctrl


def request_cancel(task_id: str, reason: str = "用户终止") -> RunControl:
    ctrl = ensure_control(task_id)
    ctrl.action = "cancel"
    ctrl.reason = reason
    return ctrl


def reset_to_run(task_id: str) -> RunControl:
    ctrl = ensure_control(task_id)
    ctrl.action = "run"
    ctrl.reason = ""
    return ctrl


class PipelinePaused(Exception):
    def __init__(self, snapshot: dict[str, Any], reason: str = "") -> None:
        super().__init__(reason or "paused")
        self.snapshot = snapshot
        self.reason = reason


class PipelineCancelled(Exception):
    def __init__(self, snapshot: dict[str, Any], reason: str = "") -> None:
        super().__init__(reason or "cancelled")
        self.snapshot = snapshot
        self.reason = reason


async def check_control(task_id: str | None, snapshot: dict[str, Any]) -> None:
    """Raise pause/cancel if user requested; no-op when task_id missing."""
    if not task_id:
        return
    ctrl = _CONTROLS.get(task_id)
    if not ctrl:
        return
    async with ctrl.lock:
        action = ctrl.action
        reason = ctrl.reason
    if action == "pause":
        raise PipelinePaused(snapshot, reason)
    if action == "cancel":
        raise PipelineCancelled(snapshot, reason)
