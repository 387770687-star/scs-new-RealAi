"""Import Office/PDF/CSV into classified Vault folders with cleaning."""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
from realai.vault.classify import CATEGORIES, classify_file
from realai.vault.clean_table import clean_csv_bytes
from realai.vault.content_quality import (
    content_sha1,
    find_existing_by_content_hash,
    is_shell_or_thin_text,
)
from realai.vault.service import delete_vault_file, write_vault_file

logger = logging.getLogger(__name__)

TABLE_EXTENSIONS = {".csv", ".xlsx", ".xls"}
TEXT_PASSTHROUGH = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".htm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PRESERVE_SOURCE_EXTENSIONS = set(CONVERTIBLE_EXTENSIONS) | {".csv", ".tsv"}
ImportProgressCallback = Callable[[str, int, str], Awaitable[None] | None]


class ImportResult:
    __slots__ = (
        "success",
        "vault_path",
        "message",
        "markdown_path",
        "table_path",
        "table_paths",
        "source_path",
        "category",
        "category_source",
        "dropped_columns",
        "skipped_duplicate",
        "vision_preanalyze",
        "table_metadata",
    )

    def __init__(
        self,
        *,
        success: bool,
        vault_path: str | None = None,
        message: str = "",
        markdown_path: str | None = None,
        table_path: str | None = None,
        table_paths: list[str] | None = None,
        source_path: str | None = None,
        category: str | None = None,
        category_source: str | None = None,
        dropped_columns: list[str] | None = None,
        skipped_duplicate: bool = False,
        vision_preanalyze: dict | None = None,
        table_metadata: dict[str, dict[str, Any]] | None = None,
    ):
        self.success = success
        self.vault_path = vault_path
        self.message = message
        self.markdown_path = markdown_path
        self.table_path = table_path
        self.table_paths = list(dict.fromkeys(table_paths or ([table_path] if table_path else [])))
        self.source_path = source_path
        self.category = category
        self.category_source = category_source
        self.dropped_columns = dropped_columns or []
        self.skipped_duplicate = skipped_duplicate
        self.vision_preanalyze = vision_preanalyze
        self.table_metadata = table_metadata or {}

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "vault_path": self.vault_path,
            "markdown_path": self.markdown_path,
            "table_path": self.table_path,
            "table_paths": self.table_paths,
            "source_path": self.source_path,
            "category": self.category,
            "category_source": self.category_source,
            "dropped_columns": self.dropped_columns,
            "skipped_duplicate": self.skipped_duplicate,
            "vision_preanalyze": self.vision_preanalyze,
            "table_metadata": self.table_metadata,
            "message": self.message,
        }


def _rel_name(category: str, filename: str, data: bytes, *, suffix: str | None = None) -> str:
    digest = hashlib.sha1(data).hexdigest()[:8]
    stem = Path(filename).stem or "upload"
    ext = suffix if suffix is not None else Path(filename).suffix
    cat = category if category in CATEGORIES else "pipelines"
    return f"{cat}/{stem}-{digest}{ext}".replace("\\", "/")


def _source_rel_name(category: str, filename: str, data: bytes) -> str:
    """Stable, non-indexed location for the exact uploaded bytes."""
    digest = hashlib.sha1(data).hexdigest()[:8]
    stem = Path(filename).stem or "upload"
    ext = Path(filename).suffix.lower()
    cat = category if category in CATEGORIES else "pipelines"
    return f"_raw_archive/{cat}/{stem}-{digest}{ext}".replace("\\", "/")


async def _report_progress(
    callback: ImportProgressCallback | None,
    stage: str,
    progress: int,
    message: str,
) -> None:
    if callback is None:
        return
    result = callback(stage, max(0, min(100, int(progress))), message)
    if result is not None:
        await result


def _reject_thin_markdown(md: str) -> ImportResult | None:
    reject, reason = is_shell_or_thin_text(md)
    if reject:
        return ImportResult(success=False, message=f"内容质量不达标，未写入 Vault：{reason}")
    return None


