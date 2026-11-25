"""Safe path helpers for Vault I/O."""

from __future__ import annotations

from pathlib import Path


def resolve_under_root(root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* under *root*; raise if it escapes."""
    root = root.resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escapes vault root")
    return target


def sql_string_literal(value: str) -> str:
    return value.replace("'", "''")
