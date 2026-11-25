"""Writing-task intelligent gap fill before outline generation."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from realai.config import load_settings
from realai.meta.writing import get_task, merge_meta, update_task
from realai.report.llm_client import chat_turn
from realai.report.progress import make_action_trace, make_llm_trace
from realai.report.strategic_types import REPORT_TYPES, normalize_report_type
from realai.skills.registry import get_skill, list_skill_package_files

INTAKE_EVIDENCE_LIMIT = 3
INTAKE_MAX_TOKENS = 400
INTAKE_TIMEOUT_SECONDS = 12.0
_QUESTION_FIELDS = {"objective", "time_scope", "scope", "audience", "hard_constraints"}
_LOCAL_QUESTION_FIELDS = {"time_scope", "scope"}

_REGION_KEYS = (
    "全国",
    "华北",
    "东北",
    "华东",
    "华中",
    "华南",
    "西南",
    "西北",
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "内蒙古",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "广西",
    "海南",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
    "台湾",
)
_BUSINESS_KEYS = (
    "天然气",
    "油气",
    "原油",
    "成品油",
    "管网",
    "管道",
    "管线",
    "站场",
    "储气",
    "调度",
    "输量",
    "运输",
    "新能源",
    "氢能",
    "电力",
    "市场",
    "客户",
    "投资",
    "工程建设",
    "科技创新",
    "数字化",
    "人工智能",
    "安全生产",
    "运营",
    "成本",
)
_AUDIENCE_KEYS = (
    "董事会",
    "董事长",
    "集团管理层",
    "公司管理层",
    "领导班子",
    "党委会",
    "政府部门",
    "监管部门",
    "投资者",
    "业务部门",
)
_CONSTRAINT_KEYS = (
    "必须",
    "不得",
    "禁止",
    "应当",
    "要求",
    "字数",
    "不少于",
    "不低于",
    "不超过",
    "格式",
    "文风",
    "引用",
    "口径",
    "截止",
    "完成时间",
)


class _StructuredQuestion(BaseModel):
    """Strict model output row; malformed output falls back deterministically."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=24)
    field: str = Field(min_length=1, max_length=32)
    prompt: str = Field(min_length=2, max_length=240)
    why: str = Field(default="", max_length=160)


class _StructuredQuestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[_StructuredQuestion] = Field(default_factory=list, max_length=2)


def _intake_skill_id() -> str:
    settings = load_settings()
    return str((settings.get("report") or {}).get("intakeSkillId") or "strategic-planning-intake")


def _skill_binding(skill_id: str) -> dict[str, Any]:
    sk = get_skill(skill_id)
    refs: list[str] = []
    scripts: list[str] = []
    for f in list_skill_package_files(skill_id):
        p = str(f.get("path") or f) if isinstance(f, dict) else str(f)
        low = p.lower()
        if "reference" in low or p.startswith("references/"):
            refs.append(p)
        elif low.endswith((".py", ".js", ".sh", ".ps1")):
            scripts.append(p)
    return {
        "skill_id": skill_id,
        "skill_name": (sk.name if sk else "") or skill_id,
        "skill_valid": sk is not None and bool(getattr(sk, "name", None)),
        "references": refs[:12],
        "scripts": scripts[:8],
        "tools": ["本地字段提取", "相关资料检索", "快速模型补缺"],
    }


def empty_intake() -> dict[str, Any]:
    return {
        "status": "pending",
        "mode": "smart_gap_fill",
        "local_context": {},
        "missing_fields": [],
        "evidence_brief": [],
        "questions": [],
        "user_provided_facts": [],
        "diagnostics": {"attempts": [], "latest": {}},
        "skill_id": _intake_skill_id(),
    }


