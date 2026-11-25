"""Regression tests for upload-to-query structured data handling."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook


@pytest.fixture
def isolated_realai_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    (tmp_path / "vault").mkdir()

    from realai.data import table_catalog
    from realai.meta import db

    monkeypatch.setattr(db, "_initialized", False)
    monkeypatch.setattr(table_catalog, "_ENSURED", False)
    return tmp_path


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    costs = workbook.active
    costs.title = "成本明细"
    costs.append(["年份", "项目", "综合运营成本_万元", "降幅_百分比"])
    costs.append([2023, "基准", 12000, 0])
    costs.append([2024, "智能调度+数字化巡检", 10500, 12.5])

    assets = workbook.create_sheet("资产")
    assets.append(["资产编号", "资产名称", "原值_万元"])
    assets.append(["A-01", "调度平台", 800])

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _wide_forecast_workbook_bytes() -> bytes:
    workbook = Workbook()
    forecast = workbook.active
    forecast.title = "天然气预测"
    forecast.append(["“十五五”全国天然气市场预测表", None, None, None])
    forecast.append(["单位：亿立方米", None, None, None])
    forecast.append(["地区", "省份", "2026年", "2027年"])
    forecast.append(["环渤海", "北京", 192, 192])
    forecast.append([None, "天津", 123, 129])

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_excel_import_registers_every_nonempty_sheet(
    isolated_realai_data: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from realai.vault import import_service
    from realai.vault.catalog import query_vault_catalog
    from realai.vault.service import vault_file_preview

    monkeypatch.setattr(
        import_service,
        "convert_file_to_markdown",
        AsyncMock(return_value=None),
    )
    progress: list[tuple[str, int, str]] = []

    async def on_progress(stage: str, percentage: int, message: str) -> None:
        progress.append((stage, percentage, message))

    workbook = _workbook_bytes()
    result = await import_service.import_file_to_vault(
        "经营数据.xlsx",
        workbook,
        target_dir="dataqa",
        run_wiki=False,
        on_progress=on_progress,
    )

    assert result.success is True
    assert result.source_path
    assert (isolated_realai_data / "vault" / result.source_path).read_bytes() == workbook
    assert len(result.table_paths) == 2
    assert any("成本明细" in path for path in result.table_paths)
    assert any("资产" in path for path in result.table_paths)
    for rel in result.table_paths:
        assert (isolated_realai_data / "vault" / rel).is_file()
    assert progress[0][0] == "validating"
    assert progress[-1][:2] == ("completed", 100)

    preview = vault_file_preview(result.source_path)
    assert preview["preview_mode"] == "spreadsheet"
    assert [sheet["name"] for sheet in preview["sheets"]] == ["成本明细", "资产"]
    assert preview["sheets"][0]["rows"][2][1] == "智能调度+数字化巡检"

    catalog = query_vault_catalog(force=True)
    imported = next(item for item in catalog["items"] if item["path"] in result.table_paths)
    assert imported["original_path"] == result.source_path
    assert any(file["role"] == "original" for file in imported["files"])


@pytest.mark.asyncio
async def test_uploaded_excel_supports_deterministic_exact_query(
    isolated_realai_data: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from realai.agents.data import run_structured_data_query
    from realai.data.table_catalog import (
        list_catalog_schemas,
        refresh_catalog_paths,
    )
    from realai.vault import import_service

    monkeypatch.setattr(
        import_service,
        "convert_file_to_markdown",
        AsyncMock(return_value=None),
    )
    result = await import_service.import_file_to_vault(
        "2024成本表.xlsx",
        _workbook_bytes(),
        target_dir="dataqa",
        run_wiki=False,
    )
    refresh_catalog_paths(result.table_paths)
    schemas = list_catalog_schemas(
        scope_paths=["dataqa"],
        query_hint="2024成本表 智能调度 运营成本",
    )
    cost_schema = next(schema for schema in schemas if "成本明细" in schema["path"])
    assert cost_schema["types"]["综合运营成本_万元"] in {"BIGINT", "DOUBLE"}
    assert cost_schema["samples"][1]["项目"] == "智能调度+数字化巡检"

    query = run_structured_data_query(
        "2024成本表中，2024年智能调度+数字化巡检的运营成本是多少？",
        force=True,
        scope_paths=["dataqa"],
    )

    assert query.mode == "exact"
    assert query.hits == 1
    assert query.pack.items[0].meta["rows"][0]["综合运营成本_万元"] == "10500"
    assert query.pack.items[0].meta["source_paths"]
    assert all(path.startswith("dataqa/") for path in query.pack.items[0].meta["source_paths"])


@pytest.mark.asyncio
async def test_uploaded_wide_year_excel_supports_deterministic_exact_query(
    isolated_realai_data: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from realai.agents.data import run_structured_data_query
    from realai.data.table_catalog import list_catalog_schemas
    from realai.vault import import_service

    monkeypatch.setattr(
        import_service,
        "convert_file_to_markdown",
        AsyncMock(return_value=None),
    )
    result = await import_service.import_file_to_vault(
        "天然气预测.xlsx",
        _wide_forecast_workbook_bytes(),
        target_dir="dataqa",
        run_wiki=False,
    )

    schemas = list_catalog_schemas(
        scope_paths=["dataqa"],
        query_hint="北京2027年天然气预测数据是多少",
    )
    schema = next(item for item in schemas if item["path"] in result.table_paths)
    assert schema["semantic"]["title"] == "“十五五”全国天然气市场预测表"
    assert schema["semantic"]["unit"] == "亿立方米"
    assert schema["semantic"]["layout"] == "wide_year"

    query = run_structured_data_query(
        "北京2027年天然气预测数据是多少",
        force=True,
        scope_paths=["dataqa"],
    )

    assert query.mode == "exact"
    assert query.hits == 1
    assert query.pack.items[0].meta["rows"] == [
        {"地区": "环渤海", "省份": "北京", "2027年": "192"}
    ]
    assert query.pack.items[0].meta["unit"] == "亿立方米"

    trend_query = run_structured_data_query(
        "用折线图展示北京天然气预测趋势",
        force=True,
        scope_paths=["dataqa"],
    )
    assert trend_query.mode == "exact"
    assert trend_query.pack.items[0].meta["columns"] == [
        "地区",
        "省份",
        "2026年",
        "2027年",
    ]


def test_low_confidence_preview_does_not_return_unrelated_pipeline(
    isolated_realai_data: Path,
) -> None:
    from realai.agents.data import _preview_top_tables

    pipeline = isolated_realai_data / "vault" / "pipelines"
    pipeline.mkdir()
    (pipeline / "西气东输四线天然气管道.csv").write_text(
        "SmUserID,pipe_section_name,pipe_section_length,pipeline_name\n"
        "0,甲站_乙站,129,西气东输四线天然气管道\n",
        encoding="utf-8",
    )

    preview = _preview_top_tables(
        "北京2027年天然气预测数据是多少",
        limit=2,
        scope_paths=["pipelines"],
    )

    assert preview.pack.items == []
    assert preview.candidates == 1
    assert preview.reason == "low_confidence"


def test_chart_requires_visual_or_comparison_intent() -> None:
    from realai.agents.light_qa import _chart_from_tables

    tables = [
        {
            "title": "管段表",
            "columns": ["SmUserID", "pipe_section_name", "pipe_section_length"],
            "rows": [
                {"SmUserID": "0", "pipe_section_name": "甲站_乙站", "pipe_section_length": "129"},
                {"SmUserID": "0", "pipe_section_name": "乙站_丙站", "pipe_section_length": "83.68"},
            ],
        }
    ]

    assert _chart_from_tables("列出所有管段", tables, data_mode="preview") is None

    chart = _chart_from_tables("用图表展示各管段长度", tables, data_mode="exact")
    assert chart
    assert chart["categories"] == ["甲站_乙站", "乙站_丙站"]
    assert chart["series"][0]["name"] == "pipe_section_length"


def test_chart_skips_single_value_and_supports_wide_year_trend() -> None:
    from realai.agents.light_qa import _chart_from_tables

    single = [
        {
            "title": "天然气预测",
            "columns": ["省份", "2027年"],
            "rows": [{"省份": "北京", "2027年": "192"}],
        }
    ]
    assert _chart_from_tables("北京2027年天然气预测数据是多少", single, data_mode="exact") is None

    trend = [
        {
            "title": "天然气预测",
            "columns": ["省份", "2026年", "2027年", "2028年", "2029年"],
            "rows": [
                {
                    "省份": "北京",
                    "2026年": "192",
                    "2027年": "192",
                    "2028年": "191",
                    "2029年": "189",
                }
            ],
        }
    ]
    chart = _chart_from_tables("用折线图展示北京天然气预测趋势", trend, data_mode="exact")
    assert chart
    assert chart["type"] == "line"
    assert chart["categories"] == ["2026年", "2027年", "2028年", "2029年"]


def test_computed_evidence_uses_source_paths_for_scope() -> None:
    from realai.agents.light_qa import _filter_by_scope
    from realai.evidence.types import EvidenceItem, EvidencePack

    item = EvidenceItem(
        id="data:computed",
        type="data",
        source="sql:nl2sql",
        excerpt="10500",
        meta={
            "path": "sql:nl2sql",
            "source_paths": ["dataqa/2024成本表.csv"],
            "rows": [{"综合运营成本_万元": "10500"}],
        },
    )

    kept = _filter_by_scope(EvidencePack(items=[item]), ["dataqa"])
    rejected = _filter_by_scope(EvidencePack(items=[item]), ["pipelines"])

    assert kept.items == [item]
    assert rejected.items == []


def test_multi_table_fallback_respects_scope(
    isolated_realai_data: Path,
) -> None:
    from realai.data.sql_engine import query_multi_table

    dataqa = isolated_realai_data / "vault" / "dataqa"
    examples = isolated_realai_data / "vault" / "examples"
    dataqa.mkdir()
    examples.mkdir()
    (dataqa / "成本表.csv").write_text(
        "年份,项目,运营成本_万元\n2024,范围内项目,10500\n",
        encoding="utf-8",
    )
    (examples / "成本表.csv").write_text(
        "年份,项目,运营成本_万元\n2024,范围外项目,99999\n",
        encoding="utf-8",
    )

    result = query_multi_table(
        "2024年运营成本是多少",
        scope_paths=["dataqa"],
    )

    assert len(result.items) == 1
    assert result.items[0].source.startswith("dataqa/")
    assert result.items[0].meta["rows"][0]["项目"] == "范围内项目"


@pytest.mark.asyncio
async def test_exact_local_result_skips_automatic_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from realai.agents import light_qa
    from realai.agents.data import DataQueryResult
    from realai.evidence.types import EvidenceItem, EvidencePack

    item = EvidenceItem(
        id="data:exact",
        type="data",
        source="dataqa/cost.csv",
        excerpt="2024 | 项目 | 10500",
        meta={
            "path": "dataqa/cost.csv",
            "source_paths": ["dataqa/cost.csv"],
            "columns": ["年份", "项目", "运营成本_万元"],
            "rows": [{"年份": "2024", "项目": "项目", "运营成本_万元": "10500"}],
        },
    )
    monkeypatch.setattr(
        light_qa,
        "run_structured_data_query",
        lambda *args, **kwargs: DataQueryResult(
            pack=EvidencePack(items=[item]),
            mode="exact",
            candidates=1,
            hits=1,
        ),
    )
    captured: dict[str, str] = {}

    async def fake_web(query, mode, **kwargs):
        captured["mode"] = str(mode)
        return EvidencePack(), ["联网跳过"], None

    monkeypatch.setattr(light_qa, "run_web_search_pipeline", fake_web)
    monkeypatch.setattr(
        "realai.agents.vision.analyze_images_on_demand",
        AsyncMock(return_value=(EvidencePack(), [])),
    )
    monkeypatch.setattr(light_qa, "_synthesize_answer", AsyncMock(return_value="10500 万元"))

    await light_qa.run_light_qa(
        "2024 年运营成本是多少",
        intent="data",
        web_search_mode="auto",
    )

    assert captured["mode"] == "off"


@pytest.mark.asyncio
async def test_import_job_reports_file_and_pipeline_progress(
    isolated_realai_data: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from realai.meta import import_jobs
    from realai.vault import import_service

    async def fake_finalize(paths: list[str]) -> dict:
        return {"wiki_cards": len(paths)}

    monkeypatch.setattr(import_service, "finalize_batch_wiki", fake_finalize)
    job = import_jobs.create_job(
        [("成本.csv", "年份,成本_万元\n2024,10500\n".encode())]
    )
    await import_jobs.run_job(job["id"])
    finished = import_jobs.get_job(job["id"])

    assert finished
    assert finished["status"] == "completed"
    assert finished["progress"] == 100
    assert finished["stage"] == "completed"
    assert finished["done"] == 1
    assert finished["items"][0]["status"] == "completed"
    assert finished["items"][0]["progress"] == 100
    assert any(
        path.startswith("_raw_archive/")
        for path in finished["items"][0]["outputs"]
    )
