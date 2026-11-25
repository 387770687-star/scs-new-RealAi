"""Logical knowledge catalog layered over the physical Vault layout."""

from __future__ import annotations

import csv
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from realai.vault.content_quality import MIN_BODY_CHARS, is_shell_or_thin_text
from realai.vault.index import get_vault_index
from realai.vault.service import VaultFileInfo, ensure_vault

KNOWLEDGE_TYPES = (
    "document",
    "dataset",
    "media",
    "knowledge_card",
    "entity",
    "metric",
    "outcome",
)

KNOWLEDGE_TYPE_LABELS = {
    "document": "文档资料",
    "dataset": "结构化数据",
    "media": "图片与多媒体",
    "knowledge_card": "知识卡片",
    "entity": "实体与关系",
    "metric": "指标与规则",
    "outcome": "报告与成果",
}

SOURCE_STATUS_LABELS = {
    "raw": "原始资料",
    "curated": "已整理",
    "derived": "知识加工",
    "generated": "生成成果",
}

QUALITY_STATUS_LABELS = {
    "ready": "可用",
    "needs_attention": "待完善",
}

_DATASET_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".xls",
    ".xlsx",
    ".json",
    ".jsonl",
    ".parquet",
    ".db",
    ".sqlite",
    ".geojson",
}
_MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".tif",
    ".tiff",
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".mov",
    ".avi",
}
_TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml"}
_NOISE_FILES = {".gitkeep", "readme.md", "thumbs.db", ".ds_store"}
_HASH_SUFFIX_RE = re.compile(r"(?:-[0-9a-f]{8}){1,3}$", re.IGNORECASE)
_HASH_CAPTURE_RE = re.compile(r"-([0-9a-f]{8})(?=\.[^.]+$)", re.IGNORECASE)
_LEADING_INDEX_RE = re.compile(r"^\d{1,4}[_\-\s]+")
_FRONTMATTER_TITLE_RE = re.compile(r"(?im)^(?:title|name)\s*:\s*[\"']?(.+?)[\"']?\s*$")
_HEADING_RE = re.compile(r"(?m)^#\s+(.+?)\s*$")

_CACHE_SIGNATURE: tuple[int, float, int] | None = None
_CACHE_ITEMS: list[dict[str, Any]] | None = None
_CACHE_BUILT_AT = 0.0


def invalidate_vault_catalog() -> None:
    global _CACHE_SIGNATURE, _CACHE_ITEMS, _CACHE_BUILT_AT
    _CACHE_SIGNATURE = None
    _CACHE_ITEMS = None
    _CACHE_BUILT_AT = 0.0


