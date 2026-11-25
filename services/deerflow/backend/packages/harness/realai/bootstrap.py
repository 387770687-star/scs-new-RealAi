"""First-run bootstrap: seed presets, demo vault, data layout."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from realai.config import load_settings, save_settings
from realai.paths import ensure_data_layout, get_app_root, get_data_root
from realai.skills.deerflow_bridge import sync_vendor_public_skills, vendor_public_skills_dir

logger = logging.getLogger(__name__)

DEMO_VAULT_REL = Path("pack-assets") / "demo-vault"


def seed_public_skills_if_empty() -> list[str]:
    """Copy bundled public skills into RealAiData when custom data dir has none."""
    ensure_data_layout()
    dest = get_data_root() / "skills" / "public"
    if dest.is_dir() and any(dest.iterdir()):
        return []
    try:
        return sync_vendor_public_skills()
    except Exception:
        logger.debug("sync_vendor_public_skills failed", exc_info=True)
        src = vendor_public_skills_dir()
        if not src.is_dir():
            return []
        copied: list[str] = []
        for entry in sorted(src.iterdir()):
            if not entry.is_dir():
                continue
            target = dest / entry.name
            if target.exists():
                continue
            shutil.copytree(entry, target)
            copied.append(entry.name)
        return copied


def seed_demo_vault() -> list[str]:
    """Copy demo markdown into vault when empty."""
    from realai.config import resolve_vault_path

    vault = resolve_vault_path()
    vault.mkdir(parents=True, exist_ok=True)
    if any(vault.rglob("*.md")):
        return []
    src = get_app_root() / DEMO_VAULT_REL
    if not src.is_dir():
        return []
    copied: list[str] = []
    for md in sorted(src.rglob("*.md")):
        rel = md.relative_to(src)
        target = vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(md, target)
            copied.append(rel.as_posix())
    return copied


def bootstrap_data_dir(*, demo_vault: bool = False) -> dict[str, list[str] | str]:
    ensure_data_layout()
    try:
        from realai.meta.db import init_db

        init_db()
    except Exception:
        logger.debug("init_db failed", exc_info=True)
    skills = seed_public_skills_if_empty()
    vault_files: list[str] = seed_demo_vault() if demo_vault else []
    return {
        "skills_seeded": skills,
        "vault_seeded": vault_files,
        "data_root": str(get_data_root()),
    }
