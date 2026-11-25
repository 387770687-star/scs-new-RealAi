"""Workbench skill-optimize mode: natural language revise + publish draft."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import yaml

from realai.config import load_settings
from realai.skills.deerflow_bridge import is_deerflow_builtin
from realai.skills.registry import (
    SKILL_ID_RE,
    get_skill,
    parse_skill_markdown,
    save_skill,
)

logger = logging.getLogger(__name__)

_THINKING_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _assert_optimizable(skill_id: str) -> None:
    """系统内置 Skill 不可进入技能优化（不可改、不可另存改写）。"""
    rec = get_skill(skill_id)
    if rec is None:
        raise ValueError(f"Skill 不存在：{skill_id}")
    if rec.read_only or not rec.editable or is_deerflow_builtin(skill_id, category=rec.category):
        raise ValueError("系统内置 Skill 不可优化，请选择业务场景 Skill")


def resolve_publish_target(skill_id: str) -> dict[str, Any]:
    """Decide where a draft can be published (仅业务/可编辑 Skill)。"""
    _assert_optimizable(skill_id)
    rec = get_skill(skill_id)
    assert rec is not None
    return {
        "source_id": skill_id,
        "publish_id": skill_id,
        "forked": False,
        "category": rec.category if rec.category in {"public", "custom"} else "custom",
        "hint": "将覆盖当前 Skill",
    }


async def run_skill_optimize(
    skill_id: str,
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    current_draft: dict[str, str] | None = None,
) -> dict[str, Any]:
    _assert_optimizable(skill_id)
    rec = get_skill(skill_id)
    if rec is None:
        raise ValueError(f"Skill 不存在：{skill_id}")

    target = resolve_publish_target(skill_id)
    base_raw = (current_draft or {}).get("raw") or rec.raw
    base_name = (current_draft or {}).get("name") or rec.name
    base_desc = (current_draft or {}).get("description") or rec.description
    base_body = (current_draft or {}).get("body") or rec.body

    llm_out = await _call_optimizer(
        message=message.strip(),
        history=history or [],
        skill_id=skill_id,
        name=base_name,
        description=base_desc,
        body=base_body,
        raw=base_raw,
        publish_id=target["publish_id"],
        forked=bool(target["forked"]),
    )

    draft = _normalize_draft(
        llm_out.get("draft") or {},
        fallback={
            "skill_id": target["publish_id"],
            "name": base_name,
            "description": base_desc,
            "body": base_body,
            "raw": base_raw,
        },
        publish_id=target["publish_id"],
    )
    answer = str(llm_out.get("answer") or "已生成草案，可继续说修改意见，或点「应用到编辑区」后保存。").strip()

    return {
        "answer": answer,
        "draft": draft,
        "can_publish": True,
        "publish_hint": target["hint"],
        "forked": target["forked"],
        "source_skill_id": skill_id,
        "trajectory": [
            f"加载 Skill：{skill_id}",
            "技能优化对话",
            target["hint"],
        ],
    }


def publish_skill_draft(
    *,
    publish_id: str,
    name: str,
    description: str,
    body: str,
    source_skill_id: str | None = None,
) -> dict[str, Any]:
    if not SKILL_ID_RE.match(publish_id):
        raise ValueError("发布 id 仅允许小写字母、数字与连字符")
    # Prefer custom for forks / user publishes
    category = "custom"
    if source_skill_id:
        src = get_skill(source_skill_id)
        if src and src.editable and publish_id == source_skill_id:
            category = src.category if src.category in {"public", "custom"} else "custom"
    saved = save_skill(
        publish_id,
        name=name,
        description=description,
        body=body,
        category=category,
    )
    return {
        "ok": True,
        "skill": {
            "id": saved.id,
            "name": saved.name,
            "description": saved.description,
            "category": saved.category,
            "valid": saved.valid,
        },
        "message": f"已发布 {saved.id}",
    }


def _normalize_draft(
    draft: dict[str, Any],
    *,
    fallback: dict[str, str],
    publish_id: str,
) -> dict[str, str]:
    raw = str(draft.get("raw") or "").strip()
    name = str(draft.get("name") or fallback["name"]).strip()
    description = str(draft.get("description") or fallback["description"]).strip()
    body = str(draft.get("body") or fallback["body"]).strip()

    if raw:
        parsed = parse_skill_markdown(raw, skill_id=publish_id)
        if parsed.name:
            name = parsed.name
        if parsed.description:
            description = parsed.description
        if parsed.body:
            body = parsed.body
    else:
        frontmatter = yaml.safe_dump(
            {"name": name, "description": description},
            allow_unicode=True,
        ).strip()
        raw = f"---\n{frontmatter}\n---\n\n{body}\n"

    return {
        "skill_id": publish_id,
        "name": name,
        "description": description,
        "body": body,
        "raw": raw,
    }


async def _call_optimizer(
    *,
    message: str,
    history: list[dict[str, str]],
    skill_id: str,
    name: str,
    description: str,
    body: str,
    raw: str,
    publish_id: str,
    forked: bool,
) -> dict[str, Any]:
    from realai.llm import chat_turn, has_api_key

    settings = load_settings()
    if not has_api_key(settings):
        return _offline_revise(message, name=name, description=description, body=body, publish_id=publish_id)

    system = (
        "你是 RealAi「技能优化」助手。用户要用自然语言改进一个 Skill（SKILL.md）。\n"
        "用户为国家管网集团工作人员；Skill 内容默认服务该集团业务语境。\n"
        "规则：\n"
        "1. 保持 YAML frontmatter 含 name、description；正文说明做什么与怎么执行。\n"
        "2. 按用户要求修改；不要删除安全边界与必要步骤。\n"
        "3. 只输出一个 JSON 对象（可包在 ```json 里），字段：\n"
        '   {"answer":"给用户看的简短中文说明","draft":{"name":"…","description":"…","body":"正文不含frontmatter","raw":"完整SKILL.md"}}\n'
        "4. draft.raw 必须是可保存的完整 SKILL.md。\n"
        f"5. 发布目标 id 为 {publish_id}" + ("（从只读 Skill 另存）" if forked else "（覆盖原 Skill）") + "。\n"
    )
    hist_lines = []
    for h in history[-8:]:
        role = h.get("role") or "user"
        content = (h.get("content") or "")[:2000]
        hist_lines.append(f"{role}: {content}")
    user = f"当前 Skill id: {skill_id}\n发布 id: {publish_id}\n【当前草案】\n{raw[:12000]}\n\n【近期对话】\n" + ("\n".join(hist_lines) or "（无）") + f"\n\n【用户本轮】\n{message}"

    try:
        turn = await chat_turn(
            user,
            system=system,
            role="primary",
            temperature=0.4,
            max_tokens=4096,
            purpose="skill_optimize",
            task_id=skill_id,
            settings=settings,
        )
        content = _THINKING_TAG_RE.sub("", turn.content).strip()
        return _parse_llm_json(content, name=name, description=description, body=body, publish_id=publish_id)
    except Exception:
        logger.exception("skill optimize LLM failed")
        return _offline_revise(message, name=name, description=description, body=body, publish_id=publish_id)


def _parse_llm_json(
    content: str,
    *,
    name: str,
    description: str,
    body: str,
    publish_id: str,
) -> dict[str, Any]:
    text = content.strip()
    m = _JSON_BLOCK_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # model returned prose + markdown skill
        raw_match = re.search(r"(---\r?\n[\s\S]+?\r?\n---\r?\n[\s\S]+)", content)
        if raw_match:
            raw = raw_match.group(1).strip()
            parsed = parse_skill_markdown(raw, skill_id=publish_id)
            return {
                "answer": "已根据你的说明更新草案。",
                "draft": {
                    "name": parsed.name or name,
                    "description": parsed.description or description,
                    "body": parsed.body or body,
                    "raw": raw,
                },
            }
        return _offline_revise(content[:200], name=name, description=description, body=body, publish_id=publish_id)


def _offline_revise(
    message: str,
    *,
    name: str,
    description: str,
    body: str,
    publish_id: str,
) -> dict[str, Any]:
    note = f"\n\n## 优化备注\n\n- 用户要求：{message.strip()[:500]}\n"
    new_body = body.rstrip() + note
    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
    ).strip()
    raw = f"---\n{frontmatter}\n---\n\n{new_body}\n"
    return {
        "answer": "模型暂不可用，已把你的要求记入草案备注；配置 Key 后可再优化。也可直接编辑后发布。",
        "draft": {
            "name": name,
            "description": description,
            "body": new_body,
            "raw": raw,
            "skill_id": publish_id,
        },
    }
