from __future__ import annotations

import asyncio
import importlib

from realai.llm.client import model_override_context, resolve_role_model
from realai.meta.eval_scorers import score_case, score_number


def test_number_score_handles_commas_units_and_unit_conversion() -> None:
    case = {
        "expect_number": 10500,
        "expect_unit": "万元",
        "number_tolerance": 0,
    }
    assert score_number(case, "综合运营成本为 10,500 万元。")[0] is True
    assert score_number(case, "综合运营成本为 1.05 亿元。")[0] is True
    assert score_number(case, "2024 年成本数据尚未确认。")[0] is False
    assert score_number(case, "成本为 10500。")[0] is False


def test_structured_table_and_source_are_hard_gates() -> None:
    case = {
        "mode": "light",
        "category": "data",
        "expect_keywords": ["成本"],
        "expect_evidence": True,
        "expect_number": 10500,
        "expect_unit": "万元",
        "number_tolerance": 0,
        "expect_source_paths": ["dataqa/2024成本表"],
        "expect_table": {
            "columns": ["年份", "项目", "综合运营成本_万元"],
            "rows": [
                {
                    "年份": 2024,
                    "项目": "智能调度+数字化巡检",
                    "综合运营成本_万元": 10500,
                }
            ],
        },
    }
    response = {
        "answer": "2024年该项目综合运营成本为10500万元。",
        "run_mode": "light",
        "tables": [
            {
                "columns": ["年份", "项目", "综合运营成本_万元"],
                "rows": [[2024, "智能调度+数字化巡检", 10500]],
            }
        ],
        "evidence": {
            "items": [
                {
                    "id": "data:dataqa/2024成本表-88d25554.csv#row=3",
                    "kind": "data",
                    "source": "dataqa/2024成本表-88d25554.csv",
                }
            ]
        },
    }
    passed, reasons, meta = score_case(case, response)
    assert passed is True, reasons
    assert meta["overall_score"] == 100

    response["tables"][0]["rows"][0][2] = 12000
    passed, _, meta = score_case(case, response)
    assert passed is False
    assert "table" in meta["failed_gates"]


def test_model_override_routes_primary_and_fast_without_mutating_settings() -> None:
    settings = {
        "llm": {
            "protocol": "openai_compatible",
            "provider": "test",
            "baseUrl": "http://localhost",
            "apiKey": "test-key",
            "models": [
                {"id": "model-a", "label": "A", "apiModel": "api-a"},
                {"id": "model-b", "label": "B", "apiModel": "api-b"},
            ],
            "roles": {"primary": "model-a", "fast": "model-a"},
        }
    }
    with model_override_context("model-b"):
        assert resolve_role_model("primary", settings).api_model == "api-b"
        assert resolve_role_model("fast", settings).api_model == "api-b"
    assert resolve_role_model("primary", settings).api_model == "api-a"
    assert settings["llm"]["roles"]["primary"] == "model-a"


def test_case_crud_and_validation_use_versioned_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    from realai.meta import db as db_module
    from realai.meta import evaluation as evaluation_module

    db_module._initialized = False
    evaluation_module._reconciled = False
    importlib.reload(evaluation_module)

    suite = evaluation_module.create_suite("精确问数回归集")
    case = evaluation_module.add_case(
        suite["id"],
        {
            "question": "2024年成本是多少",
            "intent": "data",
            "category": "data",
            "expect_number": 10500,
            "expect_unit": "万元",
            "expect_table": {"columns": ["年份", "成本"]},
            "expect_source_paths": ["dataqa/2024成本表"],
            "tags": ["Excel", "核心链路"],
        },
    )
    assert case is not None
    assert case["version"] == 1
    assert case["expect_unit"] == "万元"
    assert case["tags"] == ["Excel", "核心链路"]

    updated = evaluation_module.update_case(case["id"], {"expect_number": 10501})
    assert updated is not None
    assert updated["version"] == 2
    assert updated["expect_number"] == 10501

    duplicated = evaluation_module.duplicate_case(case["id"])
    assert duplicated is not None
    assert duplicated["question"].endswith("（副本）")
    checked = evaluation_module.validate_suite(suite["id"])
    assert checked["ready"] is True

    async def fake_execute(
        run_id: str,
        suite_id: str,
        **_: object,
    ) -> None:
        evaluation_module._finish_run(
            run_id,
            status="completed",
            passed=1,
            total=1,
            results=[],
            category_stats={},
            metrics={"avg_score": 100},
        )

    monkeypatch.setattr(evaluation_module, "_execute_run", fake_execute)

    async def start_and_wait():
        started = evaluation_module.start_run(
            suite["id"],
            case_ids=[case["id"]],
            model_override="model-b",
            concurrency=2,
            judge_enabled=True,
        )
        await asyncio.sleep(0)
        return evaluation_module.get_run(started["id"])

    finished = asyncio.run(start_and_wait())
    assert finished is not None
    assert finished["status"] == "completed"
    assert finished["options"]["concurrency"] == 2
    assert finished["model_override"] == "model-b"