def _parts(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").split("/") if part]


def knowledge_type_for(path: str, extension: str = "") -> str:
    """Map physical paths to stable, cross-industry logical data types."""
    parts = _parts(path)
    top = parts[0].lower() if parts else ""
    ext = (extension or Path(path).suffix).lower()
    if top in {"reports", "10_outputs"}:
        return "outcome"
    if top == "05_metrics":
        return "metric"
    if top == "entities":
        return "entity"
    if top == "wiki":
        return "knowledge_card"
    if ext in _MEDIA_EXTENSIONS:
        return "media"
    if ext in _DATASET_EXTENSIONS:
        return "dataset"
    return "document"


def source_status_for(path: str) -> str:
    parts = _parts(path)
    top = parts[0].lower() if parts else ""
    if top == "raw":
        return "raw"
    if top in {"wiki", "entities"}:
        return "derived"
    if top in {"reports", "10_outputs"}:
        return "generated"
    return "curated"


def business_tags_for(path: str, title: str = "") -> list[str]:
    """Return optional business facets without using them as primary classes."""
    lower_path = path.replace("\\", "/").lower()
    text = f"{lower_path} {title}".lower()
    tags: list[str] = []
    if (
        "pipelines" in lower_path
        or any(
            segment in lower_path
            for segment in (
                "entities/station/",
                "entities/pipe_section/",
                "entities/pipeline/",
            )
        )
        or any(key in text for key in ("管网", "管线", "管段", "站场", "压气站", "西气东输"))
    ):
        tags.append("管网工程")
    if "new_energy" in lower_path or any(key in text for key in ("新能源", "光伏", "储能", "绿电", "零碳", "充电")):
        tags.append("新能源")
    if any(key in text for key in ("政策", "规划办法", "指导意见", "管理办法", "通知", "发改", "国能发")):
        tags.append("政策法规")
    if "dataqa" in lower_path or any(key in text for key in ("gdp", "人口", "成本", "能源消费", "统计")):
        tags.append("经营与区域数据")
    if lower_path.startswith("reports/") or any(key in text for key in ("战略规划", "行动方案", "发展规划")):
        tags.append("战略规划")
    return list(dict.fromkeys(tags))


def _catalog_files(force: bool = False) -> list[VaultFileInfo]:
    files = list(get_vault_index(force=force))
    root = ensure_vault()
    reports = root / "reports"
    if reports.is_dir():
        indexed_paths = {item.path for item in files}
        for path in reports.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in indexed_paths:
                continue
            stat = path.stat()
            files.append(
                VaultFileInfo(
                    path=rel,
                    name=path.name,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    extension=path.suffix.lower(),
                )
            )
    return sorted(
        (item for item in files if item.name.lower() not in _NOISE_FILES and not item.name.startswith(".") and "/_raw_archive/" not in f"/{item.path.replace('\\', '/')}/"),
        key=lambda item: item.path,
    )


def _read_head(root: Path, path: str, extension: str, max_chars: int = 8000) -> str:
    if extension.lower() not in _TEXT_EXTENSIONS:
        return ""
    try:
        return (root / path).read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _clean_stem(name: str) -> str:
    stem = Path(name).stem
    stem = _HASH_SUFFIX_RE.sub("", stem)
    stem = _LEADING_INDEX_RE.sub("", stem)
    return stem.replace("_", " ").strip() or Path(name).name


def _clean_title_value(value: str) -> str:
    title = _HASH_SUFFIX_RE.sub("", value.strip().strip("\"'"))
    title = _LEADING_INDEX_RE.sub("", title)
    return title.replace("_", " ").strip() or value.strip()


def _display_title(name: str, head: str) -> str:
    frontmatter = _FRONTMATTER_TITLE_RE.search(head[:2000])
    if frontmatter:
        return _clean_title_value(frontmatter.group(1))
    heading = _HEADING_RE.search(head[:4000])
    if heading:
        return _clean_title_value(heading.group(1))
    return _clean_stem(name)


def _text_summary(head: str) -> str:
    text = re.sub(r"\A---[\s\S]*?---\s*", "", head, count=1)
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    text = re.sub(r"!\[\[.*?\]\]|\[\[(.*?)(?:\|.*?)?\]\]", r"\1", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```", "---")) or re.fullmatch(r"`[^`]+`", line):
            continue
        line = re.sub(r"^[-*>\d.\s]+", "", line).strip()
        if re.fullmatch(r"`[^`]+`", line):
            continue
        line = re.sub(r"(\*\*|__|~~)", "", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        if line:
            lines.append(line)
        if len(" ".join(lines)) >= 180:
            break
    summary = " ".join(lines)
    return summary[:180] + ("…" if len(summary) > 180 else "")


def _dataset_summary(head: str) -> str:
    if not head.strip():
        return "结构化数据集，可用于检索、统计和问数。"
    first_line = head.splitlines()[0]
    try:
        headers = next(csv.reader([first_line]))
    except (csv.Error, StopIteration):
        headers = []
    clean = [header.strip() for header in headers if header.strip()][:8]
    if not clean:
        return "结构化数据集，可用于检索、统计和问数。"
    suffix = "等" if len(headers) > len(clean) else ""
    return f"结构化数据集，包含字段：{'、'.join(clean)}{suffix}。"


def _summary_for(knowledge_type: str, head: str) -> str:
    if knowledge_type == "dataset":
        return _dataset_summary(head)
    if knowledge_type == "media":
        return "图片或多媒体资料，可通过视觉能力识别并关联到知识内容。"
    summary = _text_summary(head)
    if summary:
        return summary
    fallbacks = {
        "entity": "实体知识，包含属性、来源及与其他知识的关系。",
        "metric": "指标或业务规则，包含定义、公式、单位与权威数据源。",
        "knowledge_card": "由源资料加工形成的知识要点卡。",
        "outcome": "系统生成或沉淀的报告与分析成果。",
        "document": "文档资料，可用于检索、问答与报告写作。",
    }
    return fallbacks.get(knowledge_type, "知识资料")


def _quality_status(knowledge_type: str, extension: str, head: str) -> str:
    if knowledge_type in {"entity", "metric", "media", "outcome"}:
        return "ready"
    if extension.lower() in {".md", ".txt"} and head:
        thin, _ = is_shell_or_thin_text(head, min_chars=MIN_BODY_CHARS)
        if thin:
            return "needs_attention"
    return "ready"


def _preview_mode(extension: str) -> str:
    ext = extension.lower()
    if ext in _MEDIA_EXTENSIONS:
        return "image"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    return "download_only"


def _import_digest(name: str) -> str:
    match = _HASH_CAPTURE_RE.search(name)
    return match.group(1).lower() if match else ""


def _archived_sources(root: Path) -> dict[str, list[dict[str, Any]]]:
    archive = root / "_raw_archive"
    if not archive.is_dir():
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in archive.rglob("*"):
        if not path.is_file():
            continue
        digest = _import_digest(path.name)
        if not digest:
            continue
        stat = path.stat()
        grouped.setdefault(digest, []).append(
            {
                "path": path.relative_to(root).as_posix(),
                "name": path.name,
                "extension": path.suffix.lower(),
                "size": stat.st_size,
                "role": "original",
                "role_label": "原始文件",
            }
        )
    return grouped


def _catalog_item(
    root: Path,
    file: VaultFileInfo,
    archived_sources: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    raw = asdict(file)
    knowledge_type = knowledge_type_for(file.path, file.extension)
    head = _read_head(root, file.path, file.extension)
    title = _display_title(file.name, head)
    source_status = source_status_for(file.path)
    quality_status = _quality_status(knowledge_type, file.extension, head)
    digest = _import_digest(file.name)
    originals = list(archived_sources.get(digest) or [])
    processed_role = (
        ("structured_data", "问数数据")
        if file.extension in {".csv", ".tsv", ".xls", ".xlsx"}
        else (("searchable_text", "可检索文本") if file.extension in {".md", ".txt"} else ("file", "知识文件"))
    )
    files = [
        *originals,
        {
            "path": file.path,
            "name": file.name,
            "extension": file.extension,
            "size": file.size,
            "role": processed_role[0],
            "role_label": processed_role[1],
        },
    ]
    formats = list(dict.fromkeys([str(item.get("extension") or "other") for item in files]))
    return {
        **raw,
        "id": file.path,
        "title": title,
        "summary": _summary_for(knowledge_type, head),
        "knowledge_type": knowledge_type,
        "knowledge_type_label": KNOWLEDGE_TYPE_LABELS[knowledge_type],
        "source_status": source_status,
        "source_status_label": SOURCE_STATUS_LABELS[source_status],
        "quality_status": quality_status,
        "quality_status_label": QUALITY_STATUS_LABELS[quality_status],
        "business_tags": business_tags_for(file.path, title),
        "formats": formats,
        "files": files,
        "original_path": originals[0]["path"] if originals else None,
        "preview_mode": _preview_mode(file.extension),
    }


def group_catalog_outcomes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse multiple exports of one report into one logical knowledge item."""
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        if item.get("knowledge_type") != "outcome":
            key = f"item:{item.get('id') or item.get('path')}"
            grouped[key] = dict(item)
            order.append(key)
            continue
        path = Path(str(item.get("path") or ""))
        key = f"outcome:{path.parent.as_posix()}/{path.stem}"
        if key not in grouped:
            grouped[key] = dict(item)
            grouped[key]["formats"] = list(item.get("formats") or [])
            grouped[key]["files"] = list(item.get("files") or [])
            order.append(key)
            continue
        current = grouped[key]
        current["formats"] = sorted(set([*(current.get("formats") or []), *(item.get("formats") or [])]))
        current["files"] = [*(current.get("files") or []), *(item.get("files") or [])]
        current["size"] = int(current.get("size") or 0) + int(item.get("size") or 0)
        current["mtime"] = max(float(current.get("mtime") or 0), float(item.get("mtime") or 0))
        if item.get("extension") in {".md", ".txt"} and current.get("extension") not in {".md", ".txt"}:
            for field in (
                "id",
                "path",
                "name",
                "extension",
                "preview_mode",
                "summary",
            ):
                current[field] = item.get(field)
    return [grouped[key] for key in order]


def build_vault_catalog(*, force: bool = False) -> list[dict[str, Any]]:
    global _CACHE_SIGNATURE, _CACHE_ITEMS, _CACHE_BUILT_AT
    files = _catalog_files(force=force)
    signature = (
        len(files),
        max((item.mtime for item in files), default=0.0),
        sum(item.size for item in files),
    )
    if not force and _CACHE_ITEMS is not None and _CACHE_SIGNATURE == signature and time.time() - _CACHE_BUILT_AT < 30:
        return [dict(item) for item in _CACHE_ITEMS]
    root = ensure_vault()
    archived_sources = _archived_sources(root)
    items = group_catalog_outcomes(
        [_catalog_item(root, file, archived_sources) for file in files]
    )
    items.sort(key=lambda item: (-float(item.get("mtime") or 0), str(item.get("title"))))
    _CACHE_SIGNATURE = signature
    _CACHE_ITEMS = items
    _CACHE_BUILT_AT = time.time()
    return [dict(item) for item in items]


def query_vault_catalog(
    *,
    knowledge_type: str = "",
    source_status: str = "",
    quality_status: str = "",
    business_tag: str = "",
    q: str = "",
    limit: int = 500,
    offset: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    all_items = build_vault_catalog(force=force)
    type_counts = {key: 0 for key in KNOWLEDGE_TYPES}
    source_counts = {key: 0 for key in SOURCE_STATUS_LABELS}
    quality_counts = {key: 0 for key in QUALITY_STATUS_LABELS}
    business_counts: dict[str, int] = {}
    for item in all_items:
        type_counts[str(item["knowledge_type"])] += 1
        source_counts[str(item["source_status"])] += 1
        quality_counts[str(item["quality_status"])] += 1
        for tag in item.get("business_tags") or []:
            business_counts[str(tag)] = business_counts.get(str(tag), 0) + 1

    items = all_items
    if knowledge_type:
        items = [item for item in items if item["knowledge_type"] == knowledge_type]
    if source_status:
        items = [item for item in items if item["source_status"] == source_status]
    if quality_status:
        items = [item for item in items if item["quality_status"] == quality_status]
    if business_tag:
        items = [item for item in items if business_tag in item["business_tags"]]
    if q.strip():
        needle = q.strip().lower()
        items = [
            item
            for item in items
            if needle
            in " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("path") or ""),
                    " ".join(item.get("business_tags") or []),
                ]
            ).lower()
        ]
    filtered_total = len(items)
    page = items[offset : offset + limit]
    return {
        "items": page,
        "count": len(page),
        "total": len(all_items),
        "filtered_total": filtered_total,
        "offset": offset,
        "limit": limit,
        "type_counts": type_counts,
        "source_counts": source_counts,
        "quality_counts": quality_counts,
        "business_tag_counts": business_counts,
        "type_labels": KNOWLEDGE_TYPE_LABELS,
        "source_labels": SOURCE_STATUS_LABELS,
        "quality_labels": QUALITY_STATUS_LABELS,
    }