def _check_duplicate(data: bytes, *, source_path: str | None = None) -> ImportResult | None:
    digest = content_sha1(data)
    existing = find_existing_by_content_hash(digest)
    if existing:
        return ImportResult(
            success=True,
            vault_path=existing,
            source_path=source_path,
            skipped_duplicate=True,
            message=f"内容已存在，跳过重复导入：{existing}",
        )
    return None


async def import_file_to_vault(
    filename: str,
    data: bytes,
    *,
    target_dir: str | None = None,
    source_hint: str | None = None,
    run_wiki: bool = True,
    on_progress: ImportProgressCallback | None = None,
) -> ImportResult:
    ext = Path(filename).suffix.lower()
    await _report_progress(on_progress, "validating", 3, "正在校验文件")
    if not ext:
        return ImportResult(success=False, message="文件缺少扩展名")
    if not data:
        return ImportResult(success=False, message="空文件")

    hint = target_dir.strip().strip("/\\") if target_dir else None
    if hint and hint not in CATEGORIES:
        if hint.startswith("imports"):
            hint = None
        elif hint not in CATEGORIES:
            hint = None

    await _report_progress(on_progress, "classifying", 8, "正在识别文件类型和业务分类")
    clf = classify_file(filename, data, hint_category=hint, source_hint=source_hint)
    category = clf.category
    safe_name = Path(filename).name
    written: list[str] = []
    source_rel: str | None = None

    try:
        if ext in PRESERVE_SOURCE_EXTENSIONS:
            await _report_progress(on_progress, "preserving", 12, "正在保存原始文件")
            source_rel = _source_rel_name(category, filename, data)
            write_vault_file(source_rel, data)
            written.append(source_rel)

        dup = _check_duplicate(data, source_path=source_rel)
        if dup:
            await _report_progress(on_progress, "completed", 100, "内容已存在，已补充原始文件")
            return dup

        # --- CSV: clean + write table ---
        if ext == ".csv":
            await _report_progress(on_progress, "extracting", 28, "正在识别表头和清洗数据")
            cleaned = clean_csv_bytes(data)
            rel = _rel_name(category, filename, data, suffix=".csv")
            write_vault_file(rel, cleaned.csv_text)
            written.append(rel)
            result = ImportResult(
                success=True,
                vault_path=rel,
                table_path=rel,
                source_path=source_rel,
                category=category,
                category_source=clf.source,
                dropped_columns=cleaned.dropped_columns,
                message=f"已清洗写入 {category}" + (f"（丢弃列: {', '.join(cleaned.dropped_columns)}）" if cleaned.dropped_columns else ""),
            )
            if run_wiki:
                await _report_progress(on_progress, "indexing", 82, "正在生成知识卡片和检索索引")
                await _maybe_wiki_after_import(result)
            await _report_progress(on_progress, "completed", 100, "导入完成")
            return result

        # --- Excel: convert md + keep cleaned csv sidecar for 问数 ---
        if ext in {".xlsx", ".xls"}:
            await _report_progress(on_progress, "extracting", 22, "正在读取 Excel 工作表")
            md_rel = None
            table_paths: list[str] = []
            dropped: list[str] = []
            table_metadata: dict[str, dict[str, Any]] = {}
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / safe_name
                src.write_bytes(data)
                await _report_progress(on_progress, "converting", 38, "正在提取表格说明和文本")
                md_path = await convert_file_to_markdown(src)
                if md_path is not None and md_path.is_file():
                    md = md_path.read_text(encoding="utf-8", errors="replace")
                    # Excel md is optional; table is primary for 问数 — skip thin shells
                    if not is_shell_or_thin_text(md)[0]:
                        md_rel = _rel_name(category, filename, data, suffix=".md")
                        write_vault_file(md_rel, md)
                        written.append(md_rel)
                await _report_progress(on_progress, "structuring", 58, "正在生成可精确问数的数据表")
                table_paths, dropped, table_metadata = _excel_to_cleaned_csvs(
                    src,
                    category,
                    filename,
                    data,
                )
                written.extend(table_paths)
            table_rel = table_paths[0] if table_paths else None
            if not md_rel and not table_paths:
                return ImportResult(success=False, message="Excel 解析失败，未写入 Vault")
            result = ImportResult(
                success=True,
                vault_path=table_rel or md_rel,
                markdown_path=md_rel,
                table_path=table_rel,
                table_paths=table_paths,
                source_path=source_rel,
                category=category,
                category_source=clf.source,
                dropped_columns=dropped,
                table_metadata=table_metadata,
                message=(f"Excel 已写入 {category}" + (f"（已解析 {len(table_paths)} 个工作表）" if table_paths else "")),
            )
            try:
                from realai.data.table_catalog import refresh_catalog_paths

                refresh_catalog_paths(
                    table_paths,
                    metadata_by_path=table_metadata,
                )
            except Exception:
                logger.debug("table catalog refresh skipped", exc_info=True)
            if run_wiki:
                await _report_progress(on_progress, "indexing", 82, "正在生成知识卡片和检索索引")
                await _maybe_wiki_after_import(result)
            await _report_progress(on_progress, "completed", 100, "导入完成")
            return result

        # --- Images: store under figures/ + optional vision preanalyze ---
        if ext in IMAGE_EXTENSIONS:
            await _report_progress(on_progress, "storing", 30, "正在保存图片")
            digest = hashlib.sha1(data).hexdigest()[:8]
            stem = Path(filename).stem or "image"
            rel = f"figures/{stem}-{digest}{ext}".replace("\\", "/")
            write_vault_file(rel, data)
            written.append(rel)
            viz_info = None
            try:
                from realai.agents.vision import preanalyze_imported_image

                viz_info = await preanalyze_imported_image(rel)
            except Exception as exc:
                logger.warning("vision preanalyze skipped: %s", exc)
                viz_info = {"ok": False, "reason": str(exc), "path": rel}
            msg = "图片已写入 figures/"
            if viz_info and viz_info.get("ok"):
                msg += "，并已预识图写入 wiki/viz"
            elif viz_info and viz_info.get("skipped"):
                msg += "（未预识图：无 API Key）"
            elif viz_info and not viz_info.get("ok"):
                msg += f"（预识图失败：{viz_info.get('reason') or '未知'}）"
            result = ImportResult(
                success=True,
                vault_path=rel,
                category="figures",
                category_source="image",
                message=msg,
                vision_preanalyze=viz_info,
            )
            if run_wiki:
                await _report_progress(on_progress, "indexing", 82, "正在生成知识卡片和检索索引")
                await _maybe_wiki_after_import(result)
            await _report_progress(on_progress, "completed", 100, "导入完成")
            return result

        # --- PDF / Word / PPT → md ---
        if ext in CONVERTIBLE_EXTENSIONS:
            await _report_progress(on_progress, "extracting", 25, "正在提取原文内容")
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / safe_name
                src.write_bytes(data)
                md_path = await convert_file_to_markdown(src)
                if md_path is None or not md_path.is_file():
                    return ImportResult(success=False, message="解析失败，未写入 Vault")
                md = md_path.read_text(encoding="utf-8", errors="replace")
            thin = _reject_thin_markdown(md)
            if thin:
                return thin
            md_rel = _rel_name(category, filename, data, suffix=".md")
            await _report_progress(on_progress, "storing", 68, "正在保存可检索文本")
            write_vault_file(md_rel, md)
            written.append(md_rel)
            result = ImportResult(
                success=True,
                vault_path=md_rel,
                markdown_path=md_rel,
                source_path=source_rel,
                category=category,
                category_source=clf.source,
                message=f"已解析并写入 {category}",
            )
            if run_wiki:
                await _report_progress(on_progress, "indexing", 82, "正在生成知识卡片和检索索引")
                await _maybe_wiki_after_import(result)
            await _report_progress(on_progress, "completed", 100, "导入完成")
            return result

        # --- text / html passthrough ---
        if ext in TEXT_PASSTHROUGH:
            await _report_progress(on_progress, "extracting", 30, "正在读取文本内容")
            if ext in {".html", ".htm"}:
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        src = Path(tmp) / safe_name
                        src.write_bytes(data)
                        md_path = await convert_file_to_markdown(src)
                        if md_path is not None and md_path.is_file():
                            md = md_path.read_text(encoding="utf-8", errors="replace")
                            thin = _reject_thin_markdown(md)
                            if thin:
                                return thin
                            md_rel = _rel_name(category, filename, data, suffix=".md")
                            write_vault_file(md_rel, md)
                            result = ImportResult(
                                success=True,
                                vault_path=md_rel,
                                markdown_path=md_rel,
                                source_path=source_rel,
                                category=category,
                                category_source=clf.source,
                                message=f"HTML 已转 Markdown 写入 {category}",
                            )
                            if run_wiki:
                                await _report_progress(on_progress, "indexing", 82, "正在生成知识卡片和检索索引")
                                await _maybe_wiki_after_import(result)
                            await _report_progress(on_progress, "completed", 100, "导入完成")
                            return result
                except Exception:
                    logger.exception("html convert failed")
                # Do not write raw HTML into searchable vault
                return ImportResult(
                    success=False,
                    message="HTML 转换失败或正文过短，未写入 Vault（禁止原文 HTML 入库）",
                )

            text = data.decode("utf-8", errors="replace")
            if ext == ".md":
                thin = _reject_thin_markdown(text)
                if thin:
                    return thin
            rel = _rel_name(category, filename, data)
            write_vault_file(rel, text)
            result = ImportResult(
                success=True,
                vault_path=rel,
                markdown_path=rel if ext == ".md" else None,
                source_path=source_rel,
                category=category,
                category_source=clf.source,
                message=f"已写入 {category}",
            )
            if run_wiki:
                await _report_progress(on_progress, "indexing", 82, "正在生成知识卡片和检索索引")
                await _maybe_wiki_after_import(result)
            await _report_progress(on_progress, "completed", 100, "导入完成")
            return result

        rel = _rel_name(category, filename, data)
        await _report_progress(on_progress, "storing", 62, "正在保存文件")
        write_vault_file(rel, data)
        result = ImportResult(
            success=True,
            vault_path=rel,
            source_path=source_rel,
            category=category,
            category_source=clf.source,
            message=f"已保存原文件到 {category}（未转换为 Markdown）",
        )
        await _report_progress(on_progress, "completed", 100, "导入完成")
        return result
    except Exception as exc:
        logger.exception("import failed for %s", filename)
        for rel in written:
            try:
                delete_vault_file(rel)
            except Exception:
                pass
        return ImportResult(success=False, message=f"解析失败，未写入 Vault：{exc}")


