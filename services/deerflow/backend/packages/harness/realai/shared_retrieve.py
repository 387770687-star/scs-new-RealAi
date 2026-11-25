"""Shared vault retrieve helpers for workbench + strategic writing."""

from __future__ import annotations

from realai.agents.retrieve import search_vault
from realai.evidence.types import EvidenceItem, EvidencePack, make_kb_id
from realai.meta.metrics import list_metrics
from realai.vault.scope import has_type_selectors

DEFAULT_SHARED_SCOPE = [
    "wiki",
    "raw",
    "pipelines",
    "new_energy",
    "dataqa",
    "entities",
    "05_Metrics",
]

DEFAULT_BIZ_SCOPE = [
    "pipelines",
    "new_energy",
    "dataqa",
    "entities",
    "05_Metrics",
]


def prioritized_retrieve_quota(
    goal: str,
    scope_paths: list[str] | None,
    *,
    wiki_n: int = 5,
    raw_n: int = 3,
    biz_n: int = 6,
) -> EvidencePack:
    """Merge wiki/raw/biz tiers with fixed quotas (no early-stop starving biz tables)."""
    if has_type_selectors(scope_paths):
        return search_vault(
            goal,
            limit=max(wiki_n + raw_n + biz_n, 1),
            scope_paths=scope_paths,
        )

    biz = list(scope_paths) if scope_paths else list(DEFAULT_BIZ_SCOPE)
    # Ensure shared dirs present when user narrowed scope oddly
    for must in ("pipelines", "new_energy", "dataqa", "entities", "05_Metrics"):
        if must not in biz and scope_paths is None:
            biz.append(must)

    tiers: list[tuple[list[str], int]] = [
        (["wiki"], wiki_n),
        (["raw"], raw_n),
        (biz, biz_n),
    ]
    seen: set[str] = set()
    items: list[EvidenceItem] = []
    for tier_scope, quota in tiers:
        if quota <= 0:
            continue
        pack = search_vault(goal, limit=max(quota * 2, quota), scope_paths=list(tier_scope))
        taken = 0
        for it in pack.items:
            if it.id in seen:
                continue
            seen.add(it.id)
            items.append(it)
            taken += 1
            if taken >= quota:
                break
    return EvidencePack(items=items)


def metrics_evidence_for_query(query: str, *, limit: int = 3) -> EvidencePack:
    """Attach matching 口径 cards as kb evidence when query mentions metric names/aliases."""
    q = (query or "").strip()
    if not q:
        return EvidencePack()
    items: list[EvidenceItem] = []
    try:
        metrics = list_metrics()
    except Exception:
        return EvidencePack()
    for m in metrics:
        name = str(m.get("name") or "")
        aliases = [str(a) for a in (m.get("aliases") or [])]
        keys = [k for k in [name, *aliases] if k and len(k) >= 2]
        if not any(k in q for k in keys):
            continue
        mid = str(m.get("id") or name)
        rel = f"05_Metrics/{mid}.md"
        excerpt = f"口径「{name}」：单位={m.get('unit') or '—'}；公式={m.get('formula') or '—'}；权威表={m.get('authority_table') or '—'}；{(m.get('notes') or '')[:120]}"
        items.append(
            EvidenceItem(
                id=make_kb_id(rel, excerpt),
                type="kb",
                source=rel,
                excerpt=excerpt,
                meta={
                    "path": rel,
                    "metric_id": mid,
                    "confidence": "metric_definition",
                    "locator": "口径库",
                },
            )
        )
        if len(items) >= limit:
            break
    return EvidencePack(items=items)


def seed_default_metrics() -> list[dict]:
    """Idempotent seed of common pipeline / stats 口径."""
    from realai.meta.metrics import create_metric, get_metric, list_metrics

    seeds = [
        {
            "id": "metric-pipe-diameter",
            "name": "管径",
            "aliases": ["管径(mm)", "pipe_diameter"],
            "unit": "mm",
            "formula": "取自管段表 pipe_diameter 字段",
            "authority_table": "pipelines/*.csv",
            "notes": "工作台条件筛选与管段介绍共用此口径",
        },
        {
            "id": "metric-design-pressure",
            "name": "设计压力",
            "aliases": ["design_pressure", "设计压力(MPa)"],
            "unit": "MPa",
            "formula": "取自管段表 design_pressure",
            "authority_table": "pipelines/*.csv",
            "notes": "",
        },
        {
            "id": "metric-section-length",
            "name": "线路长度",
            "aliases": ["管段长度", "pipe_section_length", "里程"],
            "unit": "km",
            "formula": "取自管段表 pipe_section_length",
            "authority_table": "pipelines/*.csv",
            "notes": "问数条件「长度大于」默认按 km",
        },
        {
            "id": "metric-gdp",
            "name": "GDP",
            "aliases": ["国内生产总值", "gdp_current_price"],
            "unit": "依表",
            "formula": "取自 dataqa GDP 表对应年份字段",
            "authority_table": "dataqa/*gdp*",
            "notes": "须注明年份与现价/不变价",
        },
        {
            "id": "metric-population",
            "name": "人口",
            "aliases": ["常住人口", "population"],
            "unit": "人",
            "formula": "取自 dataqa 人口表对应年份",
            "authority_table": "dataqa/*population*",
            "notes": "",
        },
        {
            "id": "metric-design-flow",
            "name": "设计输量",
            "aliases": ["design_trans_flow_rate", "设计输气量"],
            "unit": "依表",
            "formula": "取自管段表 design_trans_flow_rate",
            "authority_table": "pipelines/*.csv",
            "notes": "",
        },
    ]
    existing = {m.get("id") for m in list_metrics()}
    created = []
    for s in seeds:
        if s["id"] in existing:
            continue
        try:
            created.append(create_metric(s))
        except Exception:
            # race / unique — ignore
            if get_metric(s["id"]):
                continue
    return created
