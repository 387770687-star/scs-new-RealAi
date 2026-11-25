"""P3 Skill product tests (查看/维护/执行/导入)."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("REALAI_REPO_ROOT", str(REPO_ROOT))


def test_preset_skills_listed():
    from realai.skills.registry import list_skills

    ids = {s.id for s in list_skills()}
    for expected in (
        "weekly-digest",
        "document-highlights",
        "strategic-planning-writer",
        "strategic-planning-reviewer",
        "strategic-planning-researcher",
    ):
        assert expected in ids


def test_invalid_skill_marked():
    from realai.skills.registry import parse_skill_markdown

    rec = parse_skill_markdown("no frontmatter", skill_id="bad-one")
    assert rec.valid is False
    assert "frontmatter" in rec.errors[0].lower() or "缺少" in rec.errors[0]


def test_skill_crud_roundtrip(tmp_path, monkeypatch):
    from realai.skills.registry import delete_skill, get_skill, save_skill

    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    rec = save_skill(
        "demo-skill",
        name="demo-skill",
        description="测试 Skill",
        body="## 步骤\n1. 读取输入\n2. 输出摘要",
    )
    assert rec.valid
    loaded = get_skill("demo-skill")
    assert loaded is not None
    assert loaded.description == "测试 Skill"
    delete_skill("demo-skill")
    assert get_skill("demo-skill") is None


def test_import_skill_zip(tmp_path, monkeypatch):
    from realai.skills.importer import import_skill_zip
    from realai.skills.registry import get_skill, list_skill_package_files, read_skill_package_file

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    md = (
        "---\nname: zip-skill\ndescription: from zip\n---\n\n"
        "## 约定\n输出一句摘要。\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zip-skill/SKILL.md", md)
        zf.writestr("zip-skill/references/rules.md", "# 规则\n必须引用来源。\n")
        zf.writestr("zip-skill/scripts/check.py", "print('ok')\n")
    imported = import_skill_zip(buf.getvalue())
    assert imported == ["zip-skill"]
    assert get_skill("zip-skill") is not None
    assert {item["path"] for item in list_skill_package_files("zip-skill")} == {
        "SKILL.md",
        "references/rules.md",
        "scripts/check.py",
    }
    assert "必须引用来源" in read_skill_package_file("zip-skill", "references/rules.md")["content"]


def test_skill_import_api_uses_import_route(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.routers import realai_skills

    monkeypatch.setattr(
        realai_skills,
        "import_skill_zip",
        lambda data: ["route-imported"] if data == b"zip-bytes" else [],
    )
    app = FastAPI()
    app.include_router(realai_skills.router)

    with TestClient(app) as client:
        response = client.post(
            "/api/realai/skills/import",
            files={"file": ("skills.zip", b"zip-bytes", "application/zip")},
        )

    assert response.status_code == 200
    assert response.json()["imported"] == ["route-imported"]


def test_create_mode_rejects_duplicate_skill_id(tmp_path, monkeypatch):
    from realai.skills.registry import save_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    save_skill("same-id", name="原 Skill", description="原内容", body="## 步骤\n1. 保留")

    with pytest.raises(FileExistsError, match="已存在"):
        save_skill(
            "same-id",
            name="覆盖尝试",
            description="不应覆盖",
            body="## 步骤\n1. 覆盖",
            overwrite=False,
        )


def test_import_rejects_existing_skill_without_overwriting(tmp_path, monkeypatch):
    from realai.skills.importer import import_skill_zip
    from realai.skills.registry import get_skill, save_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    save_skill("same-id", name="原 Skill", description="原内容", body="## 步骤\n1. 保留")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "same-id/SKILL.md",
            "---\nname: 覆盖尝试\ndescription: 不应覆盖\n---\n\n## 步骤\n1. 覆盖\n",
        )

    with pytest.raises(FileExistsError, match="已存在"):
        import_skill_zip(buf.getvalue())
    assert get_skill("same-id").name == "原 Skill"


@pytest.mark.asyncio
async def test_execute_invalid_skill_blocked(tmp_path, monkeypatch):
    from realai.skills.executor import execute_skill

    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    folder = tmp_path / "skills" / "invalid-skill"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")

    with pytest.raises(ValueError, match="无效"):
        await execute_skill("invalid-skill", "hello")


@pytest.mark.asyncio
async def test_execute_disabled_skill_blocked(tmp_path, monkeypatch):
    from realai.skills.executor import execute_skill
    from realai.skills.registry import save_skill, set_skill_enabled

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    save_skill("disabled-skill", name="停用 Skill", description="测试停用", body="## 步骤\n1. 返回结果")
    set_skill_enabled("disabled-skill", False)

    with pytest.raises(ValueError, match="已停用"):
        await execute_skill("disabled-skill", "hello")


@pytest.mark.asyncio
async def test_preview_execute_does_not_persist_skill(tmp_path, monkeypatch):
    from realai.skills import executor
    from realai.skills.registry import get_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))

    async def fake_llm(prompt: str) -> str:
        assert "草案 Skill" in prompt
        assert "只返回测试结果" in prompt
        return "试跑通过"

    monkeypatch.setattr(executor, "_llm", fake_llm)
    result = await executor.execute_skill_draft(
        name="草案 Skill",
        description="创建前试跑",
        body="## 执行步骤\n1. 只返回测试结果",
        user_input="开始测试",
    )

    assert result["output"] == "试跑通过"
    assert result["mode"] == "draft"
    assert get_skill("draft-skill") is None


@pytest.mark.asyncio
async def test_execute_offline_without_key(monkeypatch):
    from realai.skills.executor import execute_skill

    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    result = await execute_skill("weekly-digest", "本周完成了接口联调")
    assert result["skill_id"] == "weekly-digest"
    assert "离线" in result["output"] or len(result["output"]) > 0


@pytest.mark.asyncio
async def test_report_pipeline_binds_skills():
    from realai.report.pipeline import run_report_pipeline

    # 逐步确认：在大纲处停下，避免依赖 LLM 写长文
    result = await run_report_pipeline("P3 Skill 绑定测试", step_confirm=True, confirmed=False)
    assert result.get("phase") == "await_outline_confirm"
    skills = result.get("skills") or {}
    assert skills.get("writer") == "strategic-planning-writer"
    assert skills.get("review") == "strategic-planning-reviewer"
    assert skills.get("researcher") == "strategic-planning-researcher"
    assert skills.get("writer_valid") is True
    progress = result.get("agent_progress") or []
    assert len(progress) == 7
    assert progress[0]["id"] == "intake"
    assert progress[1]["id"] == "researcher"
    assert progress[2]["id"] == "architect"
    assert any(p["id"] == "researcher" and p["status"] == "completed" for p in progress)


def test_skills_workshop_layout(tmp_path, monkeypatch):
    from realai.skills.deerflow_bridge import ensure_skills_layout
    from realai.skills.registry import list_skills, save_skill

    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    save_skill("demo-ws", name="demo-ws", description="工坊测试", body="## 步骤\n1. 做\n")
    ensure_skills_layout()
    items = list_skills(include_deerflow=False)
    assert any(s.id == "demo-ws" for s in items)
    assert (tmp_path / "skills" / "custom" / "demo-ws" / "SKILL.md").is_file()


def test_deerflow_skill_listing_uses_global_storage(tmp_path, monkeypatch):
    from realai.skills import deerflow_bridge

    import deerflow.config
    import deerflow.skills.storage
    from deerflow.skills.types import Skill as DeerFlowSkill
    from deerflow.skills.types import SkillCategory

    sentinel_config = object()
    calls: list[object] = []
    skill_dir = tmp_path / "public" / "weekly-digest"
    skill_file = skill_dir / "SKILL.md"
    skill = DeerFlowSkill(
        name="周报整理",
        description="整理周报",
        license=None,
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path("weekly-digest"),
        category=SkillCategory.PUBLIC,
        enabled=True,
    )

    class FakeStorage:
        def load_skills(self, *, enabled_only: bool):
            assert enabled_only is False
            return [skill, skill]

    def fake_global_storage(*, app_config):
        calls.append(app_config)
        return FakeStorage()

    monkeypatch.setattr(deerflow_bridge, "ensure_skills_layout", lambda: None)
    monkeypatch.setattr(deerflow.config, "get_app_config", lambda: sentinel_config)
    monkeypatch.setattr(
        deerflow.skills.storage,
        "get_or_new_skill_storage",
        fake_global_storage,
    )

    listed = deerflow_bridge.list_deerflow_skills()
    assert len(listed) == 1
    assert listed[0]["id"] == "weekly-digest"
    assert listed[0]["name"] == "周报整理"
    assert calls == [sentinel_config]


def test_skill_enabled_toggle(tmp_path, monkeypatch):
    from realai.skills.registry import get_skill, save_skill, set_skill_enabled

    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    save_skill("toggle-skill", name="toggle-skill", description="启停", body="正文")
    set_skill_enabled("toggle-skill", False)
    loaded = get_skill("toggle-skill")
    assert loaded is not None
    assert loaded.enabled is False


def test_deerflow_builtin_readonly(tmp_path, monkeypatch):
    from realai.skills.deerflow_bridge import ensure_skills_layout, is_deerflow_builtin
    from realai.skills.registry import delete_skill, get_skill, save_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    vendor = REPO_ROOT / "skills" / "public" / "deep-research" / "SKILL.md"
    if not vendor.is_file():
        vendor = REPO_ROOT / "services" / "deerflow" / "skills" / "public" / "deep-research" / "SKILL.md"
    if not vendor.is_file():
        pytest.skip("vendor deep-research skill missing")

    ensure_skills_layout()

    assert is_deerflow_builtin("deep-research") is True
    assert is_deerflow_builtin("weekly-digest") is False

    loaded = get_skill("deep-research")
    assert loaded is not None
    assert loaded.source == "deerflow"
    assert loaded.editable is False

    with pytest.raises(ValueError, match="只读"):
        save_skill(
            "deep-research",
            name="deep-research",
            description="hack",
            body="## x\n1",
        )
    with pytest.raises(ValueError, match="不可删除"):
        delete_skill("deep-research")

    preset = get_skill("weekly-digest")
    assert preset is not None
    assert preset.source == "realai"
    assert preset.editable is True


def test_delete_realai_preset_persists(tmp_path, monkeypatch):
    from realai.skills.deerflow_bridge import ensure_skills_layout, read_removed_skills
    from realai.skills.registry import delete_skill, get_skill, save_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    ensure_skills_layout()
    assert get_skill("weekly-digest") is not None

    delete_skill("weekly-digest")
    assert get_skill("weekly-digest") is None
    assert "weekly-digest" in read_removed_skills()

    ensure_skills_layout()
    assert get_skill("weekly-digest") is None

    save_skill("demo-del", name="demo-del", description="可删", body="## 步骤\n1. 做\n")
    delete_skill("demo-del")
    assert get_skill("demo-del") is None


def test_delete_custom_skill_removes_history(tmp_path, monkeypatch):
    from realai.skills.registry import delete_skill, list_skill_history, save_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    save_skill("history-skill", name="历史 Skill", description="删除测试", body="## 步骤\n1. 做")
    assert list_skill_history("history-skill")

    delete_skill("history-skill")

    assert not (tmp_path / "skills" / "custom" / ".history" / "history-skill.jsonl").exists()


def test_rejects_heading_only_skill_body(tmp_path, monkeypatch):
    from realai.skills.registry import save_skill

    monkeypatch.setenv("REALAI_APP_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="实际执行内容"):
        save_skill(
            "empty-shell",
            name="空壳 Skill",
            description="不应创建",
            body="## 做什么\n\n## 怎么执行\n\n",
        )