def _safe_sheet_name(value: str) -> str:
    safe = re.sub(r"[\s/\\:*?\"<>|]+", "_", (value or "").strip())
    safe = safe.strip("._")
    return (safe or "Sheet")[:48]


def _detect_header_position(frame: Any) -> int:
    """Pick a likely header from the first rows of a raw worksheet."""
    best_position = 0
    best_score = float("-inf")
    for position in range(min(len(frame.index), 30)):
        values = [value for value in frame.iloc[position].tolist() if str(value).strip() and str(value) != "nan"]
        if not values:
            continue
        texts = sum(not isinstance(value, (int, float)) for value in values)
        numeric = len(values) - texts
        unique = len({str(value).strip() for value in values})
        score = len(values) * 2 + texts * 2 + unique - numeric
        if score > best_score:
            best_score = score
            best_position = position
    return best_position


def _worksheet_semantic(
    raw: Any,
    *,
    header_position: int,
    sheet_name: str,
    columns: list[str],
) -> dict[str, Any]:
    import pandas as pd

    preamble: list[str] = []
    for row_index in range(header_position):
        for value in raw.iloc[row_index].tolist():
            if pd.isna(value):
                continue
            text = str(value).replace("\n", " ").strip()
            if text and text.lower() != "nan":
                preamble.append(text)

    unit: str | None = None
    for text in preamble:
        matched = re.search(r"单位\s*[:：]\s*(.+)$", text)
        if matched:
            unit = matched.group(1).strip(" ，,；;")
            break

    title_candidates = [
        text
        for text in preamble
        if not re.match(r"^\s*单位\s*[:：]", text)
    ]
    title = max(title_candidates, key=len) if title_candidates else Path(sheet_name).stem
    year_columns = [
        column
        for column in columns
        if re.fullmatch(r"(?:19|20)\d{2}年?", column.strip())
    ]
    long_year_columns = [
        column
        for column in columns
        if column.strip().lower() in {"year", "yr", "年份", "年度"}
    ]
    if len(year_columns) >= 2:
        layout = "wide_year"
    elif long_year_columns:
        layout = "long_year"
    else:
        layout = "tabular"
    dimension_columns = [
        column
        for column in columns
        if column not in year_columns
        and any(
            token in column.lower()
            for token in ("地区", "省", "市", "名称", "项目", "类别", "类型", "region", "name")
        )
    ]
    return {
        "title": title,
        "sheet_name": sheet_name,
        "unit": unit,
        "layout": layout,
        "year_columns": year_columns,
        "dimension_columns": dimension_columns,
        "aliases": list(dict.fromkeys([title, sheet_name])),
    }


