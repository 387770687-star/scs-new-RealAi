"""Smart vault category classification: pipelines | new_energy | dataqa."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CATEGORIES = ("pipelines", "new_energy", "dataqa")

Category = str

_PIPELINE_HEADERS = (
    "pipe_section",
    "pipeline_name",
    "pipe_diameter",
    "design_pressure",
    "start_station",
    "end_station",
    "管径",
    "管段",
    "管线",
    "站场",
    "压气站",
)
_DATAQA_HEADERS = (
    "gdp",
    "population",
    "admin_division",
    "人口",
    "行政区",
    "energy_cons",
    "gas_sup",
)
_NEW_ENERGY_KEYS = (
    "新能源",
    "光伏",
    "绿电",
    "零碳",
    "充电",
    "海洋能",
    "上网电价",
    "发改",
    "国能发",
)
_PIPELINE_NAME_KEYS = (
    "中俄东线",
    "西气东输",
    "天然气管",
    "原油管",
    "成品油管",
    "压气站",
    "分输",
    "清管站",
)


@dataclass(slots=True)
class ClassifyResult:
    category: Category
    source: str  # rule | llm | fallback | override
    confidence: float
    reason: str = ""


def classify_file(
    filename: str,
    data: bytes,
    *,
    hint_category: str | None = None,
    source_hint: str | None = None,
) -> ClassifyResult:
    """Classify into pipelines / new_energy / dataqa.

    hint_category: explicit user/API override.
    source_hint: e.g. raw/raw/pipelines/... path segment.
    """
    if hint_category and hint_category in CATEGORIES:
        return ClassifyResult(hint_category, "override", 1.0, "用户指定分类")

    if source_hint:
        for cat in CATEGORIES:
            if f"/{cat}/" in source_hint.replace("\\", "/") or source_hint.replace("\\", "/").endswith(
                f"/{cat}"
            ):
                return ClassifyResult(cat, "rule", 0.95, f"路径暗示 {cat}")
            parts = Path(source_hint).parts
            if cat in parts:
                return ClassifyResult(cat, "rule", 0.95, f"路径含 {cat}")

    name = Path(filename).name.lower()
    stem = Path(filename).stem
    ext = Path(filename).suffix.lower()
    score = {c: 0.0 for c in CATEGORIES}
    reasons: list[str] = []

    if any(k in stem for k in _PIPELINE_NAME_KEYS) or any(k in name for k in _PIPELINE_NAME_KEYS):
        score["pipelines"] += 0.5
        reasons.append("文件名含管网关键词")
    if any(k in stem for k in _NEW_ENERGY_KEYS) or any(k in name for k in _NEW_ENERGY_KEYS):
        score["new_energy"] += 0.5
        reasons.append("文件名含新能源关键词")
    if any(k in name for k in ("gdp", "population", "admin", "人口", "dwd_mc", "dwd_mk")):
        score["dataqa"] += 0.45
        reasons.append("文件名含统计问数特征")

    if ext in {".html", ".htm"}:
        score["new_energy"] += 0.35
        reasons.append("HTML 倾向政策/新能源")
    if ext in {".csv", ".xlsx", ".xls"}:
        header = _peek_header(data, ext)
        if header:
            hlow = header.lower()
            if any(k in hlow for k in _PIPELINE_HEADERS):
                score["pipelines"] += 0.55
                reasons.append("表头含管网字段")
            if any(k in hlow for k in _DATAQA_HEADERS):
                score["dataqa"] += 0.55
                reasons.append("表头含统计字段")

    best = max(CATEGORIES, key=lambda c: score[c])
    conf = score[best]
    if conf >= 0.35:
        return ClassifyResult(best, "rule", min(conf, 0.99), "; ".join(reasons) or "规则命中")

    # Low confidence: try LLM, else fallback by extension
    llm = _classify_with_llm(filename, data)
    if llm:
        return llm

    if ext in {".html", ".htm", ".md"} and any(k in stem for k in _NEW_ENERGY_KEYS):
        return ClassifyResult("new_energy", "fallback", 0.3, "扩展名+弱关键词")
    if ext in {".csv", ".xlsx", ".xls"}:
        return ClassifyResult("dataqa", "fallback", 0.25, "表格默认 dataqa")
    return ClassifyResult("pipelines", "fallback", 0.2, "默认 pipelines")


def _peek_header(data: bytes, ext: str) -> str:
    try:
        text = data[:8000].decode("utf-8", errors="replace")
    except Exception:
        return ""
    if ext == ".csv":
        line = text.splitlines()[0] if text else ""
        return line
    # xlsx binary — skip deep parse here; filename rules dominate
    return ""


def _classify_with_llm(filename: str, data: bytes) -> ClassifyResult | None:
    """Optional LLM call; never raises."""
    try:
        import json

        from realai.llm import chat_text_sync, has_api_key

        if not has_api_key():
            return None
        snippet = data[:1500].decode("utf-8", errors="replace")[:800]
        prompt = (
            "将文件分到三类之一：pipelines（油气管道/站场）、new_energy（新能源政策）、dataqa（统计问数表）。"
            f"只输出 JSON：{{\"category\":\"pipelines|new_energy|dataqa\",\"reason\":\"短说明\"}}\n"
            f"文件名：{filename}\n内容片段：{snippet}"
        )
        content = chat_text_sync(
            prompt,
            role="fast",
            temperature=0,
            max_tokens=256,
            timeout=20.0,
            purpose="vault_classify",
            allow_fallback=False,
        )
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        obj = json.loads(m.group(0))
        cat = str(obj.get("category") or "")
        if cat not in CATEGORIES:
            return None
        return ClassifyResult(cat, "llm", 0.7, str(obj.get("reason") or "LLM"))
    except Exception as exc:
        logger.debug("classify LLM skipped: %s", exc)
        return None
