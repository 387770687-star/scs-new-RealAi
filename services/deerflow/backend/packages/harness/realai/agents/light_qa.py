"""P1a lightweight Q&A orchestration (structured output)."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from realai.agents.data import (
    build_entity_profile,
    needs_data_query,
    run_structured_data_query,
)
from realai.agents.retrieve import search_vault
from realai.agents.web_search_skill import run_web_search_pipeline
from realai.config import (
    VisionMode,
    WebSearchMode,
    load_settings,
    normalize_vision_mode,
    normalize_web_search_mode,
    resolve_request_vision_mode,
    resolve_request_web_search_mode,
)
from realai.evidence.types import EvidencePack, detect_conflicts
from realai.skills.runtime import require_enabled_skill, resolve_qa_skill

logger = logging.getLogger(__name__)

_THINKING_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_SECTION_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,40}_[\u4e00-\u9fffA-Za-z0-9]{2,40}")

Intent = Literal["ask", "data", "research"]
ProgressCallback = Callable[[list[str]], Awaitable[None] | None]

_PIPELINE_INTRO_SKILL_ID = "pipeline-asset-intro"
_INTRO_HINT_RE = re.compile(r"介绍|概况|基本情况|是什么|详述|说明一下|讲讲|什么情况|简介")
_ASSET_HINT_RE = re.compile(r"管段|管线|管道|站场|压气站|分输|清管站|阀室|联络站|末站")


def _wants_pipeline_asset_intro(query: str) -> bool:
    """Detect Q&A that should follow the pipeline/station intro Skill template."""
    q = (query or "").strip()
    if not q:
        return False
    if _SECTION_RE.search(q):
        return True
    if _ASSET_HINT_RE.search(q) and _INTRO_HINT_RE.search(q):
        return True
    if _ASSET_HINT_RE.search(q) and len(q) <= 40:
        # short queries like「泰安压气站」often mean introduce the asset
        return True
    return False


def _load_pipeline_intro_skill() -> tuple[str, dict[str, Any]] | None:
    try:
        skill = require_enabled_skill(_PIPELINE_INTRO_SKILL_ID)
        return skill.body.strip(), {
            "id": skill.id,
            "name": skill.name,
            "version": skill.version,
            "trigger": "auto_rule",
            "source": skill.source,
        }
    except Exception:
        logger.debug("pipeline intro skill load skipped", exc_info=True)
        return None


async def _emit_progress(
    on_progress: ProgressCallback | None,
    trajectory: list[str],
) -> None:
    if not on_progress:
        return
    maybe = on_progress(list(trajectory))
    if maybe is not None and hasattr(maybe, "__await__"):
        await maybe  # type: ignore[misc]


async def run_light_qa(
    query: str,
    *,
    web_search_enabled: bool | None = None,
    web_search_mode: str | WebSearchMode | None = None,
    vision_mode: str | VisionMode | None = None,
    image_paths: list[str] | None = None,
    intent: Intent = "ask",
    scope_paths: list[str] | None = None,
    session_id: str | None = None,
    skill_id: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    resolved_skill = resolve_qa_skill(query, selected_skill_id=skill_id)
    query = resolved_skill.query
    active_skill_body = resolved_skill.body
    active_skill = resolved_skill.skill
    mode = resolve_request_web_search_mode(web_search_mode, web_search_enabled)
    web_allowed = mode != "off"
    vmode = resolve_request_vision_mode(vision_mode, fallback_settings=True)
    trajectory: list[str] = ["接收问题"]
    await _emit_progress(on_progress, trajectory)
    if active_skill:
        trigger_label = "斜杠指定" if active_skill.get("trigger") == "slash" else "手动选择"
        trajectory.append(f"Skill：{active_skill.get('name') or active_skill.get('id')}（{trigger_label}）")
        await _emit_progress(on_progress, trajectory)

    from realai.agents.session_context import format_session_history

    history_text, history_turns = format_session_history(session_id)
    if history_turns:
        trajectory.append(f"已加载本会话 {history_turns} 轮上下文")
        await _emit_progress(on_progress, trajectory)

    if intent == "data":
        trajectory.append("意图：侧重问数")
    elif intent == "research":
        trajectory.append("意图：侧重检索")
    else:
        trajectory.append("意图：轻量问答")
    await _emit_progress(on_progress, trajectory)

    # Column-filter queries: stop for user confirm (before entity / NL2SQL).
    # Pure station/section entity asks do not parse into conditions → skip.
    if intent != "research":
        try:
            from realai.data.filter_parse import parse_filter_draft

            filter_draft = parse_filter_draft(query, scope_paths=scope_paths)
        except Exception:
            logger.debug("filter parse skipped", exc_info=True)
            filter_draft = None
        if filter_draft and filter_draft.get("conditions"):
            trajectory.append("意图：条件筛选")
            await _emit_progress(on_progress, trajectory)
            trajectory.append("等待确认筛选条件")
            await _emit_progress(on_progress, trajectory)
            return {
                "answer": "请先确认上方筛选条件，再点击「确认查询」。",
                "conclusion": "请确认筛选条件",
                "tables": [],
                "chart_spec": None,
                "entity_profile": None,
                "awaiting_confirm": True,
                "confirm_kind": "filter",
                "filter_draft": filter_draft,
                "data_query": {
                    "mode": "filter_await_confirm",
                    "candidates": 0,
                    "hits": 0,
                    "match_terms": [],
                    "sql": None,
                },
                "trajectory": trajectory,
                "evidence": {"items": []},
                "run_mode": "light",
                "intent": intent,
                "web_search_enabled": web_allowed,
                "web_search_mode": mode,
                "vision_mode": vmode,
                "scope_paths": scope_paths or [],
                "skill_used": active_skill,
            }

    force_data = intent == "data" or needs_data_query(query) or bool(_SECTION_RE.search(query))
    boost_paths: list[str] = []
    try:
        from realai.vault.wiki.entity_pages import list_entity_titles

        titles = list_entity_titles()
        for sn in _SECTION_RE.findall(query):
            if sn in titles:
                boost_paths.append(titles[sn])
        # fuzzy title contains
        for t, p in titles.items():
            if t in query and p not in boost_paths:
                boost_paths.append(p)
    except Exception:
        logger.debug("entity boost skipped", exc_info=True)

    kb = EvidencePack()
    data = EvidencePack()
    data_result = None
    entity_profile: dict[str, Any] | None = None
    if intent != "data":
        trajectory.append("知识检索")
        await _emit_progress(on_progress, trajectory)
        kb = search_vault(
            query,
            boost_paths=boost_paths or None,
            scope_paths=scope_paths,
        )
        try:
            from realai.shared_retrieve import metrics_evidence_for_query

            metric_ev = metrics_evidence_for_query(query, limit=3)
            if metric_ev.items:
                kb = EvidencePack(items=[*metric_ev.items, *kb.items])
                trajectory.append(f"口径：命中 {len(metric_ev.items)} 条")
        except Exception:
            logger.debug("metrics inject skipped", exc_info=True)
        if scope_paths:
            kb = _filter_by_scope(kb, scope_paths)
    if intent != "research":
        trajectory.append("结构化问数" + ("（强制）" if force_data else ""))
        await _emit_progress(on_progress, trajectory)
        data_result = run_structured_data_query(query, limit=8, force=force_data, scope_paths=scope_paths)
        data = data_result.pack
        if scope_paths:
            data = _filter_by_scope(data, scope_paths)
            data_result.pack = data
            data_result.hits = len(data.items)
        mode_label = {
            "exact": "精确问数",
            "entity_match": "实体命中",
            "nl2sql": "SQL问数",
            "multi_table": "多表关联",
            "preview": "表预览",
            "external": "外接库",
            "none": "无结果",
        }.get(data_result.mode, data_result.mode)
        trajectory.append(f"问数：{mode_label}（候选表 {data_result.candidates} → 命中 {data_result.hits}）")
        await _emit_progress(on_progress, trajectory)
        if data_result.mode == "entity_match" and data_result.entity_name:
            entity_profile = build_entity_profile(
                name=data_result.entity_name,
                entity_type=data_result.entity_type,
                data=data,
                match_terms=data_result.match_terms,
            )
            if entity_profile:
                trajectory.append(f"站场名片：{data_result.entity_name}")
                await _emit_progress(on_progress, trajectory)
        if data_result.sql:
            trajectory.append("已生成只读 SQL")
            await _emit_progress(on_progress, trajectory)

    # graph one-hop if evidence thin
    if len(kb.items) + len(data.items) < 2:
        try:
            from realai.vault.wiki.graph_index import neighbor_titles

            seeds = _SECTION_RE.findall(query) or [query.strip()[:40]]
            neigh: list[str] = []
            for s in seeds:
                neigh.extend(neighbor_titles(s, limit=6))
            if neigh:
                trajectory.append("图谱一跳扩展")
                await _emit_progress(on_progress, trajectory)
                extra_q = " ".join(neigh[:6])
                more = search_vault(extra_q, limit=3, scope_paths=scope_paths)
                kb.items.extend(more.items)
        except Exception:
            logger.debug("graph hop skipped", exc_info=True)

    local_pack = EvidencePack(items=[*kb.items, *data.items])
    web = EvidencePack()
    web_err: str | None = None
    effective_web_mode = mode
    if mode == "auto" and data_result is not None and data_result.mode in {"exact", "nl2sql"} and data.items:
        effective_web_mode = "off"
        trajectory.append("联网：结构化数据已精确命中，自动跳过")
        await _emit_progress(on_progress, trajectory)
    web, web_traj, web_err = await run_web_search_pipeline(
        query,
        effective_web_mode,
        local_pack=local_pack,
        history_text=history_text,
        limit=3,
        apply_whitelist=False,
    )
    for line in web_traj:
        if line:
            trajectory.append(line)
    await _emit_progress(on_progress, trajectory)

    from realai.agents.vision import analyze_images_on_demand

    viz_pack, viz_traj = await analyze_images_on_demand(
        query,
        mode=vmode,
        image_paths=image_paths,
        limit=2,
    )
    for line in viz_traj:
        if line:
            trajectory.append(line)
    await _emit_progress(on_progress, trajectory)

    items = detect_conflicts([*kb.items, *data.items, *viz_pack.items, *web.items])
    pack = EvidencePack(items=items)
    trajectory.append(f"证据 {len(pack.items)} 条")
    await _emit_progress(on_progress, trajectory)

    tables = _tables_from_data(data)
    chart_spec = (
        _chart_from_tables(
            query,
            tables,
            data_mode=data_result.mode if data_result else None,
        )
        if tables
        else None
    )

    if not active_skill_body and _wants_pipeline_asset_intro(query):
        intro_skill = _load_pipeline_intro_skill()
        if intro_skill:
            active_skill_body, active_skill = intro_skill
            trajectory.append(f"Skill：{active_skill.get('name') or '管段站点介绍'}（规则匹配）")
            await _emit_progress(on_progress, trajectory)

    answer = await _synthesize_answer(
        query,
        pack,
        web_search_enabled=web_allowed,
        web_search_mode=mode,
        vision_mode=vmode,
        intent=intent,
        skill_markdown=active_skill_body,
        skill_id=str(active_skill.get("id") or "") if active_skill else None,
        entity_profile=entity_profile,
        history_text=history_text,
    )
    conclusion = _first_sentence(answer)
    trajectory.append("输出结论")
    await _emit_progress(on_progress, trajectory)

    result = {
        "answer": answer,
        "conclusion": conclusion,
        "tables": tables,
        "chart_spec": chart_spec,
        "entity_profile": entity_profile,
        "data_query": {
            "mode": data_result.mode if data_result else "none",
            "candidates": data_result.candidates if data_result else 0,
            "hits": data_result.hits if data_result else 0,
            "match_terms": data_result.match_terms if data_result else [],
            "sql": data_result.sql if data_result else None,
            "error": data_result.error if data_result else None,
        },
        "trajectory": trajectory,
        "evidence": pack.to_dict(),
        "run_mode": "light",
        "intent": intent,
        "web_search_enabled": web_allowed,
        "web_search_mode": mode,
        "vision_mode": vmode,
        "scope_paths": scope_paths or [],
        "skill_used": active_skill,
    }
    if web_err:
        result["web_search_error"] = web_err
    return result


def _filter_by_scope(pack: EvidencePack, scope_paths: list[str]) -> EvidencePack:
    """Keep evidence under selected logical types or legacy Vault paths."""
    from realai.vault.scope import matches_scope

    kept = []
    for it in pack.items:
        source_paths = [str(value).replace("\\", "/").strip("/") for value in (it.meta.get("source_paths") or it.meta.get("tables_used") or []) if str(value).strip() and not str(value).startswith("sql:")]
        if source_paths:
            if all(matches_scope(path, scope_paths) for path in source_paths):
                kept.append(it)
            continue
        path = str(it.meta.get("path") or it.source or "").replace("\\", "/")
        if matches_scope(path, scope_paths):
            kept.append(it)
    return EvidencePack(items=kept)


def _tables_from_data(data: EvidencePack) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for it in data.items:
        cols = list(it.meta.get("columns") or [])
        meta_rows = it.meta.get("rows")
        rows: list[dict[str, Any]] = []
        if isinstance(meta_rows, list) and meta_rows:
            # Prefer structured rows from DuckDB (reliable for UI tables).
            for r in meta_rows:
                if not isinstance(r, dict):
                    continue
                if cols:
                    rows.append({c: "" if r.get(c) is None else str(r.get(c)) for c in cols})
                else:
                    rows.append({str(k): "" if v is None else str(v) for k, v in r.items()})
                    if not cols:
                        cols = list(rows[-1].keys())
        else:
            # Legacy fallback: parse excerpt "a | b; c | d"
            rows_raw = [part.strip() for part in (it.excerpt or "").split(";") if part.strip()]
            for r in rows_raw:
                cells = [c.strip() for c in r.split("|")]
                if cols and len(cells) == len(cols):
                    rows.append(dict(zip(cols, cells)))
                elif cols:
                    # Column count mismatch → one-cell dump under first column
                    padded = (cells + [""] * len(cols))[: len(cols)]
                    rows.append(dict(zip(cols, padded)))
                else:
                    rows.append({"value": r})
                    cols = ["value"]
        # Allow empty rows for filter "no hit" card
        title = str(it.meta.get("title") or it.source)
        tables.append(
            {
                "id": it.id,
                "title": title,
                "columns": cols or ["value"],
                "rows": rows,
                "evidence_id": it.id,
            }
        )
    return tables


async def run_light_qa_filter_confirm(
    query: str,
    filter_draft: dict[str, Any],
    *,
    web_search_enabled: bool | None = None,
    web_search_mode: str | WebSearchMode | None = None,
    intent: Intent = "ask",
    scope_paths: list[str] | None = None,
    skill_id: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute confirmed column filters and synthesize answer."""
    from realai.data.filter_execute import execute_filter
    from realai.data.filter_parse import validate_filter_draft

    resolved_skill = resolve_qa_skill(query, selected_skill_id=skill_id)
    query = resolved_skill.query
    active_skill = resolved_skill.skill
    mode = resolve_request_web_search_mode(web_search_mode, web_search_enabled)
    web_allowed = mode != "off"
    trajectory: list[str] = ["已确认筛选条件"]
    await _emit_progress(on_progress, trajectory)
    if active_skill:
        trigger_label = "斜杠指定" if active_skill.get("trigger") == "slash" else "手动选择"
        trajectory.append(f"Skill：{active_skill.get('name') or active_skill.get('id')}（{trigger_label}）")
        await _emit_progress(on_progress, trajectory)

    draft = validate_filter_draft(filter_draft)
    trajectory.append("跨表筛选")
    await _emit_progress(on_progress, trajectory)

    pack_data, stats = execute_filter(draft, scope_paths=scope_paths)
    trajectory.append(f"跨表筛选（候选表 {stats.get('candidates', 0)} → 命中 {stats.get('hits', 0)} 行）")
    await _emit_progress(on_progress, trajectory)

    tables = _tables_from_data(pack_data)
    chart_spec = _chart_from_tables(query, tables, data_mode="filter_union") if tables else None
    pack = EvidencePack(items=list(pack_data.items))
    # Filter confirm is strong local intent — do not web-search.
    if mode == "off":
        trajectory.append("联网跳过（已关闭）")
    else:
        trajectory.append("联网：智能跳过（条件筛选已完成）")
    await _emit_progress(on_progress, trajectory)
    trajectory.append(f"证据 {len(pack.items)} 条")
    await _emit_progress(on_progress, trajectory)

    hint = draft.get("title_hint") or ""
    answer = await _synthesize_answer(
        query,
        pack,
        web_search_enabled=web_allowed,
        web_search_mode=mode,
        intent=intent,
        skill_markdown=resolved_skill.body,
        skill_id=str(active_skill.get("id") or "") if active_skill else None,
        entity_profile=None,
        filter_hint=hint,
    )
    if not pack.items or not (pack.items[0].meta.get("rows")):
        answer = f"按条件「{hint}」未找到符合的管段记录。可放宽长度/压力等条件后重新提问。" if hint else "未找到符合条件的记录。"
    conclusion = _first_sentence(answer)
    trajectory.append("输出结论")
    await _emit_progress(on_progress, trajectory)

    return {
        "answer": answer,
        "conclusion": conclusion,
        "tables": tables,
        "chart_spec": chart_spec,
        "entity_profile": None,
        "awaiting_confirm": False,
        "confirm_kind": "filter",
        "filter_draft": draft,
        "data_query": {
            "mode": "filter_union",
            "candidates": stats.get("candidates", 0),
            "hits": stats.get("hits", 0),
            "match_terms": [],
            "sql": stats.get("sql"),
        },
        "trajectory": trajectory,
        "evidence": pack.to_dict(),
        "run_mode": "light",
        "intent": intent,
        "web_search_enabled": web_allowed,
        "web_search_mode": mode,
        "scope_paths": scope_paths or [],
        "skill_used": active_skill,
    }


