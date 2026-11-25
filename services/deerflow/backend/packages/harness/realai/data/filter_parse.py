"""Detect and parse structured column filters from natural language."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from realai.data.column_semantics import (
    COLUMN_DEFS,
    OP_ALIASES,
    all_aliases_sorted,
    field_label,
    field_unit,
    is_numeric_field,
    normalize_op,
    parse_number_with_unit,
    resolve_alias_to_key,
)

logger = logging.getLogger(__name__)

_COMPARE_HINT = re.compile(
    r"大于等于|小于等于|不少于|不超过|不等于|大于|小于|超过|高于|低于|等于|包含|[><=≠]|列出|筛选|满足|所有管段|的管段"
)
_LIST_HINT = re.compile(r"列出|筛选|查找|找出|满足|所有管段|的管段|有哪些管段")


def detect_filter_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if not _COMPARE_HINT.search(q) and not _LIST_HINT.search(q):
        return False
    # Prefer filter when we can already extract ≥1 condition
    draft = parse_filter_draft(q)
    return bool(draft and draft.get("conditions"))


def parse_filter_draft(
    query: str,
    *,
    scope_paths: list[str] | None = None,
    available_columns: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return FilterDraft dict or None."""
    q = (query or "").strip()
    if not q:
        return None

    cols = available_columns
    if cols is None:
        cols = _catalog_column_set(scope_paths)

    conditions = _rule_extract(q, cols)
    # LLM only when compare/list hints exist but rules found nothing (avoid hallucinating on station names)
    if len(conditions) < 1 and (_COMPARE_HINT.search(q) or _LIST_HINT.search(q)):
        # require at least a digit to avoid station-only queries
        if re.search(r"\d", q):
            conditions = _llm_extract(q, cols) or []

    # validate
    cleaned: list[dict[str, Any]] = []
    for c in conditions:
        key = resolve_alias_to_key(str(c.get("field_key") or "")) or str(c.get("field_key") or "")
        if key not in COLUMN_DEFS:
            continue
        if cols and key not in cols and not _column_exists_in_any_table(key, scope_paths):
            # still allow known semantic keys if catalog empty / stale
            if key not in COLUMN_DEFS:
                continue
        op = normalize_op(str(c.get("op") or "eq")) or "eq"
        raw_val = str(c.get("value") or "").strip()
        if not raw_val:
            continue
        disp, num, unit = parse_number_with_unit(raw_val)
        if unit is None:
            unit = field_unit(key)
        item = {
            "id": str(c.get("id") or f"fc-{uuid.uuid4().hex[:8]}"),
            "field_key": key,
            "field_label": field_label(key),
            "op": op,
            "value": disp if disp else raw_val,
            "unit": unit,
            "value_normalized": num if num is not None else raw_val,
        }
        cleaned.append(item)

    # dedupe by field_key (keep first)
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for c in cleaned:
        if c["field_key"] in seen:
            continue
        seen.add(c["field_key"])
        uniq.append(c)

    if not uniq:
        return None

    hint_parts = [f"{c['field_label']}{ _op_sym(c['op']) }{c['value']}{c.get('unit') or ''}" for c in uniq]
    return {
        "logic": "and",
        "conditions": uniq,
        "title_hint": " 且 ".join(hint_parts),
    }


