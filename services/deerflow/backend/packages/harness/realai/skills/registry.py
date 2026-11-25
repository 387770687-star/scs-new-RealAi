"""RealAi Skill registry (P3) with DeerFlow-compatible layout."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from realai.skills.deerflow_bridge import (
    REALAI_PRESET_IDS,
    ensure_skills_layout,
    is_deerflow_builtin,
    read_skill_enabled,
    skill_file_mtime,
    unified_skills_root,
    write_skill_enabled,
)

SKILL_FILENAME = "SKILL.md"
SKILL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)", re.DOTALL)


@dataclass(slots=True)
class SkillRecord:
    id: str
    name: str
    description: str
    body: str
    valid: bool
    errors: list[str]
    raw: str
    category: str = "custom"
    enabled: bool = True
    version: str | None = None
    source: str = "realai"
    editable: bool = True
    read_only: bool = False


def skills_root() -> Path:
    ensure_skills_layout()
    return unified_skills_root()


def validate_skill_id(skill_id: str) -> None:
    if not SKILL_ID_RE.match(skill_id):
        raise ValueError("skill-id 仅允许小写字母、数字与连字符")


def parse_skill_markdown(text: str, *, skill_id: str = "") -> SkillRecord:
    errors: list[str] = []
    meta: dict = {}
    body = text
    m = FRONTMATTER_RE.match(text.strip() + ("\n" if not text.endswith("\n") else ""))
    if not m:
        errors.append("缺少 YAML frontmatter（---）")
    else:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as exc:
            errors.append(f"frontmatter 解析失败: {exc}")
            meta = {}
        body = m.group(2).strip()

    name = str(meta.get("name") or skill_id or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name:
        errors.append("缺少 name")
    if not description:
        errors.append("缺少 description")
    if not body.strip():
        errors.append("正文不能为空")

    return SkillRecord(
        id=skill_id or name,
        name=name,
        description=description,
        body=body,
        valid=len(errors) == 0,
        errors=errors,
        raw=text,
    )


def has_executable_content(body: str) -> bool:
    """Return true when a Skill body contains more than Markdown section shells."""
    content = re.sub(r"(?m)^\s{0,3}#{1,6}\s+.*$", "", body or "")
    content = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s*$", "", content)
    content = re.sub(r"[\s`*_>#-]+", "", content)
    return bool(content)


def _iter_skill_locations() -> list[tuple[str, Path]]:
    root = skills_root()
    found: list[tuple[str, Path]] = []
    for category in ("public", "custom"):
        cat = root / category
        if not cat.is_dir():
            continue
        for d in sorted(cat.iterdir()):
            if d.is_dir() and (d / SKILL_FILENAME).is_file():
                found.append((category, d))
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name in {"public", "custom", "legacy"}:
            continue
        if (d / SKILL_FILENAME).is_file():
            found.append(("legacy", d))
    return found


def _skill_path(skill_id: str) -> Path | None:
    root = skills_root()
    for cat in ("public", "custom", "legacy"):
        path = root / cat / skill_id / SKILL_FILENAME
        if path.is_file():
            return path
    legacy = root / skill_id / SKILL_FILENAME
    return legacy if legacy.is_file() else None


def _skill_category(skill_id: str) -> str:
    root = skills_root()
    for cat in ("public", "custom", "legacy"):
        if (root / cat / skill_id / SKILL_FILENAME).is_file():
            return cat
    if (root / skill_id / SKILL_FILENAME).is_file():
        return "legacy"
    return "custom"


def _history_path(skill_id: str) -> Path:
    return skills_root() / "custom" / ".history" / f"{skill_id}.jsonl"


def append_skill_history(skill_id: str, entry: dict) -> None:
    path = _history_path(skill_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(tz=UTC).isoformat(), **entry}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def list_skill_history(skill_id: str, *, limit: int = 20) -> list[dict]:
    path = _history_path(skill_id)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _enrich_record(rec: SkillRecord, *, category: str, path: Path) -> SkillRecord:
    rec.category = category
    rec.version = skill_file_mtime(path)
    rec.enabled = read_skill_enabled(rec.id, default=True)
    if is_deerflow_builtin(rec.id, category=category):
        rec.source = "deerflow"
        rec.editable = False
        rec.read_only = True
    else:
        rec.source = "realai"
        rec.editable = True
        rec.read_only = False
    return rec


def list_skills(*, include_deerflow: bool = False) -> list[SkillRecord]:
    ensure_skills_layout()
    out: list[SkillRecord] = []
    seen: set[str] = set()
    for category, folder in _iter_skill_locations():
        if folder.name in seen:
            continue
        text = (folder / SKILL_FILENAME).read_text(encoding="utf-8")
        rec = parse_skill_markdown(text, skill_id=folder.name)
        out.append(_enrich_record(rec, category=category, path=folder / SKILL_FILENAME))
        seen.add(rec.id)

    if include_deerflow:
        from realai.skills.deerflow_bridge import list_deerflow_skills

        for item in list_deerflow_skills():
            if item["id"] in seen:
                continue
            out.append(
                SkillRecord(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    body="",
                    valid=item["valid"],
                    errors=item["errors"],
                    raw="",
                    category=item["category"],
                    enabled=item["enabled"],
                    version=item.get("version"),
                    source="deerflow",
                    editable=False,
                    read_only=True,
                )
            )
            seen.add(item["id"])
    return out


def get_skill(skill_id: str) -> SkillRecord | None:
    validate_skill_id(skill_id)
    path = _skill_path(skill_id)
    if path is None:
        return None
    category = _skill_category(skill_id)
    rec = parse_skill_markdown(path.read_text(encoding="utf-8"), skill_id=skill_id)
    return _enrich_record(rec, category=category, path=path)


def save_skill(
    skill_id: str,
    *,
    name: str,
    description: str,
    body: str,
    category: str = "custom",
    overwrite: bool = True,
) -> SkillRecord:
    validate_skill_id(skill_id)
    existing_path = _skill_path(skill_id)
    existing_cat = _skill_category(skill_id) if existing_path else category
    if is_deerflow_builtin(skill_id, category=existing_cat):
        raise ValueError("系统内置 Skill 只读，不可修改")
    if existing_path is not None and not overwrite:
        raise FileExistsError(f"Skill '{skill_id}' 已存在")
    if not name.strip():
        raise ValueError("name 不能为空")
    if not description.strip():
        raise ValueError("description 不能为空")
    if not body.strip():
        raise ValueError("正文不能为空")
    if not has_executable_content(body):
        raise ValueError("正文需要包含实际执行内容，不能只有章节标题")

    frontmatter = yaml.safe_dump({"name": name.strip(), "description": description.strip()}, allow_unicode=True).strip()
    raw = f"---\n{frontmatter}\n---\n\n{body.strip()}\n"
    rec = parse_skill_markdown(raw, skill_id=skill_id)
    if not rec.valid:
        raise ValueError("；".join(rec.errors))

    if skill_id in REALAI_PRESET_IDS:
        category = "public"
    dest = skills_root() / category / skill_id
    dest.mkdir(parents=True, exist_ok=True)
    prev = (dest / SKILL_FILENAME).read_text(encoding="utf-8") if (dest / SKILL_FILENAME).is_file() else None
    (dest / SKILL_FILENAME).write_text(raw, encoding="utf-8")
    if category == "custom":
        append_skill_history(
            skill_id,
            {
                "action": "save",
                "prev_content": prev,
                "new_content": raw,
            },
        )

    from realai.skills.deerflow_bridge import refresh_deerflow_skill_cache

    refresh_deerflow_skill_cache()
    return _enrich_record(rec, category=category, path=dest / SKILL_FILENAME)


def set_skill_enabled(skill_id: str, enabled: bool) -> None:
    validate_skill_id(skill_id)
    if get_skill(skill_id) is None:
        raise FileNotFoundError(skill_id)
    write_skill_enabled(skill_id, enabled)
    from realai.skills.deerflow_bridge import refresh_deerflow_skill_cache

    refresh_deerflow_skill_cache()


def delete_skill(skill_id: str) -> None:
    validate_skill_id(skill_id)
    category = _skill_category(skill_id)
    if is_deerflow_builtin(skill_id, category=category):
        raise ValueError("系统内置 Skill 不可删除，可改为停用")
    if category == "legacy":
        dest = skills_root() / skill_id
    else:
        dest = skills_root() / category / skill_id
    if not dest.is_dir():
        raise FileNotFoundError(skill_id)
    from realai.skills.deerflow_bridge import mark_skill_removed

    mark_skill_removed(skill_id)
    shutil.rmtree(dest)
    history_path = _history_path(skill_id)
    if history_path.is_file():
        history_path.unlink()
    from realai.skills.deerflow_bridge import refresh_deerflow_skill_cache

    refresh_deerflow_skill_cache()


def import_skill_folder(skill_id: str, skill_md: str) -> SkillRecord:
    rec = parse_skill_markdown(skill_md, skill_id=skill_id)
    if not rec.valid:
        raise ValueError("；".join(rec.errors))
    return save_skill(skill_id, name=rec.name, description=rec.description, body=rec.body, category="custom")


_SKIP_DIR_NAMES = frozenset({".git", "__pycache__", "node_modules", ".history"})
_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".py",
        ".js",
        ".ts",
        ".mjs",
        ".cjs",
        ".html",
        ".htm",
        ".css",
        ".sh",
        ".bash",
        ".csv",
        ".tsv",
        ".toml",
        ".ini",
        ".xml",
        ".svg",
        ".vue",
        ".jsx",
        ".tsx",
        ".r",
        ".sql",
        ".prompt",
        ".tmpl",
        ".template",
    }
)
_MAX_PREVIEW_BYTES = 512_000


def skill_package_dir(skill_id: str) -> Path | None:
    """Resolve skill folder containing SKILL.md."""
    validate_skill_id(skill_id)
    path = _skill_path(skill_id)
    if path is not None:
        return path.parent
    # DeerFlow builtins may live under unified public even when get_skill path differs
    for cat in ("public", "custom", "legacy"):
        d = skills_root() / cat / skill_id
        if d.is_dir() and (d / SKILL_FILENAME).is_file():
            return d
    return None


def _classify_skill_file(rel: str) -> str:
    norm = rel.replace("\\", "/")
    name = Path(norm).name
    if name == SKILL_FILENAME and "/" not in norm:
        return "main"
    top = norm.split("/", 1)[0].lower()
    if top in {"references", "reference", "refs", "docs"}:
        return "reference"
    if top in {"scripts", "script", "bin", "tools"}:
        return "script"
    if top in {"templates", "template", "tmpl"}:
        return "template"
    if top in {"assets", "static", "media", "images"}:
        return "asset"
    if name.lower().endswith((".py", ".js", ".ts", ".sh", ".mjs")):
        return "script"
    if "template" in name.lower() or name.lower().endswith((".tmpl", ".template")):
        return "template"
    return "other"


def list_skill_package_files(skill_id: str) -> list[dict]:
    """List files in a skill package (relative paths)."""
    root = skill_package_dir(skill_id)
    if root is None:
        return []
    items: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name.startswith(".") and path.name != SKILL_FILENAME:
            continue
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        suffix = path.suffix.lower()
        kind = _classify_skill_file(rel)
        items.append(
            {
                "path": rel,
                "size": size,
                "kind": kind,
                "text": suffix in _TEXT_SUFFIXES or path.name.upper() == SKILL_FILENAME,
            }
        )
    # main first, then by kind, then path
    order = {"main": 0, "reference": 1, "template": 2, "script": 3, "asset": 4, "other": 5}
    items.sort(key=lambda x: (order.get(str(x["kind"]), 9), str(x["path"])))
    return items


def read_skill_package_file(skill_id: str, rel_path: str) -> dict:
    """Read one package file; rejects path traversal."""
    root = skill_package_dir(skill_id)
    if root is None:
        raise FileNotFoundError(skill_id)
    raw = (rel_path or "").replace("\\", "/").lstrip("/")
    if not raw or ".." in raw.split("/"):
        raise ValueError("非法文件路径")
    target = (root / raw).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("非法文件路径") from exc
    if not target.is_file():
        raise FileNotFoundError(raw)
    size = target.stat().st_size
    kind = _classify_skill_file(raw)
    is_text = target.suffix.lower() in _TEXT_SUFFIXES or target.name.upper() == SKILL_FILENAME
    if not is_text:
        return {
            "path": raw,
            "size": size,
            "kind": kind,
            "text": False,
            "content": None,
            "message": "二进制或不支持预览的文件类型",
        }
    if size > _MAX_PREVIEW_BYTES:
        return {
            "path": raw,
            "size": size,
            "kind": kind,
            "text": True,
            "content": None,
            "message": f"文件过大（>{_MAX_PREVIEW_BYTES // 1024}KB），请在磁盘打开",
        }
    content = target.read_text(encoding="utf-8", errors="replace")
    return {
        "path": raw,
        "size": size,
        "kind": kind,
        "text": True,
        "content": content,
        "message": None,
    }
