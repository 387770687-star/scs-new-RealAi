"""P4: portable paths, vault index pagination, onboarding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def portable_env(tmp_path, monkeypatch):
    app = tmp_path / "RealAi"
    data = tmp_path / "RealAiData"
    app.mkdir()
    data.mkdir()
    deer = app / "services" / "deerflow"
    deer.mkdir(parents=True)
    (deer / "config.example.yaml").write_text("models:\n", encoding="utf-8")
    monkeypatch.setenv("REALAI_APP_ROOT", str(app))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(data))
    monkeypatch.setenv("REALAI_REPO_ROOT", str(app))
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(deer))
    return app, data, deer


def test_settings_under_data_root(portable_env):
    from realai.config import get_settings_path, save_settings

    _, data, _ = portable_env
    save_settings({"llm": {"apiKey": "x", "modelId": "minimax-m3"}})
    assert get_settings_path().is_file()
    assert get_settings_path().parent == data / "config"


def test_vault_pagination(portable_env):
    from realai.config import save_settings
    from realai.vault.index import invalidate_vault_index, query_vault_files

    _, data, _ = portable_env
    save_settings({"obsidianVaultPath": "./vault"})
    vault = data / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    for i in range(12):
        (vault / f"doc-{i:02d}.md").write_text(f"# {i}", encoding="utf-8")
    invalidate_vault_index()
    page, total = query_vault_files(limit=5, offset=0)
    assert total == 12
    assert len(page) == 5
    page2, _ = query_vault_files(limit=5, offset=5)
    assert len(page2) == 5
    assert page[0].path != page2[0].path


def test_onboarding_needed_without_key(portable_env):
    from realai.onboarding import onboarding_needed

    assert onboarding_needed() is True


def test_onboarding_complete(portable_env):
    from realai.config import load_settings
    from realai.onboarding import complete_onboarding, onboarding_needed

    app, data, deer = portable_env
    (app / "pack-assets" / "demo-vault" / "pipeline").mkdir(parents=True)
    (app / "pack-assets" / "demo-vault" / "pipeline" / "01.md").write_text("# demo", encoding="utf-8")

    result = complete_onboarding(api_key="test-key", import_demo=True)
    assert result["ok"] is True
    assert onboarding_needed() is False
    settings = load_settings()
    assert settings["onboarding"]["completed"] is True
    assert (deer / ".env").read_text(encoding="utf-8").find("test-key") >= 0
