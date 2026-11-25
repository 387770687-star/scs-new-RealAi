"""Save / export writing preview as MD / Word / PDF."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from realai.config import resolve_report_output_dir, resolve_vault_path
from realai.report.pdf_export import markdown_to_pdf
from realai.report.word_export import markdown_to_docx
from realai.vault.service import write_vault_file

ExportFormat = Literal["md", "docx", "pdf"]


def _rel_dir() -> Path:
    vault_root = resolve_vault_path()
    out_dir = resolve_report_output_dir()
    try:
        return out_dir.relative_to(vault_root)
    except ValueError:
        return Path("reports")


def _slug(goal: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "-", goal)[:40].strip("-") or "report"


def write_report_files(goal: str, markdown: str) -> dict[str, str]:
    """Write MD/DOCX/PDF under reports/; return relative vault paths."""
    rel_dir = _rel_dir()
    slug = _slug(goal)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{slug}-{ts}"
    paths: dict[str, str] = {}

    md_rel = str(rel_dir / f"{base}.md").replace("\\", "/")
    write_vault_file(md_rel, markdown)
    paths["vault_path"] = md_rel

    docx_rel = str(rel_dir / f"{base}.docx").replace("\\", "/")
    write_vault_file(docx_rel, markdown_to_docx(markdown, title=goal))
    paths["vault_path_docx"] = docx_rel

    try:
        pdf_rel = str(rel_dir / f"{base}.pdf").replace("\\", "/")
        write_vault_file(pdf_rel, markdown_to_pdf(markdown, title=goal))
        paths["vault_path_pdf"] = pdf_rel
    except Exception:
        # PDF is best-effort; MD/Word still succeed
        pass
    return paths


def _download_name(goal: str, ext: str) -> str:
    """ASCII-safe download filename (Chinese kept in document title/body)."""
    raw = _slug(goal)
    safe = re.sub(r"[^\w.-]+", "-", raw).strip("-.") or "report"
    if not re.search(r"[A-Za-z0-9]", safe):
        safe = "report"
    return f"{safe[:48]}.{ext}"


def build_export_bytes(
    markdown: str,
    *,
    goal: str,
    fmt: ExportFormat,
) -> tuple[bytes, str, str]:
    """Return (content, media_type, filename)."""
    if fmt == "md":
        return markdown.encode("utf-8"), "text/markdown; charset=utf-8", _download_name(goal, "md")
    if fmt == "docx":
        return (
            markdown_to_docx(markdown, title=goal),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _download_name(goal, "docx"),
        )
    if fmt == "pdf":
        return markdown_to_pdf(markdown, title=goal), "application/pdf", _download_name(goal, "pdf")
    raise ValueError(f"unsupported format: {fmt}")


def apply_preview_to_result(
    result: dict[str, Any] | None,
    markdown: str,
    *,
    goal: str,
    rewrite_files: bool = True,
) -> dict[str, Any]:
    """Update result dict with new markdown and optional vault rewrite."""
    from realai.report.llm_client import count_chinese_chars

    out = dict(result or {})
    out["preview_markdown"] = markdown
    total_chars = count_chinese_chars(markdown)
    out["chinese_chars"] = total_chars
    min_chars = int(out.get("min_chars") or 0)
    chars_met = total_chars >= min_chars if min_chars > 0 else True
    out["chars_met"] = chars_met
    # Refresh length-related completion notes when user edits preview
    note = str(out.get("completion_note") or "")
    if note in ("completed_under_length", "completed", "completed_weak_evidence", "completed_with_gaps"):
        weak = bool(out.get("evidence_weak"))
        if weak and not chars_met:
            out["completion_note"] = "completed_with_gaps"
        elif weak:
            out["completion_note"] = "completed_weak_evidence"
        elif not chars_met:
            out["completion_note"] = "completed_under_length"
        elif note.startswith("completed"):
            out["completion_note"] = "completed"
    if rewrite_files:
        paths = write_report_files(goal, markdown)
        out.update(paths)
    return out
