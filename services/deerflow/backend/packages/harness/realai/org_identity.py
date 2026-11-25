"""Product-fixed organization identity: 国家管网集团 staff.

Hardcoded — not configurable. Used by RealAi LLM prompts and DeerFlow memory seed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

ORG_NAME = "国家管网集团"

# Stable marker to avoid double-injection and to find the seeded memory fact.
ORG_IDENTITY_MARKER = "【用户身份（产品默认）】"

ORG_IDENTITY_FACT_ID = "fact_realai_org_pipechina"

ORG_IDENTITY_FACT_CONTENT = (
    "不论账号角色或界面身份，对话与写作中的用户均为国家管网集团工作人员。"
    "「本集团 / 我司 / 我们」一律指国家管网集团（含所属企业语境时按集团口径理解）。"
    "禁止再追问或猜测用户是否属于其他集团；禁止写「疑似国家管网」。"
)

ORG_IDENTITY_BLOCK = (
    f"{ORG_IDENTITY_MARKER}\n"
    f"- 不论账号角色或界面身份，对话与写作中的「用户」均为「{ORG_NAME}」工作人员。\n"
    f"- 「本集团 / 我司 / 我们」一律指{ORG_NAME}（含所属企业语境时按集团口径理解）。\n"
    "- 禁止再追问或猜测用户是否属于其他集团；禁止写「疑似国家管网」。"
)

ORG_WORK_CONTEXT_SUMMARY = (
    f"用户为国家管网集团工作人员。产品默认身份不可动摇；"
    f"对话中「本集团/我司/我们」均指{ORG_NAME}。"
)


def append_org_identity(text: str | None) -> str:
    """Prepend identity block to a system/prompt string (idempotent)."""
    base = (text or "").strip()
    if ORG_IDENTITY_MARKER in base:
        return base
    if not base:
        return ORG_IDENTITY_BLOCK
    return f"{ORG_IDENTITY_BLOCK}\n\n{base}"


def ensure_messages_org_identity(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure the first system message carries org identity (idempotent)."""
    out = [dict(m) for m in messages]
    for m in out:
        if (m.get("role") or "") == "system":
            content = m.get("content")
            if isinstance(content, list):
                # Multimodal system is unusual; prepend text block if needed.
                text_parts = [
                    str(p.get("text") or "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                joined = "\n".join(t for t in text_parts if t)
                m["content"] = append_org_identity(joined)
            else:
                m["content"] = append_org_identity(str(content or ""))
            return out
    return [{"role": "system", "content": ORG_IDENTITY_BLOCK}, *out]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ensure_org_identity_in_deerflow_memory(*, user_id: str = "default") -> dict[str, Any]:
    """Upsert fixed org identity into DeerFlow memory for Agent injection.

    Safe to call repeatedly. Returns a small status dict; never raises to callers
    that treat memory as best-effort.
    """
    try:
        from deerflow.agents.memory import get_memory_manager
    except Exception as exc:
        logger.debug("org identity memory seed skipped (import): %s", exc)
        return {"ok": False, "reason": "import_failed", "error": str(exc)}

    try:
        mgr = get_memory_manager()
    except Exception as exc:
        logger.debug("org identity memory seed skipped (manager): %s", exc)
        return {"ok": False, "reason": "manager_unavailable", "error": str(exc)}

    if not hasattr(mgr, "get_memory") or not hasattr(mgr, "import_memory"):
        return {"ok": False, "reason": "backend_unsupported"}

    try:
        data = dict(mgr.get_memory(user_id=user_id) or {})
        now = _utc_now()

        user = dict(data.get("user") or {})
        work = dict(user.get("workContext") or {})
        summary = str(work.get("summary") or "")
        if ORG_NAME not in summary or "工作人员" not in summary:
            work["summary"] = ORG_WORK_CONTEXT_SUMMARY
            work["updatedAt"] = now
            user["workContext"] = work
            data["user"] = user

        facts = list(data.get("facts") or [])
        found = False
        for i, fact in enumerate(facts):
            if not isinstance(fact, dict):
                continue
            fid = str(fact.get("id") or "")
            content = str(fact.get("content") or "")
            if fid == ORG_IDENTITY_FACT_ID or ORG_IDENTITY_MARKER in content or (
                ORG_NAME in content and "工作人员" in content and "禁止" in content
            ):
                facts[i] = {
                    **fact,
                    "id": ORG_IDENTITY_FACT_ID,
                    "content": ORG_IDENTITY_FACT_CONTENT,
                    "category": "context",
                    "confidence": 1.0,
                    "source": "realai_org_identity",
                    "expected_valid_days": 3650,
                }
                found = True
                break
        if not found:
            facts.insert(
                0,
                {
                    "id": ORG_IDENTITY_FACT_ID,
                    "content": ORG_IDENTITY_FACT_CONTENT,
                    "category": "context",
                    "confidence": 1.0,
                    "createdAt": now,
                    "source": "realai_org_identity",
                    "expected_valid_days": 3650,
                },
            )
        data["facts"] = facts
        data["lastUpdated"] = now
        data.setdefault("version", "1.0")

        mgr.import_memory(data, user_id=user_id)
        return {"ok": True, "user_id": user_id, "fact_id": ORG_IDENTITY_FACT_ID}
    except Exception as exc:
        logger.warning("org identity memory seed failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "seed_failed", "error": str(exc)}
