"""Strategic planning report pipeline: intake → researcher → architect → writer → citer → reviewer → optimizer."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from realai.agents.data import needs_data_query, query_vault_data
from realai.agents.web_search_skill import run_web_search_pipeline
from realai.config import (
    WebSearchMode,
    get_web_search_mode,
    load_settings,
    normalize_web_search_mode,
    resolve_report_output_dir,
    resolve_vault_path,
)
from realai.evidence.types import EvidencePack
from realai.llm.sanitize import (
    clean_report_markdown,
    is_usable_report_body,
    validate_report_revision,
)
from realai.meta.writing import get_task
from realai.org_identity import append_org_identity
from realai.report.intake import user_provided_facts_from_task
from realai.report.llm_client import chat_turn, chat_turn_stream, count_chinese_chars
from realai.report.progress import (
    REPORT_AGENTS,
    ProgressCallback,
    ReportProgressTracker,
    make_action_trace,
    make_llm_trace,
)
from realai.report.run_control import (
    PipelineCancelled,
    PipelinePaused,
    check_control,
    clear_control,
    reset_to_run,
)
from realai.report.strategic_types import REPORT_TYPES, default_outline, normalize_report_type
from realai.report.whitelist import url_allowed
from realai.report.word_export import markdown_to_docx
from realai.skills.executor import skill_prompt_excerpt
from realai.skills.registry import get_skill, list_skill_package_files
from realai.vault.service import write_vault_file

EventCallback = ProgressCallback

_STEP_ORDER = ["intake", "researcher", "architect", "writer", "citer", "reviewer", "optimizer"]
_CN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_REPORT_TITLE_PLACEHOLDERS = {
    "自定义规划",
    "战略规划",
    "战略规划报告",
    "规划报告",
    "报告",
    "报告标题",
}
_REPORT_TITLE_SUFFIXES = (
    "行动方案",
    "实施方案",
    "工作方案",
    "发展规划",
    "专项规划",
    "总体规划",
    "规划",
    "研究报告",
    "报告",
    "计划",
    "意见",
    "备参",
)
_RESEARCH_LOCAL_TIMEOUT_SECONDS = 20.0
_RESEARCH_DATA_TIMEOUT_SECONDS = 20.0
_RESEARCH_WEB_TIMEOUT_SECONDS = 25.0


def _writer_concurrency(step_confirm: bool, configured: int) -> int:
    """Keep approval mode serial; otherwise cap provider pressure at three chapters."""
    if step_confirm:
        return 1
    return max(1, min(3, int(configured or 3)))


def _chapter_batches(start: int, total: int, concurrency: int) -> list[list[int]]:
    width = max(1, int(concurrency or 1))
    return [list(range(i, min(total, i + width))) for i in range(max(0, start), total, width)]


def _outline_ready_for_writing(outline: dict[str, Any] | None) -> bool:
    """Only a complete, ordered section list may enter the writer stage."""

    if not isinstance(outline, dict):
        return False
    sections = outline.get("sections")
    if not isinstance(sections, list) or not sections:
        return False
    seen: set[str] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            return False
        chapter_id = str(section.get("id") or f"sec-{index + 1}").strip()
        heading = str(section.get("heading") or "").strip()
        if not chapter_id or not heading or chapter_id in seen:
            return False
        seen.add(chapter_id)
    return True


def _first_missing_chapter_index(
    outline: dict[str, Any] | None,
    drafts: list[dict[str, Any]] | None,
) -> int:
    """Return the first outline position without a persisted non-empty body."""

    if not _outline_ready_for_writing(outline):
        return 0
    completed = {str(draft.get("id") or "") for draft in drafts or [] if isinstance(draft, dict) and str(draft.get("body") or "").strip()}
    for index, section in enumerate(outline.get("sections") or []):
        chapter_id = str(section.get("id") or f"sec-{index + 1}")
        if chapter_id not in completed:
            return index
    return len(outline.get("sections") or [])


def _writer_token_limit(remaining_chars: int, configured_cap: int) -> int:
    """Dynamic output budget: enough for Chinese正文, never the old 8192-token burst."""
    cap = max(1800, min(4096, int(configured_cap or 4096)))
    return min(cap, max(1800, int(max(0, remaining_chars) * 1.6)))


def _default_strategic_main_line(goal: str) -> str:
    return f"以服务国家能源安全和现代能源体系建设为统领，以「{goal}」为主线，以基础设施能力提升、安全韧性与改革发展为重点，统筹管网运营与价值创造，推动高质量发展。"


def _normalize_strategic_main_line(raw: str, goal: str) -> str:
    """Keep one Chinese paragraph; reject leaked English thinking / empty residue."""
    from deerflow.utils.llm_text import strip_think_blocks

    text = strip_think_blocks(raw or "").strip()
    text = re.sub(r'^["“‘「『]+|["”’」』]+$', "", text).strip()
    # Drop common meta preambles if model ignored "只输出一段话"
    text = re.sub(
        r"^(战略主线[:：]\s*|如下[:：]\s*|以下是[^。\n]*[:：]\s*)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    candidates = paras or ([text] if text else [])
    picked = ""
    for p in candidates:
        if "主线" in p or "统领" in p:
            picked = p
            break
    if not picked and candidates:
        picked = candidates[0]
    # Single line preferred for UI; collapse inner newlines
    picked = re.sub(r"\s*\n+\s*", "", picked).strip()
    cn = len(_CN_CHAR_RE.findall(picked))
    if cn < 20 or len(picked) > 800:
        return _default_strategic_main_line(goal)
    # English analysis dumps (even after strip) often start with "The user"
    if re.match(r"^(The user|I need|Let me|Okay|Sure)\b", picked, re.I):
        return _default_strategic_main_line(goal)
    return picked[:500]


def _is_placeholder_report_title(value: str) -> bool:
    text = re.sub(r"\s+", "", str(value or "")).strip("《》“”\"'：:")
    return not text or text in _REPORT_TITLE_PLACEHOLDERS


def _report_title_needs_generation(raw: str, goal: str) -> bool:
    title = re.sub(r"\s+", " ", str(raw or "")).strip()
    normalized_goal = re.sub(r"\s+", " ", str(goal or "")).strip()
    return _is_placeholder_report_title(title) or title == normalized_goal or len(title) > 60


def _fallback_report_title(goal: str, report_type_label: str = "") -> str:
    """Extract a usable title from an instruction without copying the whole query."""
    text = re.sub(r"\s+", " ", str(goal or "")).strip()
    suffixes = "|".join(map(re.escape, _REPORT_TITLE_SUFFIXES))
    match = re.search(
        r"(?:撰写|编制|制定|形成|起草|写)(?:一篇|一份|一个)?\s*"
        rf"([^，。！？\n]{{4,80}}?(?:{suffixes}))(?:[，。！？]|$)",
        text,
    )
    if match:
        title = match.group(1).strip().replace("国家官网集团", "国家管网集团")
        title = re.sub(
            r"(?:遵循|贯彻)(?:该|上述)?(?:文章|文件)?(?:精神和指示|精神|指示)的?",
            "",
            title,
        ).strip()
        return title[:60]

    # Many users enter an already-title-shaped goal without an imperative,
    # e.g. “国家管网集团……行动方案”. Preserve it instead of falling back to
    # the internal template label.
    title_like = re.search(
        rf"([^，。！？\n]{{4,60}}?(?:{suffixes}))(?:[，。！？]|$)",
        text,
    )
    if title_like:
        return title_like.group(1).strip().replace("国家官网集团", "国家管网集团")
    if text and len(text) <= 60:
        return text.replace("国家官网集团", "国家管网集团")

    label = str(report_type_label or "").strip()
    if label and not _is_placeholder_report_title(label):
        return label
    return "战略规划报告"


def _normalize_report_title(raw: str, goal: str, report_type_label: str = "") -> str:
    from deerflow.utils.llm_text import strip_think_blocks

    text = strip_think_blocks(str(raw or "")).strip()
    text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    text = text.splitlines()[0].strip() if text else ""
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^(?:报告)?标题[:：]\s*", "", text)
    text = re.sub(r'^[《“"「]+|[》”"」]+$', "", text).strip()
    text = re.sub(r"[。；;，,]+$", "", text).strip()
    text = text.replace("国家官网集团", "国家管网集团")
    normalized_goal = re.sub(r"\s+", " ", str(goal or "")).strip()
    if _report_title_needs_generation(text, normalized_goal):
        return _fallback_report_title(goal, report_type_label)
    return text


def _parse_architecture_copy(
    raw: str,
    *,
    goal: str,
    report_type_label: str,
) -> tuple[str, str]:
    """Parse the architect's concise title + strategic main line JSON."""
    from deerflow.utils.llm_text import strip_think_blocks

    text = strip_think_blocks(str(raw or "")).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("架构文案结果不是 JSON 对象")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("架构文案结果必须是对象")
    return (
        _normalize_report_title(str(data.get("title") or ""), goal, report_type_label),
        _normalize_strategic_main_line(str(data.get("strategic_main_line") or ""), goal),
    )


def _parse_custom_outline(raw: str, goal: str, report_type: str) -> dict[str, Any]:
    """Parse and normalize an AI-generated outline for the no-template flow."""
    from deerflow.utils.llm_text import strip_think_blocks

    text = strip_think_blocks(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("大纲结果不是 JSON 对象")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("大纲结果必须是对象")

    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError("大纲缺少 sections")
    sections: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, value in enumerate(raw_sections[:12]):
        if not isinstance(value, dict):
            continue
        heading = str(value.get("heading") or "").strip()
        if not heading:
            continue
        raw_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value.get("id") or "")).strip("-")
        section_id = raw_id or f"custom-{index + 1}"
        if section_id in used_ids:
            section_id = f"custom-{index + 1}"
        used_ids.add(section_id)
        try:
            budget = int(value.get("word_budget") or 0)
        except (TypeError, ValueError):
            budget = 0
        sections.append(
            {
                "id": section_id,
                "heading": heading,
                "purpose": str(value.get("purpose") or "").strip(),
                "word_budget": max(800, budget or 2500),
            }
        )
    if len(sections) < 3:
        raise ValueError("动态大纲至少需要 3 个章节")

    rt = normalize_report_type(report_type)
    raw_title = str(data.get("title") or "")
    return {
        "title": _normalize_report_title(raw_title, goal, "自定义规划"),
        "_title_needs_generation": _is_placeholder_report_title(raw_title),
        "report_type": rt,
        "report_type_label": "自定义规划",
        "min_chars": REPORT_TYPES[rt]["min_chars"],
        "strategic_main_line": _normalize_strategic_main_line(str(data.get("strategic_main_line") or ""), goal),
        "sections": sections,
        "pipeline_agents": [
            "intake",
            "researcher",
            "architect",
            "writer",
            "citer",
            "reviewer",
            "optimizer",
        ],
    }


