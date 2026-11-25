"""Portable layout: REALAI_APP_ROOT (replaceable) + REALAI_DATA_ROOT (persistent)."""

from __future__ import annotations

import os
from pathlib import Path


def get_app_root() -> Path:
    """Application bundle root (DeerFlow vendored tree, runtime, presets)."""
    env = os.environ.get("REALAI_APP_ROOT")
    if env:
        return Path(env).resolve()
    return get_repo_root()


def get_data_root() -> Path:
    """User data root (config, vault, custom skills). Defaults to repo root in dev."""
    env = os.environ.get("REALAI_DATA_ROOT")
    if env:
        return Path(env).resolve()
    return get_repo_root()


def get_repo_root() -> Path:
    env = os.environ.get("REALAI_REPO_ROOT")
    if env:
        return Path(env).resolve()
    deer = os.environ.get("DEER_FLOW_PROJECT_ROOT")
    if deer:
        deer_path = Path(deer).resolve()
        # DEER_FLOW_PROJECT_ROOT 通常是 …/services/deerflow
        if (deer_path / "skills" / "public").is_dir() and (deer_path.parent.parent / "apps").is_dir():
            return deer_path.parent.parent
        if (deer_path.parent / "deerflow").is_dir():
            return deer_path.parent.parent
        return deer_path.parent.parent

    # 从本文件上溯：…/services/deerflow/backend/packages/harness/realai/paths.py
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "services" / "deerflow" / "skills" / "public").is_dir() and (p / "apps").is_dir():
            return p
        if (p / "skills" / "public").is_dir() and (p / "backend").is_dir() and (p.name == "deerflow"):
            # 落在 deerflow 根时，再上两级到 RealAi 仓库根
            repo = p.parent.parent
            if (repo / "apps").is_dir():
                return repo

    # 兼容旧逻辑：cwd=services/deerflow 时 parent.parent=仓库根
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / "services" / "deerflow" / "skills" / "public").is_dir() and (p / "apps").is_dir():
            return p
    return cwd.parent.parent


def ensure_data_layout() -> Path:
    root = get_data_root()
    for sub in ("config", "vault", "skills/custom", "skills/public"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    _ensure_extensions_config(root / "config")
    return root


def _ensure_extensions_config(config_dir: Path) -> None:
    target = config_dir / "extensions_config.json"
    if target.is_file():
        return
    example = get_app_root() / "config" / "extensions_config.example.json"
    deer_example = get_app_root() / "services" / "deerflow" / "extensions_config.example.json"
    if example.is_file():
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return
    if deer_example.is_file():
        target.write_text(deer_example.read_text(encoding="utf-8"), encoding="utf-8")
        return
    target.write_text('{\n  "mcpServers": {},\n  "skills": {}\n}\n', encoding="utf-8")


def resolve_data_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    return (get_data_root() / p).resolve()
