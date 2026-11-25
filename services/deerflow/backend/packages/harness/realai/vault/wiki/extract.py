"""S1 whitelist entity extraction from docs and CSV rows."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from realai.vault.content_quality import (
    SHORT_METRIC_TOPICS,
    is_generic_org_name,
    is_linkable_entity_title,
)

# Entity type ids used in vault/entities/<type>/
ENTITY_TYPES = (
    "pipe_section",
    "station",
    "pipeline",
    "lng",
    "storage",
    "org",
    "metric",
    "document",
)

METRIC_TOPICS = (
    "油气管道总里程",
    "天然气分介质里程",
    "原油分介质里程",
    "成品油分介质里程",
    "在役里程",
    "封存里程",
    "封存管线明细",
    "起止点",
    "线路长度",
    "管径",
    "设计压力",
    "设计输量",
    "在役明细",
    "LNG接收站",
    "总接收规模",
    "储罐数",
    "罐容",
    "年气化量",
    "储气库",
    "总库容",
    "有效工作气量",
    "注气能力",
    "采气能力",
    "应急采气能力",
    "组织机构",
    "编制人数",
    "管输天然气",
    "管输原油",
    "管输成品油",
    "一次上载",
    "一次下载",
)

_ORG_SUFFIX_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{2,40}(?:公司|分公司|作业区|维抢修(?:中心|队)?|压气站|分输站|清管站|接收站|储气库))"
)
_STATION_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{2,40}(?:压气站|分输清管站|分输站|清管站|分输压气站))"
)
_HEADING_RE = re.compile(r"^#{1,3}\s+.+", re.MULTILINE)

PRIMARY_COLS = (
    "pipe_section_name",
    "管段名称",
    "station_name",
    "站场名称",
    "pipeline_name",
    "管线名称",
)

METRIC_COLS = {
    "pipe_section_length": "线路长度",
    "pipe_diameter": "管径",
    "design_pressure": "设计压力",
    "design_trans_flow_rate": "设计输量",
    "start_station_name": "起点站",
    "end_station_name": "终点站",
    "medium_tran": "介质",
    "pipeline_name": "管线名称",
    "use_status": "使用状态",
    "owner_company": "所属单位",
}


@dataclass(slots=True)
class EntityDraft:
    name: str
    type: str
    aliases: list[str] = field(default_factory=list)
    metrics: dict[str, str] = field(default_factory=dict)
    source_files: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    low_quality: bool = False


def safe_entity_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    s = re.sub(r"\s+", "_", s)
    return (s or "unnamed")[:120]


def _row_metrics(row: dict[str, str]) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for col, label in METRIC_COLS.items():
        if col in row and str(row[col]).strip():
            metrics[label] = str(row[col]).strip()
    return metrics


def _should_emit_metric_topic(topic: str, text: str) -> bool:
    if topic not in text:
        return False
    if topic not in SHORT_METRIC_TOPICS and len(topic) >= 4:
        return True
    for m in _HEADING_RE.finditer(text):
        if topic in m.group(0):
            return True
    for ctx in (f"{topic}是", f"{topic}指", f"{topic}：", f"{topic}:", f"**{topic}**"):
        if ctx in text:
            return True
    return False


def extract_from_csv_text(csv_text: str, source_rel: str, *, category: str = "pipelines") -> list[EntityDraft]:
    """T1: one entity per important row (pipelines only for row explosion)."""
    rel = source_rel.replace("\\", "/")
    top = rel.split("/", 1)[0]
    if category == "dataqa" or top == "dataqa" or "dataqa/" in rel:
        return []
    if category not in ("pipelines",) and top != "pipelines":
        return []

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        return []
    fields = list(reader.fieldnames)
    primary = next((c for c in PRIMARY_COLS if c in fields), None)
    if not primary:
        return []

    drafts: list[EntityDraft] = []
    seen: set[str] = set()
    station_metrics: dict[str, dict[str, str]] = {}
    station_related: dict[str, list[str]] = {}

    for row in reader:
        name = (row.get(primary) or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)

        metrics = _row_metrics(row)
        related: list[str] = []
        for col in ("start_station_name", "end_station_name", "pipeline_name"):
            v = (row.get(col) or "").strip()
            if v and v != name:
                related.append(v)

        etype = "pipe_section"
        if primary == "pipeline_name":
            etype = "pipeline"
        elif primary in ("station_name", "站场名称") or ("站" in name and "_" not in name):
            etype = "station"
        elif primary in ("pipe_section_name", "管段名称"):
            etype = "pipe_section"

        drafts.append(
            EntityDraft(
                name=name,
                type=etype,
                aliases=[],
                metrics=metrics,
                source_files=[source_rel],
                related=list(dict.fromkeys(related)),
                low_quality=False,
            )
        )

        for col in ("start_station_name", "end_station_name"):
            sn = (row.get(col) or "").strip()
            if not sn:
                continue
            sm = station_metrics.setdefault(sn, {})
            for label in ("管径", "设计压力", "管线名称", "介质", "使用状态", "所属单位"):
                if label in metrics and label not in sm:
                    sm[label] = metrics[label]
            if "线路长度" in metrics:
                role = "起点关联管段长度" if col.startswith("start") else "终点关联管段长度"
                sm.setdefault(role, metrics["线路长度"])
            station_related.setdefault(sn, [])
            if name not in station_related[sn]:
                station_related[sn].append(name)

        pn = (row.get("pipeline_name") or "").strip()
        if pn and pn not in seen:
            seen.add(pn)
            drafts.append(
                EntityDraft(
                    name=pn,
                    type="pipeline",
                    source_files=[source_rel],
                    related=[name],
                    metrics={k: metrics[k] for k in ("管径", "设计压力", "介质") if k in metrics},
                )
            )

    for sn, sm in station_metrics.items():
        if sn in seen and any(d.name == sn for d in drafts):
            for d in drafts:
                if d.name == sn and d.type == "station":
                    d.metrics = {**sm, **d.metrics}
                    d.related = list(dict.fromkeys([*(d.related or []), *station_related.get(sn, [])]))
                    break
            continue
        if sn in seen:
            continue
        seen.add(sn)
        drafts.append(
            EntityDraft(
                name=sn,
                type="station",
                metrics=sm,
                source_files=[source_rel],
                related=list(dict.fromkeys(station_related.get(sn, []))),
            )
        )

    return drafts


def extract_from_markdown(text: str, source_rel: str) -> list[EntityDraft]:
    drafts: list[EntityDraft] = []
    seen: set[str] = set()

    for topic in METRIC_TOPICS:
        if not _should_emit_metric_topic(topic, text):
            continue
        if topic in seen:
            continue
        seen.add(topic)
        drafts.append(EntityDraft(name=topic, type="metric", source_files=[source_rel]))

    for m in _STATION_RE.finditer(text):
        name = m.group(1)
        if name not in seen and len(name) >= 4:
            seen.add(name)
            drafts.append(EntityDraft(name=name, type="station", source_files=[source_rel]))

    for m in _ORG_SUFFIX_RE.finditer(text):
        name = m.group(1)
        if name in seen:
            continue
        if any(name.endswith(s) for s in ("压气站", "分输站", "清管站", "分输清管站", "分输压气站")):
            continue
        if name.endswith(("接收站",)):
            drafts.append(EntityDraft(name=name, type="lng", source_files=[source_rel]))
            seen.add(name)
            continue
        if name.endswith("储气库"):
            drafts.append(EntityDraft(name=name, type="storage", source_files=[source_rel]))
            seen.add(name)
            continue
        if is_generic_org_name(name) or not is_linkable_entity_title(name):
            continue
        drafts.append(EntityDraft(name=name, type="org", source_files=[source_rel]))
        seen.add(name)

    return drafts