def _parse_chart_number(raw: Any) -> float | None:
    """Return a float only when the cell is clearly numeric; else None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        v = float(raw)
        return v if v == v else None  # NaN check
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null", "nan", "-"):
        return None
    # pure number or with thousand separators / trailing unit letters stripped lightly
    cleaned = s.replace(",", "").replace("，", "")
    cleaned = re.sub(r"[%％]$", "", cleaned)
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


_CHART_INTENT_RE = re.compile(r"(图表|可视化|折线图|柱状图|饼图|画图|作图|趋势|变化|走势|对比|比较|排名|分布|占比|构成)")
_TECHNICAL_COLUMN_RE = re.compile(
    r"(^id$|_id$|^id_|userid|user_id|^smuserid$|code$|_code$|^code_|编号|序号|排序|order|timestamp|时间戳|^is_)",
    re.IGNORECASE,
)
_CATEGORY_HINT_RE = re.compile(
    r"(名称|地区|省份|城市|项目|类别|类型|管段|管线|站|name|region|province|city|category|type)",
    re.IGNORECASE,
)
_MEASURE_HINTS = {
    "长度": ("长度", "length"),
    "成本": ("成本", "cost"),
    "费用": ("费用", "expense", "fee"),
    "数量": ("数量", "count", "amount"),
    "压力": ("压力", "pressure"),
    "输量": ("输量", "flow"),
    "人口": ("人口", "population"),
    "价格": ("价格", "price"),
    "金额": ("金额", "amount"),
}


def _chart_from_tables(
    query: str,
    tables: list[dict[str, Any]],
    *,
    data_mode: str | None = None,
) -> dict[str, Any] | None:
    """Build a chart only for explicit visual/comparison intent and sound fields."""
    if not tables:
        return None
    if data_mode == "preview" or not _CHART_INTENT_RE.search(query or ""):
        return None
    t0 = tables[0]
    rows = t0.get("rows") or []
    cols = list(t0.get("columns") or [])
    if not rows or len(cols) < 2:
        return None

    # Wide-year tables are already a time series in columns.
    year_columns = [column for column in cols if re.fullmatch(r"(?:19|20)\d{2}年?", str(column).strip()) and _parse_chart_number(rows[0].get(column)) is not None]
    if len(rows) == 1 and len(year_columns) >= 3:
        dimension_candidates: list[tuple[int, str]] = []
        for column in cols:
            value = str(rows[0].get(column, "")).strip()
            if column in year_columns or _TECHNICAL_COLUMN_RE.search(column) or not value:
                continue
            score = 0
            if value in query:
                score += 30
            if re.search(r"(省份|城市|名称|项目|name|province|city)", column, re.IGNORECASE):
                score += 10
            dimension_candidates.append((score, column))
        dimension_candidates.sort(reverse=True)
        dimension = dimension_candidates[0][1] if dimension_candidates else None
        series_name = str(rows[0].get(dimension)).strip() if dimension else str(t0.get("title") or "预测值")
        return {
            "type": "line",
            "title": t0.get("title") or "趋势",
            "categories": year_columns,
            "series": [
                {
                    "name": series_name,
                    "data": [float(_parse_chart_number(rows[0].get(column)) or 0) for column in year_columns],
                }
            ],
            "evidence_id": t0.get("evidence_id"),
        }

    if len(rows) < 2:
        return None

    category_candidates: list[tuple[int, str, list[str]]] = []
    for column in cols:
        if _TECHNICAL_COLUMN_RE.search(column):
            continue
        labels = [str(row.get(column, "") or "").strip() for row in rows]
        nonempty = [label for label in labels if label]
        distinct = len(set(nonempty))
        if len(nonempty) < 2 or distinct < 2:
            continue
        numeric_count = sum(_parse_chart_number(row.get(column)) is not None for row in rows)
        score = distinct * 3
        if _CATEGORY_HINT_RE.search(column):
            score += 20
        if numeric_count >= max(2, (len(rows) + 1) // 2):
            score -= 12
        category_candidates.append((score, column, labels))
    if not category_candidates:
        return None
    category_candidates.sort(reverse=True)

    best: tuple[int, str, str, list[str], list[float]] | None = None
    for vcol in cols:
        if _TECHNICAL_COLUMN_RE.search(vcol):
            continue
        parsed = [_parse_chart_number(r.get(vcol)) for r in rows]
        numeric_idx = [i for i, v in enumerate(parsed) if v is not None]
        if len(numeric_idx) < 2:
            continue
        # need majority of rows numeric for this column
        if len(numeric_idx) < max(2, (len(rows) + 1) // 2):
            continue
        nonzero = sum(1 for i in numeric_idx if parsed[i] != 0)
        if nonzero < 1:
            continue
        values = [parsed[i] for i in numeric_idx]
        if len({float(value) for value in values if value is not None}) < 2:
            continue
        category = next(
            (candidate for candidate in category_candidates if candidate[1] != vcol),
            None,
        )
        if category is None:
            continue
        category_score, cat_col, labels = category
        cats = [label or f"#{i + 1}" for i, label in enumerate(labels)]
        vals = [float(parsed[i]) if parsed[i] is not None else 0.0 for i in range(len(rows))]
        score = len(numeric_idx) * 10 + nonzero + category_score
        vcol_lower = vcol.lower()
        if vcol_lower in (query or "").lower():
            score += 30
        for query_token, column_hints in _MEASURE_HINTS.items():
            if query_token in query and any(hint in vcol_lower for hint in column_hints):
                score += 24
        if best is None or score > best[0]:
            best = (score, cat_col, vcol, cats, vals)

    if not best:
        return None
    _, _cat, vcol, cats, vals = best
    looks_temporal = all(re.fullmatch(r"(?:19|20)\d{2}年?", category.strip()) for category in cats)
    return {
        "type": "line" if looks_temporal and re.search(r"(趋势|变化|走势|折线)", query) else "bar",
        "title": t0.get("title") or "问数结果",
        "categories": cats,
        "series": [{"name": vcol, "data": vals}],
        "evidence_id": t0.get("evidence_id"),
    }


def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    for sep in ("。", "！", "？", "\n"):
        i = t.find(sep)
        if i > 0:
            return t[: i + (0 if sep == "\n" else 1)].strip()
    return t[:160]


async def _synthesize_answer(
    query: str,
    pack: EvidencePack,
    *,
    web_search_enabled: bool,
    intent: Intent,
    skill_markdown: str | None = None,
    skill_id: str | None = None,
    entity_profile: dict[str, Any] | None = None,
    filter_hint: str | None = None,
    web_search_mode: str | WebSearchMode | None = None,
    vision_mode: str | VisionMode | None = None,
    history_text: str = "",
) -> str:
    from realai.llm import chat_turn, has_api_key

    settings = load_settings()
    role = "fast" if intent == "data" else "primary"
    mode = normalize_web_search_mode(
        str(web_search_mode) if web_search_mode else None,
        enabled=web_search_enabled if web_search_mode is None else None,
    )
    vmode = normalize_vision_mode(str(vision_mode) if vision_mode else None)

    evidence_text = _format_evidence_for_prompt(pack)
    if not has_api_key(settings):
        return _fallback_answer(query, pack, mode != "off")

    system = (
        "你是 RealAi 轻量问答助手。只能依据【证据包】与【实体名片】回答；引用证据时在句末标注证据 ID（如 kb:…、data:…、viz:…、web:…）。"
        "证据不足时明确说明，不要编造数字。"
        "用户为国家管网集团工作人员；「本集团/我司/我们」指国家管网集团，勿猜测其他归属。"
        "若提供【会话上文】，请结合上下文理解指代（如「它」「那条线」），保持同一对话连贯。"
    )
    temperature = 0.7
    max_tokens = 2048
    if skill_markdown:
        system += f"\n\n【本轮明确启用的 Skill】\n请遵守下面的业务方法、输出结构和风格要求；若与证据约束、权限或系统安全规则冲突，以系统规则为准。\n\n{skill_markdown[:6000]}"
        temperature = 0.35
        max_tokens = 3072
    else:
        system += "先给一句话核心结论，再给要点。"
    if entity_profile:
        system += " 若提供了实体名片，请先对齐名片中的管线/管段统计，再展开明细要点。"
    if filter_hint:
        system += " 若提供了筛选条件，请先复述条件，再根据结果表归纳命中管段；无命中时明确说明。"
    if intent == "data" and not skill_markdown:
        system += " 优先给出数值、口径与表格要点。单位只能来自证据中的单位字段或明确列名；证据未提供单位时只写“单位未注明”，禁止根据常识推测单位。"
    elif intent == "research" and not skill_markdown:
        system += " 优先引用政策/报告原文要点。"
    if any(i.type == "viz" for i in pack.items):
        system += " 证据包含图片依据（viz:）：必须优先用图意与图中可读数字回答；看不清或未列出的数字写 ==[待补充]==，禁止臆造。引用时标注 viz: 证据 ID。"
    elif vmode == "off":
        system += " 用户已关闭视觉，勿声称已读图。"
    if mode == "off":
        system += " 用户已关闭联网，禁止使用 web: 证据。"
    elif not any(i.type == "web" for i in pack.items):
        system += " 本次未进行联网检索或无联网结果，禁止编造 web: 证据。"
    profile_text = ""
    if entity_profile:
        bullets = entity_profile.get("summary_bullets") or []
        profile_text = f"\n\n【实体名片】{entity_profile.get('name')}\n" + "\n".join(f"- {b}" for b in bullets) + ("\n相关：" + "、".join(entity_profile.get("related") or []) if entity_profile.get("related") else "")
    if filter_hint:
        profile_text += f"\n\n【已确认筛选条件】{filter_hint}"
    history_block = ""
    if history_text.strip():
        history_block = f"\n\n【会话上文】\n{history_text.strip()}\n"
    user = f"{history_block}问题：{query}{profile_text}\n\n【证据包】\n{evidence_text or '（无匹配证据）'}"

    purpose = f"light_ask:{intent}" + (f":skill:{skill_id}" if skill_id else "")
    try:
        turn = await chat_turn(
            user,
            system=system,
            role=role,
            temperature=temperature,
            max_tokens=max_tokens,
            purpose=purpose,
            settings=settings,
        )
        return _strip_thinking_tags(turn.content)
    except Exception:
        logger.exception("light QA LLM call failed")
        return _fallback_answer(query, pack, mode != "off")


def _strip_thinking_tags(text: str) -> str:
    return _THINKING_TAG_RE.sub("", text).strip()


def _format_evidence_for_prompt(pack: EvidencePack) -> str:
    lines = []
    for it in pack.items[:12]:
        loc = it.meta.get("locator") or ""
        context = []
        if it.meta.get("title"):
            context.append(f"标题={it.meta['title']}")
        if it.meta.get("sheet_name"):
            context.append(f"工作表={it.meta['sheet_name']}")
        if it.meta.get("unit"):
            context.append(f"单位={it.meta['unit']}")
        if it.meta.get("columns"):
            context.append("列=" + "、".join(str(value) for value in it.meta["columns"][:12]))
        context_text = f"\n  {'；'.join(context)}" if context else ""
        lines.append(f"- [{it.id}] ({it.type}) {it.source} {loc}{context_text}\n  {it.excerpt}")
    return "\n".join(lines)


def _fallback_answer(query: str, pack: EvidencePack, web_search_enabled: bool) -> str:
    if not pack.items:
        tip = "未开启联网。" if not web_search_enabled else "可尝试换关键词。"
        return f"证据不足，无法可靠回答「{query}」。{tip}"
    parts = [f"基于 {len(pack.items)} 条证据的要点："]
    for it in pack.items[:5]:
        parts.append(f"- {it.excerpt[:120]}（{it.id}）")
    return "\n".join(parts)
