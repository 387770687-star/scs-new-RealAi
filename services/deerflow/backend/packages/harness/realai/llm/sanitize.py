"""Normalize LLM visible text: strip leaked <think> blocks into reasoning."""

from __future__ import annotations

import re

from deerflow.utils.llm_text import strip_think_blocks

_THINK_INNER_RE = re.compile(r"<think\b[^>]*>(.*?)</think\s*>", re.IGNORECASE | re.DOTALL)
_OPEN_THINK_TAIL_RE = re.compile(r"<think\b[^>]*>(.*)$", re.IGNORECASE | re.DOTALL)
_CN_RE = re.compile(r"[\u4e00-\u9fff]")
_META_EN_RE = re.compile(
    r"^(The user wants|The user asked|I need to|Let me |Okay[,.]|Sure[,.]|"
    r"I'll |I will |As a |You are |Acting as )\b",
    re.IGNORECASE | re.MULTILINE,
)
_HEADING_RE = re.compile(r"^#{1,3}\s+\S+", re.MULTILINE)
_MARKDOWN_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_AUDIT_OUTPUT_MARKERS = (
    "被引用论断",
    "实际来源",
    "审核意见",
    "引用质量评估",
    "待补充引用清单",
    "七维评分表",
    "问题清单",
    "重写计划",
)


def finalize_llm_text(content: str, reasoning: str | None = None) -> tuple[str, str | None]:
    """Return (visible_content, reasoning).

    MiniMax 等模型常把思考过程写进 content 的 ``<think>`` 标签；
    可见正文必须去掉这些块。若接口未单独返回 reasoning，则把标签内文字并入 reasoning。
    """
    raw = content or ""
    extracted_parts = [m.group(1).strip() for m in _THINK_INNER_RE.finditer(raw) if m.group(1).strip()]
    dangling = _OPEN_THINK_TAIL_RE.search(_THINK_INNER_RE.sub("", raw))
    if dangling and dangling.group(1).strip():
        extracted_parts.append(dangling.group(1).strip())

    visible = strip_think_blocks(raw)
    merged = reasoning.strip() if isinstance(reasoning, str) and reasoning.strip() else None
    if extracted_parts:
        joined = "\n\n".join(extracted_parts)
        merged = f"{merged}\n\n{joined}".strip() if merged else joined
    return visible, merged


def count_chinese_chars_simple(text: str) -> int:
    return len(_CN_RE.findall(text or ""))


def clean_report_markdown(text: str) -> str:
    """Strip think tags and obvious English meta-narration from report body."""
    visible, _ = finalize_llm_text(text or "", None)
    # Obsidian/Typora 的 ==高亮== 在 Web 预览、Word 和 PDF 中会露出字面符号。
    # 报告正文统一降级为纯文本标记，例如 ==[待补充：…]== → [待补充：…]。
    s = visible.replace("==", "").strip()
    if not s:
        return ""
    # Drop leading English role-play / planning paragraphs
    paras = re.split(r"\n{2,}", s)
    kept: list[str] = []
    skipping_meta = True
    for p in paras:
        p = p.strip()
        if not p:
            continue
        first = p.splitlines()[0].strip() if p else ""
        if skipping_meta and _META_EN_RE.match(first):
            continue
        if skipping_meta and count_chinese_chars_simple(p) < 8 and re.search(r"[A-Za-z]{20,}", p):
            continue
        skipping_meta = False
        kept.append(p)
    return "\n\n".join(kept).strip()


def is_usable_report_body(
    text: str,
    *,
    min_chinese: int = 40,
    require_heading: bool = False,
) -> bool:
    """True when cleaned text looks like report body rather than leaked thinking."""
    cleaned = clean_report_markdown(text)
    if not cleaned:
        return False
    if _META_EN_RE.match(cleaned.lstrip()):
        return False
    cn = count_chinese_chars_simple(cleaned)
    if cn < min_chinese:
        return False
    if require_heading and not _HEADING_RE.search(cleaned):
        # Single chapter body may omit H2; full-doc replace should have headings
        return False
    return True


def validate_report_revision(
    baseline: str,
    candidate: str,
    *,
    required_headings: list[str] | tuple[str, ...] | None = None,
    min_retention_ratio: float = 0.8,
) -> tuple[bool, str]:
    """Reject destructive full-document replacements before they reach the UI.

    Citation and optimization model calls are allowed to revise a report, but
    their auxiliary outputs (audit tables, scorecards, review notes) must never
    become the report body. The guard intentionally favors preserving a good
    draft over accepting a shorter, structurally incomplete model response.
    """

    before = clean_report_markdown(baseline)
    after = clean_report_markdown(candidate)
    if not is_usable_report_body(after, min_chinese=80, require_heading=True):
        return False, "改写结果不是完整报告正文"

    before_chars = count_chinese_chars_simple(before)
    after_chars = count_chinese_chars_simple(after)
    if before_chars >= 200:
        ratio = after_chars / max(before_chars, 1)
        if ratio < max(0.1, min(1.0, min_retention_ratio)):
            return False, f"改写正文大幅缩减（仅保留 {ratio:.0%}）"

    headings = [re.sub(r"\s+", "", str(item or "")) for item in (required_headings or [])]
    headings = [item for item in headings if item]
    if headings:
        compact = re.sub(r"\s+", "", after)
        matched = sum(1 for heading in headings if heading in compact)
        coverage = matched / len(headings)
        if coverage < 0.8:
            return False, f"章节结构不完整（仅保留 {matched}/{len(headings)} 章）"

    audit_hits = sum(1 for marker in _AUDIT_OUTPUT_MARKERS if marker in after)
    baseline_audit_hits = sum(1 for marker in _AUDIT_OUTPUT_MARKERS if marker in before)
    table_chars = sum(count_chinese_chars_simple(match.group(0)) for match in _MARKDOWN_TABLE_ROW_RE.finditer(after))
    table_ratio = table_chars / max(after_chars, 1)
    if audit_hits >= 2 and audit_hits > baseline_audit_hits and table_ratio >= 0.2:
        return False, "检测到引用审计表或评审输出，不能替换正文"
    if table_ratio >= 0.6:
        return False, "改写结果以表格为主，不能替换叙事正文"

    return True, "ok"