def validate_filter_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Normalize user-edited draft from confirm API; raise ValueError if invalid."""
    if not isinstance(draft, dict):
        raise ValueError("filter 无效")
    raw_conds = draft.get("conditions")
    if not isinstance(raw_conds, list) or not raw_conds:
        raise ValueError("至少需要一条筛选条件")
    out: list[dict[str, Any]] = []
    for c in raw_conds:
        if not isinstance(c, dict):
            continue
        key = resolve_alias_to_key(str(c.get("field_key") or "")) or str(c.get("field_key") or "")
        if key not in COLUMN_DEFS:
            raise ValueError(f"不支持的字段: {c.get('field_key')}")
        op = normalize_op(str(c.get("op") or ""))
        if not op:
            raise ValueError(f"不支持的运算符: {c.get('op')}")
        raw_val = str(c.get("value") or "").strip()
        if not raw_val:
            raise ValueError(f"字段 {key} 缺少取值")
        disp, num, unit = parse_number_with_unit(raw_val)
        if unit is None:
            unit = c.get("unit") or field_unit(key)
        if is_numeric_field(key) and op != "contains" and num is None:
            raise ValueError(f"字段 {field_label(key)} 需要数字")
        out.append(
            {
                "id": str(c.get("id") or f"fc-{uuid.uuid4().hex[:8]}"),
                "field_key": key,
                "field_label": field_label(key),
                "op": op,
                "value": disp if disp else raw_val,
                "unit": unit,
                "value_normalized": num if num is not None else raw_val,
            }
        )
    if not out:
        raise ValueError("没有有效的筛选条件")
    hint_parts = [f"{c['field_label']}{_op_sym(c['op'])}{c['value']}{c.get('unit') or ''}" for c in out]
    return {"logic": "and", "conditions": out, "title_hint": " 且 ".join(hint_parts)}


def _op_sym(op: str) -> str:
    return {
        "eq": "=",
        "ne": "≠",
        "gt": ">",
        "gte": "≥",
        "lt": "<",
        "lte": "≤",
        "contains": "含",
    }.get(op, "=")


def _rule_extract(query: str, cols: set[str] | None) -> list[dict[str, Any]]:
    q = query
    found: list[dict[str, Any]] = []

    # Pattern: alias + optional op + number(+unit)
    # Also: alias + number without explicit op → eq
    op_pat = "|".join(re.escape(a) for a, _ in OP_ALIASES)
    for alias, key in all_aliases_sorted():
        if cols and key not in cols and key not in COLUMN_DEFS:
            continue
        # with operator
        pat = re.compile(
            rf"{re.escape(alias)}\s*({op_pat})?\s*([+-]?\d+(?:\.\d+)?)\s*(km|Km|KM|mm|MM|MPa|mpa|千米|公里)?",
            re.IGNORECASE,
        )
        for m in pat.finditer(q):
            op_raw = m.group(1) or "等于"
            op = normalize_op(op_raw) or "eq"
            num_s = m.group(2)
            unit_s = m.group(3)
            value = f"{num_s}{unit_s or ''}"
            found.append(
                {
                    "field_key": key,
                    "op": op,
                    "value": value,
                }
            )
        # "alias为/是 xxx" text contains
        if not is_numeric_field(key):
            pat2 = re.compile(rf"{re.escape(alias)}\s*(?:等于|为|是|包含)\s*([^\s,，、]{{2,40}})")
            for m in pat2.finditer(q):
                found.append({"field_key": key, "op": "contains", "value": m.group(1)})

    return found


def _llm_extract(query: str, cols: set[str] | None) -> list[dict[str, Any]] | None:
    """Optional LLM fallback; returns None if no key / failure."""
    from realai.llm import chat_text_sync, has_api_key

    if not has_api_key():
        return None

    keys = sorted(COLUMN_DEFS.keys())
    system = (
        "从用户问题中抽取表格筛选条件，只输出 JSON 数组。"
        '每项格式：{"field_key":"...","op":"eq|ne|gt|gte|lt|lte|contains","value":"..."}。'
        f"field_key 必须是以下之一：{', '.join(keys)}。"
        "不要解释。"
    )
    try:
        content = chat_text_sync(
            query,
            system=system,
            role="fast",
            temperature=0.1,
            max_tokens=512,
            timeout=30.0,
            purpose="filter_parse",
        )
        return _parse_json_conditions(content)
    except Exception:
        logger.debug("filter llm extract failed", exc_info=True)
        return None


def _parse_json_conditions(text: str) -> list[dict[str, Any]]:
    import json

    t = (text or "").strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
        if m:
            t = m.group(1).strip()
    start = t.find("[")
    end = t.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        data = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _catalog_column_set(scope_paths: list[str] | None) -> set[str]:
    try:
        from realai.data.table_catalog import list_catalog_schemas

        schemas = list_catalog_schemas(scope_paths=scope_paths, limit=40, query_hint="")
        cols: set[str] = set()
        for s in schemas:
            for c in s.get("columns") or []:
                cols.add(str(c))
        return cols
    except Exception:
        return set(COLUMN_DEFS.keys())


def _column_exists_in_any_table(field_key: str, scope_paths: list[str] | None) -> bool:
    cols = _catalog_column_set(scope_paths)
    return field_key in cols
