"""Obsidian Vault file operations."""

from __future__ import annotations

import csv
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from realai.config import resolve_vault_path
from realai.vault.paths import resolve_under_root

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
SPREADSHEET_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx"}
DOCUMENT_EXTENSIONS = {".docx"}
PREVIEW_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
PREVIEW_TEXT_MAX = 12000
PREVIEW_TABLE_ROWS = 100
SKIP_DIRS = {
    ".obsidian",
    ".git",
    ".deer-flow",
    "node_modules",
    "__pycache__",
    "reports",
    "_raw_archive",
}


@dataclass(slots=True)
class VaultFileInfo:
    path: str
    name: str
    size: int
    mtime: float
    extension: str


def ensure_vault() -> Path:
    root = resolve_vault_path()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _skip_path(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def list_vault_files(limit: int = 500) -> list[VaultFileInfo]:
    root = ensure_vault()
    out: list[VaultFileInfo] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        base = Path(dirpath)
        if _skip_path(base.relative_to(root)):
            continue
        for name in filenames:
            p = base / name
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            stat = p.stat()
            out.append(
                VaultFileInfo(
                    path=rel,
                    name=p.name,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    extension=p.suffix.lower(),
                )
            )
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    out.sort(key=lambda f: f.path)
    return out[:limit]


def read_vault_text(rel_path: str, max_chars: int = 8000) -> str:
    root = ensure_vault()
    target = resolve_under_root(root, rel_path)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    text = target.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]


def resolve_vault_file(rel_path: str) -> Path:
    root = ensure_vault()
    target = resolve_under_root(root, rel_path)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    return target


def _safe_preview_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if bool(value != value):
            return None
    except Exception:
        pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _table_sheet(name: str, rows: list[list[Any]], *, total_rows: int | None = None) -> dict[str, Any]:
    width = max((len(row) for row in rows), default=0)
    columns = [f"列 {index + 1}" for index in range(width)]
    normalized = [
        [_safe_preview_value(row[index]) if index < len(row) else None for index in range(width)]
        for row in rows
    ]
    return {
        "name": name,
        "columns": columns,
        "rows": normalized,
        "total_rows": total_rows if total_rows is not None else len(normalized),
        "truncated": bool(total_rows is not None and total_rows > len(normalized)),
    }


def _csv_preview(target: Path, ext: str) -> list[dict[str, Any]]:
    delimiter = "\t" if ext == ".tsv" else ","
    rows: list[list[Any]] = []
    total = 0
    with target.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        for row in reader:
            total += 1
            if len(rows) < PREVIEW_TABLE_ROWS:
                rows.append(list(row))
    return [_table_sheet(target.stem, rows, total_rows=total)]


def _excel_preview(target: Path) -> list[dict[str, Any]]:
    if target.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(target, read_only=True, data_only=True)
        try:
            sheets: list[dict[str, Any]] = []
            for worksheet in workbook.worksheets:
                rows: list[list[Any]] = []
                total = int(worksheet.max_row or 0)
                for index, row in enumerate(worksheet.iter_rows(values_only=True)):
                    if index >= PREVIEW_TABLE_ROWS:
                        break
                    rows.append([_safe_preview_value(value) for value in row])
                sheets.append(_table_sheet(worksheet.title, rows, total_rows=total))
            return sheets
        finally:
            workbook.close()

    import pandas as pd

    excel = pd.ExcelFile(target, engine="xlrd")
    sheets = []
    for sheet_name in excel.sheet_names:
        frame = pd.read_excel(excel, sheet_name=sheet_name, header=None, dtype=object)
        total = len(frame.index)
        rows = frame.head(PREVIEW_TABLE_ROWS).values.tolist()
        sheets.append(_table_sheet(str(sheet_name), rows, total_rows=total))
    return sheets


