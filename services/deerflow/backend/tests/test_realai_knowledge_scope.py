"""Regression tests for logical knowledge-type scopes."""

from __future__ import annotations


def test_logical_scope_matches_the_same_types_used_by_the_catalog() -> None:
    from realai.vault.scope import matches_scope

    assert matches_scope("raw/制度办法.pdf", ["type:document"])
    assert matches_scope("raw/经营数据.xlsx", ["type:dataset"])
    assert matches_scope("media/站场照片.png", ["type:media"])
    assert matches_scope("wiki/制度办法.md", ["type:knowledge_card"])
    assert matches_scope("entities/station/中卫压气站.md", ["type:entity"])
    assert matches_scope("05_Metrics/输量.md", ["type:metric"])
    assert matches_scope("reports/年度规划.docx", ["type:outcome"])

    assert not matches_scope("raw/经营数据.xlsx", ["type:document"])
    assert not matches_scope("wiki/制度办法.md", ["type:document"])


def test_logical_and_legacy_path_scopes_can_coexist() -> None:
    from realai.vault.scope import matches_scope

    scopes = ["type:dataset", "new_energy"]

    assert matches_scope("dataqa/人口.csv", scopes)
    assert matches_scope("new_energy/政策.md", scopes)
    assert not matches_scope("pipelines/建设方案.md", scopes)


def test_empty_and_legacy_scopes_keep_existing_behavior() -> None:
    from realai.vault.scope import has_type_selectors, matches_scope

    assert matches_scope("pipelines/管线.csv", None)
    assert matches_scope("pipelines/管线.csv", [])
    assert matches_scope("pipelines/管线.csv", ["pipelines"])
    assert not matches_scope("new_energy/政策.md", ["pipelines"])
    assert has_type_selectors(["type:dataset"])
    assert not has_type_selectors(["raw", "wiki"])