def _worksheet_frame(excel: Any, sheet_name: str) -> tuple[Any | None, dict[str, Any]]:
    import pandas as pd

    raw = pd.read_excel(excel, sheet_name=sheet_name, header=None, dtype=object)
    if raw is None or raw.empty:
        return None, {}
    raw = raw.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if raw.empty:
        return None, {}
    header_position = _detect_header_position(raw)
    header_values = raw.iloc[header_position].tolist()
    columns: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(header_values):
        name = "" if pd.isna(value) else str(value).replace("\n", " ").strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"列{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        columns.append(name)
    frame = raw.iloc[header_position + 1 :].copy()
    frame.columns = columns
    frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
    semantic = _worksheet_semantic(
        raw,
        header_position=header_position,
        sheet_name=sheet_name,
        columns=list(frame.columns),
    )
    return (None if frame.empty else frame), semantic


def _excel_to_cleaned_csvs(
    src: Path,
    category: str,
    filename: str,
    data: bytes,
) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
    try:
        import pandas as pd

        engine = "xlrd" if src.suffix.lower() == ".xls" else "openpyxl"
        excel = pd.ExcelFile(src, engine=engine)
        nonempty: list[tuple[str, Any, dict[str, Any]]] = []
        for sheet_name in excel.sheet_names:
            frame, semantic = _worksheet_frame(excel, sheet_name)
            if frame is not None:
                nonempty.append((sheet_name, frame, semantic))
        if not nonempty:
            return [], [], {}

        digest = hashlib.sha1(data).hexdigest()[:8]
        stem = Path(filename).stem or "upload"
        cat = category if category in CATEGORIES else "pipelines"
        multiple = len(nonempty) > 1
        paths: list[str] = []
        dropped_all: list[str] = []
        metadata_by_path: dict[str, dict[str, Any]] = {}
        for sheet_name, frame, semantic in nonempty:
            cleaned = clean_csv_bytes(frame.to_csv(index=False).encode("utf-8"))
            if cleaned.row_count < 1:
                continue
            if multiple:
                sheet = _safe_sheet_name(sheet_name)
                rel = f"{cat}/{stem}__{sheet}-{digest}.csv".replace("\\", "/")
            else:
                rel = _rel_name(category, filename, data, suffix=".csv")
            write_vault_file(rel, cleaned.csv_text)
            paths.append(rel)
            metadata_by_path[rel] = semantic
            dropped_all.extend(cleaned.dropped_columns)
        return paths, list(dict.fromkeys(dropped_all)), metadata_by_path
    except Exception as exc:
        logger.warning("excel→csv failed: %s", exc)
        return [], [], {}


