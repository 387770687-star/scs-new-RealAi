"""Evaluation-only runners: light QA (auto-confirm filters) and report pipeline."""

from __future__ import annotations

import logging
from typing import Any

from realai.agents.light_qa import run_light_qa, run_light_qa_filter_confirm

logger = logging.getLogger(__name__)


async def run_light_qa_for_eval(
    query: str,
    *,
    web_search_enabled: bool = False,
    intent: str = "ask",
    scope_paths: list[str] | None = None,
    image_paths: list[str] | None = None,
    vision_mode: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Run light QA; if filter confirm is required, auto-accept draft and continue.

    Eval maps web checkbox to force/off (no auto jitter).
    Viz category cases default vision_mode=force so multimodal evidence is exercised.
    """
    mode = "force" if web_search_enabled else "off"
    vmode = vision_mode
    if not vmode:
        vmode = "force" if (category or "").lower() == "viz" else "auto"
    resp = await run_light_qa(
        query,
        web_search_mode=mode,
        vision_mode=vmode,
        intent=intent,  # type: ignore[arg-type]
        scope_paths=scope_paths,
        image_paths=image_paths,
    )
    if resp.get("awaiting_confirm") and resp.get("confirm_kind") == "filter":
        draft = resp.get("filter_draft") or {}
        if draft.get("conditions"):
            logger.info("eval auto-confirm filter for query=%s", query[:80])
            resp = await run_light_qa_filter_confirm(
                query,
                draft,
                web_search_mode=mode,
                intent=intent,  # type: ignore[arg-type]
                scope_paths=scope_paths,
            )
            resp["eval_auto_confirmed"] = True
        else:
            resp["eval_auto_confirmed"] = False
    return resp


async def run_report_for_eval(
    goal: str,
    *,
    writer_skill_id: str | None = None,
    review_skill_id: str | None = None,
    scope_paths: list[str] | None = None,
    web_search_enabled: bool = False,
) -> dict[str, Any]:
    """Run report pipeline without outline confirm; optional skill overrides."""
    from realai.report.pipeline import run_report_pipeline

    mode = "force" if web_search_enabled else "off"
    return await run_report_pipeline(
        goal,
        step_confirm=False,
        confirmed=True,
        scope_paths=scope_paths,
        writer_skill_id=writer_skill_id,
        review_skill_id=review_skill_id,
        web_search_mode=mode,
    )
