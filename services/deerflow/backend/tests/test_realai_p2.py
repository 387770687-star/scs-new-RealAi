"""P2 regression tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("REALAI_REPO_ROOT", str(REPO_ROOT))


def test_readonly_sql_blocks_write():
    from realai.data.sql_engine import run_vault_sql

    with pytest.raises(ValueError, match="只读"):
        run_vault_sql("DELETE FROM t")


def test_readonly_sql_select():
    from realai.data.sql_engine import _list_data_files, _safe_alias, ensure_vault, run_vault_sql

    root = ensure_vault()
    files = _list_data_files(root)
    if not files:
        return
    alias = _safe_alias(files[0].relative_to(root).as_posix())
    pack = run_vault_sql(f"SELECT * FROM {alias}")
    assert isinstance(pack.items, list)


def test_pipeline_review_pipeline_topic():
    from realai.report.blocks import ReportBlock
    from realai.report.review import review_with_pipeline_rules

    blocks = [
        ReportBlock(heading="背景与目标", purpose="p", body="x", evidence_ids=[]),
        ReportBlock(heading="关键发现", purpose="p", body="x", evidence_ids=["kb:a"]),
        ReportBlock(heading="建议与下一步", purpose="p", body="x", evidence_ids=[]),
    ]
    r = review_with_pipeline_rules("油气管道管网工程建设进展", blocks)
    assert r["pipeline_adapted"] is True
    assert r["score"] >= 70


def test_word_export_bytes():
    from realai.report.word_export import markdown_to_docx

    data = markdown_to_docx("# Title\n\nHello", title="T")
    assert data[:2] == b"PK"


@pytest.mark.asyncio
async def test_report_strategic_agents_and_whitelist():
    from realai.report.pipeline import run_report_pipeline
    from realai.report.whitelist import url_allowed

    result = await run_report_pipeline("P2测试报告", step_confirm=True, confirmed=False)
    assert result["phase"] == "await_outline_confirm"
    ids = [p["id"] for p in (result.get("agent_progress") or [])]
    assert ids == ["intake", "researcher", "architect", "writer", "citer", "reviewer", "optimizer"]
    assert url_allowed("https://www.nea.gov.cn/foo")
    assert not url_allowed("https://www.baidu.com/s?wd=1")