def get_intake(task: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return intake blob; None means legacy task (no intake required)."""
    if not task:
        return None
    meta = task.get("meta") or {}
    if "intake" not in meta:
        return None
    raw = meta.get("intake")
    return raw if isinstance(raw, dict) else empty_intake()


def intake_is_done(task: dict[str, Any] | None) -> bool:
    """Legacy (no intake key) or status=done → ready to run six-step."""
    intake = get_intake(task)
    if intake is None:
        return True
    return str(intake.get("status") or "") == "done"


def intake_blocks_run(task: dict[str, Any] | None) -> str | None:
    """Return error message if run should be blocked, else None."""
    if intake_is_done(task):
        return None
    intake = get_intake(task) or {}
    st = str(intake.get("status") or "pending")
    if st == "await_answers":
        return "请先完成智能补缺（可跳过个别题），或直接跳过后生成大纲"
    if st == "running":
        return "正在识别关键信息缺口，请稍候"
    return "请先完成智能补缺后再运行报告流水线"


def _prioritized_retrieve(goal: str, scope_paths: list[str] | None, limit: int = 10):
    from realai.shared_retrieve import prioritized_retrieve_quota

    pack = prioritized_retrieve_quota(goal, scope_paths)
    return pack.items[: max(0, limit)]


def _unique_matches(text: str, values: tuple[str, ...]) -> list[str]:
    return [value for value in values if value in text]


def _extract_local_context(goal: str, audience: str) -> dict[str, Any]:
    """Extract stable planning context locally before spending a model call."""
    text = re.sub(r"\s+", " ", str(goal or "")).strip()
    audience_text = re.sub(r"\s+", " ", str(audience or "")).strip()

    time_scope: list[str] = []
    time_patterns = (
        r"20\d{2}\s*(?:年)?\s*(?:[-—至到]\s*20\d{2}\s*年?)?",
        r"[“\"']?(?:十[四五六]五)[”\"']?",
        r"未来\s*[一二三四五六七八九十\d]+\s*年",
    )
    for pattern in time_patterns:
        for match in re.findall(pattern, text):
            normalized = str(match).strip("“”\"'")
            if normalized and normalized not in time_scope:
                time_scope.append(normalized)

    audiences: list[str] = []
    if audience_text:
        audiences.append(audience_text)
    for key in _AUDIENCE_KEYS:
        if key in text and key not in audiences:
            audiences.append(key)
    for match in re.findall(
        r"(?:面向|提交给|供)([^，。；\n]{2,20}?)(?:阅读|审议|决策|使用|，|。|；)",
        text,
    ):
        value = str(match).strip()
        if value and value not in audiences:
            audiences.append(value)

    constraints: list[str] = []
    for sentence in re.split(r"(?<=[。！？；])|\n+", text):
        value = sentence.strip()
        if value and any(key in value for key in _CONSTRAINT_KEYS):
            constraints.append(value[:300])
        if len(constraints) >= 6:
            break

    return {
        "time_scope": time_scope,
        "regions": _unique_matches(text, _REGION_KEYS),
        "business_scope": _unique_matches(text, _BUSINESS_KEYS),
        "goals": [text] if text else [],
        "audience": audiences,
        "hard_constraints": constraints,
    }


def _missing_critical_fields(goal: str, context: dict[str, Any]) -> list[str]:
    """Only block on fields that materially change a planning outline."""
    text = str(goal or "").strip()
    missing: list[str] = []
    if len(text) < 6:
        missing.append("objective")
    planning_task = bool(re.search(r"规划|计划|行动方案|发展目标|战略", text))
    if planning_task and not context.get("time_scope"):
        missing.append("time_scope")
    if not context.get("regions") and not context.get("business_scope"):
        missing.append("scope")
    return missing[:2]


def _brief_from_items(items: list[Any]) -> list[dict[str, Any]]:
    brief: list[dict[str, Any]] = []
    for it in items:
        brief.append(
            {
                "id": it.id,
                "source": it.source,
                "title": str((it.meta or {}).get("title") or it.source),
                "excerpt": (it.excerpt or "")[:240],
            }
        )
    return brief


def _load_skill_body(skill_id: str, max_len: int = 2800) -> str:
    sk = get_skill(skill_id)
    if not sk or not sk.enabled:
        return ""
    body = getattr(sk, "body", None) or ""
    text = str(body).strip()
    return text[:max_len]


def _json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("模型未返回内容")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as first_error:
        start = text.find("{")
        if start < 0:
            raise ValueError(f"未找到 JSON 对象：{first_error}") from first_error
        try:
            data, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as second_error:
            raise ValueError(f"JSON 解析失败：{second_error}") from second_error
    if not isinstance(data, dict):
        raise ValueError("结构化输出顶层必须是对象")
    return data


def _parse_question_payload(
    raw: str,
    *,
    allowed_fields: list[str],
) -> tuple[list[dict[str, Any]], str | None]:
    """Validate a strict two-question schema and keep only requested gaps."""
    try:
        payload = _StructuredQuestions.model_validate(_json_object(raw))
    except (ValueError, ValidationError) as exc:
        return [], str(exc)

    allowed = {field for field in allowed_fields if field in _QUESTION_FIELDS}
    out: list[dict[str, Any]] = []
    for row in payload.questions:
        if row.field not in allowed:
            continue
        out.append(
            {
                "id": row.id,
                "field": row.field,
                "prompt": row.prompt,
                "why": row.why,
                "answer": "",
                "skipped": False,
            }
        )
    return out[:2], None


def _fallback_questions_for_fields(
    goal: str,
    audience: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    aud = audience or "战略/规划读者"
    templates: dict[str, tuple[str, str]] = {
        "objective": (
            f"请用一句话说明「{goal[:40] or '本报告'}」最需要解决的问题和预期产出。",
            "明确报告目标，避免大纲泛化",
        ),
        "time_scope": (
            f"本报告「{goal[:40]}」的规划期或目标年份是什么？",
            "时间范围决定检索与章节口径",
        ),
        "scope": (
            "请限定本报告的地理区域和核心业务范围；如有明确排除项也请一并说明。",
            "限定边界，避免资料检索和写作跑偏",
        ),
        "audience": (
            f"面向「{aud}」时，最希望报告支持哪一项决策？",
            "突出决策主线",
        ),
        "hard_constraints": (
            "是否有必须遵守的政策、投资、工期、口径或格式约束？",
            "将硬约束前置，减少后续返工",
        ),
    }
    questions: list[dict[str, Any]] = []
    for field in fields[:2]:
        prompt, why = templates.get(field, templates["objective"])
        questions.append(
            {
                "id": f"q{len(questions) + 1}",
                "field": field,
                "prompt": prompt,
                "why": why,
                "answer": "",
                "skipped": False,
            }
        )
    return questions


def _can_build_questions_locally(fields: list[str]) -> bool:
    """Standard boundary gaps do not need a network/model round trip."""

    return bool(fields) and set(fields).issubset(_LOCAL_QUESTION_FIELDS)


def _diagnostic_traces(intake: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = intake.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return []
    latest = diagnostics.get("latest")
    if not isinstance(latest, dict):
        return []
    traces = latest.get("traces")
    return [row for row in (traces or []) if isinstance(row, dict)]


def _append_diagnostics(
    intake: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    previous = intake.get("diagnostics")
    attempts = list(previous.get("attempts") or []) if isinstance(previous, dict) else []
    attempts.append(attempt)
    return {"attempts": attempts[-10:], "latest": attempt}


def _intake_progress_step(
    *,
    status: str,
    message: str,
    binding: dict[str, Any],
    traces: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    step = {
        "id": "intake",
        "label": "智能补缺",
        "status": status,
        "message": message,
        "updated_at": None,
        **binding,
    }
    if traces:
        step["traces"] = traces
    return step


async def start_intake(task_id: str) -> dict[str, Any]:
    """Extract locally, skip when sufficient, otherwise ask at most two gaps."""
    task = get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    skill_id = _intake_skill_id()
    binding = _skill_binding(skill_id)

    intake = get_intake(task)
    if intake is None:
        intake = empty_intake()
    if str(intake.get("status") or "") == "done":
        return get_task(task_id)  # type: ignore[return-value]

    started_at = time.time()
    timer = time.perf_counter()
    goal = str(task.get("goal") or "")
    audience = str(task.get("audience") or "")
    scope_paths = list(task.get("scope_paths") or [])
    local_context = _extract_local_context(goal, audience)
    missing_fields = _missing_critical_fields(goal, local_context)

    intake["status"] = "running"
    intake["mode"] = "smart_gap_fill"
    intake["skill_id"] = skill_id
    intake["local_context"] = local_context
    intake["missing_fields"] = missing_fields
    merge_meta(task_id, {"intake": intake})
    update_task(
        task_id,
        status="await_intake",
        progress_json=[
            _intake_progress_step(
                status="running",
                message="正在识别时间、区域、业务范围、目标与硬约束…",
                binding=binding,
            )
        ],
        error=None,
    )

    if not missing_fields:
        traces = [
            make_action_trace(
                "本地字段提取",
                summary="关键信息充分，无需模型补问",
                detail=json.dumps(local_context, ensure_ascii=False, indent=2),
            )
        ]
        attempt = {
            "started_at": started_at,
            "finished_at": time.time(),
            "duration_ms": round((time.perf_counter() - timer) * 1000),
            "model_called": False,
            "model_role": "fast",
            "max_tokens": INTAKE_MAX_TOKENS,
            "timeout_seconds": INTAKE_TIMEOUT_SECONDS,
            "retrieved_count": 0,
            "missing_fields": [],
            "parse_error": None,
            "model_error": None,
            "traces": traces,
        }
        intake["status"] = "done"
        intake["mode"] = "auto_skipped"
        intake["questions"] = []
        intake["evidence_brief"] = []
        intake["diagnostics"] = _append_diagnostics(intake, attempt)
        merge_meta(task_id, {"intake": intake})
        update_task(
            task_id,
            status="draft",
            progress_json=[
                _intake_progress_step(
                    status="completed",
                    message="信息充分，已自动跳过补缺，可直接生成大纲",
                    binding=binding,
                    traces=traces,
                )
            ],
            error=None,
        )
        return get_task(task_id)  # type: ignore[return-value]

    # Time and scope are closed, schema-known gaps. Asking the fast model to
    # paraphrase these two questions added 10–12 seconds without changing the
    # information collected, so return deterministic, query-aware questions
    # immediately. The model path remains available for genuinely ambiguous
    # objective gaps.
    if _can_build_questions_locally(missing_fields):
        questions = _fallback_questions_for_fields(goal, audience, missing_fields)
        traces = [
            make_action_trace(
                "本地字段提取",
                summary=f"发现 {len(missing_fields)} 个关键缺口：{', '.join(missing_fields)}",
                detail=json.dumps(local_context, ensure_ascii=False, indent=2),
            ),
            make_action_trace(
                "生成结构化补缺题",
                summary="标准时间/范围缺口已本地生成，无需等待模型或检索",
            ),
        ]
        attempt = {
            "started_at": started_at,
            "finished_at": time.time(),
            "duration_ms": round((time.perf_counter() - timer) * 1000),
            "model_called": False,
            "model_role": "fast",
            "max_tokens": 0,
            "timeout_seconds": 0,
            "retrieved_count": 0,
            "missing_fields": missing_fields,
            "parse_error": None,
            "model_error": None,
            "traces": traces,
        }
        intake["status"] = "await_answers"
        intake["mode"] = "local_questions"
        intake["local_context"] = local_context
        intake["missing_fields"] = missing_fields
        intake["evidence_brief"] = []
        intake["questions"] = questions
        intake.setdefault("user_provided_facts", [])
        intake["diagnostics"] = _append_diagnostics(intake, attempt)
        merge_meta(task_id, {"intake": intake})
        update_task(
            task_id,
            status="await_intake",
            progress_json=[
                _intake_progress_step(
                    status="running",
                    message=f"已即时识别 {len(questions)} 项关键缺口，等待确认",
                    binding=binding,
                    traces=traces,
                )
            ],
            error=None,
        )
        return get_task(task_id)  # type: ignore[return-value]

    rt = normalize_report_type(task.get("report_type"))
    rt_label = REPORT_TYPES.get(rt, {}).get("label") or rt

    items = _prioritized_retrieve(goal, scope_paths, limit=INTAKE_EVIDENCE_LIMIT)
    brief = _brief_from_items(items)
    traces: list[dict[str, Any]] = [
        make_action_trace(
            "本地字段提取",
            summary=f"发现 {len(missing_fields)} 个关键缺口：{', '.join(missing_fields)}",
            detail=json.dumps(local_context, ensure_ascii=False, indent=2),
        ),
        make_action_trace(
            "相关资料检索",
            summary=f"保留相关性排序前 {len(brief)} 条（仅本地，未联网）",
            detail="\n".join(f"- [{b['id']}] {b.get('title') or b.get('source')}: {(b.get('excerpt') or '')[:100]}" for b in brief),
        ),
    ]

    skill_body = _load_skill_body(skill_id, max_len=1200)
    brief_text = "\n".join(f"- [{b['id']}] {b.get('title') or b.get('source')}: {b.get('excerpt')}" for b in brief) or "（知识库暂无命中）"
    from realai.org_identity import ORG_IDENTITY_BLOCK, append_org_identity

    system = append_org_identity("你是战略报告智能补缺助手。不要展开思考，不要解释。输出必须严格符合给定 JSON Schema，最多两个问题。禁止生成关于用户所属集团/公司归属的澄清题。")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["questions"],
        "properties": {
            "questions": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "field", "prompt", "why"],
                    "properties": {
                        "id": {"type": "string"},
                        "field": {"enum": missing_fields},
                        "prompt": {"type": "string"},
                        "why": {"type": "string"},
                    },
                },
            }
        },
    }
    prompt = (
        f"{ORG_IDENTITY_BLOCK}\n\n"
        f"报告目标：{goal}\n"
        f"目标读者：{audience or '（未填）'}\n"
        f"报告类型：{rt_label}\n\n"
        f"本地已提取字段：\n{json.dumps(local_context, ensure_ascii=False)}\n"
        f"仅补充这些关键缺口：{json.dumps(missing_fields, ensure_ascii=False)}\n\n"
        f"相关资料（最多三条）：\n{brief_text}\n\n"
        f"Skill 要求：\n{skill_body}\n\n"
        f"JSON Schema：\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        "每个缺口最多一题，总计 1～2 题。不要询问已经从原文提取出的信息。"
    )
    questions: list[dict[str, Any]] = []
    reply = ""
    parse_error: str | None = None
    model_error: str | None = None
    try:
        turn = await asyncio.wait_for(
            chat_turn(
                prompt,
                system=system,
                role="fast",
                max_tokens=INTAKE_MAX_TOKENS,
                temperature=0,
                timeout=INTAKE_TIMEOUT_SECONDS,
                purpose="report_intake",
                reasoning_max_chars=0,
                allow_fallback=False,
            ),
            timeout=INTAKE_TIMEOUT_SECONDS + 1,
        )
        reply = str(turn.get("content") or "")
        questions, parse_error = _parse_question_payload(
            reply,
            allowed_fields=missing_fields,
        )
        if not questions and parse_error is None:
            parse_error = "结构化输出未包含本轮缺口对应的问题"
        traces.append(
            make_llm_trace(
                "快速模型补缺",
                system=system,
                prompt=prompt,
                reply=reply,
                reasoning=None,
            )
        )
    except Exception as exc:
        model_error = str(exc)
        traces.append(make_action_trace("快速模型补缺", summary=f"模型失败，使用结构化兜底题：{exc}"))

    if not questions:
        questions = _fallback_questions_for_fields(goal, audience, missing_fields)
        if parse_error:
            traces.append(
                make_action_trace(
                    "结构化输出校验",
                    summary="模型输出未通过 Schema，已切换确定性兜底",
                    detail=parse_error,
                )
            )

    attempt = {
        "started_at": started_at,
        "finished_at": time.time(),
        "duration_ms": round((time.perf_counter() - timer) * 1000),
        "model_called": True,
        "model_role": "fast",
        "max_tokens": INTAKE_MAX_TOKENS,
        "timeout_seconds": INTAKE_TIMEOUT_SECONDS,
        "retrieved_count": len(brief),
        "missing_fields": missing_fields,
        "parse_error": parse_error,
        "model_error": model_error,
        "traces": traces,
    }

    # A user can click “skip” while the bounded model call is still in flight.
    current = get_task(task_id)
    current_intake = get_intake(current)
    if current_intake and str(current_intake.get("status") or "") == "done":
        return current  # type: ignore[return-value]

    intake["status"] = "await_answers"
    intake["mode"] = "questions"
    intake["local_context"] = local_context
    intake["missing_fields"] = missing_fields
    intake["evidence_brief"] = brief
    intake["questions"] = questions
    intake.setdefault("user_provided_facts", [])
    intake["skill_id"] = skill_id
    intake["diagnostics"] = _append_diagnostics(intake, attempt)
    merge_meta(task_id, {"intake": intake})
    update_task(
        task_id,
        status="await_intake",
        progress_json=[
            _intake_progress_step(
                status="running",
                message=f"仅缺少 {len(questions)} 项关键信息（已答 0）",
                binding=binding,
                traces=traces,
            )
        ],
        error=None,
    )
    return get_task(task_id)  # type: ignore[return-value]


def save_intake_answers(
    task_id: str,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge answer/skipped flags onto questions."""
    task = get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    intake = get_intake(task)
    if intake is None:
        raise ValueError("旧任务无需智能补缺")
    if str(intake.get("status") or "") == "done":
        raise ValueError("智能补缺已完成，不可再改答案")
    by_id = {str(a.get("id")): a for a in answers if isinstance(a, dict) and a.get("id")}
    questions = list(intake.get("questions") or [])
    for q in questions:
        if not isinstance(q, dict):
            continue
        patch = by_id.get(str(q.get("id")))
        if not patch:
            continue
        if "skipped" in patch:
            q["skipped"] = bool(patch["skipped"])
        if "answer" in patch:
            q["answer"] = str(patch.get("answer") or "")
            if q["answer"].strip():
                q["skipped"] = False
    intake["questions"] = questions
    intake["status"] = "await_answers"
    merge_meta(task_id, {"intake": intake})

    skill_id = str(intake.get("skill_id") or _intake_skill_id())
    binding = _skill_binding(skill_id)
    answered = sum(1 for q in questions if isinstance(q, dict) and (str(q.get("answer") or "").strip() or q.get("skipped")))
    update_task(
        task_id,
        status="await_intake",
        progress_json=[
            _intake_progress_step(
                status="running",
                message=f"待补充 {len(questions)} 项（已处理 {answered}）",
                binding=binding,
                traces=_diagnostic_traces(intake),
            )
        ],
    )
    return get_task(task_id)  # type: ignore[return-value]


def skip_intake(task_id: str) -> dict[str, Any]:
    """Skip remaining questions without discarding diagnostics."""
    task = get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    intake = get_intake(task)
    if intake is None:
        return task
    if str(intake.get("status") or "") == "done":
        return task

    questions = list(intake.get("questions") or [])
    for question in questions:
        if not isinstance(question, dict):
            continue
        if not str(question.get("answer") or "").strip():
            question["skipped"] = True
    intake["questions"] = questions
    intake["status"] = "done"
    intake["mode"] = "user_skipped"
    intake["skipped_at"] = time.time()
    merge_meta(task_id, {"intake": intake})

    binding = _skill_binding(str(intake.get("skill_id") or _intake_skill_id()))
    update_task(
        task_id,
        status="draft",
        progress_json=[
            _intake_progress_step(
                status="skipped",
                message="用户已跳过智能补缺，直接进入大纲生成",
                binding=binding,
                traces=_diagnostic_traces(intake),
            )
        ],
        error=None,
    )
    return get_task(task_id)  # type: ignore[return-value]


def confirm_intake(task_id: str) -> dict[str, Any]:
    """Build user_provided_facts and mark intake done; unlock six-step run."""
    task = get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    intake = get_intake(task)
    if intake is None:
        return task
    if str(intake.get("status") or "") == "done":
        return task

    facts: list[dict[str, Any]] = []
    questions = list(intake.get("questions") or [])
    answered = 0
    skipped = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "")
        ans = str(q.get("answer") or "").strip()
        if q.get("skipped") and not ans:
            skipped += 1
            continue
        if not ans:
            # treat unanswered as skipped on confirm
            skipped += 1
            q["skipped"] = True
            continue
        answered += 1
        prompt = str(q.get("prompt") or "")
        facts.append(
            {
                "id": f"user_intake:{qid}",
                "statement": f"问：{prompt}\n答：{ans}",
                "question": prompt,
                "answer": ans,
                "source": "user_intake",
            }
        )

    skill_id = str(intake.get("skill_id") or _intake_skill_id())
    binding = _skill_binding(skill_id)
    intake["questions"] = questions
    intake["user_provided_facts"] = facts
    intake["status"] = "done"
    merge_meta(task_id, {"intake": intake})
    update_task(
        task_id,
        status="draft",
        progress_json=[
            _intake_progress_step(
                status="completed",
                message=f"已答 {answered} · 跳过 {skipped} · 用户事实 {len(facts)} 条",
                binding=binding,
                traces=_diagnostic_traces(intake),
            )
        ],
        error=None,
    )
    return get_task(task_id)  # type: ignore[return-value]


def user_provided_facts_from_task(task: dict[str, Any] | None) -> list[dict[str, Any]]:
    intake = get_intake(task)
    if not intake:
        return []
    facts = intake.get("user_provided_facts") or []
    return [f for f in facts if isinstance(f, dict)]
