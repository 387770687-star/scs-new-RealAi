"""Vault file index with mtime cache (P4: 5k+ files)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from realai.vault.service import VaultFileInfo, ensure_vault, list_vault_files, vault_snapshot_mtime


@dataclass(slots=True)
class VaultIndexCache:
    mtime: float
    files: list[VaultFileInfo]
    built_at: float


_CACHE: VaultIndexCache | None = None


def invalidate_vault_index() -> None:
    global _CACHE
    _CACHE = None


def get_vault_index(*, force: bool = False) -> list[VaultFileInfo]:
    global _CACHE
    snapshot = vault_snapshot_mtime()
    if (
        not force
        and _CACHE is not None
        and _CACHE.mtime >= snapshot
        and time.time() - _CACHE.built_at < 30
    ):
        return _CACHE.files

    files = list_vault_files(limit=100_000)
    _CACHE = VaultIndexCache(mtime=snapshot, files=files, built_at=time.time())
    return files


def query_vault_files(
    *,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
    force: bool = False,
) -> tuple[list[VaultFileInfo], int]:
    ensure_vault()
    items = get_vault_index(force=force)
    if q.strip():
        needle = q.strip().lower()
        items = [f for f in items if needle in f.path.lower() or needle in f.name.lower()]
    total = len(items)
    page = items[offset : offset + limit]
    return page, total
