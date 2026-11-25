"""Execute markdown-based RealAi Skills (instruction following, no arbitrary scripts)."""

from __future__ import annotations

import logging

from realai.llm import chat_text, has_api_key
from realai.skills.registry import SkillRecord, get_skill, has_executable_content

logger = logging.getLogger(__name__)


async def execute_skill(skill_id: str, user_input: str) -> dict:
    skill = get_skill(skill_id)
    if skill is None:
        raise FileNotFoundError(f"Skill '{skill_id}' 不存在")
    if not skill.valid:
        raise ValueError(f"Skill 无效：{'；'.join(skill.errors)}")
    if not skill.enabled:
        raise ValueError(f"Skill '{skill_id}' 已停用")

    answer = await _execute_draft(
        name=skill.name,
        description=skill.description,
        body=skill.body,
        user_input=user_input,
    )
    return {
        "skill_id": skill_id,
        "skill_name": skill.name,
        "input": user_input,
        "output": answer,
        "mode": "instruction",
    }


async def execute_skill_draft(
    *,
    name: str,
    description: str,
    body: str,
    user_input: str,
) -> dict:
    """Try an unsaved Skill draft without creating files or history."""
    if not name.strip():
        raise ValueError("名称不能为空")
    if not description.strip():
        raise ValueError("说明不能为空")
    if not has_executable_content(body):
        raise ValueError("正文需要包含实际执行内容，不能只有章节标题")
    if not user_input.strip():
        raise ValueError("请输入试跑内容")
    answer = await _execute_draft(
        name=name.strip(),
        description=description.strip(),
        body=body.strip(),
        user_input=user_input.strip(),
    )
    return {
        "skill_id": "",
        "skill_name": name.strip(),
        "input": user_input.strip(),
        "output": answer,
        "mode": "draft",
    }


async def _execute_draft(*, name: str, description: str, body: str, user_input: str) -> str:
    prompt = (
        f"你是 RealAi Skill 执行器。严格遵循下列 Skill 约定处理用户输入，输出可直接交付的结果。\n\n"
        f"## Skill: {name}\n{description}\n\n### 约定\n{body}\n\n"
        f"### 用户输入\n{user_input}"
    )
    return await _llm(prompt)


async def _llm(prompt: str) -> str:
    if not has_api_key():
        return f"[离线执行] 已加载 Skill 约定，请在「模型」页配置 API Key 后重试。\n\n{prompt[:800]}"
    try:
        return await chat_text(
            prompt,
            role="primary",
            temperature=0.7,
            max_tokens=2048,
            purpose="skill_execute",
        )
    except Exception:
        logger.exception("skill execute LLM failed")
        return "Skill 执行失败，请检查网络与 API Key。"


def skill_prompt_excerpt(skill: SkillRecord | None, *, max_len: int = 600) -> str:
    if skill is None or not skill.valid or not skill.enabled:
        return ""
    return f"[Skill:{skill.name}] {skill.body[:max_len]}"
