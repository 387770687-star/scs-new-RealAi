"""Bridge RealAi Skill storage with DeerFlow skill runtime."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from realai.config import get_app_root, get_repo_root
from realai.paths import ensure_data_layout, get_data_root

logger = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"
REALAI_PRESET_IDS = frozenset(
    {
        "weekly-digest",
        "document-highlights",
        "pipeline-asset-intro",
        "web-search",
        "strategic-planning-intake",
        "strategic-planning-researcher",
        "strategic-planning-architect",
        "strategic-planning-writer",
        "strategic-planning-citer",
        "strategic-planning-reviewer",
        "strategic-planning-optimizer",
    }
)


def unified_skills_root() -> Path:
    ensure_data_layout()
    root = get_data_root() / "skills"
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "custom").mkdir(parents=True, exist_ok=True)
    return root


def vendor_public_skills_dir() -> Path:
    """Bundled public skills shipped with the app (may include RealAi presets)."""
    app = get_app_root()
    candidates = [
        app / "skills" / "public",
        get_repo_root() / "skills" / "public",
    ]
    for bundled in candidates:
        if bundled.is_dir() and any(bundled.iterdir()):
            return bundled
    return deerflow_upstream_public_dir()


def deerflow_upstream_public_dir() -> Path:
    """DeerFlow upstream public skills only (English built-ins).

    不依赖 cwd：优先相对本文件定位 …/services/deerflow/skills/public，
    避免 REALAI_* 未设置时路径变成 services/services/deerflow/... 导致内置检测全失败。
    """
    here = Path(__file__).resolve()
    # …/backend/packages/harness/realai/skills/deerflow_bridge.py → deerflow 根 = parents[5]
    by_file = here.parents[5] / "skills" / "public"
    candidates = [
        by_file,
        get_app_root() / "services" / "deerflow" / "skills" / "public",
        get_repo_root() / "services" / "deerflow" / "skills" / "public",
        get_app_root() / "skills" / "public",  # app_root 已是 deerflow 时
    ]
    for c in candidates:
        try:
            if c.is_dir() and any((c / d.name / SKILL_FILENAME).is_file() for d in c.iterdir() if d.is_dir()):
                return c
        except OSError:
            continue
    return by_file


def is_realai_project_skill(skill_id: str, *, category: str = "public") -> bool:
    """RealAi-owned skills: presets + user custom/legacy."""
    if skill_id in REALAI_PRESET_IDS:
        return True
    return category in {"custom", "legacy"}


def is_deerflow_builtin(skill_id: str, *, category: str = "public") -> bool:
    """True for DeerFlow upstream public skills (excludes RealAi presets/custom)."""
    if is_realai_project_skill(skill_id, category=category):
        return False
    upstream = deerflow_upstream_public_dir() / skill_id
    return (upstream / SKILL_FILENAME).is_file()


def migrate_legacy_flat_skills() -> list[str]:
    """Move legacy flat skills/<id>/ into skills/public/<id>/."""
    root = unified_skills_root()
    moved: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in {"public", "custom", "legacy"}:
            continue
        if not (entry / SKILL_FILENAME).is_file():
            continue
        dest = root / "public" / entry.name
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry), str(dest))
        moved.append(entry.name)
    return moved


def sync_vendor_public_skills() -> list[str]:
    """Copy DeerFlow built-in + RealAi preset skills into unified public when missing."""
    synced = sync_deerflow_public_skills()
    synced.extend(sync_realai_preset_skills())
    return synced


def _removed_skills_path() -> Path:
    return get_data_root() / "config" / "removed_skills.json"


def read_removed_skills() -> set[str]:
    path = _removed_skills_path()
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("removed") if isinstance(data, dict) else data
        if isinstance(items, list):
            return {str(x) for x in items if x}
    except (OSError, json.JSONDecodeError):
        logger.debug("failed reading removed skills", exc_info=True)
    return set()


def mark_skill_removed(skill_id: str) -> None:
    if not is_realai_project_skill(skill_id, category=_skill_category_for_removed(skill_id)):
        return
    path = _removed_skills_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    removed = read_removed_skills()
    removed.add(skill_id)
    path.write_text(
        json.dumps({"removed": sorted(removed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _skill_category_for_removed(skill_id: str) -> str:
    root = unified_skills_root()
    for cat in ("public", "custom", "legacy"):
        if (root / cat / skill_id / SKILL_FILENAME).is_file():
            return cat
    if (root / skill_id / SKILL_FILENAME).is_file():
        return "legacy"
    if skill_id in REALAI_PRESET_IDS:
        return "public"
    return "custom"


def sync_deerflow_public_skills() -> list[str]:
    """Seed DeerFlow upstream public skills when missing (never RealAi presets)."""
    source = deerflow_upstream_public_dir()
    if not source.is_dir():
        return []
    dest_root = unified_skills_root() / "public"
    synced: list[str] = []
    for skill_dir in sorted(source.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        if skill_dir.name in REALAI_PRESET_IDS:
            continue
        skill_md = skill_dir / SKILL_FILENAME
        if not skill_md.is_file():
            continue
        target = dest_root / skill_dir.name
        if (target / SKILL_FILENAME).is_file():
            continue
        shutil.copytree(skill_dir, target)
        synced.append(skill_dir.name)
    return synced


def sync_realai_preset_skills() -> list[str]:
    """Seed/refresh RealAi preset skills from bundled public (respect user removals).

    - 若目标目录不存在：整包 copytree
    - 若已存在：补齐缺失的附属文件（references/scripts/templates 等），不覆盖已有文件
    """
    candidates = [
        get_app_root() / "skills" / "public",
        get_repo_root() / "skills" / "public",
    ]
    bundled = next((p for p in candidates if p.is_dir()), None)
    if bundled is None:
        return []
    dest_root = unified_skills_root() / "public"
    removed = read_removed_skills()
    synced: list[str] = []
    for preset_id in sorted(REALAI_PRESET_IDS):
        if preset_id in removed:
            continue
        source = bundled / preset_id
        if not (source / SKILL_FILENAME).is_file():
            continue
        target = dest_root / preset_id
        if not (target / SKILL_FILENAME).is_file():
            shutil.copytree(source, target)
            synced.append(preset_id)
            continue
        # 补齐附属文件（不覆盖用户已改的文件）
        filled = False
        for src_file in source.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(source)
            dest_file = target / rel
            if dest_file.is_file():
                continue
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_file)
            filled = True
        if filled:
            synced.append(preset_id)
    return synced


def refresh_deerflow_builtin_skills() -> list[str]:
    """Restore DeerFlow built-in SKILL.md from upstream into unified public (keeps RealAi presets)."""
    source = deerflow_upstream_public_dir()
    if not source.is_dir():
        return []
    dest_root = unified_skills_root() / "public"
    if source.resolve() == dest_root.resolve():
        return []
    refreshed: list[str] = []
    for skill_dir in sorted(source.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        if skill_dir.name in REALAI_PRESET_IDS:
            continue
        skill_md = skill_dir / SKILL_FILENAME
        if not skill_md.is_file():
            continue
        target = dest_root / skill_dir.name
        target.mkdir(parents=True, exist_ok=True)
        dest_md = target / SKILL_FILENAME
        if skill_md.resolve() == dest_md.resolve():
            continue
        shutil.copy2(skill_md, dest_md)
        refreshed.append(skill_dir.name)
    return refreshed


def ensure_skills_layout() -> None:
    migrate_legacy_flat_skills()
    sync_vendor_public_skills()
    refresh_deerflow_builtin_skills()


def skill_file_mtime(path: Path) -> str | None:
    if not path.is_file():
        return None
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _extensions_config_path() -> Path:
    """RealAi unified extensions path (skill enable/disable)."""
    env = os.environ.get("DEER_FLOW_EXTENSIONS_CONFIG_PATH")
    if env:
        return Path(env)
    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        resolved = ExtensionsConfig.resolve_config_path()
        if resolved is not None:
            return resolved
    except Exception:
        logger.debug("extensions config not resolved", exc_info=True)
    return get_data_root() / "config" / "extensions_config.json"


def read_skill_enabled(skill_name: str, *, default: bool = True) -> bool:
    path = _extensions_config_path()
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = (data.get("skills") or {}).get(skill_name)
        if isinstance(entry, dict) and "enabled" in entry:
            return bool(entry["enabled"])
    except (OSError, json.JSONDecodeError):
        logger.debug("failed reading extensions for %s", skill_name, exc_info=True)
    return default


def write_skill_enabled(skill_name: str, enabled: bool) -> None:
    path = _extensions_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(json.dumps({"skills": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

    data: dict[str, Any] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
    skills_map = data.setdefault("skills", {})
    skills_map[skill_name] = {"enabled": enabled}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from deerflow.config.extensions_config import reload_extensions_config

        reload_extensions_config(str(path))
    except Exception:
        logger.debug("reload extensions failed", exc_info=True)

    try:
        from deerflow.config import get_app_config
        from deerflow.skills.storage import get_or_new_skill_storage

        storage = get_or_new_skill_storage(app_config=get_app_config())
        if hasattr(storage, "set_skill_enabled_state"):
            storage.set_skill_enabled_state(skill_name, enabled)
    except Exception:
        logger.debug("storage enable sync skipped", exc_info=True)


def list_deerflow_skills() -> list[dict[str, Any]]:
    """Load DeerFlow-visible skills from unified storage."""
    ensure_skills_layout()
    try:
        from deerflow.config import get_app_config
        from deerflow.skills.storage import get_or_new_skill_storage

        storage = get_or_new_skill_storage(app_config=get_app_config())
        skills = storage.load_skills(enabled_only=False)
        out: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for skill in skills:
            category = skill.category.value if hasattr(skill.category, "value") else str(skill.category)
            # DeerFlow Skill.name comes from frontmatter and may be a Chinese
            # display name. The package directory is the stable API identifier.
            skill_id = skill.skill_dir.name
            if skill_id in seen_ids:
                continue
            seen_ids.add(skill_id)
            out.append(
                {
                    "id": skill_id,
                    "name": skill.name,
                    "description": skill.description or "",
                    "category": category,
                    "enabled": skill.enabled,
                    "source": "deerflow",
                    "editable": category == "custom",
                    "valid": True,
                    "errors": [],
                    "version": skill_file_mtime(skill.skill_file),
                }
            )
        return out
    except Exception:
        logger.exception("list_deerflow_skills failed")
        return []


def refresh_deerflow_skill_cache() -> None:
    try:
        import asyncio

        from deerflow.agents.lead_agent.prompt import refresh_user_skills_system_prompt_cache_async

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(refresh_user_skills_system_prompt_cache_async(None))
        except RuntimeError:
            asyncio.run(refresh_user_skills_system_prompt_cache_async(None))
    except Exception:
        logger.debug("skill cache refresh skipped", exc_info=True)
