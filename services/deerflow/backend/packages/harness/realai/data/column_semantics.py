"""Column aliases, units, and display labels for filter / NL ask-data."""

from __future__ import annotations

import re
from typing import Any

# Canonical field_key -> Chinese label + aliases (longer aliases first when matching)
COLUMN_DEFS: dict[str, dict[str, Any]] = {
    "pipe_diameter": {
        "label": "管径(mm)",
        "unit": "mm",
        "aliases": ("管径(mm)", "管径（mm）", "管径mm", "管径", "直径"),
        "numeric": True,
    },
    "design_pressure": {
        "label": "设计压力",
        "unit": "MPa",
        "aliases": ("设计压力", "压力"),
        "numeric": True,
    },
    "pipe_section_length": {
        "label": "管段长度(km)",
        "unit": "km",
        "aliases": ("管段长度(km)", "管段长度（km）", "管段长度", "长度(km)", "长度（km）", "长度"),
        "numeric": True,
    },
    "pipe_section_name": {
        "label": "管段名称",
        "unit": None,
        "aliases": ("管段名称", "管段名", "管段"),
        "numeric": False,
    },
    "pipeline_name": {
        "label": "管线名称",
        "unit": None,
        "aliases": ("管线名称", "管线名", "管线", "管道名称"),
        "numeric": False,
    },
    "start_station_name": {
        "label": "起始站",
        "unit": None,
        "aliases": ("起始站", "起点站", "起点"),
        "numeric": False,
    },
    "end_station_name": {
        "label": "终止站",
        "unit": None,
        "aliases": ("终止站", "终点站", "终点"),
        "numeric": False,
    },
    "use_status": {
        "label": "使用状态",
        "unit": None,
        "aliases": ("使用状态", "投产状态", "状态"),
        "numeric": False,
    },
    "design_trans_flow_rate": {
        "label": "设计输量",
        "unit": None,
        "aliases": ("设计输量", "输量"),
        "numeric": True,
    },
}

FilterOp = str  # eq|ne|gt|gte|lt|lte|contains

OP_ALIASES: list[tuple[str, str]] = [
    ("大于等于", "gte"),
    ("不少于", "gte"),
    ("小于等于", "lte"),
    ("不超过", "lte"),
    ("不等于", "ne"),
    ("不等于", "ne"),
    ("大于", "gt"),
    ("超过", "gt"),
    ("高于", "gt"),
    ("小于", "lt"),
    ("低于", "lt"),
    ("等于", "eq"),
    ("为", "eq"),
    ("是", "eq"),
    ("包含", "contains"),
    (">=", "gte"),
    ("≤", "lte"),
    ("<=", "lte"),
    ("≠", "ne"),
    ("!=", "ne"),
    (">", "gt"),
    ("<", "lt"),
    ("=", "eq"),
]

OP_LABELS: dict[str, str] = {
    "eq": "等于",
    "ne": "不等于",
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
    "contains": "包含",
}

_VALID_OPS = frozenset(OP_LABELS.keys())


def all_aliases_sorted() -> list[tuple[str, str]]:
    """Return (alias, field_key) sorted by alias length desc for greedy match."""
    pairs: list[tuple[str, str]] = []
    for key, meta in COLUMN_DEFS.items():
        for a in meta["aliases"]:
            pairs.append((a, key))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def field_label(field_key: str) -> str:
    meta = COLUMN_DEFS.get(field_key)
    return str(meta["label"]) if meta else field_key


def field_unit(field_key: str) -> str | None:
    meta = COLUMN_DEFS.get(field_key)
    if not meta:
        return None
    u = meta.get("unit")
    return str(u) if u else None


def is_numeric_field(field_key: str) -> bool:
    meta = COLUMN_DEFS.get(field_key)
    return bool(meta and meta.get("numeric"))


def normalize_op(raw: str) -> str | None:
    t = (raw or "").strip()
    if t in _VALID_OPS:
        return t
    for alias, op in OP_ALIASES:
        if alias == t or t.lower() == alias.lower():
            return op
    return None


def parse_number_with_unit(raw: str) -> tuple[str, float | None, str | None]:
    """Return (display_value, normalized_number, unit)."""
    s = (raw or "").strip()
    if not s:
        return "", None, None
    m = re.fullmatch(
        r"([+-]?\d+(?:\.\d+)?)\s*(km|Km|KM|mm|MM|MPa|mpa|mpa)?",
        s,
    )
    if not m:
        # strip trailing unit words
        m2 = re.fullmatch(
            r"([+-]?\d+(?:\.\d+)?)\s*(千米|公里|兆帕)?",
            s,
        )
        if not m2:
            try:
                return s, float(s.replace(",", "")), None
            except ValueError:
                return s, None, None
        num = float(m2.group(1))
        u = m2.group(2)
        unit = "km" if u in ("千米", "公里") else ("MPa" if u == "兆帕" else None)
        return m2.group(1), num, unit
    num = float(m.group(1))
    u = m.group(2)
    unit = None
    if u:
        ul = u.lower()
        if ul == "km":
            unit = "km"
        elif ul == "mm":
            unit = "mm"
        elif ul == "mpa":
            unit = "MPa"
    return m.group(1), num, unit


def resolve_alias_to_key(alias: str) -> str | None:
    a = (alias or "").strip()
    if not a:
        return None
    if a in COLUMN_DEFS:
        return a
    for al, key in all_aliases_sorted():
        if al == a or al.lower() == a.lower():
            return key
    return None
