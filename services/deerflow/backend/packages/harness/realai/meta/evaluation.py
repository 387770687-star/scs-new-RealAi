"""Golden-question evaluation suites and runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any

from realai.meta.db import ensure_eval_schema, get_db, init_db
from realai.meta.eval_scorers import score_case
from realai.meta.eval_seed import (
    SEED_LIGHT_NAME,
    SEED_LIGHT_SUITE_ID,
    SEED_REPORT_NAME,
    SEED_REPORT_SUITE_ID,
    light_seed_cases,
    report_seed_cases,
)

logger = logging.getLogger(__name__)

_run_lock = threading.Lock()
_background_tasks: dict[str, asyncio.Task[Any]] = {}
_worker_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
_reconciled = False


def reconcile_orphaned_runs() -> int:
    """Mark runs owned by an earlier backend process as interrupted."""
    global _reconciled
    with _run_lock:
        if _reconciled:
            return 0
        ensure_eval_schema()
        con = get_db()
        try:
            cur = con.execute(
                """
                UPDATE eval_runs
                SET status='failed', finished_at=?, heartbeat_at=?,
                    error=COALESCE(error, '后端服务重启，运行已中断')
                WHERE status='running' AND (worker_id IS NULL OR worker_id<>?)
                """,
                (time.time(), time.time(), _worker_id),
            )
            con.commit()
            _reconciled = True
            return int(cur.rowcount or 0)
        finally:
            con.close()


def create_suite(
    name: str,
    description: str = "",
    *,
    suite_id: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    ensure_eval_schema()
    sid = suite_id or f"suite-{uuid.uuid4().hex[:10]}"
    con = get_db()
    try:
        con.execute(
            "INSERT INTO eval_suites(id, created_at, name, description, kind) VALUES (?,?,?,?,?)",
            (sid, time.time(), name.strip(), description or "", kind),
        )
        con.commit()
    finally:
        con.close()
    return get_suite(sid)  # type: ignore[return-value]


def list_suites() -> list[dict[str, Any]]:
    ensure_eval_schema()
    con = get_db()
    try:
        rows = con.execute("SELECT * FROM eval_suites ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            cases = con.execute(
                "SELECT COUNT(*) AS c FROM eval_cases WHERE suite_id=?", (r["id"],)
            ).fetchone()
            out.append(
                {
                    "id": r["id"],
                    "created_at": r["created_at"],
                    "name": r["name"],
                    "description": r["description"],
                    "kind": _row_get(r, "kind"),
                    "case_count": int(cases["c"] if cases else 0),
                }
            )
        return out
    finally:
        con.close()


def get_suite(suite_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM eval_suites WHERE id=?", (suite_id,)).fetchone()
        if not r:
            return None
        cases = list_cases(suite_id)
        return {
            "id": r["id"],
            "created_at": r["created_at"],
            "name": r["name"],
            "description": r["description"],
            "kind": _row_get(r, "kind"),
            "cases": cases,
            "case_count": len(cases),
        }
    finally:
        con.close()


def delete_suite(suite_id: str) -> bool:
    init_db()
    con = get_db()
    try:
        con.execute("DELETE FROM eval_cases WHERE suite_id=?", (suite_id,))
        con.execute("DELETE FROM eval_runs WHERE suite_id=?", (suite_id,))
        cur = con.execute("DELETE FROM eval_suites WHERE id=?", (suite_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def add_case(suite_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    if not get_suite(suite_id):
        return None
    cid = f"case-{uuid.uuid4().hex[:10]}"
    con = get_db()
    try:
        now = time.time()
        con.execute(
            """
            INSERT INTO eval_cases(
              id, suite_id, created_at, updated_at, version, question, expect_keywords_json,
              expect_evidence, expect_number, number_tolerance, intent,
              category, mode, expect_evidence_kinds_json, expect_min_rows, skip_if, notes,
              expect_answer, answer_match_mode, expect_unit, expect_table_json,
              expect_source_paths_json, rubric_json, fixture_json, tags_json, difficulty
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                suite_id,
                now,
                now,
                1,
                str(body.get("question") or "").strip(),
                json.dumps(body.get("expect_keywords") or [], ensure_ascii=False),
                1 if body.get("expect_evidence", True) else 0,
                body.get("expect_number"),
                body.get("number_tolerance"),
                body.get("intent") or "ask",
                body.get("category") or "general",
                body.get("mode") or "light",
                json.dumps(body.get("expect_evidence_kinds") or [], ensure_ascii=False),
                body.get("expect_min_rows"),
                body.get("skip_if"),
                body.get("notes") or "",
                body.get("expect_answer"),
                body.get("answer_match_mode") or "contains",
                body.get("expect_unit"),
                json.dumps(body.get("expect_table") or {}, ensure_ascii=False),
                json.dumps(body.get("expect_source_paths") or [], ensure_ascii=False),
                json.dumps(body.get("rubric") or {}, ensure_ascii=False),
                json.dumps(body.get("fixture") or {}, ensure_ascii=False),
                json.dumps(body.get("tags") or [], ensure_ascii=False),
                body.get("difficulty") or "medium",
            ),
        )
        con.commit()
    finally:
        con.close()
    return get_case(cid)