def _needs_outline_confirmation(
    *,
    step_confirm: bool,
    outline_confirm_required: bool,
    confirmed: bool,
    resume_chapter_index: int | None,
    resume_from: str | None,
) -> bool:
    """Outline approval is independent from optional per-chapter approval."""
    del resume_chapter_index, resume_from
    return bool((step_confirm or outline_confirm_required) and not confirmed)


def _format_user_facts(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "（无）"
    lines = []
    for f in facts[:20]:
        stmt = str(f.get("statement") or f.get("answer") or "").strip()
        if stmt:
            lines.append(f"- {stmt}")
    return "\n".join(lines) if lines else "（无）"


def _skill_id(settings: dict[str, Any], key: str, default: str) -> str:
    return str((settings.get("report") or {}).get(key) or default)


def _evidence_to_cards(pack: EvidencePack, *, kind: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in pack.items:
        card: dict[str, Any] = {
            "id": item.id,
            "kind": kind if kind != "auto" else item.type,
            "type": item.type,
            "title": str((item.meta or {}).get("title") or item.source),
            "source": item.source,
            "excerpt": item.excerpt,
            "meta": item.meta or {},
        }
        if item.type == "data" and item.meta:
            card["table"] = item.meta.get("table") or item.meta.get("preview") or item.meta.get("rows")
            card["columns"] = item.meta.get("columns")
        cards.append(card)
    return cards


def _prioritized_retrieve(goal: str, scope_paths: list[str] | None, limit: int = 10) -> EvidencePack:
    """wiki/raw/biz quota merge (shared with workbench/writing)."""
    from realai.shared_retrieve import prioritized_retrieve_quota

    pack = prioritized_retrieve_quota(goal, scope_paths)
    return EvidencePack(items=pack.items[: max(0, limit)])


async def _writing_web_search(goal: str, mode: WebSearchMode, local: EvidencePack) -> tuple[EvidencePack, list[str]]:
    if mode == "off":
        return EvidencePack(), ["联网跳过（已关闭）"]
    try:
        pack, traj, _err = await asyncio.wait_for(
            run_web_search_pipeline(
                goal,
                mode,
                local_pack=local,
                history_text="",
                limit=5,
                apply_whitelist=True,
            ),
            timeout=_RESEARCH_WEB_TIMEOUT_SECONDS,
        )
        return pack, traj
    except TimeoutError:
        return EvidencePack(), [f"联网检索超过 {_RESEARCH_WEB_TIMEOUT_SECONDS:.0f} 秒，已降级为本地资料继续"]


async def _bounded_sync_evidence(
    func: Callable[..., EvidencePack],
    /,
    *args: Any,
    timeout: float,
    **kwargs: Any,
) -> tuple[EvidencePack, str | None]:
    """Run blocking Vault/DuckDB work off-loop and keep research bounded."""

    try:
        pack = await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout,
        )
        return pack, None
    except TimeoutError:
        return EvidencePack(), f"超过 {timeout:.0f} 秒，已跳过"
    except Exception as exc:
        return EvidencePack(), str(exc)[:200]


def _load_skill_body(skill_id: str, max_len: int = 2500) -> str:
    skill = get_skill(skill_id)
    if not skill or not skill.valid or not skill.enabled:
        return ""
    return skill_prompt_excerpt(skill, max_len=max_len) or (skill.body[:max_len] if skill.body else "")


def _skill_binding(skill_id: str, *, default_tools: list[str] | None = None) -> dict[str, Any]:
    """Resolve skill display meta for progress UI (name, refs, scripts). Scripts are package files, not executed."""
    sk = get_skill(skill_id)
    refs: list[str] = []
    scripts: list[str] = []
    try:
        for f in list_skill_package_files(skill_id):
            kind = str(f.get("kind") or "")
            path = str(f.get("path") or "")
            if not path or path.upper() == "SKILL.MD":
                continue
            if kind == "reference":
                refs.append(path)
            elif kind == "script":
                scripts.append(path)
    except Exception:
        pass
    return {
        "skill_id": skill_id,
        "skill_name": (sk.name if sk else "") or skill_id,
        "skill_valid": bool(sk and sk.valid and sk.enabled),
        "skill_enabled": bool(sk and sk.enabled),
        "references": refs[:12],
        "scripts": scripts[:12],
        "tools": list(default_tools or []),
    }


def _snapshot_skill_binding(
    snapshot: dict[str, Any],
    *,
    default_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Progress metadata for an immutable task-level customer Skill."""

    return {
        "skill_id": str(snapshot.get("id") or ""),
        "skill_name": str(snapshot.get("name") or snapshot.get("id") or ""),
        "skill_valid": bool(snapshot.get("id") and snapshot.get("body")),
        "skill_enabled": True,
        "skill_version": snapshot.get("version"),
        "skill_trigger": "task_profile",
        "references": [],
        "scripts": [],
        "tools": list(default_tools or []),
    }


def _step_index(step: str) -> int:
    try:
        return _STEP_ORDER.index(step)
    except ValueError:
        return 0


def _should_skip(step: str, resume_from: str | None) -> bool:
    if not resume_from:
        return False
    return _step_index(step) < _step_index(resume_from)


def _pack_from_checkpoint(raw: Any) -> EvidencePack:
    if isinstance(raw, EvidencePack):
        return raw
    if isinstance(raw, dict):
        try:
            return EvidencePack.model_validate(raw)
        except Exception:
            items = raw.get("items") or []
            return EvidencePack.model_validate({"items": items})
    return EvidencePack()


def _control_snapshot(
    *,
    resume_from: str,
    resume_chapter_index: int = 0,
    outline: dict[str, Any] | None = None,
    chapter_drafts: list[dict[str, Any]] | None = None,
    evidence: EvidencePack | None = None,
    knowledge_cards: list[dict[str, Any]] | None = None,
    fact_pack: dict[str, Any] | None = None,
    preview_markdown: str = "",
    agent_progress: list[dict[str, Any]] | None = None,
    scorecards: list[dict[str, Any]] | None = None,
    citation_ledger: list[dict[str, Any]] | None = None,
    cited_md: str = "",
    scorecard: dict[str, Any] | None = None,
    skills: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "resume_from": resume_from,
        "resume_chapter_index": resume_chapter_index,
        "outline": outline or {},
        "chapter_drafts": chapter_drafts or [],
        "evidence": (evidence.to_dict() if evidence else {"items": []}),
        "knowledge_cards": knowledge_cards or [],
        "fact_pack": fact_pack or {},
        "preview_markdown": preview_markdown,
        "agent_progress": agent_progress or [],
        "scorecards": scorecards or [],
        "citation_ledger": citation_ledger or [],
        "cited_md": cited_md,
        "scorecard": scorecard,
        "skills": skills or {},
    }


async def run_report_pipeline(
    goal: str,
    *,
    step_confirm: bool = False,
    outline_confirm_required: bool = False,
    confirmed: bool = False,
    on_progress: ProgressCallback | None = None,
    on_event: EventCallback | None = None,
    outline_override: dict[str, Any] | None = None,
    scope_paths: list[str] | None = None,
    report_type: str | None = None,
    audience: str | None = None,
    writer_skill_id: str | None = None,
    review_skill_id: str | None = None,
    skill_profile: dict[str, Any] | None = None,
    web_search_mode: str | WebSearchMode | None = None,
    resume_chapter_index: int | None = None,
    confirmed_chapter: bool = False,
    task_id: str | None = None,
    resume_from: str | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    report_cfg = settings.get("report") or {}
    step_confirm = step_confirm or bool(report_cfg.get("stepConfirm"))
    mode: WebSearchMode = normalize_web_search_mode(str(web_search_mode)) if web_search_mode is not None else get_web_search_mode(settings)
    cp = checkpoint or {}
    if not resume_from:
        resume_from = str(cp.get("resume_from") or "") or None
    rt = normalize_report_type(report_type or (outline_override or {}).get("report_type") or (cp.get("outline") or {}).get("report_type"))

    researcher_id = _skill_id(settings, "researcherSkillId", "strategic-planning-researcher")
    architect_id = _skill_id(settings, "architectSkillId", "strategic-planning-architect")
    writer_id = writer_skill_id or _skill_id(settings, "writerSkillId", "strategic-planning-writer")
    citer_id = _skill_id(settings, "citerSkillId", "strategic-planning-citer")
    review_id = review_skill_id or _skill_id(settings, "reviewSkillId", "strategic-planning-reviewer")
    optimizer_id = _skill_id(settings, "optimizerSkillId", "strategic-planning-optimizer")
    intake_id = _skill_id(settings, "intakeSkillId", "strategic-planning-intake")
    profile = dict(skill_profile) if isinstance(skill_profile, dict) and str(skill_profile.get("id") or "").strip() and str(skill_profile.get("body") or "").strip() else None
    if profile:
        # A task-level customer method controls structure, prose and review.
        # Research, citation and optimization remain system-governed so a
        # customer prompt cannot bypass evidence or data safeguards.
        profile_id = str(profile["id"]).strip()
        architect_id = profile_id
        writer_id = profile_id
        review_id = profile_id
    max_rounds = int(report_cfg.get("optimizerMaxRounds") or 5)
    pass_score = float(report_cfg.get("optimizerPassScore") or 85)

    skill_bindings = {
        "intake": _skill_binding(intake_id, default_tools=["知识检索", "加载 Skill 正文", "LLM 出题"]),
        "researcher": _skill_binding(researcher_id, default_tools=["知识检索", "问数", "白名单联网"]),
        "architect": _skill_binding(architect_id, default_tools=["加载 Skill 正文", "LLM 生成战略主线"]),
        "writer": _skill_binding(writer_id, default_tools=["加载 Skill 正文", "LLM 逐章写作"]),
        "citer": _skill_binding(citer_id, default_tools=["证据台账", "加载 Skill 正文", "LLM 引用审核"]),
        "reviewer": _skill_binding(review_id, default_tools=["加载 Skill 正文", "LLM 七维评分"]),
        "optimizer": _skill_binding(optimizer_id, default_tools=["加载 Skill 正文", "LLM 迭代改写", f"最多 {max_rounds} 轮"]),
    }
    if profile:
        skill_bindings["architect"] = _snapshot_skill_binding(
            profile,
            default_tools=["任务级 Skill 快照", "LLM 生成战略主线"],
        )
        skill_bindings["writer"] = _snapshot_skill_binding(
            profile,
            default_tools=["任务级 Skill 快照", "LLM 逐章写作"],
        )
        skill_bindings["reviewer"] = _snapshot_skill_binding(
            profile,
            default_tools=["任务级 Skill 快照", "LLM 七维评分"],
        )
    tracker = ReportProgressTracker(on_step=on_progress, on_event=on_event, skill_bindings=skill_bindings)
    # Restore progress labels from checkpoint when resuming
    if isinstance(cp.get("agent_progress"), list) and cp["agent_progress"]:
        for prev in cp["agent_progress"]:
            pid = prev.get("id")
            if pid in tracker._index:
                tracker.steps[tracker._index[pid]].update(prev)

    skills_payload = _skills_payload(intake_id, researcher_id, architect_id, writer_id, citer_id, review_id, optimizer_id)
    if profile:
        for stage in ("architect", "writer", "review"):
            skills_payload[stage] = profile["id"]
            skills_payload[f"{stage}_valid"] = True
        skills_payload["profile"] = {
            "id": profile.get("id"),
            "name": profile.get("name"),
            "version": profile.get("version"),
            "snapshot": True,
        }

    def stage_skill_body(stage: str, skill_id: str, max_len: int) -> str:
        if profile and stage in {"architect", "writer", "reviewer"}:
            return str(profile.get("body") or "")[:max_len]
        return _load_skill_body(skill_id, max_len)

    knowledge_cards: list[dict[str, Any]] = list(cp.get("knowledge_cards") or [])
    evidence = _pack_from_checkpoint(cp.get("evidence")) if resume_from else EvidencePack()
    fact_pack: dict[str, Any] = dict(cp.get("fact_pack") or {})
    scorecards: list[dict[str, Any]] = list(cp.get("scorecards") or [])
    citation_ledger: list[dict[str, Any]] = list(cp.get("citation_ledger") or [])
    cited_md = str(cp.get("cited_md") or "")
    scorecard: dict[str, Any] = dict(cp.get("scorecard") or {}) if cp.get("scorecard") else {}

    task_row = get_task(task_id) if task_id else None
    user_facts = user_provided_facts_from_task(task_row)
    if user_facts and not fact_pack.get("user_provided"):
        fact_pack["user_provided"] = user_facts
    user_facts_text = _format_user_facts(user_facts or list(fact_pack.get("user_provided") or []))

    async def gate(next_step: str, **fields: Any) -> None:
        snap = _control_snapshot(
            resume_from=next_step,
            outline=fields.get("outline"),
            chapter_drafts=fields.get("chapter_drafts"),
            evidence=fields.get("evidence", evidence),
            knowledge_cards=fields.get("knowledge_cards", knowledge_cards),
            fact_pack=fields.get("fact_pack", fact_pack),
            preview_markdown=fields.get("preview_markdown", ""),
            agent_progress=tracker.snapshot(),
            scorecards=fields.get("scorecards", scorecards),
            citation_ledger=fields.get("citation_ledger", citation_ledger),
            cited_md=fields.get("cited_md", cited_md),
            scorecard=fields.get("scorecard", scorecard or None),
            skills=skills_payload,
            resume_chapter_index=int(fields.get("resume_chapter_index") or 0),
        )
        # A gate is both a pause/cancel boundary and a durable resume boundary.
        # The app layer persists this event before forwarding it to SSE clients,
        # so leaving the page or restarting Gateway never discards completed
        # research, the outline, or accepted chapters.
        await tracker.emit_event({"type": "checkpoint", "checkpoint": snap})
        await check_control(task_id, snap)

    # ----- intake (already done before run; mark completed) -----
    if not _should_skip("intake", resume_from):
        await tracker.start("intake", f"Skill：{intake_id}", **skill_bindings["intake"])
        n_facts = len(user_facts or list(fact_pack.get("user_provided") or []))
        await tracker.complete(
            "intake",
            f"智能补缺已完成 · 用户给定事实 {n_facts} 条",
            **skill_bindings["intake"],
        )
        await gate("researcher", fact_pack=fact_pack)

    # ----- researcher -----
    if not _should_skip("researcher", resume_from):
        await tracker.start(
            "researcher",
            f"Skill：{researcher_id}",
            **skill_bindings["researcher"],
        )
        await tracker.append_trace(
            "researcher",
            make_action_trace(
                "启动资料研究",
                summary="正在并行检索本地知识；有明确数字或表格意图时才启动问数",
            ),
        )
        data_requested = needs_data_query(goal)
        kb_job = _bounded_sync_evidence(
            _prioritized_retrieve,
            goal,
            scope_paths,
            limit=14,
            timeout=_RESEARCH_LOCAL_TIMEOUT_SECONDS,
        )
        if data_requested:
            data_job = _bounded_sync_evidence(
                query_vault_data,
                goal,
                limit=8,
                force=False,
                scope_paths=scope_paths or ["pipelines", "new_energy", "dataqa", "entities", "05_Metrics"],
                timeout=_RESEARCH_DATA_TIMEOUT_SECONDS,
            )
        else:

            async def _skip_data() -> tuple[EvidencePack, str | None]:
                return EvidencePack(), "当前目标无明确数字或表格意图"

            data_job = _skip_data()

        (kb, kb_error), (data, data_error) = await asyncio.gather(kb_job, data_job)
        from realai.shared_retrieve import metrics_evidence_for_query

        metric_ev = await asyncio.to_thread(metrics_evidence_for_query, goal, limit=3)
        if metric_ev.items:
            kb = EvidencePack(items=[*metric_ev.items, *kb.items])
        knowledge_cards.extend(_evidence_to_cards(kb, kind="retrieve"))
        await tracker.emit_event({"type": "card", "cards": knowledge_cards[-len(kb.items) :] if kb.items else []})
        kb_sources = "、".join((i.source or i.id)[:40] for i in kb.items[:5])
        await tracker.append_trace(
            "researcher",
            make_action_trace(
                "知识检索",
                summary=((f"命中 {len(kb.items)} 条" + (f"；示例：{kb_sources}" if kb_sources else "")) if not kb_error else f"本地检索已降级：{kb_error}"),
                detail="\n".join(f"- [{i.id}] {i.source}: {i.excerpt[:120]}" for i in kb.items[:12]),
            ),
        )

        knowledge_cards.extend(_evidence_to_cards(data, kind="data"))
        await tracker.emit_event({"type": "card", "cards": _evidence_to_cards(data, kind="data")})
        await tracker.append_trace(
            "researcher",
            make_action_trace(
                "问数",
                summary=(f"命中 {len(data.items)} 条（按问题意图触发）" if data.items else (f"问数已降级：{data_error}" if data_requested else "当前目标无明确数字或表格意图，已跳过问数")),
                detail="\n".join(f"- [{i.id}] {i.source}: {i.excerpt[:120]}" for i in data.items[:8]),
            ),
        )

        local = EvidencePack(items=[*kb.items, *data.items])
        web, web_traj = await _writing_web_search(goal, mode, local)
        if web.items:
            knowledge_cards.extend(_evidence_to_cards(web, kind="web"))
            await tracker.emit_event({"type": "card", "cards": _evidence_to_cards(web, kind="web")})
            await tracker.append_trace(
                "researcher",
                make_action_trace(
                    "白名单联网",
                    summary=f"模式 {mode} · 命中 {len(web.items)} 条",
                    detail="\n".join([*(web_traj or []), *[f"- [{i.id}] {i.source}: {i.excerpt[:120]}" for i in web.items[:8]]]),
                ),
            )
        else:
            await tracker.append_trace(
                "researcher",
                make_action_trace(
                    "联网检索",
                    summary=(web_traj[0] if web_traj else (f"模式 {mode} · 未调用或未命中" if mode != "off" else "模式 off · 未联网")),
                    detail="\n".join(web_traj or []),
                ),
            )

        evidence = EvidencePack(items=[*local.items, *web.items])
        fact_pack = {
            "scope": goal,
            "audience": audience or "集团战略/规划领导",
            "report_type": rt,
            "user_provided": user_facts or list(fact_pack.get("user_provided") or []),
            "findings": [{"id": i.id, "type": i.type, "source": i.source, "excerpt": i.excerpt[:300]} for i in evidence.items[:16]],
            "data_gaps": [] if evidence.items else ["知识库与问数暂无足够命中，正文须标注[待补充]"],
        }
        researcher_tools = ["知识检索"]
        if data.items:
            researcher_tools.append("问数")
        if web.items:
            researcher_tools.append("白名单联网")
        elif mode != "off":
            researcher_tools.append(f"联网({mode}·未命中)")
        await tracker.complete(
            "researcher",
            f"事实包 {len(evidence.items)} 条 / 卡片 {len(knowledge_cards)}",
            tools=researcher_tools,
            **{k: v for k, v in skill_bindings["researcher"].items() if k != "tools"},
        )
        await gate("architect", evidence=evidence, knowledge_cards=knowledge_cards, fact_pack=fact_pack)

    # ----- architect -----
    if not _should_skip("architect", resume_from):
        await tracker.start(
            "architect",
            f"Skill：{architect_id}",
            **skill_bindings["architect"],
        )
        outline = outline_override or default_outline(goal, rt)
        if outline_confirm_required and not outline_override:
            try:
                arch_hint = stage_skill_body("architect", architect_id, 1600)
                evidence_text = "\n".join(f"- {item.source}: {item.excerpt[:180]}" for item in evidence.items[:12]) or "（暂无，可在大纲中保留待补充项）"
                custom_system = append_org_identity("你是战略规划架构师。根据用户目标自主设计报告大纲，只输出严格 JSON，禁止 Markdown 围栏和解释。")
                custom_prompt = (
                    f"用户写作目标：{goal}\n"
                    f"目标读者：{audience or '集团战略/规划领导'}\n\n"
                    f"## 用户给定事实\n{user_facts_text}\n\n"
                    f"## 已检索事实\n{evidence_text}\n\n"
                    "请生成 5–10 章的战略规划大纲。章节必须围绕用户目标动态设计，"
                    "不得套用固定的区域油气模板。严格输出：\n"
                    '{"title":"报告标题","strategic_main_line":"一段战略主线",'
                    '"sections":[{"id":"section-1","heading":"章节名",'
                    '"purpose":"本章作用与要回答的问题","word_budget":2500}]}\n'
                    "title 必须根据用户目标拟定正式标题，禁止使用“自定义规划”、"
                    "“战略规划报告”“报告”等占位名称。\n"
                    "章节 id 用英文、数字或连字符；word_budget 为内部写作预算。\n\n"
                    f"Skill 要点：\n{arch_hint}"
                )
                await tracker.mark_llm_pending("architect", "生成自定义大纲")
                turn = await chat_turn(
                    custom_prompt,
                    system=custom_system,
                    max_tokens=3072,
                    temperature=0.35,
                )
                raw_outline = str(turn.get("content") or "")
                outline = _parse_custom_outline(raw_outline, goal, rt)
                await tracker.append_trace(
                    "architect",
                    make_llm_trace(
                        "生成自定义大纲",
                        system=custom_system,
                        prompt=custom_prompt,
                        reply=raw_outline,
                        reasoning=(turn.get("reasoning") if isinstance(turn.get("reasoning"), str) else None),
                    ),
                )
            except Exception as exc:
                await tracker.clear_llm_pending("architect", "生成自定义大纲")
                await tracker.append_trace(
                    "architect",
                    make_action_trace(
                        "自定义大纲生成失败，已用通用大纲回退",
                        summary=str(exc)[:200],
                    ),
                )
        if not outline.get("sections"):
            outline = default_outline(goal, rt)
        outline["report_type"] = rt
        outline["report_type_label"] = "自定义规划" if outline_confirm_required else REPORT_TYPES[rt]["label"]
        outline["min_chars"] = outline.get("min_chars") or REPORT_TYPES[rt]["min_chars"]
        raw_title = str(outline.get("title") or "").strip()
        needs_title = bool(outline.pop("_title_needs_generation", False)) or _report_title_needs_generation(raw_title, goal)
        needs_main_line = not str(outline.get("strategic_main_line") or "").strip()
        if needs_title or needs_main_line:
            try:
                arch_hint = stage_skill_body("architect", architect_id, 1200)
                arch_system = append_org_identity("你是战略规划架构师。提炼正式报告标题和战略主线，只输出严格 JSON，不要输出思考过程、Markdown 或英文分析。")
                arch_prompt = (
                    f"报告目标：{goal}\n类型：{outline['report_type_label']}\n受众：{audience or '战略部'}\n"
                    f"## 用户给定事实（智能补缺）\n{user_facts_text}\n\n"
                    "请输出：\n"
                    '{"title":"正式报告标题","strategic_main_line":"一段战略主线"}\n'
                    "标题要求：12–30 个汉字，采用正式公文标题；不得照抄整个用户问题，"
                    "不得出现“根据……写一篇”“用户要求”等指令性措辞，"
                    "禁止使用“自定义规划”“战略规划报告”“报告”等占位名称。\n"
                    "战略主线句式参考：以…为统领，以…为主线，以…为重点，"
                    "统筹…和…，推动…，为…提供支撑。\n\n"
                    f"Skill要点：\n{arch_hint}"
                )
                await tracker.mark_llm_pending("architect", "提炼报告标题与战略主线")
                turn = await chat_turn(
                    arch_prompt,
                    system=arch_system,
                    max_tokens=1024,
                    temperature=0.4,
                )
                raw_copy = str(turn.get("content") or "")
                title, main_line = _parse_architecture_copy(
                    raw_copy,
                    goal=goal,
                    report_type_label=str(outline["report_type_label"]),
                )
                if needs_title:
                    outline["title"] = title
                if needs_main_line:
                    outline["strategic_main_line"] = main_line
                await tracker.append_trace(
                    "architect",
                    make_llm_trace(
                        "提炼报告标题与战略主线",
                        system=arch_system,
                        prompt=arch_prompt,
                        reply=raw_copy,
                        reasoning=turn.get("reasoning") if isinstance(turn.get("reasoning"), str) else None,
                    ),
                )
            except Exception as exc:
                await tracker.clear_llm_pending("architect", "提炼报告标题与战略主线")
                if needs_title:
                    outline["title"] = _fallback_report_title(goal, str(outline["report_type_label"]))
                if needs_main_line:
                    outline["strategic_main_line"] = _default_strategic_main_line(goal)
                await tracker.append_trace(
                    "architect",
                    make_action_trace(
                        "标题或战略主线生成失败，已使用规范化回退",
                        summary=str(exc)[:200],
                    ),
                )
        else:
            outline["title"] = _normalize_report_title(raw_title, goal, str(outline["report_type_label"]))
            outline["strategic_main_line"] = _normalize_strategic_main_line(str(outline.get("strategic_main_line") or ""), goal)
            await tracker.append_trace(
                "architect",
                make_action_trace(
                    "沿用已有战略主线",
                    summary=(outline.get("strategic_main_line") or "")[:160],
                ),
            )
        # Final invariant: an internal template label must never become the
        # reader-facing report title, even when a provider returned a valid
        # JSON object with a placeholder value.
        outline["title"] = _normalize_report_title(
            str(outline.get("title") or ""),
            goal,
            str(outline["report_type_label"]),
        )
        await tracker.emit_event({"type": "outline", "outline": outline})
        await tracker.complete(
            "architect",
            f"{len(outline.get('sections', []))} 章 · 大纲已生成",
            **skill_bindings["architect"],
        )

        if _needs_outline_confirmation(
            step_confirm=step_confirm,
            outline_confirm_required=outline_confirm_required,
            confirmed=confirmed,
            resume_chapter_index=resume_chapter_index,
            resume_from=resume_from,
        ):
            # Do not persist a writer resume boundary before the user has
            # approved the outline. A crash in this narrow window used to
            # recover directly into chapter writing.
            await gate(
                "architect",
                outline=outline,
                evidence=evidence,
                knowledge_cards=knowledge_cards,
                fact_pack=fact_pack,
            )
            return {
                "run_mode": "report",
                "phase": "await_outline_confirm",
                "step_confirm": step_confirm,
                "outline_confirm_required": outline_confirm_required,
                "outline": outline,
                "evidence": evidence.to_dict(),
                "knowledge_cards": knowledge_cards,
                "fact_pack": fact_pack,
                "agent_progress": tracker.snapshot(),
                "web_search_mode": mode,
                "web_search_enabled": mode != "off",
                "message": "请确认大纲后继续生成正文",
                "skills": skills_payload,
            }
        await gate(
            "writer",
            outline=outline,
            evidence=evidence,
            knowledge_cards=knowledge_cards,
            fact_pack=fact_pack,
        )
    else:
        outline = outline_override or dict(cp.get("outline") or {}) or default_outline(goal, rt)
        outline["report_type"] = rt
        outline["report_type_label"] = "自定义规划" if outline_confirm_required else (outline.get("report_type_label") or REPORT_TYPES[rt]["label"])
        outline["min_chars"] = outline.get("min_chars") or REPORT_TYPES[rt]["min_chars"]
        outline["title"] = _normalize_report_title(
            str(outline.get("title") or ""),
            goal,
            str(outline["report_type_label"]),
        )

    # ----- writer (token streaming + bounded chapter concurrency) -----
    chapter_drafts: list[dict[str, Any]] = list((outline_override or {}).get("chapter_drafts") or cp.get("chapter_drafts") or (outline.get("chapter_drafts") if isinstance(outline.get("chapter_drafts"), list) else []) or [])
    if resume_chapter_index is None and cp.get("resume_chapter_index") is not None:
        resume_chapter_index = int(cp.get("resume_chapter_index") or 0)

    if not _outline_ready_for_writing(outline):
        # A malformed checkpoint must never manufacture a chapter list from
        # residual model output. Rebuild a visible outline and stop for user
        # confirmation instead.
        fallback = default_outline(goal, rt)
        fallback["title"] = _normalize_report_title(
            str(outline.get("title") or fallback.get("title") or goal),
            goal,
            "自定义规划" if outline_confirm_required else REPORT_TYPES[rt]["label"],
        )
        fallback["strategic_main_line"] = str(outline.get("strategic_main_line") or fallback.get("strategic_main_line") or "")
        fallback["report_type"] = rt
        fallback["report_type_label"] = "自定义规划" if outline_confirm_required else REPORT_TYPES[rt]["label"]
        fallback["min_chars"] = REPORT_TYPES[rt]["min_chars"]
        outline = fallback
        chapter_drafts = []
        await tracker.emit_event({"type": "outline", "outline": outline})
        await tracker.append_trace(
            "architect",
            make_action_trace(
                "阻止无大纲写作",
                summary="检测到空白或损坏的大纲，已重建并等待确认",
            ),
        )
        return {
            "run_mode": "report",
            "phase": "await_outline_confirm",
            "step_confirm": step_confirm,
            "outline_confirm_required": True,
            "outline": outline,
            "chapter_drafts": [],
            "evidence": evidence.to_dict(),
            "knowledge_cards": knowledge_cards,
            "fact_pack": fact_pack,
            "preview_markdown": "",
            "agent_progress": tracker.snapshot(),
            "web_search_mode": mode,
            "web_search_enabled": mode != "off",
            "message": "检测到大纲缺失，已停止正文写作，请确认大纲后继续",
            "skills": skills_payload,
        }

    first_missing = _first_missing_chapter_index(outline, chapter_drafts)
    if resume_from and _step_index(resume_from) > _step_index("writer") and first_missing < len(outline.get("sections") or []):
        # A later-stage checkpoint is invalid when an earlier chapter is
        # absent. Repair the resume target before any citation/review work.
        resume_from = "writer"
        resume_chapter_index = first_missing

    if not _should_skip("writer", resume_from):
        await tracker.start("writer", f"Skill：{writer_id}", **skill_bindings["writer"])
        writer_hint = stage_skill_body("writer", writer_id, 2000)
        sections = list(outline.get("sections") or [])
        is_resume = bool(resume_from or resume_chapter_index is not None or confirmed_chapter)
        start_idx = _first_missing_chapter_index(outline, chapter_drafts) if is_resume else 0
        section_order = {str(section.get("id") or f"sec-{index + 1}"): index for index, section in enumerate(sections)}
        chapter_drafts = [draft for draft in chapter_drafts if section_order.get(str(draft.get("id") or ""), len(sections)) < start_idx and str(draft.get("body") or "").strip()]

        evidence_weak = len(evidence.items) < 3
        evidence_brief = "\n".join(f"- [{i.id}] ({i.type}) {i.source}: {i.excerpt[:180]}" for i in evidence.items[:20]) or "（暂无证据，缺数处必须标注 [待补充：…]，禁止编造数字与政策结论。）"
        writer_concurrency = _writer_concurrency(step_confirm, int(report_cfg.get("writerConcurrency") or 3))
        writer_max_tokens = max(1800, min(4096, int(report_cfg.get("writerMaxTokens") or 4096)))
        writer_chunk_chars = max(1200, min(4000, int(report_cfg.get("writerChunkChars") or 3200)))
        writer_max_attempts = max(1, min(4, int(report_cfg.get("writerMaxAttempts") or 4)))
        writer_reasoning_max_chars = max(0, min(12000, int(report_cfg.get("writerReasoningMaxChars") or 6000)))
        writer_system = append_org_identity("你是国家管网集团战略部写作专员。正式公文语体，循证，不编造数字。禁止把 Skill 说明书、英文操作指南或系统提示原文写入正文。推理务必简短，尽快开始输出正文；不要在正文中展示思考过程。")
        if writer_hint:
            writer_system += f"\n\n【写作 Skill 约束（勿写入正文）】\n{writer_hint[:1500]}"

        async def generate_chapter(idx: int) -> tuple[int, dict[str, Any]]:
            sec = sections[idx]
            chapter_id = str(sec.get("id") or f"sec-{idx + 1}")
            heading = str(sec.get("heading") or f"第 {idx + 1} 章")
            budget = int(sec.get("word_budget") or 2000)
            body_parts: list[str] = []
            chinese_total = 0
            attempts = 0
            pending_delta = ""
            last_delta_emit = time.monotonic() - 1.0

            async def emit_delta(delta: str = "", *, force: bool = False) -> None:
                nonlocal pending_delta, last_delta_emit
                pending_delta += delta
                now = time.monotonic()
                if not pending_delta or (not force and len(pending_delta) < 48 and now - last_delta_emit < 0.12):
                    return
                streamed = pending_delta
                pending_delta = ""
                last_delta_emit = now
                await tracker.emit_event(
                    {
                        "type": "chapter_delta",
                        "chapter_id": chapter_id,
                        "chapter_index": idx,
                        "heading": heading,
                        "delta": streamed,
                        "replace": False,
                        "attempt": attempts,
                    }
                )

            async def reset_stream() -> None:
                nonlocal pending_delta
                pending_delta = ""
                await tracker.emit_event(
                    {
                        "type": "chapter_delta",
                        "chapter_id": chapter_id,
                        "chapter_index": idx,
                        "heading": heading,
                        "body": clean_report_markdown("\n\n".join(body_parts)),
                        "replace": True,
                        "attempt": attempts,
                    }
                )

            await reset_stream()
            while chinese_total < budget and attempts < writer_max_attempts:
                attempts += 1
                remain = min(writer_chunk_chars, max(800, budget - chinese_total + 300))
                prompt = (
                    f"你正在撰写战略规划报告《{outline.get('title') or goal}》的第 {idx + 1}/{len(sections)} 章。\n"
                    f"章节标题：{heading}\n章节ID：{chapter_id}\n"
                    f"战略主线：{outline.get('strategic_main_line')}\n"
                    f"报告类型：{outline.get('report_type_label')}\n"
                    f"本章目标中文字数（汉字+中文标点）约 {budget}，本次请写约 {remain} 字"
                    f"{'（续写扩充，勿重复已有段落开头）' if body_parts else ''}。\n"
                    f"单次输出中文不超过 {writer_chunk_chars} 字。禁止输出其他章节。\n"
                    "请将内部推理控制在最短范围，立即开始输出正式正文。\n"
                    "数字与政策判断必须来自下列证据；没有则写 [待补充：说明]。\n"
                    "用户给定事实可用于范围、口径与叙事，但其中的具体数字仍须有证据支持，禁止臆造。\n"
                    "正文引用可用 【1】【2】 序号（对应证据顺序）。"
                    "不要在本章末尾输出参考文献、证据引用或来源清单，全文引用由后续阶段统一汇总。\n"
                    f"{'【弱证据模式】当前证据不足，请写可核验的框架与待补充标记，禁止用空话凑字数。' if evidence_weak else ''}\n\n"
                    f"## 用户给定事实（智能补缺）\n{user_facts_text}\n\n"
                    f"## 证据\n{evidence_brief}\n\n"
                )
                if body_parts:
                    prompt += f"## 已写内容（续写）\n{body_parts[-1][-2000:]}\n\n请继续扩充本章，直接输出续写正文。"
                else:
                    prompt += "请直接输出本章 Markdown 正文（可含二级标题），不要前言客套。"
                writer_title = f"撰写第 {idx + 1} 章 · 第 {attempts} 次" + (f"（{heading}）" if heading else "")
                await tracker.mark_llm_pending("writer", writer_title)
                call_has_delta = False

                async def on_text_delta(delta: str) -> None:
                    nonlocal call_has_delta
                    if not call_has_delta and body_parts:
                        await emit_delta("\n\n")
                    call_has_delta = True
                    await emit_delta(delta)

                try:
                    turn = await chat_turn_stream(
                        prompt,
                        system=writer_system,
                        max_tokens=_writer_token_limit(remain, writer_max_tokens),
                        temperature=0.55,
                        task_id=task_id,
                        reasoning_max_chars=writer_reasoning_max_chars,
                        on_text_delta=on_text_delta,
                        on_reset=reset_stream,
                    )
                    await emit_delta(force=True)
                    chunk = clean_report_markdown(str(turn.get("content") or ""))
                except Exception as exc:
                    await tracker.clear_llm_pending("writer", writer_title)
                    await tracker.fail("writer", str(exc))
                    raise
                await tracker.clear_llm_pending("writer", writer_title)
                await tracker.append_trace(
                    "writer",
                    make_llm_trace(
                        writer_title,
                        system=writer_system,
                        prompt=prompt,
                        reply=chunk,
                        reasoning=(turn.get("reasoning") if isinstance(turn.get("reasoning"), str) else None),
                    ),
                )
                if "Strategic Planning Writer" in chunk or "## Operating Stance" in chunk:
                    chunk = "\n".join(line for line in chunk.splitlines() if "Strategic Planning" not in line and "Operating Stance" not in line and not line.strip().startswith("Write formal Chinese"))
                    chunk = clean_report_markdown(chunk)
                if not is_usable_report_body(chunk, min_chinese=15, require_heading=False):
                    await tracker.append_trace(
                        "writer",
                        make_action_trace(
                            "本轮输出无效已跳过",
                            summary="清洗后无可用中文正文（可能仅为思考过程）",
                        ),
                    )
                    await reset_stream()
                    continue
                body_parts.append(chunk)
                chinese_total = count_chinese_chars("\n\n".join(body_parts))
                await reset_stream()

            chapter_body = clean_report_markdown("\n\n".join(body_parts))
            if not chapter_body:
                chapter_body = f"[待补充：第 {idx + 1} 章「{heading}」生成失败，请重跑]"
            if evidence_weak and "[待补充" not in chapter_body:
                chapter_body += "\n\n[待补充：本章证据不足，请补充 wiki/表数据后重跑]\n"
            draft = {
                "id": chapter_id,
                "heading": heading,
                "body": chapter_body,
                "chinese_chars": count_chinese_chars(chapter_body),
                "word_budget": budget,
                "evidence_weak": evidence_weak,
            }
            await tracker.emit_event({"type": "chapter", "chapter": draft, "chapter_index": idx})
            return idx, draft

        for batch in _chapter_batches(start_idx, len(sections), writer_concurrency):
            batch_results = await asyncio.gather(*(generate_chapter(idx) for idx in batch))
            for _, draft in sorted(batch_results, key=lambda item: item[0]):
                existing = next(
                    (i for i, saved in enumerate(chapter_drafts) if saved.get("id") == draft["id"]),
                    None,
                )
                if existing is not None:
                    chapter_drafts[existing] = draft
                else:
                    chapter_drafts.append(draft)
            section_order = {str(section.get("id") or f"sec-{idx + 1}"): idx for idx, section in enumerate(sections)}
            chapter_drafts.sort(key=lambda draft: section_order.get(str(draft.get("id")), 999))
            last_idx = batch[-1]
            preview_md = _assemble_markdown(goal, outline, chapter_drafts)
            await gate(
                "writer",
                outline={**outline, "chapter_drafts": chapter_drafts},
                chapter_drafts=chapter_drafts,
                resume_chapter_index=last_idx + 1,
                preview_markdown=preview_md,
                evidence=evidence,
                knowledge_cards=knowledge_cards,
                fact_pack=fact_pack,
            )

            if step_confirm and not confirmed_chapter and last_idx < len(sections) - 1:
                await tracker.complete("writer", f"已写至第 {last_idx + 1}/{len(sections)} 章，等待确认")
                return {
                    "run_mode": "report",
                    "phase": "await_chapter_confirm",
                    "step_confirm": True,
                    "outline": {**outline, "chapter_drafts": chapter_drafts},
                    "chapter_drafts": chapter_drafts,
                    "next_chapter_index": last_idx + 1,
                    "evidence": evidence.to_dict(),
                    "knowledge_cards": knowledge_cards,
                    "fact_pack": fact_pack,
                    "preview_markdown": preview_md,
                    "agent_progress": tracker.snapshot(),
                    "web_search_mode": mode,
                    "message": f"第 {last_idx + 1} 章已完成，请确认后继续下一章",
                    "skills": skills_payload,
                }

        await tracker.complete(
            "writer",
            f"完成 {len(chapter_drafts)} 章 · 流式输出 · 并发 {writer_concurrency}",
            **skill_bindings["writer"],
        )
        await gate(
            "citer",
            outline={**outline, "chapter_drafts": chapter_drafts},
            chapter_drafts=chapter_drafts,
            preview_markdown=_assemble_markdown(goal, outline, chapter_drafts),
            evidence=evidence,
            knowledge_cards=knowledge_cards,
            fact_pack=fact_pack,
        )
    else:
        # skipped writer: drafts already in checkpoint
        pass

    # ----- citer -----
    if not _should_skip("citer", resume_from):
        await tracker.start("citer", f"Skill：{citer_id}", **skill_bindings["citer"])
        md_raw = _assemble_markdown(goal, outline, chapter_drafts)
        cited_md, citation_ledger = await _run_citer(
            md_raw,
            evidence,
            citer_id,
            required_headings=_outline_headings(outline),
            tracker=tracker,
            agent_id="citer",
        )
        cited_md = clean_report_markdown(cited_md) or md_raw
        chapter_drafts = split_markdown_by_outline(cited_md, list(outline.get("sections") or []), previous=chapter_drafts)
        outline = await _emit_chapters_and_outline(
            tracker,
            outline=outline,
            chapter_drafts=chapter_drafts,
            preview_markdown=cited_md,
        )
        await tracker.append_trace(
            "citer",
            make_action_trace(
                "构建证据台账",
                summary=f"参考文献 {len(citation_ledger)} 条",
            ),
        )
        await tracker.complete(
            "citer",
            f"参考文献 {len(citation_ledger)} 条",
            **skill_bindings["citer"],
        )
        await gate(
            "reviewer",
            outline={**outline, "chapter_drafts": chapter_drafts},
            chapter_drafts=chapter_drafts,
            preview_markdown=cited_md,
            cited_md=cited_md,
            citation_ledger=citation_ledger,
            evidence=evidence,
            knowledge_cards=knowledge_cards,
            fact_pack=fact_pack,
        )
    elif not cited_md:
        cited_md = clean_report_markdown(str(cp.get("preview_markdown") or _assemble_markdown(goal, outline, chapter_drafts)))

    # ----- reviewer + optimizer -----
    if not _should_skip("reviewer", resume_from):
        await tracker.start("reviewer", f"Skill：{review_id}", **skill_bindings["reviewer"])
        scorecard = await _run_reviewer(
            goal,
            cited_md,
            outline,
            review_id,
            skill_body_override=stage_skill_body("reviewer", review_id, 1200),
            tracker=tracker,
            agent_id="reviewer",
        )
        scorecards = [scorecard]
        await tracker.emit_event({"type": "scorecard", "scorecard": scorecard, "round": 0})
        await tracker.complete(
            "reviewer",
            f"总分 {scorecard.get('total', 0)}",
            **skill_bindings["reviewer"],
        )
        await gate(
            "optimizer",
            outline={**outline, "chapter_drafts": chapter_drafts},
            chapter_drafts=chapter_drafts,
            preview_markdown=cited_md,
            cited_md=cited_md,
            citation_ledger=citation_ledger,
            scorecard=scorecard,
            scorecards=scorecards,
            evidence=evidence,
            knowledge_cards=knowledge_cards,
            fact_pack=fact_pack,
        )

    if not _should_skip("optimizer", resume_from):
        await tracker.start("optimizer", f"Skill：{optimizer_id}", **skill_bindings["optimizer"])
        final_md = cited_md
        prev_total = float(scorecard.get("total") or 0)
        stagnant = 0
        best_md = final_md
        best_score = prev_total
        best_scorecard = scorecard

        for round_i in range(1, max_rounds + 1):
            stop_after_commit = False
            total = float(scorecard.get("total") or 0)
            if total >= pass_score:
                await tracker.emit_event({"type": "scorecard", "scorecard": scorecard, "round": round_i, "status": "pass"})
                break
            weak = scorecard.get("weak_dimensions") or []
            issues = scorecard.get("issues") or []
            if not weak and not issues:
                break
            try:
                rewrite_hint = _load_skill_body(optimizer_id, 1000)
                opt_system = append_org_identity("你是战略报告迭代优化器，只输出完整 Markdown 报告。")
                opt_prompt = (
                    f"报告目标：{goal}\n本轮优化第 {round_i}/{max_rounds} 轮。\n"
                    f"当前总分：{total}，薄弱维度：{weak}\n问题清单：{json.dumps(issues[:12], ensure_ascii=False)}\n"
                    "请只修改最薄弱的 2-3 个章节，其他章节必须逐字保留，并输出完整修订后的 Markdown 全文。"
                    "必须保留全部章节标题和叙事段落；不得输出评分卡、引用审核表、问题清单、"
                    "审核意见或重写计划代替正文。\n"
                    "不得编造证据包外数字；缺数保留[待补充]。\n\n"
                    f"## Skill\n{rewrite_hint}\n\n## 原文\n{final_md[:48000]}"
                )
                await tracker.mark_llm_pending("optimizer", f"第 {round_i} 轮改写")
                turn = await chat_turn(
                    opt_prompt,
                    system=opt_system,
                    max_tokens=8192,
                    temperature=0.45,
                )
                rewritten = clean_report_markdown(str(turn.get("content") or ""))
                await tracker.append_trace(
                    "optimizer",
                    make_llm_trace(
                        f"第 {round_i} 轮改写",
                        system=opt_system,
                        prompt=opt_prompt,
                        reply=rewritten,
                        reasoning=turn.get("reasoning") if isinstance(turn.get("reasoning"), str) else None,
                    ),
                )
                revision_ok, revision_reason = validate_report_revision(
                    final_md,
                    rewritten,
                    required_headings=_outline_headings(outline),
                    min_retention_ratio=0.8,
                )
                if not revision_ok:
                    await tracker.append_trace(
                        "optimizer",
                        make_action_trace(
                            "本轮改写未提交",
                            summary=f"{revision_reason}，原稿保持不变",
                        ),
                    )
                    await tracker.emit_event(
                        {
                            "type": "scorecard",
                            "scorecard": scorecard,
                            "round": round_i,
                            "status": "rejected",
                            "message": revision_reason,
                        }
                    )
                    break
                candidate_md, candidate_ledger = await _run_citer(
                    rewritten,
                    evidence,
                    citer_id,
                    required_headings=_outline_headings(outline),
                    tracker=tracker,
                    agent_id="optimizer",
                )
                candidate_md = clean_report_markdown(candidate_md) or rewritten
                accepted, reason = validate_report_revision(
                    final_md,
                    candidate_md,
                    required_headings=_outline_headings(outline),
                    min_retention_ratio=0.8,
                )
                if not accepted:
                    await tracker.append_trace(
                        "optimizer",
                        make_action_trace(
                            "本轮改写未提交",
                            summary=f"{reason}，原稿保持不变",
                        ),
                    )
                    await tracker.emit_event(
                        {
                            "type": "scorecard",
                            "scorecard": scorecard,
                            "round": round_i,
                            "status": "rejected",
                            "message": reason,
                        }
                    )
                    break
                candidate_drafts = split_markdown_by_outline(
                    candidate_md,
                    list(outline.get("sections") or []),
                    previous=chapter_drafts,
                )
                candidate_scorecard = await _run_reviewer(
                    goal,
                    candidate_md,
                    outline,
                    review_id,
                    skill_body_override=stage_skill_body("reviewer", review_id, 1200),
                    tracker=tracker,
                    agent_id="optimizer",
                )
                scorecards.append(candidate_scorecard)
                new_total = float(candidate_scorecard.get("total") or 0)
                await tracker.emit_event(
                    {
                        "type": "scorecard",
                        "scorecard": candidate_scorecard,
                        "round": round_i,
                    }
                )
                if new_total <= best_score:
                    await tracker.emit_event(
                        {
                            "type": "scorecard",
                            "scorecard": best_scorecard,
                            "round": round_i,
                            "status": "rollback",
                            "message": "本轮未提分，原稿保持不变",
                        }
                    )
                    break
                # Only now is the candidate allowed to replace the persisted
                # preview. Validation and re-scoring happen off-screen first.
                final_md = candidate_md
                citation_ledger = candidate_ledger
                chapter_drafts = candidate_drafts
                scorecard = candidate_scorecard
                best_score = new_total
                best_md = final_md
                best_scorecard = scorecard
                outline = await _emit_chapters_and_outline(
                    tracker,
                    outline=outline,
                    chapter_drafts=chapter_drafts,
                    preview_markdown=final_md,
                )
                delta = (new_total - prev_total) / max(prev_total, 1.0)
                if delta < 0.05:
                    stagnant += 1
                else:
                    stagnant = 0
                prev_total = new_total
                if stagnant >= 2:
                    stop_after_commit = True
            except Exception as exc:
                await tracker.clear_llm_pending("optimizer", f"第 {round_i} 轮改写")
                await tracker.emit_event({"type": "scorecard", "message": str(exc), "round": round_i, "status": "error"})
                break
            await gate(
                "optimizer",
                outline={**outline, "chapter_drafts": chapter_drafts},
                chapter_drafts=chapter_drafts,
                preview_markdown=final_md,
                cited_md=final_md,
                citation_ledger=citation_ledger,
                scorecard=scorecard,
                scorecards=scorecards,
                evidence=evidence,
                knowledge_cards=knowledge_cards,
                fact_pack=fact_pack,
            )
            if stop_after_commit:
                break

        final_md = best_md
        scorecard = best_scorecard
        final_md = clean_report_markdown(final_md) or final_md
        chapter_drafts = split_markdown_by_outline(final_md, list(outline.get("sections") or []), previous=chapter_drafts)
        outline = {**outline, "chapter_drafts": chapter_drafts}
        await tracker.complete(
            "optimizer",
            f"终分 {scorecard.get('total', 0)} · {len(scorecards)} 轮评分",
            **skill_bindings["optimizer"],
        )
    else:
        final_md = clean_report_markdown(cited_md or str(cp.get("preview_markdown") or ""))
        if not scorecard:
            scorecard = {"total": 0, "verdict": "revise", "fallback": True}

    final_md = normalize_report_references(
        clean_report_markdown(final_md) or final_md,
        citation_ledger,
    )
    chapter_drafts = split_markdown_by_outline(final_md, list(outline.get("sections") or []), previous=chapter_drafts)
    outline = {**outline, "chapter_drafts": chapter_drafts}

    report_title = str(outline.get("title") or goal)
    vault_rel_md = _write_report_to_vault(report_title, final_md, suffix=".md")
    vault_rel_docx = _write_report_docx(report_title, final_md)
    total_chars = count_chinese_chars(final_md)
    evidence_weak = len(evidence.items) < 3
    chars_met = total_chars >= int(outline.get("min_chars") or 0)
    completion_note = "completed"
    if evidence_weak and not chars_met:
        completion_note = "completed_with_gaps"
    elif evidence_weak:
        completion_note = "completed_weak_evidence"
    elif not chars_met:
        completion_note = "completed_under_length"

    return {
        "run_mode": "report",
        "phase": "completed",
        "completion_note": completion_note,
        "step_confirm": step_confirm,
        "outline_confirm_required": outline_confirm_required,
        "outline": {**outline, "chapter_drafts": chapter_drafts},
        "chapter_drafts": chapter_drafts,
        "citation_ledger": citation_ledger,
        "evidence": evidence.to_dict(),
        "evidence_weak": evidence_weak,
        "evidence_count": len(evidence.items),
        "knowledge_cards": knowledge_cards,
        "fact_pack": fact_pack,
        "scorecard": scorecard,
        "scorecards": scorecards,
        "review": {
            "score": scorecard.get("total"),
            "scorecard": scorecard,
            "verdict": scorecard.get("verdict"),
            "pipeline_adapted": True,
        },
        "preview_markdown": final_md,
        "chinese_chars": total_chars,
        "min_chars": outline.get("min_chars"),
        "chars_met": chars_met,
        "vault_path": vault_rel_md,
        "vault_path_docx": vault_rel_docx,
        "agent_progress": tracker.snapshot(),
        "web_search_mode": mode,
        "web_search_enabled": mode != "off",
        "skills": skills_payload,
    }


def _skills_payload(*ids: str) -> dict[str, Any]:
    keys = ["intake", "researcher", "architect", "writer", "citer", "review", "optimizer"]
    out: dict[str, Any] = {}
    for k, sid in zip(keys, ids, strict=False):
        sk = get_skill(sid)
        out[k] = sid
        out[f"{k}_valid"] = bool(sk and sk.valid)
    return out


def assemble_report_markdown(goal: str, outline: dict[str, Any], drafts: list[dict[str, Any]]) -> str:
    title = _normalize_report_title(
        str(outline.get("title") or ""),
        goal,
        str(outline.get("report_type_label") or ""),
    )
    lines = [f"# {title}", ""]
    if outline.get("strategic_main_line"):
        lines += [f"> 战略主线：{outline['strategic_main_line']}", ""]
    for d in drafts:
        heading = str(d.get("heading") or "").strip() or "未命名章节"
        body = clean_report_markdown(str(d.get("body") or ""))
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body)
        lines.append("")
        lines.append(f"<!-- 本章中文字数：{count_chinese_chars(body)} -->")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# Internal compatibility alias. New persistence code should use the public
# name so the exact preview assembly rules stay shared across layers.
_assemble_markdown = assemble_report_markdown


def _heading_key(heading: str) -> str:
    h = str(heading or "").strip()
    h = re.sub(r"^#{1,6}\s*", "", h)
    return re.sub(r"\s+", "", h)


def _outline_headings(outline: dict[str, Any]) -> list[str]:
    return [str(section.get("heading") or "").strip() for section in (outline.get("sections") or []) if isinstance(section, dict) and str(section.get("heading") or "").strip()]


def split_markdown_by_outline(
    md: str,
    sections: list[dict[str, Any]],
    *,
    previous: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Split a full report markdown into chapter_drafts aligned to outline sections."""
    text = clean_report_markdown(md or "")
    prev_by_id = {str(d.get("id")): d for d in (previous or []) if isinstance(d, dict) and d.get("id") is not None}
    heading_re = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
    all_matches = list(heading_re.finditer(text))

    def body_for_heading(heading: str) -> str:
        key = _heading_key(heading)
        if not key:
            return ""
        for i, m in enumerate(all_matches):
            mk = _heading_key(m.group(2))
            if mk == "参考文献":
                continue
            if mk == key or (key and key in mk) or (mk and mk in key):
                start = m.end()
                end = all_matches[i + 1].start() if i + 1 < len(all_matches) else len(text)
                return text[start:end].strip()
        return ""

    drafts: list[dict[str, Any]] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        sid = str(sec.get("id") or "")
        heading = str(sec.get("heading") or "")
        budget = int(sec.get("word_budget") or 0) or None
        body = body_for_heading(heading)
        if not body and sid in prev_by_id:
            body = clean_report_markdown(str(prev_by_id[sid].get("body") or ""))
        drafts.append(
            {
                "id": sid or _heading_key(heading) or f"sec-{len(drafts) + 1}",
                "heading": heading or f"第 {len(drafts) + 1} 章",
                "body": body,
                "chinese_chars": count_chinese_chars(body),
                "word_budget": budget or prev_by_id.get(sid, {}).get("word_budget"),
                "evidence_weak": bool(prev_by_id.get(sid, {}).get("evidence_weak")),
            }
        )
    return drafts


async def _emit_chapters_and_outline(
    tracker: ReportProgressTracker,
    *,
    outline: dict[str, Any],
    chapter_drafts: list[dict[str, Any]],
    preview_markdown: str,
) -> dict[str, Any]:
    synced = {**outline, "chapter_drafts": chapter_drafts}
    await tracker.emit_event({"type": "outline", "outline": synced})
    for idx, draft in enumerate(chapter_drafts):
        await tracker.emit_event(
            {
                "type": "chapter",
                "chapter": draft,
                "chapter_index": idx,
                "preview_markdown": preview_markdown,
            }
        )
    return synced


_REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?"
    r"(?:证据引用|参考文献|参考来源|引用来源|参考资料)"
    r"(?:\*\*)?\s*[:：]?\s*$",
    re.IGNORECASE,
)
_H2_HEADING_RE = re.compile(r"^\s*##(?!#)\s+\S+")
_SEPARATOR_RE = re.compile(r"^\s*(?:---+|___+|\*\*\*+)\s*$")


def strip_report_reference_sections(markdown: str) -> str:
    """Remove chapter-local/global reference lists before rebuilding one canonical footer."""
    lines = (markdown or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _REFERENCE_HEADING_RE.match(lines[i]):
            out.append(lines[i])
            i += 1
            continue

        while out and not out[-1].strip():
            out.pop()
        if out and _SEPARATOR_RE.match(out[-1]):
            out.pop()

        i += 1
        # 单章引用位于章末：跳到下一章 H2；全文参考文献则自然跳到 EOF。
        while i < len(lines) and not _H2_HEADING_RE.match(lines[i]):
            i += 1
        while out and not out[-1].strip():
            out.pop()
        out.extend(["", ""])
    return clean_report_markdown("\n".join(out))


def normalize_report_references(
    markdown: str,
    ledger: list[dict[str, Any]] | None,
) -> str:
    """Guarantee exactly one reference list at the very end of the full report."""
    body = strip_report_reference_sections(markdown).rstrip()
    if not ledger:
        return body
    refs = ["", "## 参考文献", ""]
    for i, entry in enumerate(ledger, start=1):
        n = int(entry.get("n") or i)
        label = re.sub(r"^【\d+】\s*", "", str(entry.get("label") or entry.get("id") or f"来源 {n}"))
        url = str(entry.get("url") or "")
        if url:
            refs.append(f"【{n}】{label}。检索自：[查看原文]({url})")
        else:
            source_type = str(entry.get("source_type") or "知识库")
            source_id = str(entry.get("id") or "")
            suffix = f"（{source_id}）" if source_id else ""
            refs.append(f"【{n}】{label}。来源：{source_type}{suffix}")
        refs.append("")
    return clean_report_markdown(body + "\n" + "\n".join(refs))


async def _run_citer(
    markdown: str,
    evidence: EvidencePack,
    citer_id: str,
    *,
    required_headings: list[str] | None = None,
    tracker: ReportProgressTracker | None = None,
    agent_id: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    ledger: list[dict[str, Any]] = []
    for i, item in enumerate(evidence.items, start=1):
        src_type = "知识库" if item.type == "kb" else ("问数" if item.type == "data" else "联网")
        entry = {
            "n": i,
            "id": item.id,
            "label": f"【{i}】{item.source}",
            "source_type": src_type,
            "url": item.source if item.type == "web" and url_allowed(item.source) else "",
            "excerpt": item.excerpt[:200],
        }
        ledger.append(entry)

    # Writer 只负责正文；统一移除误生成的章末列表，并在全文末尾重建一次引用。
    markdown = normalize_report_references(markdown, ledger)

    # Light LLM polish of citations when key available; fallback to ledger-only
    try:
        hint = _load_skill_body(citer_id, 800)
        citer_system = append_org_identity("你是引用审核专员，输出完整 Markdown。")
        citer_prompt = (
            "请审核下列报告的引用：确保数字有来源；文末参考文献保留。"
            "只允许微调【N】标注，不得删除、缩写或重排正文，不得把正文改成引用审核表、"
            "问题清单或审核意见。必须原样保留全部章节标题和叙事段落，并输出完整报告。\n"
            "不要改写战略结论，不要编造新来源。\n\n"
            f"Skill：{hint}\n\n## 证据台账\n{json.dumps(ledger[:30], ensure_ascii=False)}"
            f"\n\n## 正文\n{markdown[:48000]}"
        )
        if tracker and agent_id:
            await tracker.mark_llm_pending(agent_id, "引用审核润色")
        turn = await chat_turn(
            citer_prompt,
            system=citer_system,
            max_tokens=8192,
            temperature=0.2,
        )
        polished = clean_report_markdown(str(turn.get("content") or ""))
        if tracker and agent_id:
            await tracker.append_trace(
                agent_id,
                make_llm_trace(
                    "引用审核润色",
                    system=citer_system,
                    prompt=citer_prompt,
                    reply=polished,
                    reasoning=turn.get("reasoning") if isinstance(turn.get("reasoning"), str) else None,
                ),
            )
        accepted, reason = validate_report_revision(
            markdown,
            polished,
            required_headings=required_headings,
            min_retention_ratio=0.9,
        )
        if accepted:
            markdown = polished
        elif polished and tracker and agent_id:
            await tracker.append_trace(
                agent_id,
                make_action_trace(
                    "引用审核输出未采用",
                    summary=f"{reason}，已保留写作稿",
                ),
            )
    except Exception as exc:
        if tracker and agent_id:
            await tracker.clear_llm_pending(agent_id, "引用审核润色")
            await tracker.append_trace(
                agent_id,
                make_action_trace("引用审核 LLM 跳过", summary=str(exc)[:200]),
            )
    return normalize_report_references(clean_report_markdown(markdown) or markdown, ledger), ledger


async def _run_reviewer(
    goal: str,
    markdown: str,
    outline: dict[str, Any],
    review_id: str,
    *,
    skill_body_override: str | None = None,
    tracker: ReportProgressTracker | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Seven-dimension scorecard; LLM preferred, heuristic fallback."""
    dims = [
        ("战略主线", 0.15),
        ("结构", 0.15),
        ("逻辑闭环", 0.20),
        ("证据支撑", 0.20),
        ("管网适配", 0.10),
        ("可操作性", 0.10),
        ("语言规范", 0.10),
    ]
    try:
        hint = skill_body_override or _load_skill_body(review_id, 1200)
        review_system = append_org_identity("你是战略报告评审官，只输出 JSON。管网适配维度按国家管网集团语境评审。")
        review_prompt = (
            f"请按七维评分审查战略报告，严格输出 JSON（不要Markdown围栏）：\n"
            f'{{"dimensions":[{{"name":"战略主线","score":1-5,"reason":"..."}}],'
            f'"total":0-100,"verdict":"pass|conditional|revise",'
            f'"issues":[{{"severity":"P0|P1|P2|P3","chapter":"...","detail":"..."}}],'
            f'"weak_dimensions":["..."]}}\n'
            f"权重：战略主线15% 结构15% 逻辑闭环20% 证据20% 管网适配10% 可操作性10% 语言10%。\n"
            f"目标：{goal}\n类型：{outline.get('report_type_label')}\n字数底线：{outline.get('min_chars')}\n"
            f"Skill：{hint}\n\n## 正文\n{markdown[:22000]}"
        )
        if tracker and agent_id:
            await tracker.mark_llm_pending(agent_id, "七维评分")
        turn = await chat_turn(
            review_prompt,
            system=review_system,
            max_tokens=2048,
            temperature=0.2,
        )
        raw = str(turn.get("content") or "")
        if tracker and agent_id:
            await tracker.append_trace(
                agent_id,
                make_llm_trace(
                    "七维评分",
                    system=review_system,
                    prompt=review_prompt,
                    reply=raw,
                    reasoning=turn.get("reasoning") if isinstance(turn.get("reasoning"), str) else None,
                ),
            )
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        if "total" not in data and data.get("dimensions"):
            score_map = {d["name"]: float(d.get("score") or 0) for d in data["dimensions"]}
            total = 0.0
            for name, w in dims:
                total += (score_map.get(name) or 3) / 5.0 * 100 * w
            data["total"] = round(total, 1)
        data.setdefault("weak_dimensions", [])
        data.setdefault("issues", [])
        data.setdefault("verdict", "revise")
        return data
    except Exception as exc:
        if tracker and agent_id:
            await tracker.clear_llm_pending(agent_id, "七维评分")
            await tracker.append_trace(
                agent_id,
                make_action_trace("评分改用启发式回退", summary=str(exc)[:200]),
            )
        chars = count_chinese_chars(markdown)
        min_c = int(outline.get("min_chars") or 20000)
        pipe_kw = ("管网", "油气", "储运", "一张网", "公平开放")
        hit = sum(1 for k in pipe_kw if k in markdown)
        base = 55
        if chars >= min_c:
            base += 15
        elif chars >= min_c * 0.5:
            base += 8
        base += min(10, hit * 2)
        if "【" in markdown or "参考文献" in markdown:
            base += 5
        dims_out = [{"name": n, "score": 3, "reason": "规则回退评分"} for n, _ in dims]
        return {
            "dimensions": dims_out,
            "total": min(92, base),
            "verdict": "conditional" if base >= 70 else "revise",
            "issues": [],
            "weak_dimensions": ["证据支撑"] if "待补充" in markdown else [],
            "fallback": True,
        }


def _write_report_to_vault(goal: str, content: str, *, suffix: str) -> str:
    vault_root = resolve_vault_path()
    out_dir = resolve_report_output_dir()
    try:
        rel_dir = out_dir.relative_to(vault_root)
    except ValueError:
        rel_dir = Path("reports")
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", goal)[:40].strip("-") or "report"
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    rel = str(rel_dir / f"{slug}-{ts}{suffix}").replace("\\", "/")
    write_vault_file(rel, content)
    return rel


def _write_report_docx(goal: str, markdown: str) -> str:
    docx_bytes = markdown_to_docx(markdown, title=goal)
    vault_root = resolve_vault_path()
    out_dir = resolve_report_output_dir()
    try:
        rel_dir = out_dir.relative_to(vault_root)
    except ValueError:
        rel_dir = Path("reports")
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", goal)[:40].strip("-") or "report"
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    rel = str(rel_dir / f"{slug}-{ts}.docx").replace("\\", "/")
    write_vault_file(rel, docx_bytes)
    return rel


def control_result(phase: str, snapshot: dict[str, Any], reason: str = "") -> dict[str, Any]:
    outline = dict(snapshot.get("outline") or {})
    drafts = list(snapshot.get("chapter_drafts") or outline.get("chapter_drafts") or [])
    if drafts:
        outline = {**outline, "chapter_drafts": drafts}
    preview = str(snapshot.get("preview_markdown") or snapshot.get("cited_md") or "")
    return {
        "run_mode": "report",
        "phase": phase,
        "message": reason or ("已暂停" if phase == "paused" else "已终止"),
        "resume_from": snapshot.get("resume_from"),
        "resume_chapter_index": snapshot.get("resume_chapter_index") or 0,
        "outline": outline,
        "chapter_drafts": drafts,
        "evidence": snapshot.get("evidence") or {"items": []},
        "knowledge_cards": snapshot.get("knowledge_cards") or [],
        "fact_pack": snapshot.get("fact_pack") or {},
        "preview_markdown": preview,
        "cited_md": snapshot.get("cited_md") or "",
        "citation_ledger": snapshot.get("citation_ledger") or [],
        "scorecard": snapshot.get("scorecard"),
        "scorecards": snapshot.get("scorecards") or [],
        "agent_progress": snapshot.get("agent_progress") or [],
        "skills": snapshot.get("skills") or {},
        "checkpoint": True,
    }


async def iter_report_pipeline_events(
    goal: str,
    *,
    step_confirm: bool = False,
    outline_confirm_required: bool = False,
    confirmed: bool = False,
    outline_override: dict[str, Any] | None = None,
    scope_paths: list[str] | None = None,
    report_type: str | None = None,
    audience: str | None = None,
    skill_profile: dict[str, Any] | None = None,
    web_search_mode: str | WebSearchMode | None = None,
    resume_chapter_index: int | None = None,
    confirmed_chapter: bool = False,
    task_id: str | None = None,
    resume_from: str | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    import asyncio

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_progress(step: dict[str, Any]) -> None:
        await queue.put({"type": "progress", "step": step})
        # An unbounded Queue.put may complete without suspending. Explicitly
        # yield so the SSE consumer can paint the new phase before the runner
        # starts any CPU/file-heavy research work.
        await asyncio.sleep(0)

    async def on_event(event: dict[str, Any]) -> None:
        await queue.put(event)
        await asyncio.sleep(0)

    async def runner() -> None:
        if task_id:
            reset_to_run(task_id)
        try:
            result = await run_report_pipeline(
                goal,
                step_confirm=step_confirm,
                outline_confirm_required=outline_confirm_required,
                confirmed=confirmed,
                on_progress=on_progress,
                on_event=on_event,
                outline_override=outline_override,
                scope_paths=scope_paths,
                report_type=report_type,
                audience=audience,
                skill_profile=skill_profile,
                web_search_mode=web_search_mode,
                resume_chapter_index=resume_chapter_index,
                confirmed_chapter=confirmed_chapter,
                task_id=task_id,
                resume_from=resume_from,
                checkpoint=checkpoint,
            )
            await queue.put(
                {
                    "type": "result",
                    "agent_progress": result.get("agent_progress"),
                    "result": result,
                }
            )
        except PipelinePaused as exc:
            result = control_result("paused", exc.snapshot, exc.reason)
            await queue.put({"type": "result", "agent_progress": result.get("agent_progress"), "result": result})
        except PipelineCancelled as exc:
            result = control_result("cancelled", exc.snapshot, exc.reason)
            await queue.put({"type": "result", "agent_progress": result.get("agent_progress"), "result": result})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            if task_id:
                clear_control(task_id)
            await queue.put(None)

    task = asyncio.create_task(runner())
    progress_cache = [{"id": aid, "label": label, "status": "pending", "message": ""} for aid, label in REPORT_AGENTS]
    if isinstance((checkpoint or {}).get("agent_progress"), list):
        for prev in checkpoint["agent_progress"]:  # type: ignore[index]
            pid = prev.get("id")
            idx = next((i for i, a in enumerate(REPORT_AGENTS) if a[0] == pid), None)
            if idx is not None:
                progress_cache[idx] = prev
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            if event.get("type") == "progress":
                step = event["step"]
                idx = next((i for i, a in enumerate(REPORT_AGENTS) if a[0] == step["id"]), None)
                if idx is not None:
                    progress_cache[idx] = step
                event = {**event, "agent_progress": list(progress_cache)}
            yield event
    finally:
        await task
