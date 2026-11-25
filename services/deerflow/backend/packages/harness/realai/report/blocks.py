"""Report Block schema (TECH §11)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from realai.evidence.types import EvidencePack


class ReportBlock(BaseModel):
    heading: str
    purpose: str
    body: str
    tables: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    word_budget: int = 800


class ReportDocument(BaseModel):
    title: str
    blocks: list[ReportBlock] = Field(default_factory=list)
    evidence: EvidencePack = Field(default_factory=EvidencePack)

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        for block in self.blocks:
            lines.append(f"## {block.heading}")
            lines.append("")
            lines.append(block.body)
            if block.evidence_ids:
                lines.append("")
                lines.append("**证据引用：** " + ", ".join(block.evidence_ids))
            lines.append("")
        return "\n".join(lines)
