"""Skill loader hook (P1b — P3 productizes UI)."""

from __future__ import annotations

from realai.skills.registry import list_skills
from realai.skills.runtime import require_enabled_skill


def list_skill_ids() -> list[str]:
    return [s.id for s in list_skills()]


def load_skill_markdown(skill_id: str) -> str | None:
    try:
        rec = require_enabled_skill(skill_id)
    except ValueError:
        return None
    return rec.raw
