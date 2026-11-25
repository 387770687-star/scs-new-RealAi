"""US-09: RealAi settings sync with DeerFlow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REALAI_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("REALAI_DATA_ROOT", str(tmp_path))
    deer = tmp_path / "deerflow"
    deer.mkdir()
    (deer / "config.example.yaml").write_text("models:\n", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(deer))
    return tmp_path, deer


def test_save_settings_merges_api_key(settings_env):
    from realai.config import load_settings, save_settings

    tmp_path, _ = settings_env
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.json").write_text(
        json.dumps({"llm": {"apiKey": "keep-me-secret"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    saved = save_settings({"llm": {"baseUrl": "https://api.minimaxi.com/v1", "apiKey": ""}})
    assert saved["llm"]["apiKey"] == "keep-me-secret"
    assert saved["llm"]["baseUrl"] == "https://api.minimaxi.com/v1"
    assert saved["llm"]["protocol"] == "openai_compatible"
    assert saved["llm"]["models"]
    assert saved["llm"]["roles"]["primary"]


def test_migrate_flat_to_catalog(settings_env):
    from realai.config import load_settings, save_settings

    tmp_path, _ = settings_env
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.json").write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "minimax",
                    "apiKey": "k",
                    "modelId": "minimax-m3",
                    "model": "MiniMax-M3",
                    "fastModel": "MiniMax-M3-fast",
                    "fallbackModel": "MiniMax-M3-bak",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    llm = load_settings()["llm"]
    assert len(llm["models"]) >= 2
    assert llm["roles"]["primary"] == "minimax-m3"
    assert llm["fastModel"] == "MiniMax-M3-fast"
    assert llm["fallbackModel"] == "MiniMax-M3-bak"


def test_public_settings_masks_key(settings_env):
    from realai.config import public_settings, save_settings

    tmp_path, _ = settings_env
    save_settings({"llm": {"apiKey": "abcd1234wxyz9876", "modelId": "minimax-m3"}})
    pub = public_settings()
    assert "apiKey" not in pub["llm"]
    assert pub["llm"]["hasApiKey"] is True
    assert "abcd" in pub["llm"]["apiKeyPreview"]
    assert "models" in pub["llm"]
    assert "roles" in pub["llm"]


def test_sync_deerflow_writes_env_and_yaml(settings_env):
    from realai.config import load_settings, save_settings
    from realai.config_sync import sync_deerflow_config

    tmp_path, deer = settings_env
    save_settings(
        {
            "llm": {
                "protocol": "openai_compatible",
                "provider": "minimax",
                "apiKey": "test-key-123",
                "baseUrl": "https://api.minimaxi.com/v1",
                "models": [
                    {"id": "minimax-m3", "label": "MiniMax M3", "apiModel": "MiniMax-M3"},
                    {"id": "backup", "label": "Backup", "apiModel": "MiniMax-M3"},
                ],
                "roles": {
                    "primary": "minimax-m3",
                    "fast": "",
                    "vision": "",
                    "fallback": "backup",
                },
            }
        }
    )
    result = sync_deerflow_config(load_settings())
    assert result["has_api_key"] is True
    env_text = (deer / ".env").read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=test-key-123" in env_text
    yaml_text = (deer / "config.yaml").read_text(encoding="utf-8")
    assert "REALAI_MANAGED_MODELS_START" in yaml_text
    assert "minimax-m3" in yaml_text
    assert "name: backup" in yaml_text
    assert "https://api.minimaxi.com/v1" in yaml_text
    assert "PatchedChatMiniMax" in yaml_text


def test_sync_anthropic_protocol(settings_env):
    from realai.config import load_settings, save_settings
    from realai.config_sync import sync_deerflow_config

    _, deer = settings_env
    save_settings(
        {
            "llm": {
                "protocol": "anthropic",
                "provider": "anthropic",
                "apiKey": "anth-key",
                "baseUrl": "https://api.anthropic.com",
                "models": [{"id": "claude", "label": "Claude", "apiModel": "claude-sonnet-4-5"}],
                "roles": {"primary": "claude", "fast": "", "vision": "", "fallback": ""},
            }
        }
    )
    result = sync_deerflow_config(load_settings())
    assert result["env_var"] == "ANTHROPIC_API_KEY"
    env_text = (deer / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=anth-key" in env_text
    yaml_text = (deer / "config.yaml").read_text(encoding="utf-8")
    assert "ChatAnthropic" in yaml_text
    assert "claude-sonnet-4-5" in yaml_text