def _excel_to_cleaned_csv(src: Path, category: str, filename: str, data: bytes) -> tuple[str | None, list[str]]:
    """Compatibility wrapper for callers that only expect the first worksheet."""
    paths, dropped, _metadata = _excel_to_cleaned_csvs(src, category, filename, data)
    return (paths[0] if paths else None), dropped


async def _maybe_wiki_after_import(result: ImportResult) -> None:
    if not result.success or not result.vault_path or result.skipped_duplicate:
        return
    try:
        from realai.vault.wiki.pipeline import process_imported_paths

        paths = [
            *result.table_paths,
            *[p for p in (result.markdown_path, result.vault_path) if p],
        ]
        await process_imported_paths(list(dict.fromkeys(paths)))
    except Exception:
        logger.exception("wiki post-import failed (non-fatal)")
    try:
        from realai.data.table_catalog import refresh_catalog_paths

        paths = [*result.table_paths, *[p for p in (result.vault_path,) if p]]
        refresh_catalog_paths(
            list(dict.fromkeys(paths)),
            metadata_by_path=result.table_metadata,
        )
    except Exception:
        logger.debug("table catalog refresh skipped", exc_info=True)


async def finalize_batch_wiki(paths: list[str]) -> dict:
    """Run entity/wiki/graph once after a batch of imports (run_wiki=False per file)."""
    clean = list(dict.fromkeys([p.replace("\\", "/") for p in paths if p]))
    if not clean:
        return {"entities_written": 0, "docs_linked": 0, "wiki_cards": 0}
    from realai.vault.wiki.pipeline import process_imported_paths

    result = await process_imported_paths(clean)
    try:
        from realai.data.table_catalog import refresh_catalog_paths

        refresh_catalog_paths(clean)
    except Exception:
        logger.debug("table catalog refresh skipped", exc_info=True)
    return result


