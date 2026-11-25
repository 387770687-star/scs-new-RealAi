"""P1a/P1b regression tests for RealAi layer."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("REALAI_REPO_ROOT", str(REPO_ROOT))


def test_tokenize_chinese_query():
    from realai.agents.retrieve import _tokenize, search_vault

    tokens = _tokenize("去年采用了什么最新技术策略，降低了多少成本？")
    assert "策略" in tokens
    assert "成本" in tokens
    pack = search_vault("策略 成本 降低")
    assert len(pack.items) >= 1


def test_data_query_finds_csv():
    from realai.agents.data import query_vault_data

    pack = query_vault_data("综合运营成本降低了多少")
    assert any(i.type == "data" for i in pack.items)


def test_vault_path_traversal_blocked():
    from realai.vault.service import write_vault_file

    with pytest.raises(ValueError, match="escapes"):
        write_vault_file("../../outside.txt", "hack")


@pytest.mark.asyncio
async def test_import_failure_does_not_write(tmp_path, monkeypatch):
    from realai.vault import import_service as imp

    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(imp, "convert_file_to_markdown", AsyncMock(side_effect=RuntimeError("bad pdf")))

    result = await imp.import_file_to_vault("bad.pdf", b"%PDF-bad")
    assert result.success is False
    assert list(vault.rglob("*")) == []


@pytest.mark.asyncio
async def test_report_pipeline_outline_phase(monkeypatch):
    from realai.evidence.types import EvidencePack
    from realai.report import strategic_pipeline
    from realai.report.pipeline import run_report_pipeline
    from realai.report.progress import REPORT_AGENTS

    monkeypatch.setattr(
        strategic_pipeline,
        "query_vault_data",
        lambda *args, **kwargs: EvidencePack(),
    )
    monkeypatch.setattr(
        strategic_pipeline,
        "_prioritized_retrieve",
        lambda *args, **kwargs: EvidencePack(),
    )

    result = await run_report_pipeline(
        "测试报告复盘",
        step_confirm=True,
        confirmed=False,
        web_search_mode="off",
        outline_override={
            "title": "系统能力测试复盘报告",
            "strategic_main_line": "以测试复盘为主线，形成可执行的改进方案。",
            "sections": [
                {
                    "id": "summary",
                    "heading": "摘要",
                    "purpose": "概括测试复盘结论",
                    "word_budget": 500,
                }
            ],
        },
    )
    assert result["phase"] == "await_outline_confirm"
    assert result.get("outline")
    assert result.get("knowledge_cards") is not None
    assert len(result.get("agent_progress") or []) == len(REPORT_AGENTS)


@pytest.mark.asyncio
async def test_light_qa_offline_fallback(monkeypatch):
    from realai.agents import light_qa

    monkeypatch.setattr(light_qa, "_synthesize_answer", AsyncMock(return_value="stub answer"))
    result = await light_qa.run_light_qa("策略 成本", web_search_enabled=False)
    assert result["run_mode"] == "light"
    assert result["answer"] == "stub answer"
    assert len(result["evidence"]["items"]) >= 1


@pytest.mark.asyncio
async def test_web_search_disabled_skips_web_pack(monkeypatch):
    from realai.agents import light_qa

    called = False

    async def _fake_search(query, *, limit=3, return_error=False):
        nonlocal called
        called = True
        from realai.evidence.types import EvidencePack

        if return_error:
            return EvidencePack(), None
        return EvidencePack()

    monkeypatch.setattr("realai.agents.web.search_web", _fake_search)
    monkeypatch.setattr(light_qa, "_synthesize_answer", AsyncMock(return_value="ok"))
    await light_qa.run_light_qa("test", web_search_mode="off")
    assert called is False


@pytest.mark.asyncio
async def test_web_search_force_calls_search(monkeypatch):
    from realai.agents import light_qa

    called = False

    async def _fake_search(query, *, limit=3, return_error=False):
        nonlocal called
        called = True
        from realai.evidence.types import EvidencePack

        if return_error:
            return EvidencePack(), None
        return EvidencePack()

    monkeypatch.setattr("realai.agents.web.search_web", _fake_search)
    monkeypatch.setattr(light_qa, "_synthesize_answer", AsyncMock(return_value="ok"))
    result = await light_qa.run_light_qa("test", web_search_mode="force")
    assert called is True
    assert result["web_search_mode"] == "force"
    assert any("强制" in t or "搜索" in t for t in result["trajectory"])

@pytest.mark.asyncio
async def test_report_pipeline_off_skips_web(monkeypatch):
    from realai.evidence.types import EvidencePack
    from realai.report import pipeline, strategic_pipeline

    called = False

    async def _fake_search(query, *, limit=3, return_error=False):
        nonlocal called
        called = True

        if return_error:
            return EvidencePack(), None
        return EvidencePack()

    monkeypatch.setattr("realai.agents.web.search_web", _fake_search)
    monkeypatch.setattr(
        strategic_pipeline,
        "query_vault_data",
        lambda *args, **kwargs: EvidencePack(),
    )
    monkeypatch.setattr(
        strategic_pipeline,
        "_prioritized_retrieve",
        lambda *args, **kwargs: EvidencePack(),
    )
    result = await pipeline.run_report_pipeline(
        "测试报告目标",
        step_confirm=True,
        confirmed=False,
        outline_override={
            "title": "测试报告",
            "strategic_main_line": "以测试目标为主线，形成可执行的行动方案。",
            "sections": [
                {
                    "id": "summary",
                    "heading": "摘要",
                    "purpose": "概括报告目标",
                    "word_budget": 500,
                }
            ],
        },
        web_search_mode="off",
    )
    assert called is False
    assert result["web_search_mode"] == "off"


def test_vault_file_preview_and_download(tmp_path, monkeypatch):
    import io

    from docx import Document
    from realai.vault.service import vault_file_preview, write_vault_file

    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    vault = tmp_path / "vault"
    vault.mkdir()
    write_vault_file("notes/demo.md", "# Hello\n\nRealAi preview test.")
    preview = vault_file_preview("notes/demo.md")
    assert preview["preview_mode"] == "text"
    assert "Hello" in preview["content"]
    assert preview["name"] == "demo.md"

    write_vault_file("data/sample.bin", b"\x00\x01binary")
    bin_preview = vault_file_preview("data/sample.bin")
    assert bin_preview["preview_mode"] == "download_only"

    document = Document()
    document.add_heading("战略规划原文", level=1)
    document.add_paragraph("这是 Word 文件中的原始正文。")
    document.add_table(rows=2, cols=2)
    output = io.BytesIO()
    document.save(output)
    write_vault_file("notes/source.docx", output.getvalue())
    word_preview = vault_file_preview("notes/source.docx")
    assert word_preview["preview_mode"] == "document"
    assert "Word 文件中的原始正文" in word_preview["content"]

    write_vault_file("notes/source.pdf", b"%PDF-invalid-for-text-preview")
    pdf_preview = vault_file_preview("notes/source.pdf")
    assert pdf_preview["preview_mode"] == "pdf"
