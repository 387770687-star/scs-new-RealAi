from __future__ import annotations

from realai.vault.catalog import (
    _text_summary,
    business_tags_for,
    group_catalog_outcomes,
    knowledge_type_for,
    source_status_for,
)


def test_knowledge_type_is_based_on_data_shape_not_business_folder() -> None:
    assert knowledge_type_for("new_energy/policy.md", ".md") == "document"
    assert knowledge_type_for("pipelines/assets.csv", ".csv") == "dataset"
    assert knowledge_type_for("uploads/map.png", ".png") == "media"
    assert knowledge_type_for("wiki/new_energy/policy.md", ".md") == "knowledge_card"
    assert knowledge_type_for("entities/station/A站.md", ".md") == "entity"
    assert knowledge_type_for("05_Metrics/metric-flow.md", ".md") == "metric"
    assert knowledge_type_for("reports/年度规划.docx", ".docx") == "outcome"


def test_raw_is_a_source_status_and_keeps_the_real_data_type() -> None:
    assert knowledge_type_for("raw/raw/dataqa/population.csv", ".csv") == "dataset"
    assert knowledge_type_for("raw/raw/new_energy/policy.md", ".md") == "document"
    assert source_status_for("raw/raw/dataqa/population.csv") == "raw"


def test_generated_and_derived_source_statuses_are_distinct() -> None:
    assert source_status_for("wiki/pipelines/a.md") == "derived"
    assert source_status_for("entities/station/a.md") == "derived"
    assert source_status_for("reports/a.md") == "generated"
    assert source_status_for("10_Outputs/artifacts/a.json") == "generated"
    assert source_status_for("new_energy/a.md") == "curated"


def test_business_topics_are_facets_instead_of_primary_categories() -> None:
    assert business_tags_for("pipelines/a.csv", "西气东输") == ["管网工程"]
    assert business_tags_for("new_energy/a.md", "绿电直连政策") == ["新能源", "政策法规"]
    assert business_tags_for("dataqa/gdp.csv", "地区 GDP") == ["经营与区域数据"]
    assert business_tags_for("reports/年度战略规划.md", "年度战略规划") == ["战略规划"]


def test_summary_hides_wiki_and_markdown_storage_markers() -> None:
    summary = _text_summary(
        """<!-- realai:wiki -->
**字段数**：5
**主要字段**：年份, 项目, 综合运营成本
- `dataqa/2024成本表.csv`
<!-- /realai:wiki -->
"""
    )

    assert summary == "字段数：5 主要字段：年份, 项目, 综合运营成本"


def test_report_export_formats_are_grouped_as_one_knowledge_outcome() -> None:
    grouped = group_catalog_outcomes(
        [
            {
                "id": "reports/年度规划.md",
                "path": "reports/年度规划.md",
                "name": "年度规划.md",
                "title": "年度规划",
                "knowledge_type": "outcome",
                "extension": ".md",
                "formats": [".md"],
                "size": 120,
                "mtime": 10.0,
            },
            {
                "id": "reports/年度规划.docx",
                "path": "reports/年度规划.docx",
                "name": "年度规划.docx",
                "title": "年度规划",
                "knowledge_type": "outcome",
                "extension": ".docx",
                "formats": [".docx"],
                "size": 240,
                "mtime": 12.0,
            },
            {
                "id": "new_energy/policy.md",
                "path": "new_energy/policy.md",
                "name": "policy.md",
                "title": "政策",
                "knowledge_type": "document",
                "extension": ".md",
                "formats": [".md"],
                "size": 30,
                "mtime": 8.0,
            },
        ]
    )

    assert len(grouped) == 2
    report = next(item for item in grouped if item["knowledge_type"] == "outcome")
    assert report["path"] == "reports/年度规划.md"
    assert report["formats"] == [".docx", ".md"]
    assert report["size"] == 360
    assert report["mtime"] == 12.0