async def import_from_raw_tree(
    *,
    raw_root: Path | None = None,
    run_wiki: bool = True,
) -> dict:
    """Scan raw/raw/{pipelines,new_energy,dataqa} and import each file."""
    from realai.paths import get_repo_root

    # Prefer vault/raw/raw; fall back to repo raw/raw for legacy layouts
    root = raw_root
    if root is None:
        vault_raw = None
        try:
            from realai.vault.service import ensure_vault

            vault_raw = ensure_vault() / "raw" / "raw"
        except Exception:
            vault_raw = None
        repo_raw = get_repo_root() / "raw" / "raw"
        if vault_raw and vault_raw.is_dir():
            root = vault_raw
        else:
            root = repo_raw

    if not root.is_dir():
        return {"success": False, "message": f"未找到 raw 目录: {root}", "items": []}

    items: list[dict] = []
    written_paths: list[str] = []
    for cat in CATEGORIES:
        cat_dir = root / cat
        if not cat_dir.is_dir():
            continue
        for p in sorted(cat_dir.rglob("*")):
            if not p.is_file():
                continue
            if p.name.startswith("."):
                continue
            data = p.read_bytes()
            rel_hint = p.relative_to(root).as_posix()
            result = await import_file_to_vault(
                p.name,
                data,
                target_dir=cat,
                source_hint=rel_hint,
                run_wiki=False,  # defer wiki/graph to batch end
            )
            items.append({"source": rel_hint, **result.to_dict()})
            if result.success and not result.skipped_duplicate:
                for key in (
                    *result.table_paths,
                    result.markdown_path,
                    result.vault_path,
                ):
                    if key:
                        written_paths.append(key)

    wiki_result: dict = {}
    if run_wiki and written_paths:
        try:
            wiki_result = await finalize_batch_wiki(written_paths)
        except Exception as exc:
            logger.exception("batch wiki failed")
            wiki_result = {"error": str(exc)}

    ok = sum(1 for i in items if i.get("success"))
    return {
        "success": True,
        "message": f"完成 {ok}/{len(items)}",
        "total": len(items),
        "ok": ok,
        "items": items,
        "wiki": wiki_result,
        "raw_root": str(root),
    }
