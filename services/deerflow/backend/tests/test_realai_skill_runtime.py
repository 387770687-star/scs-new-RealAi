from __future__ import annotations

from types import SimpleNamespace

import pytest
from realai.skills import runtime


def _skill(
    skill_id: str = "customer-strategy",
    *,
    enabled: bool = True,
    valid: bool = True,
):
    return SimpleNamespace(
        id=skill_id,
        name="客户战略方法",
        description="客户自己的战略分析与写作方法",
        body="先识别事实，再形成判断，最后给出行动方案。",
        raw="---\nname: 客户战略方法\ndescription: 客户方法\n---\n\n正文",
        enabled=enabled,
        valid=valid,
        errors=[] if valid else ["正文不能为空"],
        version="2026-07-24T10:00:00",
        source="realai",
        category="custom",
        read_only=False,
    )


def test_resolve_qa_skill_uses_selected_skill(monkeypatch):
    monkeypatch.setattr(runtime, "get_skill", lambda skill_id: _skill(skill_id))

    resolved = runtime.resolve_qa_skill("分析今年经营重点", selected_skill_id="customer-strategy")

    assert resolved.query == "分析今年经营重点"
    assert resolved.skill is not None
    assert resolved.skill["id"] == "customer-strategy"
    assert resolved.skill["trigger"] == "selected"
    assert resolved.body.startswith("先识别事实")


def test_resolve_qa_skill_slash_overrides_selector(monkeypatch):
    monkeypatch.setattr(runtime, "get_skill", lambda skill_id: _skill(skill_id))

    resolved = runtime.resolve_qa_skill(
        "/customer-review 评审这份方案",
        selected_skill_id="customer-strategy",
    )

    assert resolved.query == "评审这份方案"
    assert resolved.skill is not None
    assert resolved.skill["id"] == "customer-review"
    assert resolved.skill["trigger"] == "slash"


def test_resolve_qa_skill_rejects_disabled_skill(monkeypatch):
    monkeypatch.setattr(runtime, "get_skill", lambda skill_id: _skill(skill_id, enabled=False))

    with pytest.raises(ValueError, match="已停用"):
        runtime.resolve_qa_skill("分析方案", selected_skill_id="customer-strategy")


def test_snapshot_skill_profile_is_stable_serializable_copy(monkeypatch):
    record = _skill()
    monkeypatch.setattr(runtime, "get_skill", lambda skill_id: record)

    snapshot = runtime.snapshot_skill_profile("customer-strategy")
    record.body = "后来修改的正文"

    assert snapshot == {
        "id": "customer-strategy",
        "name": "客户战略方法",
        "description": "客户自己的战略分析与写作方法",
        "version": "2026-07-24T10:00:00",
        "body": "先识别事实，再形成判断，最后给出行动方案。",
        "source": "realai",
        "category": "custom",
    }


def test_resolve_qa_skill_requires_question_after_slash(monkeypatch):
    monkeypatch.setattr(runtime, "get_skill", lambda skill_id: _skill(skill_id))

    with pytest.raises(ValueError, match="请输入问题"):
        runtime.resolve_qa_skill("/customer-strategy")
