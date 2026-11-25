"""Match user-facing logical knowledge scopes against physical Vault paths."""

from __future__ import annotations

from collections.abc import Iterable

from realai.vault.catalog import KNOWLEDGE_TYPES, knowledge_type_for

TYPE_SCOPE_PREFIX = "type:"
_KNOWLEDGE_TYPE_SET = frozenset(KNOWLEDGE_TYPES)


def _normalize(scope_paths: Iterable[str] | None) -> list[str]:
    if not scope_paths:
        return []
    return [str(value).replace("\\", "/").strip("/") for value in scope_paths if str(value).strip()]


def has_type_selectors(scope_paths: Iterable[str] | None) -> bool:
    """Return whether a scope contains at least one logical ``type:*`` selector."""
    return any(value.startswith(TYPE_SCOPE_PREFIX) for value in _normalize(scope_paths))


def matches_scope(rel: str, scope_paths: Iterable[str] | None) -> bool:
    """Match a Vault-relative path by logical type or legacy physical directory.

    Logical selectors use the same classifier as the knowledge catalog, for example
    ``type:dataset``. Legacy values such as ``raw`` or ``pipelines`` remain valid so
    persisted writing tasks do not change behavior.
    """
    scopes = _normalize(scope_paths)
    if not scopes:
        return True

    logical_types = {value.removeprefix(TYPE_SCOPE_PREFIX) for value in scopes if value.startswith(TYPE_SCOPE_PREFIX) and value.removeprefix(TYPE_SCOPE_PREFIX) in _KNOWLEDGE_TYPE_SET}
    legacy_paths = [value for value in scopes if not value.startswith(TYPE_SCOPE_PREFIX)]
    path = str(rel).replace("\\", "/").strip("/")
    top = path.split("/", 1)[0]

    if logical_types and knowledge_type_for(path) in logical_types:
        return True
    return any(path == scope or path.startswith(scope + "/") or top == scope for scope in legacy_paths)