def update_case(case_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    current = get_case(case_id)
    if not current:
        return None
    merged = {**current, **body}
    con = get_db()
    try:
        con.execute(
            """
            UPDATE eval_cases SET
              updated_at=?, version=COALESCE(version, 1)+1, question=?,
              expect_keywords_json=?, expect_evidence=?, expect_number=?,
              number_tolerance=?, intent=?, category=?, mode=?,
              expect_evidence_kinds_json=?, expect_min_rows=?, skip_if=?, notes=?,
              expect_answer=?, answer_match_mode=?, expect_unit=?, expect_table_json=?,
              expect_source_paths_json=?, rubric_json=?, fixture_json=?, tags_json=?,
              difficulty=?
            WHERE id=?
            """,
            (
                time.time(),
                str(merged.get("question") or "").strip(),
                json.dumps(merged.get("expect_keywords") or [], ensure_ascii=False),
                1 if merged.get("expect_evidence", True) else 0,
                merged.get("expect_number"),
                merged.get("number_tolerance"),
                merged.get("intent") or "ask",
                merged.get("category") or "general",
                merged.get("mode") or "light",
                json.dumps(merged.get("expect_evidence_kinds") or [], ensure_ascii=False),
                merged.get("expect_min_rows"),
                merged.get("skip_if"),
                merged.get("notes") or "",
                merged.get("expect_answer"),
                merged.get("answer_match_mode") or "contains",
                merged.get("expect_unit"),
                json.dumps(merged.get("expect_table") or {}, ensure_ascii=False),
                json.dumps(merged.get("expect_source_paths") or [], ensure_ascii=False),
                json.dumps(merged.get("rubric") or {}, ensure_ascii=False),
                json.dumps(merged.get("fixture") or {}, ensure_ascii=False),
                json.dumps(merged.get("tags") or [], ensure_ascii=False),
                merged.get("difficulty") or "medium",
                case_id,
            ),
        )
        con.commit()
    finally:
        con.close()
    return get_case(case_id)


def duplicate_case(case_id: str) -> dict[str, Any] | None:
    current = get_case(case_id)
    if not current:
        return None
    body = {k: v for k, v in current.items() if k not in {"id", "suite_id", "created_at", "updated_at", "version"}}
    body["question"] = f"{body['question']}（副本）"
    return add_case(current["suite_id"], body)


def list_cases(suite_id: str, *, category: str | None = None) -> list[dict[str, Any]]:
    init_db()
    con = get_db()
    try:
        if category:
            rows = con.execute(
                "SELECT * FROM eval_cases WHERE suite_id=? AND category=? ORDER BY created_at ASC",
                (suite_id, category),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM eval_cases WHERE suite_id=? ORDER BY created_at ASC",
                (suite_id,),
            ).fetchall()
        return [_case_row(r) for r in rows]
    finally:
        con.close()


def get_case(case_id: str) -> dict[str, Any] | None:
    init_db()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM eval_cases WHERE id=?", (case_id,)).fetchone()
        return _case_row(r) if r else None
    finally:
        con.close()


def delete_case(case_id: str) -> bool:
    init_db()
    con = get_db()
    try:
        cur = con.execute("DELETE FROM eval_cases WHERE id=?", (case_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def seed_suites(*, recreate: bool = False) -> dict[str, Any]:
    """Import / rebuild built-in golden suites. Idempotent unless recreate=True."""
    ensure_eval_schema()
    created: list[str] = []
    for sid, name, desc, kind, cases_fn in (
        (
            SEED_LIGHT_SUITE_ID,
            SEED_LIGHT_NAME,
            "README/PRD 轻量问答黄金题（可删可重建）",
            "seed_light",
            light_seed_cases,
        ),
        (
            SEED_REPORT_SUITE_ID,
            SEED_REPORT_NAME,
            "报告写作黄金题（可删可重建）",
            "seed_report",
            report_seed_cases,
        ),
    ):
        existing = get_suite(sid)
        if existing and not recreate:
            created.append(sid)
            continue
        if existing and recreate:
            delete_suite(sid)
        create_suite(name, desc, suite_id=sid, kind=kind)
        for body in cases_fn():
            add_case(sid, body)
        created.append(sid)
    return {
        "ok": True,
        "suite_ids": created,
        "suites": [get_suite(x) for x in created],
    }


def export_suite(suite_id: str) -> dict[str, Any] | None:
    suite = get_suite(suite_id)
    if not suite:
        return None
    return {
        "version": 2,
        "name": suite["name"],
        "description": suite.get("description") or "",
        "kind": suite.get("kind"),
        "cases": [
            {
                "question": c["question"],
                "expect_keywords": c.get("expect_keywords") or [],
                "expect_evidence": c.get("expect_evidence", True),
                "expect_number": c.get("expect_number"),
                "number_tolerance": c.get("number_tolerance"),
                "expect_answer": c.get("expect_answer"),
                "answer_match_mode": c.get("answer_match_mode") or "contains",
                "expect_unit": c.get("expect_unit"),
                "expect_table": c.get("expect_table") or {},
                "expect_source_paths": c.get("expect_source_paths") or [],
                "rubric": c.get("rubric") or {},
                "fixture": c.get("fixture") or {},
                "tags": c.get("tags") or [],
                "difficulty": c.get("difficulty") or "medium",
                "intent": c.get("intent") or "ask",
                "category": c.get("category") or "general",
                "mode": c.get("mode") or "light",
                "expect_evidence_kinds": c.get("expect_evidence_kinds") or [],
                "expect_min_rows": c.get("expect_min_rows"),
                "skip_if": c.get("skip_if"),
                "notes": c.get("notes") or "",
            }
            for c in suite.get("cases") or []
        ],
    }


def import_suite(payload: dict[str, Any], *, name_override: str | None = None) -> dict[str, Any]:
    name = (name_override or payload.get("name") or "导入套件").strip()
    desc = str(payload.get("description") or "")
    suite = create_suite(name, desc, kind=payload.get("kind") or "imported")
    for body in payload.get("cases") or []:
        if not body.get("question"):
            continue
        add_case(suite["id"], body)
    return get_suite(suite["id"])  # type: ignore[return-value]


def _build_snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {"ts": time.time()}
    try:
        from realai.config import load_settings
        from realai.vault.service import vault_snapshot_mtime

        settings = load_settings()
        llm = settings.get("llm") or {}
        report = settings.get("report") or {}
        snap["vault_mtime"] = vault_snapshot_mtime()
        snap["llm"] = {
            "provider": llm.get("provider"),
            "model": llm.get("model"),
            "modelId": llm.get("modelId"),
            "models": llm.get("models") or [],
            "roles": llm.get("roles") or {},
        }
        snap["report"] = {
            "writerSkillId": report.get("writerSkillId"),
            "reviewSkillId": report.get("reviewSkillId"),
        }
        stable = json.dumps(
            {"llm": snap["llm"], "report": snap["report"], "vault_mtime": snap["vault_mtime"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        snap["config_hash"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    except Exception as exc:
        snap["error"] = str(exc)
    return snap


def start_run(
    suite_id: str,
    *,
    web_search_enabled: bool = False,
    mode: str = "auto",
    model_override: str | None = None,
    skill_overrides: dict[str, str] | None = None,
    compare_base_run_id: str | None = None,
    case_ids: list[str] | None = None,
    concurrency: int = 3,
    light_timeout_seconds: int = 180,
    report_timeout_seconds: int = 900,
    judge_enabled: bool = False,
    judge_model_override: str | None = None,
) -> dict[str, Any]:
    """Create a running record and schedule background execution. Returns immediately."""
    ensure_eval_schema()
    reconcile_orphaned_runs()
    suite = get_suite(suite_id)
    if not suite:
        raise ValueError("套件不存在")
    cases = suite.get("cases") or []
    if case_ids:
        allowed = set(case_ids)
        cases = [case for case in cases if case.get("id") in allowed]
    if not cases:
        raise ValueError("套件没有用例，请先加题或导入示例黄金套件")

    rid = f"run-{uuid.uuid4().hex[:10]}"
    snapshot = _build_snapshot()
    if model_override:
        snapshot["model_override"] = model_override
    if skill_overrides:
        snapshot["skill_overrides"] = skill_overrides
    snapshot["case_versions"] = {
        str(case.get("id")): int(case.get("version") or 1) for case in cases
    }
    options = {
        "case_ids": [case["id"] for case in cases],
        "concurrency": max(1, min(int(concurrency or 1), 6)),
        "light_timeout_seconds": max(30, min(int(light_timeout_seconds or 180), 1800)),
        "report_timeout_seconds": max(60, min(int(report_timeout_seconds or 900), 3600)),
        "judge_enabled": bool(judge_enabled),
        "judge_model_override": judge_model_override,
    }

    con = get_db()
    try:
        now = time.time()
        con.execute(
            """
            INSERT INTO eval_runs(
              id, suite_id, created_at, finished_at, heartbeat_at, status, passed, total, results_json,
              mode, web_search_enabled, model_override, skill_overrides_json,
              snapshot_json, progress_json, compare_base_run_id, category_stats_json,
              metrics_json, options_json, error, worker_id, cancel_requested
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                suite_id,
                now,
                None,
                now,
                "running",
                None,
                len(cases),
                None,
                mode or "auto",
                1 if web_search_enabled else 0,
                model_override,
                json.dumps(skill_overrides or {}, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
                json.dumps({"done": 0, "total": len(cases)}, ensure_ascii=False),
                compare_base_run_id,
                None,
                None,
                json.dumps(options, ensure_ascii=False),
                None,
                _worker_id,
                0,
            ),
        )
        con.commit()
    finally:
        con.close()

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            _execute_run(
                rid,
                suite_id,
                web_search_enabled=web_search_enabled,
                model_override=model_override,
                skill_overrides=skill_overrides or {},
                compare_base_run_id=compare_base_run_id,
                options=options,
            )
        )
        _background_tasks[rid] = task
        task.add_done_callback(lambda _: _background_tasks.pop(rid, None))
    except RuntimeError:
        # No running loop (sync context): run in thread with new loop
        def _thread_main() -> None:
            asyncio.run(
                _execute_run(
                    rid,
                    suite_id,
                    web_search_enabled=web_search_enabled,
                    model_override=model_override,
                    skill_overrides=skill_overrides or {},
                    compare_base_run_id=compare_base_run_id,
                    options=options,
                )
            )

        threading.Thread(target=_thread_main, daemon=True).start()

    return get_run(rid)  # type: ignore[return-value]


async def run_suite(
    suite_id: str,
    *,
    web_search_enabled: bool = False,
    mode: str = "auto",
    model_override: str | None = None,
    skill_overrides: dict[str, str] | None = None,
    compare_base_run_id: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible: start async run and wait until completed."""
    run = start_run(
        suite_id,
        web_search_enabled=web_search_enabled,
        mode=mode,
        model_override=model_override,
        skill_overrides=skill_overrides,
        compare_base_run_id=compare_base_run_id,
    )
    rid = run["id"]
    for _ in range(3600):
        cur = get_run(rid)
        if not cur:
            break
        if cur.get("status") in ("completed", "failed", "empty", "cancelled"):
            return cur
        await asyncio.sleep(0.5)
    return get_run(rid) or run


async def _execute_run(
    run_id: str,
    suite_id: str,
    *,
    web_search_enabled: bool,
    model_override: str | None,
    skill_overrides: dict[str, str],
    compare_base_run_id: str | None,
    options: dict[str, Any],
) -> None:
    from realai.agents.eval_runner import run_light_qa_for_eval, run_report_for_eval
    from realai.llm import model_override_context
    from realai.meta.routing import list_routing, model_call_task

    suite = get_suite(suite_id)
    if not suite:
        _finish_run(
            run_id,
            status="failed",
            passed=0,
            total=0,
            results=[],
            category_stats={},
            error="套件不存在",
        )
        return

    cases = suite.get("cases") or []
    allowed = set(options.get("case_ids") or [])
    if allowed:
        cases = [case for case in cases if case.get("id") in allowed]
    results: list[dict[str, Any]] = []
    passed = 0
    skipped = 0
    cat_stats: dict[str, dict[str, int]] = {}
    semaphore = asyncio.Semaphore(max(1, min(int(options.get("concurrency") or 3), 6)))

    async def run_one(index: int, case: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        case_mode = (case.get("mode") or "light").lower()
        category = case.get("category") or "general"
        task_id = f"eval:{run_id}:{case['id']}"
        started = time.perf_counter()
        fixture = case.get("fixture") if isinstance(case.get("fixture"), dict) else {}
        timeout = (
            int(options.get("report_timeout_seconds") or 900)
            if case_mode == "report"
            else int(options.get("light_timeout_seconds") or 180)
        )
        resp: dict[str, Any] = {}
        try:
            async with semaphore:
                if _cancel_requested(run_id):
                    raise asyncio.CancelledError

                async def invoke() -> dict[str, Any]:
                    with model_override_context(model_override), model_call_task(task_id):
                        if case_mode == "report":
                            return await run_report_for_eval(
                                case["question"],
                                writer_skill_id=skill_overrides.get("writer"),
                                review_skill_id=skill_overrides.get("review"),
                                web_search_enabled=web_search_enabled,
                                scope_paths=fixture.get("scope_paths") or None,
                            )
                        return await run_light_qa_for_eval(
                            case["question"],
                            web_search_enabled=web_search_enabled,
                            intent=case.get("intent") or "ask",
                            category=category,
                            scope_paths=fixture.get("scope_paths") or None,
                            image_paths=fixture.get("image_paths") or None,
                        )

                resp = await asyncio.wait_for(invoke(), timeout=timeout)
            ok, reasons, meta = score_case(case, resp)
            if options.get("judge_enabled"):
                with model_override_context(
                    options.get("judge_model_override") or model_override
                ), model_call_task(task_id):
                    judge = await _run_llm_judge(case, resp)
                meta["judge"] = judge
                meta.setdefault("dimensions", {})["judge"] = {
                    "passed": bool(judge.get("passed")),
                    "score": float(judge.get("score") or 0),
                    "reasons": judge.get("reasons") or [],
                }
                dimension_scores = [
                    float(value.get("score") or 0)
                    for value in meta["dimensions"].values()
                    if isinstance(value, dict)
                ]
                if dimension_scores:
                    meta["overall_score"] = round(
                        sum(dimension_scores) / len(dimension_scores),
                        2,
                    )
                if not judge.get("passed"):
                    ok = False
                    judge_reasons = [f"智能评审：{reason}" for reason in (judge.get("reasons") or ["未通过"])]
                    reasons.extend(judge_reasons)
                    meta.setdefault("failed_gates", []).append("judge")
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            calls = list_routing(limit=500, task_id=task_id)
            preview = (
                resp.get("conclusion")
                or resp.get("answer")
                or str(resp.get("preview_markdown") or "")[:240]
                or ""
            )
            meta["failure_stage"] = _diagnose_failure(reasons, resp, meta) if ok is False else None
            meta["duration_ms"] = duration_ms
            return index, {
                "case_id": case["id"],
                "case_version": case.get("version") or 1,
                "question": case["question"],
                "category": category,
                "mode": case_mode,
                "passed": ok is True,
                "skipped": ok is None,
                "reasons": reasons,
                "answer_preview": str(preview)[:240],
                "answer": str(
                    resp.get("answer")
                    or resp.get("conclusion")
                    or resp.get("preview_markdown")
                    or ""
                ),
                "response": _json_safe(resp),
                "evidence_count": meta.get("evidence_count", 0),
                "model_calls": calls,
                "duration_ms": duration_ms,
                "meta": meta,
            }
        except TimeoutError:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return index, _failed_case_result(
                case,
                category,
                case_mode,
                f"用例执行超时（{timeout} 秒）",
                "timeout",
                duration_ms,
                list_routing(limit=500, task_id=task_id),
                resp,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("eval case failed: %s", case.get("question"))
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return index, _failed_case_result(
                case,
                category,
                case_mode,
                str(exc),
                "runtime",
                duration_ms,
                list_routing(limit=500, task_id=task_id),
                resp,
            )

    tasks = [asyncio.create_task(run_one(index, case)) for index, case in enumerate(cases)]
    try:
        done_count = 0
        for future in asyncio.as_completed(tasks):
            index, item = await future
            item["_order"] = index
            results.append(item)
            category = item.get("category") or "general"
            cat_stats.setdefault(
                category,
                {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
            )
            cat_stats[category]["total"] += 1
            if item.get("skipped"):
                skipped += 1
                cat_stats[category]["skipped"] += 1
            elif item.get("passed"):
                passed += 1
                cat_stats[category]["passed"] += 1
            else:
                cat_stats[category]["failed"] += 1
            done_count += 1
            results.sort(key=lambda row: int(row.get("_order") or 0))
            _update_progress(
                run_id,
                done=done_count,
                total=len(cases),
                partial_results=[{k: v for k, v in row.items() if k != "_order"} for row in results],
            )
            if _cancel_requested(run_id):
                raise asyncio.CancelledError
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        clean = [{k: v for k, v in row.items() if k != "_order"} for row in results]
        _finish_run(
            run_id,
            status="cancelled",
            passed=passed,
            total=len(cases),
            results=clean,
            category_stats=cat_stats,
            skipped=skipped,
            metrics=_aggregate_metrics(clean),
            error="用户取消运行",
        )
        return

    results = [{k: v for k, v in row.items() if k != "_order"} for row in results]

    # Regression: new failures vs base run
    regression: dict[str, Any] | None = None
    if compare_base_run_id:
        regression = compare_runs(compare_base_run_id, run_id, new_results=results)
    elif len(list_runs(suite_id=suite_id, limit=5)) > 1:
        # auto-compare with previous completed run (excluding current)
        prev = [
            r
            for r in list_runs(suite_id=suite_id, limit=5)
            if r["id"] != run_id and r.get("status") == "completed"
        ]
        if prev:
            regression = compare_runs(prev[0]["id"], run_id, new_results=results)

    _finish_run(
        run_id,
        status="completed",
        passed=passed,
        total=len(cases),
        results=results,
        category_stats=cat_stats,
        skipped=skipped,
        regression=regression,
        metrics=_aggregate_metrics(results),
    )


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return {"serialization_error": True, "preview": str(value)[:1000]}


async def _run_llm_judge(case: dict[str, Any], resp: dict[str, Any]) -> dict[str, Any]:
    """Evidence-grounded secondary judge. Deterministic scorers remain the primary gate."""
    from realai.llm import chat_turn

    payload = {
        "question": case.get("question"),
        "expected_answer": case.get("expect_answer"),
        "expected_number": case.get("expect_number"),
        "expected_unit": case.get("expect_unit"),
        "expected_sources": case.get("expect_source_paths") or [],
        "rubric": case.get("rubric") or {},
        "answer": resp.get("answer") or resp.get("conclusion") or resp.get("preview_markdown"),
        "tables": resp.get("tables") or [],
        "evidence": resp.get("evidence") or {},
    }
    system = (
        "你是独立的评测裁判。仅依据给定期望与证据判断回答是否正确，"
        "禁止因为文风好而忽略事实错误。输出严格 JSON："
        '{"score":0到100,"passed":true或false,"reasons":["简短原因"],'
        '"factuality":0到100,"grounding":0到100,"completeness":0到100}。'
    )
    turn = await chat_turn(
        json.dumps(payload, ensure_ascii=False, default=str)[:24_000],
        system=system,
        role="fast",
        temperature=0,
        max_tokens=600,
        purpose="evaluation:judge",
        allow_fallback=False,
    )
    text = turn.content.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    try:
        parsed = json.loads(match.group(0) if match else text)
    except Exception:
        return {"score": 0, "passed": False, "reasons": ["评审模型未返回有效 JSON"]}
    score = max(0.0, min(100.0, float(parsed.get("score") or 0)))
    threshold = float((case.get("rubric") or {}).get("judge_min_score", 70))
    return {
        "score": score,
        "passed": bool(parsed.get("passed")) and score >= threshold,
        "reasons": [str(x) for x in (parsed.get("reasons") or [])][:5],
        "factuality": parsed.get("factuality"),
        "grounding": parsed.get("grounding"),
        "completeness": parsed.get("completeness"),
        "model": turn.model,
    }


def _failed_case_result(
    case: dict[str, Any],
    category: str,
    mode: str,
    reason: str,
    stage: str,
    duration_ms: float,
    calls: list[dict[str, Any]],
    resp: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "case_version": case.get("version") or 1,
        "question": case["question"],
        "category": category,
        "mode": mode,
        "passed": False,
        "skipped": False,
        "reasons": [reason],
        "answer_preview": "",
        "answer": "",
        "response": _json_safe(resp),
        "evidence_count": 0,
        "model_calls": calls,
        "duration_ms": duration_ms,
        "meta": {"failure_stage": stage, "duration_ms": duration_ms, "overall_score": 0},
    }


def _diagnose_failure(
    reasons: list[str],
    resp: dict[str, Any],
    meta: dict[str, Any],
) -> str:
    dimensions = meta.get("dimensions") if isinstance(meta.get("dimensions"), dict) else {}
    if dimensions.get("number", {}).get("passed") is False:
        return "calculation"
    if dimensions.get("table", {}).get("passed") is False:
        return "structured_data"
    data_query = resp.get("data_query") if isinstance(resp.get("data_query"), dict) else {}
    if resp.get("intent") == "data" and not data_query.get("sql"):
        return "query_planning"
    if resp.get("intent") == "data" and int(data_query.get("hits") or 0) == 0:
        return "data_retrieval"
    if dimensions.get("sources", {}).get("passed") is False:
        return "source_selection"
    if dimensions.get("evidence", {}).get("passed") is False:
        return "retrieval"
    if dimensions.get("report", {}).get("passed") is False:
        return "citation"
    if dimensions.get("rubric", {}).get("passed") is False:
        return "writing"
    if any("模型" in str(reason) for reason in reasons):
        return "model"
    return "synthesis"


def _aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = sorted(float(row.get("duration_ms") or 0) for row in results)
    calls = [call for row in results for call in (row.get("model_calls") or [])]
    scores = [
        float((row.get("meta") or {}).get("overall_score") or 0)
        for row in results
        if not row.get("skipped")
    ]
    failures: dict[str, int] = {}
    for row in results:
        stage = (row.get("meta") or {}).get("failure_stage")
        if stage:
            failures[str(stage)] = failures.get(str(stage), 0) + 1
    p95_index = max(0, min(len(durations) - 1, int(round(len(durations) * 0.95)) - 1)) if durations else 0
    return {
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "avg_latency_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "p95_latency_ms": round(durations[p95_index], 2) if durations else None,
        "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in calls),
        "completion_tokens": sum(int(call.get("completion_tokens") or 0) for call in calls),
        "model_calls": len(calls),
        "failure_stages": failures,
    }


def _cancel_requested(run_id: str) -> bool:
    con = get_db()
    try:
        row = con.execute(
            "SELECT cancel_requested FROM eval_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        return bool(row and row["cancel_requested"])
    finally:
        con.close()


def compare_runs(
    base_run_id: str,
    new_run_id: str,
    *,
    new_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = get_run(base_run_id)
    new = get_run(new_run_id) if new_results is None else None
    base_results = (base or {}).get("results") or []
    cur_results = new_results if new_results is not None else ((new or {}).get("results") or [])

    def key(row: dict[str, Any]) -> str:
        return str(row.get("case_id") or _stable_question(row.get("question")))

    base_map = {key(r): r for r in base_results}
    cur_map = {key(r): r for r in cur_results}
    base_fail = {k: r for k, r in base_map.items() if not r.get("passed") and not r.get("skipped")}
    cur_fail = {k: r for k, r in cur_map.items() if not r.get("passed") and not r.get("skipped")}
    new_failures = [
        {
            "case_id": k,
            "question": cur_fail[k].get("question"),
            "reasons": (cur_fail[k].get("reasons") or []),
            "failure_stage": (cur_fail[k].get("meta") or {}).get("failure_stage"),
        }
        for k in cur_fail
        if k not in base_fail
    ]
    fixed = [
        {
            "case_id": k,
            "question": base_fail[k].get("question"),
            "reasons": (base_fail[k].get("reasons") or []),
        }
        for k in base_fail
        if k not in cur_fail
    ]
    still_failing = [
        {
            "case_id": k,
            "question": cur_fail[k].get("question"),
            "reasons": cur_fail[k].get("reasons") or [],
        }
        for k in sorted(set(base_fail) & set(cur_fail))
    ]
    score_changes = []
    for k in sorted(set(base_map) & set(cur_map)):
        before = float((base_map[k].get("meta") or {}).get("overall_score") or 0)
        after = float((cur_map[k].get("meta") or {}).get("overall_score") or 0)
        if before != after:
            score_changes.append(
                {
                    "case_id": k,
                    "question": cur_map[k].get("question"),
                    "before": before,
                    "after": after,
                    "delta": round(after - before, 2),
                }
            )
    return {
        "base_run_id": base_run_id,
        "new_run_id": new_run_id,
        "new_failures": new_failures,
        "fixed": fixed,
        "still_failing": still_failing,
        "score_changes": score_changes,
        "base_pass_rate": (base or {}).get("pass_rate"),
        "new_pass_rate": (new or {}).get("pass_rate"),
    }


def list_runs(suite_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    init_db()
    reconcile_orphaned_runs()
    con = get_db()
    try:
        if suite_id:
            rows = con.execute(
                "SELECT * FROM eval_runs WHERE suite_id=? ORDER BY created_at DESC LIMIT ?",
                (suite_id, max(1, min(limit, 100))),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [_run_row(r) for r in rows]
    finally:
        con.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    init_db()
    reconcile_orphaned_runs()
    con = get_db()
    try:
        r = con.execute("SELECT * FROM eval_runs WHERE id=?", (run_id,)).fetchone()
        return _run_row(r) if r else None
    finally:
        con.close()


def latest_pass_rate() -> float | None:
    runs = list_runs(limit=10)
    for run in runs:
        if run.get("status") != "completed":
            continue
        total = run.get("total") or 0
        if total <= 0:
            continue
        # exclude skipped from denominator when present in results
        results = run.get("results") or []
        if results:
            scored = [x for x in results if not x.get("skipped")]
            if not scored:
                continue
            p = sum(1 for x in scored if x.get("passed"))
            return float(p) / float(len(scored))
        return float(run.get("passed") or 0) / float(total)
    return None


def cancel_run(run_id: str) -> dict[str, Any] | None:
    run = get_run(run_id)
    if not run:
        return None
    if run.get("status") != "running":
        return run
    con = get_db()
    try:
        con.execute(
            "UPDATE eval_runs SET cancel_requested=1, heartbeat_at=? WHERE id=?",
            (time.time(), run_id),
        )
        con.commit()
    finally:
        con.close()
    task = _background_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
    elif run.get("worker_id") != _worker_id:
        _finish_run(
            run_id,
            status="cancelled",
            passed=int(run.get("passed") or 0),
            total=int(run.get("total") or 0),
            results=run.get("results") or [],
            category_stats=run.get("category_stats") or {},
            skipped=int(run.get("skipped") or 0),
            metrics=run.get("metrics") or {},
            error="用户取消运行",
        )
    return get_run(run_id)


def retry_failed_run(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if not run:
        raise ValueError("跑批记录不存在")
    failed_ids = [
        str(item.get("case_id"))
        for item in (run.get("results") or [])
        if not item.get("passed") and not item.get("skipped") and item.get("case_id")
    ]
    if not failed_ids:
        raise ValueError("当前运行没有失败用例")
    options = run.get("options") or {}
    return start_run(
        str(run["suite_id"]),
        web_search_enabled=bool(run.get("web_search_enabled")),
        mode=str(run.get("mode") or "auto"),
        model_override=run.get("model_override"),
        skill_overrides=run.get("skill_overrides") or {},
        compare_base_run_id=run_id,
        case_ids=failed_ids,
        concurrency=int(options.get("concurrency") or 3),
        light_timeout_seconds=int(options.get("light_timeout_seconds") or 180),
        report_timeout_seconds=int(options.get("report_timeout_seconds") or 900),
        judge_enabled=bool(options.get("judge_enabled")),
        judge_model_override=options.get("judge_model_override"),
    )


def validate_suite(suite_id: str) -> dict[str, Any]:
    suite = get_suite(suite_id)
    if not suite:
        raise ValueError("套件不存在")
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in suite.get("cases") or []:
        cid = case["id"]
        question = _stable_question(case.get("question"))
        if question in seen:
            issues.append({"case_id": cid, "level": "warning", "message": "问题与其他用例重复"})
        seen.add(question)
        has_assertion = any(
            [
                case.get("expect_keywords"),
                case.get("expect_answer"),
                case.get("expect_number") is not None,
                case.get("expect_table"),
                case.get("expect_source_paths"),
                case.get("rubric"),
                case.get("expect_evidence"),
                case.get("expect_evidence_kinds"),
            ]
        )
        if not has_assertion:
            issues.append({"case_id": cid, "level": "warning", "message": "没有配置任何可验证的期望结果"})
        if case.get("expect_number") is not None and not case.get("expect_unit"):
            issues.append({"case_id": cid, "level": "warning", "message": "期望数值未配置单位"})
        if case.get("category") == "viz" and not (case.get("fixture") or {}).get("image_paths"):
            issues.append({"case_id": cid, "level": "warning", "message": "多模态用例未绑定固定测试图片，结果可能不可复现"})
        if case.get("mode") == "report" and not case.get("rubric"):
            issues.append({"case_id": cid, "level": "warning", "message": "报告用例没有配置评分规则"})
    errors = sum(1 for issue in issues if issue["level"] == "error")
    return {
        "suite_id": suite_id,
        "case_count": len(suite.get("cases") or []),
        "ready": errors == 0 and bool(suite.get("cases")),
        "errors": errors,
        "warnings": sum(1 for issue in issues if issue["level"] == "warning"),
        "issues": issues,
    }


def evaluation_overview(suite_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    runs = [
        run
        for run in list_runs(suite_id=suite_id, limit=limit)
        if run.get("status") in {"completed", "failed", "cancelled"}
    ]
    trend = [
        {
            "id": run["id"],
            "created_at": run["created_at"],
            "status": run["status"],
            "pass_rate": run.get("pass_rate"),
            "avg_score": (run.get("metrics") or {}).get("avg_score"),
            "avg_latency_ms": (run.get("metrics") or {}).get("avg_latency_ms"),
            "prompt_tokens": (run.get("metrics") or {}).get("prompt_tokens") or 0,
            "completion_tokens": (run.get("metrics") or {}).get("completion_tokens") or 0,
        }
        for run in reversed(runs)
    ]
    latest = next((run for run in runs if run.get("status") == "completed"), None)
    failures: dict[str, int] = {}
    for run in runs:
        for stage, count in ((run.get("metrics") or {}).get("failure_stages") or {}).items():
            failures[str(stage)] = failures.get(str(stage), 0) + int(count or 0)
    return {
        "latest": latest,
        "trend": trend,
        "failure_stages": failures,
        "running": sum(1 for run in list_runs(suite_id=suite_id, limit=100) if run.get("status") == "running"),
        "completed_count": sum(1 for run in runs if run.get("status") == "completed"),
    }


def _stable_question(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def _update_progress(
    run_id: str,
    *,
    done: int,
    total: int,
    partial_results: list[dict[str, Any]],
) -> None:
    con = get_db()
    try:
        con.execute(
            """
            UPDATE eval_runs SET progress_json=?, results_json=?, heartbeat_at=?
            WHERE id=?
            """,
            (
                json.dumps({"done": done, "total": total}, ensure_ascii=False),
                json.dumps(partial_results, ensure_ascii=False),
                time.time(),
                run_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def _finish_run(
    run_id: str,
    *,
    status: str,
    passed: int,
    total: int,
    results: list[dict[str, Any]],
    category_stats: dict[str, Any],
    skipped: int = 0,
    regression: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    payload = results
    category_stats = {**category_stats, "_skipped": skipped}
    if regression:
        category_stats["_regression"] = regression
    con = get_db()
    try:
        con.execute(
            """
            UPDATE eval_runs SET finished_at=?, heartbeat_at=?, status=?, passed=?, total=?, results_json=?,
              progress_json=?, category_stats_json=?, metrics_json=?, error=?
            WHERE id=?
            """,
            (
                time.time(),
                time.time(),
                status,
                passed,
                total,
                json.dumps(payload, ensure_ascii=False),
                json.dumps({"done": total, "total": total}, ensure_ascii=False),
                json.dumps(category_stats, ensure_ascii=False),
                json.dumps(metrics or {}, ensure_ascii=False),
                error,
                run_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def _row_get(r: Any, key: str, default: Any = None) -> Any:
    try:
        if key in r.keys():
            return r[key]
    except Exception:
        pass
    return default


def _case_row(r: Any) -> dict[str, Any]:
    def loads(s: str | None, default: Any):
        if not s:
            return default
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return default

    return {
        "id": r["id"],
        "suite_id": r["suite_id"],
        "created_at": r["created_at"],
        "updated_at": _row_get(r, "updated_at"),
        "version": int(_row_get(r, "version") or 1),
        "question": r["question"],
        "expect_keywords": loads(r["expect_keywords_json"], []),
        "expect_evidence": bool(r["expect_evidence"]),
        "expect_number": r["expect_number"],
        "number_tolerance": r["number_tolerance"],
        "expect_answer": _row_get(r, "expect_answer"),
        "answer_match_mode": _row_get(r, "answer_match_mode") or "contains",
        "expect_unit": _row_get(r, "expect_unit"),
        "expect_table": loads(_row_get(r, "expect_table_json"), {}),
        "expect_source_paths": loads(_row_get(r, "expect_source_paths_json"), []),
        "rubric": loads(_row_get(r, "rubric_json"), {}),
        "fixture": loads(_row_get(r, "fixture_json"), {}),
        "tags": loads(_row_get(r, "tags_json"), []),
        "difficulty": _row_get(r, "difficulty") or "medium",
        "intent": r["intent"] or "ask",
        "category": _row_get(r, "category") or "general",
        "mode": _row_get(r, "mode") or "light",
        "expect_evidence_kinds": loads(_row_get(r, "expect_evidence_kinds_json"), []),
        "expect_min_rows": _row_get(r, "expect_min_rows"),
        "skip_if": _row_get(r, "skip_if"),
        "notes": _row_get(r, "notes") or "",
    }


def _run_row(r: Any) -> dict[str, Any]:
    def loads(s: str | None, default: Any):
        if not s:
            return default
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return default

    total = r["total"] or 0
    passed = r["passed"]
    cat_stats = loads(_row_get(r, "category_stats_json"), {}) or {}
    regression = cat_stats.pop("_regression", None) if isinstance(cat_stats, dict) else None
    skipped = cat_stats.pop("_skipped", 0) if isinstance(cat_stats, dict) else 0
    scored_total = max(0, int(total) - int(skipped or 0))
    return {
        "id": r["id"],
        "suite_id": r["suite_id"],
        "created_at": r["created_at"],
        "finished_at": r["finished_at"],
        "status": r["status"],
        "passed": passed,
        "total": total,
        "skipped": skipped,
        "pass_rate": (float(passed) / float(scored_total)) if passed is not None and scored_total else None,
        "results": loads(r["results_json"], []),
        "mode": _row_get(r, "mode") or "auto",
        "web_search_enabled": bool(_row_get(r, "web_search_enabled") or 0),
        "model_override": _row_get(r, "model_override"),
        "skill_overrides": loads(_row_get(r, "skill_overrides_json"), {}),
        "snapshot": loads(_row_get(r, "snapshot_json"), {}),
        "progress": loads(_row_get(r, "progress_json"), {}),
        "metrics": loads(_row_get(r, "metrics_json"), {}),
        "options": loads(_row_get(r, "options_json"), {}),
        "error": _row_get(r, "error"),
        "worker_id": _row_get(r, "worker_id"),
        "heartbeat_at": _row_get(r, "heartbeat_at"),
        "cancel_requested": bool(_row_get(r, "cancel_requested") or 0),
        "compare_base_run_id": _row_get(r, "compare_base_run_id"),
        "category_stats": cat_stats,
        "regression": regression,
    }