def _docx_preview(target: Path, max_chars: int) -> tuple[str, bool]:
    from docx import Document

    document = Document(target)
    blocks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style else ""
        heading_match = re.search(r"heading\s*(\d+)", style)
        if heading_match:
            level = max(1, min(6, int(heading_match.group(1))))
            blocks.append(f"{'#' * level} {text}")
        else:
            blocks.append(text)
    for table in document.tables:
        matrix = [[cell.text.strip().replace("\n", " ") for cell in row.cells] for row in table.rows]
        if not matrix:
            continue
        width = max(len(row) for row in matrix)
        header = (matrix[0] + [""] * width)[:width]
        blocks.append("| " + " | ".join(header) + " |")
        blocks.append("| " + " | ".join(["---"] * width) + " |")
        for row in matrix[1:]:
            blocks.append("| " + " | ".join((row + [""] * width)[:width]) + " |")
    raw = "\n\n".join(blocks)
    return raw[:max_chars], len(raw) > max_chars


def _pdf_text_preview(target: Path, max_chars: int) -> tuple[str, int]:
    try:
        import pymupdf

        document = pymupdf.open(str(target))
        try:
            parts: list[str] = []
            size = 0
            for page in document:
                text = page.get_text("text")
                parts.append(text)
                size += len(text)
                if size >= max_chars:
                    break
            return "\n".join(parts)[:max_chars], len(document)
        finally:
            document.close()
    except Exception:
        return "", 0


def vault_file_preview(rel_path: str, *, max_chars: int = PREVIEW_TEXT_MAX) -> dict:
    target = resolve_vault_file(rel_path)
    ext = target.suffix.lower()
    stat = target.stat()
    base = {
        "path": rel_path.replace("\\", "/"),
        "name": target.name,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "extension": ext,
    }
    if ext in SPREADSHEET_EXTENSIONS:
        try:
            sheets = _csv_preview(target, ext) if ext in {".csv", ".tsv"} else _excel_preview(target)
        except Exception as exc:
            logger.exception("spreadsheet preview failed for %s", rel_path)
            return {
                **base,
                "preview_mode": "download_only",
                "content": None,
                "truncated": False,
                "message": f"表格预览失败：{exc}",
            }
        return {
            **base,
            "preview_mode": "spreadsheet",
            "content": None,
            "sheets": sheets,
            "truncated": any(bool(sheet.get("truncated")) for sheet in sheets),
        }
    if ext == ".pdf":
        content, page_count = _pdf_text_preview(target, max_chars)
        return {
            **base,
            "preview_mode": "pdf",
            "content": content,
            "page_count": page_count,
            "truncated": len(content) >= max_chars,
        }
    if ext in DOCUMENT_EXTENSIONS:
        try:
            content, truncated = _docx_preview(target, max_chars)
        except Exception as exc:
            logger.exception("document preview failed for %s", rel_path)
            return {
                **base,
                "preview_mode": "download_only",
                "content": None,
                "truncated": False,
                "message": f"Word 预览失败：{exc}",
            }
        return {
            **base,
            "preview_mode": "document",
            "content": content,
            "truncated": truncated,
        }
    if ext in TEXT_EXTENSIONS:
        raw = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(raw) > max_chars
        return {
            **base,
            "preview_mode": "text",
            "content": raw[:max_chars],
            "truncated": truncated,
        }
    if ext in PREVIEW_IMAGE_EXTENSIONS:
        return {**base, "preview_mode": "image", "content": None, "truncated": False}
    return {
        **base,
        "preview_mode": "download_only",
        "content": None,
        "truncated": False,
        "message": "此格式请下载后在本地打开",
    }


def write_vault_file(rel_path: str, content: bytes | str) -> str:
    root = ensure_vault()
    target = resolve_under_root(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    return rel_path.replace("\\", "/")


def delete_vault_file(rel_path: str) -> None:
    root = ensure_vault()
    target = resolve_under_root(root, rel_path)
    if target.is_file():
        target.unlink()
    parent = target.parent
    while parent != root and parent.is_dir():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def vault_snapshot_mtime() -> float:
    try:
        from realai.vault.index import get_vault_index

        files = get_vault_index()
        if files:
            return max(f.mtime for f in files)
    except Exception:
        pass
    root = ensure_vault()
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if _skip_path(p.relative_to(root)):
                continue
            latest = max(latest, p.stat().st_mtime)
    return latest
