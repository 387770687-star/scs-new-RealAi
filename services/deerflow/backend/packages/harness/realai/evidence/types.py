"""Evidence ID contract (TECH §4)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceType = Literal["kb", "data", "viz", "web", "inference"]


def _slug(text: str, max_len: int = 12) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:max_len]
    return digest


def make_kb_id(source: str, excerpt: str) -> str:
    return f"kb:{source}#c:{_slug(source + excerpt)}"


def make_data_id(source: str, cell_ref: str) -> str:
    return f"data:{source}:{cell_ref}"


def make_web_id(url: str) -> str:
    return f"web:u:{_slug(url)}"


class EvidenceItem(BaseModel):
    id: str
    type: EvidenceType
    source: str
    excerpt: str
    meta: dict[str, Any] = Field(default_factory=dict)


class EvidencePack(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)

    def by_type(self, kind: EvidenceType) -> list[EvidenceItem]:
        return [i for i in self.items if i.type == kind]

    def to_dict(self) -> dict[str, Any]:
        return {"items": [i.model_dump() for i in self.items]}


def extract_cited_ids(text: str) -> list[str]:
    return re.findall(r"\b(?:kb|data|viz|web):[^\s\])>,]+", text)


def detect_conflicts(items: list[EvidenceItem]) -> list[EvidenceItem]:
    by_key: dict[str, list[EvidenceItem]] = {}
    num_re = re.compile(r"(\d+(?:\.\d+)?)")
    for it in items:
        if it.type != "data":
            continue
        key = re.sub(r"\d+(?:\.\d+)?", "#", (it.excerpt or "")[:80])
        by_key.setdefault(key, []).append(it)
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        nums = set()
        for g in group:
            m = num_re.search(g.excerpt or "")
            if m:
                nums.add(m.group(1))
        if len(nums) > 1:
            cg = f"conflict:{_slug(key)}"
            for g in group:
                g.meta["conflict_group"] = cg
                g.meta["conflict"] = True
    return items
