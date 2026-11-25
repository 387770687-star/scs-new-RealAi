"""Unit tests for smart web-search decision."""

from __future__ import annotations

from realai.agents.web_decision import (
    decide_web_search,
    decide_web_search_post,
    decide_web_search_pre,
    local_evidence_weak,
)
from realai.evidence.types import EvidenceItem, EvidencePack


def _pack(*excerpts: str, kind: str = "kb") -> EvidencePack:
    items = [
        EvidenceItem(
            id=f"{kind}:t{i}",
            type=kind,  # type: ignore[arg-type]
            source="test",
            excerpt=ex,
        )
        for i, ex in enumerate(excerpts)
    ]
    return EvidencePack(items=items)


def test_off_never_searches():
    d = decide_web_search_pre("上网查一下政策", "off")
    assert d.should_search is False
    assert d.phase == "skip"
    assert "关闭" in d.trajectory


def test_force_immediate():
    d = decide_web_search_pre("随便问", "force")
    assert d.should_search is True
    assert d.phase == "immediate"
    assert "强制" in d.trajectory


def test_explicit_web_intent_immediate():
    d = decide_web_search_pre("请上网查一下天然气政策", "auto")
    assert d.should_search is True
    assert d.phase == "immediate"
    assert "用户要求" in d.trajectory


def test_strong_local_with_enough_evidence_skips():
    pack = _pack(
        "中卫压气站位于宁夏，设计压力 10 MPa，管径 1422 mm。" * 2,
        "相关管段数据表行命中若干。",
        kind="data",
    )
    assert local_evidence_weak(pack) is False
    d = decide_web_search_post("介绍一下 济南西分输清管站_泰安压气站", "auto", pack)
    assert d.should_search is False
    assert d.phase == "skip"
    assert "已足够" in d.trajectory


def test_empty_evidence_auto_supplements():
    d = decide_web_search_post("某外部行业动态如何", "auto", EvidencePack())
    assert d.should_search is True
    assert "补搜" in d.trajectory or "不足" in d.reason


def test_uncertain_prefers_search():
    pack = _pack("短摘录", kind="kb")
    # thin single kb → weak → search
    d = decide_web_search_post("战略规划域有哪些趋势", "auto", pack)
    assert d.should_search is True


def test_decide_auto_stage_with_pack():
    d = decide_web_search("搜一下最新新闻", "auto", EvidencePack(), stage="auto")
    assert d.phase == "immediate"
    assert d.should_search is True
