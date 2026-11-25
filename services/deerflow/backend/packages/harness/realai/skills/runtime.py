"""Runtime resolution for RealAi customer-authored Skills.

This module is intentionally small and deterministic: a Skill is activated
only when the caller selects it or uses the strict ``/skill-id task`` syntax.
Semantic/automatic routing can be layered on later without changing the
request contracts introduced here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from realai.skills.registry import SkillRecord, get_skill

_SLASH_SKILL_RE = re.compile(r"^/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)")


@dataclass(frozen=True, slots=True)
class ResolvedQaSkill:
    query: str
    body: str | None
    skill: dict[str, Any] | None


def require_enabled_skill(skill_id: str) -> SkillRecord:
    """Resolve one runtime Skill and fail closed on invalid/disabled records."""

    sid = (skill_id or "").strip()
    if not sid:
        raise ValueError("Skill ID 不能为空")
    skill = get_skill(sid)
    if skill is None:
        raise ValueError(f"Skill「{sid}」不存在")
    if not skill.valid:
        detail = "；".join(skill.errors) or "格式无效"
        raise ValueError(f"Skill「{sid}」无效：{detail}")
    if not skill.enabled:
        raise ValueError(f"Skill「{sid}」已停用")
    if not (skill.body or "").strip():
        raise ValueError(f"Skill「{sid}」正文为空")
    return skill


def _runtime_meta(skill: SkillRecord, *, trigger: str) -> dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "version": skill.version,
        "trigger": trigger,
        "source": skill.source,
    }


def resolve_qa_skill(
    query: str,
    *,
    selected_skill_id: str | None = None,
) -> ResolvedQaSkill:
    """Resolve explicit Q&A Skill selection.

    A leading slash command is closest to the current user turn and therefore
    overrides the composer selection. No automatic matching happens here.
    """

    original = (query or "").strip()
    match = _SLASH_SKILL_RE.match(original)
    if match:
        skill = require_enabled_skill(match.group(1))
        remaining = original[match.end() :].lstrip()
        if not remaining:
            raise ValueError(f"请输入问题，例如：/{skill.id} 问题内容")
        return ResolvedQaSkill(
            query=remaining,
            body=skill.body.strip(),
            skill=_runtime_meta(skill, trigger="slash"),
        )

    sid = (selected_skill_id or "").strip()
    if sid:
        skill = require_enabled_skill(sid)
        return ResolvedQaSkill(
            query=original,
            body=skill.body.strip(),
            skill=_runtime_meta(skill, trigger="selected"),
        )

    return ResolvedQaSkill(query=original, body=None, skill=None)


def snapshot_skill_profile(skill_id: str) -> dict[str, Any]:
    """Create the immutable, JSON-serializable Skill copy stored on a task."""

    skill = require_enabled_skill(skill_id)
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "body": skill.body.strip(),
        "source": skill.source,
        "category": skill.category,
    }
