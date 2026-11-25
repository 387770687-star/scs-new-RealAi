"""Multi-dimensional evaluation scorers (keywords / evidence / number / table / report)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _loads_text_blob(resp: dict[str, Any]) -> str:
    parts: list[str] = [
        str(resp.get("answer") or ""),
        str(resp.get("conclusion") or ""),
        str(resp.get("preview_markdown") or ""),
    ]
    profile = resp.get("entity_profile") or {}
    if isinstance(profile, dict):
        parts.append(str(profile.get("title") or ""))
        parts.append(str(profile.get("summary") or ""))
        for k, v in (profile.get("fields") or {}).items():
            parts.append(f"{k}:{v}")
    for t in resp.get("tables") or []:
        if not isinstance(t, dict):
            continue
        parts.append(str(t.get("title") or ""))
        cols = t.get("columns") or []
        parts.append(" ".join(str(c) for c in cols))
        for row in (t.get("rows") or [])[:80]:
            if isinstance(row, (list, tuple)):
                parts.append(" ".join(str(x) for x in row))
            elif isinstance(row, dict):
                parts.append(" ".join(f"{k}:{v}" for k, v in row.items()))
    for b in resp.get("blocks") or []:
        if isinstance(b, dict):
            parts.append(str(b.get("heading") or ""))
            parts.append(str(b.get("body") or ""))
    return "\n".join(parts)


def _evidence_items(resp: dict[str, Any]) -> list[dict[str, Any]]:
    ev = resp.get("evidence") or {}
    items = ev.get("items") if isinstance(ev, dict) else None
    return [i for i in (items or []) if isinstance(i, dict)]


def _evidence_kinds(items: list[dict[str, Any]]) -> set[str]:
    kinds: set[str] = set()
    for it in items:
        eid = str(it.get("id") or "")
        kind = str(it.get("kind") or "")
        if eid.startswith("kb:") or kind in ("kb", "knowledge"):
            kinds.add("kb")
        elif eid.startswith("data:") or kind in ("data", "table"):
            kinds.add("data")
        elif eid.startswith("viz:") or kind in ("viz", "vision", "image"):
            kinds.add("viz")
        elif eid.startswith("web:") or kind == "web":
            kinds.add("web")
        elif eid.startswith("inference:") or kind == "inference":
            kinds.add("inference")
    return kinds


def _table_row_count(resp: dict[str, Any]) -> int:
    n = 0
    for t in resp.get("tables") or []:
        if isinstance(t, dict):
            n += len(t.get("rows") or [])
    if n:
        return n
    for it in _evidence_items(resp):
        meta = it.get("meta") or {}
        rows = meta.get("rows")
        if isinstance(rows, list):
            n += len(rows)
    return n


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"\s+", "", text)


_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<number>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>亿元|万元|元|百分比|%|公里|千米|km|米|m|人|户|条|个|项|座)?",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "公里": "km",
    "千米": "km",
    "km": "km",
    "米": "m",
    "m": "m",
    "百分比": "%",
    "%": "%",
}


def _canonical_unit(unit: Any) -> str:
    raw = _normalize_text(unit)
    return _UNIT_ALIASES.get(raw, raw)


def _unit_factor(unit: str) -> float:
    return {"元": 1.0, "万元": 10_000.0, "亿元": 100_000_000.0, "km": 1_000.0, "m": 1.0}.get(
        _canonical_unit(unit),
        1.0,
    )


def _text_mentions_unit(text: str, unit: str) -> bool:
    canonical = _canonical_unit(unit)
    aliases = {
        "km": ("km", "公里", "千米"),
        "m": ("米",),
        "%": ("%", "百分比"),
    }.get(canonical, (canonical,))
    normalized = _normalize_text(text)
    return any(_normalize_text(alias) in normalized for alias in aliases if alias)


def _extract_numbers(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in _NUMBER_RE.finditer(text):
        try:
            number = float(match.group("number").replace(",", ""))
        except (TypeError, ValueError):
            continue
        unit = _canonical_unit(match.group("unit") or "")
        out.append({"number": number, "unit": unit, "raw": match.group(0)})
    return out


def _dimension(ok: bool, reasons: list[str], *, score: float | None = None) -> dict[str, Any]:
    return {
        "passed": bool(ok),
        "score": round(float(score if score is not None else (100 if ok else 0)), 2),
        "reasons": reasons,
    }


def score_keywords(case: dict[str, Any], text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ok = True
    for kw in case.get("expect_keywords") or []:
        if str(kw) and _normalize_text(kw) not in _normalize_text(text):
            ok = False
            reasons.append(f"缺少关键词：{kw}")
    return ok, reasons


def score_answer(case: dict[str, Any], text: str) -> tuple[bool, list[str]]:
    expected = str(case.get("expect_answer") or "").strip()
    if not expected:
        return True, []
    mode = str(case.get("answer_match_mode") or "contains").lower()
    if mode == "exact":
        ok = _normalize_text(text) == _normalize_text(expected)
    elif mode == "regex":
        try:
            ok = bool(re.search(expected, text, re.IGNORECASE | re.MULTILINE))
        except re.error:
            return False, ["期望答案的正则表达式无效"]
    else:
        ok = _normalize_text(expected) in _normalize_text(text)
    return (True, []) if ok else (False, [f"未匹配期望答案：{expected[:80]}"])


def score_evidence(case: dict[str, Any], resp: dict[str, Any]) -> tuple[bool, list[str], str | None]:
    """Returns (ok, reasons, skip_reason). skip_reason means case should be skipped."""
    reasons: list[str] = []
    items = _evidence_items(resp)
    kinds = _evidence_kinds(items)
    skip_if = (case.get("skip_if") or "").strip()
    expect_kinds = set(str(k).lower() for k in (case.get("expect_evidence_kinds") or []))

    def _vault_has_images() -> bool:
        try:
            from realai.agents.vision import IMAGE_EXTENSIONS
            from realai.vault.service import SKIP_DIRS, ensure_vault

            root = ensure_vault()
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                return True
        except Exception:
            return False
        return False

    if skip_if == "no_vision" and "viz" in expect_kinds:
        # Soft-skip only when Vault has no images to read; otherwise require real viz:
        if "viz" not in kinds and not resp.get("chart_spec"):
            if not _vault_has_images():
                return True, ["跳过：Vault 无图片可供识图"], "no_vision"
            # Images exist but no viz evidence → fail (vision capability is expected)
            return False, ["缺少证据类型：viz（Vault 有图但未产出视觉证据）"], None

    ok = True
    if case.get("expect_evidence", True) and not items and not resp.get("tables"):
        # report mode may put evidence differently
        if resp.get("run_mode") != "report" or not items:
            ok = False
            reasons.append("未返回证据")

    for k in expect_kinds:
        kk = str(k).lower()
        if kk == "viz":
            if "viz" not in kinds and not resp.get("chart_spec"):
                if skip_if == "no_vision" and not _vault_has_images():
                    return True, ["跳过：无 viz/图表"], "no_vision"
                ok = False
                reasons.append(f"缺少证据类型：{kk}")
        elif kk not in kinds:
            ok = False
            reasons.append(f"缺少证据类型：{kk}")
    return ok, reasons, None


def score_number(case: dict[str, Any], text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    expect_num = case.get("expect_number")
    if expect_num is None:
        return True, reasons
    tol = float(case.get("number_tolerance") if case.get("number_tolerance") is not None else 0.01)
    expect_unit = _canonical_unit(case.get("expect_unit") or "")
    candidates = _extract_numbers(text)
    matched = False
    for candidate in candidates:
        unit = candidate["unit"]
        if expect_unit and unit and unit != expect_unit:
            comparable = {unit, expect_unit} <= {"元", "万元", "亿元"} or {unit, expect_unit} <= {
                "m",
                "km",
            }
            if not comparable:
                continue
            actual = candidate["number"] * _unit_factor(unit) / _unit_factor(expect_unit)
        else:
            actual = candidate["number"]
        if expect_unit and not unit:
            # Markdown/table output often places the unit in the column name or
            # immediately following prose instead of directly after the number.
            if not _text_mentions_unit(text, expect_unit):
                continue
        if abs(actual - float(expect_num)) <= tol:
            matched = True
            break
    if not matched:
        suffix = f" {case.get('expect_unit')}" if case.get("expect_unit") else ""
        return False, [f"未匹配数值 {expect_num}{suffix}（容差 ±{tol}）"]
    return True, reasons


def score_table(case: dict[str, Any], resp: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    expected = case.get("expect_table") or {}
    if not isinstance(expected, dict):
        expected = {}
    min_rows = expected.get("min_rows", case.get("expect_min_rows"))
    n = _table_row_count(resp)
    if min_rows is not None and n < int(min_rows):
        reasons.append(f"表行数不足：{n} < {min_rows}")

    tables = [t for t in (resp.get("tables") or []) if isinstance(t, dict)]
    expected_columns = [str(c) for c in (expected.get("columns") or [])]
    actual_columns = {
        _normalize_text(c)
        for table in tables
        for c in (table.get("columns") or [])
    }
    for column in expected_columns:
        if _normalize_text(column) not in actual_columns:
            reasons.append(f"缺少表格列：{column}")

    actual_rows: list[dict[str, Any]] = []
    for table in tables:
        columns = [str(c) for c in (table.get("columns") or [])]
        for row in table.get("rows") or []:
            if isinstance(row, dict):
                actual_rows.append(row)
            elif isinstance(row, (list, tuple)):
                actual_rows.append({columns[i]: value for i, value in enumerate(row) if i < len(columns)})

    def row_matches(expected_row: Any, actual_row: dict[str, Any]) -> bool:
        if isinstance(expected_row, dict):
            normalized_actual = {_normalize_text(k): _normalize_text(v) for k, v in actual_row.items()}
            return all(
                normalized_actual.get(_normalize_text(key)) == _normalize_text(value)
                for key, value in expected_row.items()
            )
        return _normalize_text(expected_row) in _normalize_text(" ".join(str(v) for v in actual_row.values()))

    expected_rows = expected.get("rows") or []
    for expected_row in expected_rows:
        if not any(row_matches(expected_row, actual) for actual in actual_rows):
            reasons.append(f"缺少期望数据行：{str(expected_row)[:100]}")

    if expected.get("match_mode") == "exact" and expected_rows and len(actual_rows) != len(expected_rows):
        reasons.append(f"表行数不完全一致：{len(actual_rows)} != {len(expected_rows)}")

    if reasons:
        return False, reasons
    return True, reasons


def score_sources(case: dict[str, Any], resp: dict[str, Any]) -> tuple[bool, list[str]]:
    expected = [str(x).replace("\\", "/").lower() for x in (case.get("expect_source_paths") or []) if str(x)]
    if not expected:
        return True, []
    searchable: list[str] = []
    for item in _evidence_items(resp):
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        searchable.extend(
            [
                str(item.get("id") or ""),
                str(item.get("source") or ""),
                str(meta.get("path") or ""),
                str(meta.get("source") or ""),
                str(meta.get("locator") or ""),
            ]
        )
    haystack = "\n".join(searchable).replace("\\", "/").lower()
    missing = [path for path in expected if path not in haystack]
    if missing:
        return False, [f"未引用指定来源：{path}" for path in missing]
    return True, []


def score_rubric(case: dict[str, Any], resp: dict[str, Any], text: str) -> tuple[bool, list[str]]:
    rubric = case.get("rubric") or {}
    if not isinstance(rubric, dict) or not rubric:
        return True, []
    reasons: list[str] = []
    visible = text.strip()
    min_chars = rubric.get("min_chars")
    if min_chars is not None and len(visible) < int(min_chars):
        reasons.append(f"正文长度不足：{len(visible)} < {min_chars}")
    for section in rubric.get("required_sections") or []:
        if _normalize_text(section) not in _normalize_text(visible):
            reasons.append(f"缺少必需章节：{section}")
    for term in rubric.get("prohibited_terms") or []:
        if _normalize_text(term) in _normalize_text(visible):
            reasons.append(f"包含禁用内容：{term}")
    review_min = rubric.get("review_min_score")
    review_score = (resp.get("review") or {}).get("score")
    if review_min is not None and (review_score is None or float(review_score) < float(review_min)):
        reasons.append(f"评审分不足：{review_score if review_score is not None else '无'} < {review_min}")
    return not reasons, reasons


def score_report(case: dict[str, Any], resp: dict[str, Any]) -> tuple[bool, list[str]]:
    """Report-specific: evidence audit, citation coverage, review score."""
    reasons: list[str] = []
    ok = True
    if resp.get("run_mode") != "report" and not resp.get("preview_markdown"):
        return False, ["非报告产出"]

    audit = resp.get("evidence_audit") or {}
    if audit and not audit.get("passed", True):
        ok = False
        for issue in (audit.get("issues") or [])[:5]:
            reasons.append(f"证据审核：{issue}")

    blocks = resp.get("blocks") or []
    rubric = case.get("rubric") if isinstance(case.get("rubric"), dict) else {}
    min_coverage = float(rubric.get("min_citation_coverage", 0.3))
    cited = 0
    total_blocks = 0
    for b in blocks:
        if not isinstance(b, dict):
            continue
        total_blocks += 1
        if b.get("evidence_ids"):
            cited += 1
    if total_blocks and cited == 0:
        ok = False
        reasons.append("正文块均无证据引用")
    elif total_blocks:
        coverage = cited / total_blocks
        if coverage < min_coverage:
            ok = False
            reasons.append(f"引用覆盖偏低：{cited}/{total_blocks} < {min_coverage:.0%}")

    review = resp.get("review") or {}
    score = review.get("score")
    review_min = float(rubric.get("review_min_score", 60))
    if score is not None and float(score) < review_min:
        ok = False
        reasons.append(f"评审分过低：{score} < {review_min:g}")

    # Skill validity (report path)
    skills = resp.get("skills") or {}
    if case.get("expect_skill_valid", True):
        if skills.get("writer_valid") is False:
            ok = False
            reasons.append("写作 Skill 无效")
        if skills.get("review_valid") is False:
            ok = False
            reasons.append("评审 Skill 无效")

    return ok, reasons


def score_case(case: dict[str, Any], resp: dict[str, Any]) -> tuple[bool | None, list[str], dict[str, Any]]:
    """
    Returns (passed, reasons, meta).
    passed=None means skipped (not counted as pass or fail in totals when caller chooses).
    """
    mode = (case.get("mode") or resp.get("run_mode") or "light").lower()
    text = _loads_text_blob(resp)
    reasons: list[str] = []
    meta: dict[str, Any] = {
        "category": case.get("category") or "general",
        "mode": mode,
        "evidence_count": len(_evidence_items(resp)),
        "table_rows": _table_row_count(resp),
        "evidence_kinds": sorted(_evidence_kinds(_evidence_items(resp))),
    }

    dimensions: dict[str, dict[str, Any]] = {}

    ok_kw, r1 = score_keywords(case, text)
    reasons.extend(r1)
    expected_keywords = case.get("expect_keywords") or []
    keyword_score = (
        100.0
        if not expected_keywords
        else 100.0
        * sum(1 for kw in expected_keywords if _normalize_text(kw) in _normalize_text(text))
        / len(expected_keywords)
    )
    dimensions["keywords"] = _dimension(ok_kw, r1, score=keyword_score)

    ok_answer, answer_reasons = score_answer(case, text)
    reasons.extend(answer_reasons)
    dimensions["answer"] = _dimension(ok_answer, answer_reasons)

    ok_ev, r2, skip = score_evidence(case, resp)
    reasons.extend(r2)
    dimensions["evidence"] = _dimension(ok_ev, r2)
    if skip:
        meta["skipped"] = True
        meta["skip_reason"] = skip
        meta["dimensions"] = dimensions
        return None, reasons or ["已跳过"], meta

    ok_num, r3 = score_number(case, text)
    reasons.extend(r3)
    dimensions["number"] = _dimension(ok_num, r3)
    ok_tbl, r4 = score_table(case, resp)
    reasons.extend(r4)
    dimensions["table"] = _dimension(ok_tbl, r4)

    ok_sources, source_reasons = score_sources(case, resp)
    reasons.extend(source_reasons)
    dimensions["sources"] = _dimension(ok_sources, source_reasons)

    ok_rubric, rubric_reasons = score_rubric(case, resp, text)
    reasons.extend(rubric_reasons)
    dimensions["rubric"] = _dimension(ok_rubric, rubric_reasons)

    ok_rep = True
    if mode == "report":
        ok_rep, r5 = score_report(case, resp)
        reasons.extend(r5)
        dimensions["report"] = _dimension(ok_rep, r5)

    hard_gates = case.get("hard_gates") or [
        name
        for name in dimensions
        if name != "keywords" or bool(case.get("expect_keywords"))
    ]
    failed_gates = [
        name for name in hard_gates if name in dimensions and not dimensions[name]["passed"]
    ]
    ok = not failed_gates
    scores = [float(d["score"]) for d in dimensions.values()]
    meta["dimensions"] = dimensions
    meta["overall_score"] = round(sum(scores) / len(scores), 2) if scores else 100.0
    meta["failed_gates"] = failed_gates
    if ok:
        reasons.append("通过")
    return ok, reasons, meta
