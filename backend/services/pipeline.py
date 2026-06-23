import asyncio
from datetime import datetime
from typing import Any

from agents.analyzer import analyzer_node
from agents.collector import collector_node
from agents.critic import critic_node
from agents.orchestrator import merge_schema_extensions, orchestrator_node
from agents.reporter import reporter_node
from models_db import InterventionLogRecord, QualityFeedbackRecord, async_session
from schemas import TaskCreateRequest
from core.runtime import runner
from services.events import event_broker
from services.repositories import (
    add_intervention,
    build_field_index,
    get_task,
    is_task_run_active,
    latest_schema,
    load_source_materials,
    resolve_feedback_items,
    save_analysis_module,
    save_quality_feedback,
    save_schema,
    save_source_materials,
    update_task_state,
    write_checkpoint,
)
from services.stats import count_schema_stats, source_stats
from services.task_intent import build_task_intent
from sqlalchemy import select, desc


class StaleRunError(Exception):
    pass


async def guard_active(task_id: str, run_id: str) -> None:
    """Raise StaleRunError if this run is no longer the active run for the task."""
    if runner.is_cancelled(task_id):
        raise StaleRunError("Task was cancelled")
    async with async_session() as session:
        if not await is_task_run_active(session, task_id, run_id):
            raise StaleRunError("Stale task run")


async def is_current_run(task_id: str, run_id: str) -> bool:
    """Check if a run is still the current active run (in-memory + DB)."""
    if runner.is_cancelled(task_id):
        return False
    async with async_session() as session:
        return await is_task_run_active(session, task_id, run_id)


async def publish_event(task_id: str, event_type: str, data: dict[str, Any], run_id: str | None = None, allow_inactive: bool = False):
    return await event_broker.publish(task_id, event_type, data, run_id=run_id, allow_inactive=allow_inactive)


async def event_generator(task_id: str, since: int = 0):
    async for message in event_broker.stream(task_id, since=since):
        yield message


def _field_label(field: dict[str, Any]) -> str:
    return str(field.get("field_name") or field.get("name") or field.get("id") or "").strip()


def _field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or "").strip()


def _match_feedback_field_ids(feedback: QualityFeedbackRecord, field_index: list[dict[str, Any]]) -> list[str]:
    """Best-effort mapping from persisted critic feedback to schema field ids."""
    haystacks = [
        str(value).lower()
        for value in (feedback.target_id, feedback.module_id, feedback.code, feedback.message)
        if value
    ]
    matched: list[str] = []
    for field in field_index:
        fid = _field_id(field)
        label = _field_label(field)
        candidates = [fid.lower(), label.lower()]
        if any(candidate and candidate in haystack for candidate in candidates for haystack in haystacks):
            if fid:
                matched.append(fid)
    return list(dict.fromkeys(matched))


def _all_field_ids(field_index: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys([_field_id(field) for field in field_index if _field_id(field)]))


def _material_urls(materials: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for material in materials:
        source_url = str(material.get("source_url") or "").strip()
        if source_url:
            urls.append(source_url)
        source_urls = material.get("source_urls") or []
        if isinstance(source_urls, list):
            urls.extend(str(url).strip() for url in source_urls if str(url).strip())
    return list(dict.fromkeys(urls))


def make_initial_state(
    req: TaskCreateRequest,
    task_id: str,
    run_id: str,
    schema_version: int = 1,
    task_intent: dict | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "run_id": run_id,
        "task_context": {
            "domain": req.domain,
            "competitors": req.competitors,
            "execution_mode": req.execution_mode,
            "predefined_schema": req.predefined_schema or [],
            "analysis_goal": req.analysis_goal or "",
            "task_intent": task_intent or {},
        },
        "schema_version": schema_version,
        "dynamic_schema": {},
        "raw_materials": [],
        "source_ids": [],
        "analysis_results": {},
        "critic_feedback": [],
        "suggested_schema_extensions": [],
        "task_events": [],
        "progress": 0,
        "module_updates": [],
        "retry_counts": {},
    }


def _task_intent_end_payload(task_intent: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(task_intent, dict) or not task_intent:
        return None

    meta = task_intent.get("_meta") if isinstance(task_intent, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    return {
        "agent": "Discoverer.TaskIntent",
        "event": "end",
        "message": "Task intent parsed.",
        "input_json": meta.get("llm_input") or [],
        "output_json": {
            "target_object": task_intent.get("target_object"),
            "primary_axes": task_intent.get("primary_axes") or [],
            "deferred_outputs": task_intent.get("deferred_outputs") or [],
            "source": meta.get("source"),
            "fallback": str(meta.get("source") or "").startswith("fallback"),
            "error_type": meta.get("error_type"),
            "raw_output": meta.get("llm_raw_output") or meta.get("content_preview") or "",
        },
    }


async def publish_task_intent_debug(task_id: str, run_id: str, task_intent: dict[str, Any] | None) -> None:
    payload = _task_intent_end_payload(task_intent)
    if payload:
        await publish_event(task_id, "debug_log", payload, run_id=run_id)


async def process_initial_pipeline(task_id: str, run_id: str, initial_state: dict[str, Any], *, continue_after_schema: bool = False):
    try:
        context = initial_state.get("task_context") or {}
        from agents.discoverer.node import discoverer_node
        if not await is_current_run(task_id, run_id):
            return

        await guard_active(task_id, run_id)
        await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "start", "message": "Starting competitor discovery and market context gathering."}, run_id=run_id)
        await publish_event(
            task_id,
            "debug_log",
            {
                "agent": "Discoverer.TaskIntent",
                "event": "start",
                "message": "Parsing task intent from domain and analysis goal.",
            },
            run_id=run_id,
        )
        task_intent = await build_task_intent(str(context.get("domain") or ""), str(context.get("analysis_goal") or ""))
        context["task_intent"] = task_intent
        initial_state["task_context"] = context
        async with async_session() as session:
            task = await get_task(session, task_id)
            if task:
                task.task_intent = task_intent
            await session.commit()
        await guard_active(task_id, run_id)
        await publish_task_intent_debug(task_id, run_id, task_intent)

        had_seed_competitors = bool((initial_state.get("task_context") or {}).get("competitors"))
        state = await discoverer_node(initial_state)
        await guard_active(task_id, run_id)
        discoverer_context = state.get("task_context") or {}
        await publish_event(
            task_id,
            "debug_log",
            {
                "agent": "Discoverer",
                "event": "end",
                "message": "Competitors discovered and market context loaded.",
                # "output_json": {
                #     "competitors": discoverer_context.get("competitors") or [],
                #     "market_context": discoverer_context.get("market_context") or "",
                #     "skipped_recommendation": had_seed_competitors,
                # },
            },
            run_id=run_id,
        )
        await publish_event(task_id, "progress_update", {"progress": 15, "stage": "DISCOVERING"}, run_id=run_id)

        await guard_active(task_id, run_id)
        await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Completing competitors and schema from domain inputs."}, run_id=run_id)
        state = await orchestrator_node(state)
        await guard_active(task_id, run_id)
        schema_json = state.get("dynamic_schema") or {}
        discovered_competitors = (state.get("task_context") or {}).get("competitors") or []
        async with async_session() as session:
            task = await get_task(session, task_id)
            if task and discovered_competitors:
                task.competitors = discovered_competitors
            record = await save_schema(session, task_id, schema_json, created_by="agent", status="active")
            await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=30)
            await session.commit()

        # ── Pre-collection snapshot (separate session, non-fatal) ──
        print(f"[SNAPSHOT] writing pre_collection checkpoint for {task_id}...", flush=True)
        async with async_session() as ckpt_session:
            await _checkpoint_timeout(task_id, run_id, "write_checkpoint(pre_collection)", write_checkpoint(
                ckpt_session, task_id, "pre_collection", "SCHEMA_READY",
                f"Schema ready: {len(discovered_competitors)} competitors, {sum(len(v) if isinstance(v, list) else 0 for v in schema_json.values())} fields",
                {
                    "competitors": discovered_competitors,
                    "progress": 30,
                    "dynamic_schema": schema_json,
                    "state": "SCHEMA_REVIEW",
                    "raw_materials": [],
                    "task_intent": (state.get("task_context") or {}).get("task_intent", {}),
                },
            ))
            await _checkpoint_timeout(task_id, run_id, "commit(pre_collection_checkpoint)", ckpt_session.commit())
        print(f"[SNAPSHOT] checkpoint done for {task_id}", flush=True)
        await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Competitor list and schema completed."}, run_id=run_id)
        await publish_event(task_id, "progress_update", {"progress": 30, "stage": "SCHEMA_REVIEW"}, run_id=run_id)
        await publish_event(
            task_id,
            "schema_ready",
            {
                "dynamic_schema": schema_json,
                "schema_version": record.version,
                "competitors": discovered_competitors,
                "stats": count_schema_stats(schema_json),
            },
            run_id=run_id,
        )
        await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW", "progress": 30}, run_id=run_id)
        if continue_after_schema:
            async with async_session() as session:
                await update_task_state(session, task_id, state="COLLECTING", progress=40)
                await session.commit()
            await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "previous_state": "SCHEMA_REVIEW", "progress": 40}, run_id=run_id)
            if runner.is_cancelled(task_id):
                return
            await process_agent_pipeline(task_id, run_id, emit_prerequisite_logs=False)
    except (StaleRunError, asyncio.CancelledError):
        return
    except Exception as exc:
        if not await is_current_run(task_id, run_id):
            return
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True}, run_id=run_id)



async def _with_timeout(task_id: str, run_id: str, label: str, coro):
    """Run a coro with 30s timeout, publishing debug events on success/failure."""
    try:
        result = await asyncio.wait_for(coro, timeout=30)
        return result
    except asyncio.TimeoutError:
        await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "error", "message": f"[TIMEOUT] {label} timed out after 30s"}, run_id=run_id)
        raise


async def _checkpoint_timeout(task_id: str, run_id: str, label: str, coro):
    """Soft timeout for checkpoint writes — warn and continue on failure."""
    try:
        return await asyncio.wait_for(coro, timeout=30)
    except asyncio.TimeoutError:
        await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "warn", "message": f"[WARN] {label} timed out after 30s, checkpoint skipped"}, run_id=run_id)
        return None
    except Exception as exc:
        await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "warn", "message": f"[WARN] {label} failed: {exc}, checkpoint skipped"}, run_id=run_id)
        return None


async def process_agent_pipeline(
    task_id: str,
    run_id: str,
    start_from: str = "collector",
    snapshot_data: dict[str, Any] | None = None,
    *,
    emit_prerequisite_logs: bool = True,
):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            return
        schema_record = await latest_schema(session, task_id)

        snapshot_collection_run_id = snapshot_data.get("collection_run_id") if isinstance(snapshot_data, dict) else None
        current_collection_run_id = db_task.current_collection_run_id

        if snapshot_data and snapshot_data.get("raw_material_ids"):
            raw_materials = await load_source_materials(
                session,
                task_id,
                material_ids=[str(item) for item in snapshot_data.get("raw_material_ids") or []],
                collection_run_id=str(snapshot_collection_run_id) if snapshot_collection_run_id else None,
                schema=schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
            )
        elif snapshot_data and "raw_materials" in snapshot_data:
            raw_materials = snapshot_data["raw_materials"]
        elif start_from != "collector":
            material_ids = db_task.current_material_ids or []
            if material_ids:
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    material_ids=material_ids,
                    collection_run_id=current_collection_run_id,
                    schema=schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
                )
            elif current_collection_run_id:
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    collection_run_id=current_collection_run_id,
                    schema=schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
                )
            else:
                # Fallback: no material_ids and no collection_run_id
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    schema=schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
                )
            if not raw_materials:
                raw_materials = list(db_task.raw_materials or [])
        else:
            raw_materials = []

        state = {
            "task_id": task_id,
            "run_id": run_id,
            "task_context": {
                "domain": db_task.domain,
                "competitors": db_task.competitors or [],
                "execution_mode": db_task.execution_mode,
                "predefined_schema": [],
                "analysis_goal": db_task.analysis_goal or "",
                "task_intent": db_task.task_intent or {},
            },
            "schema_version": schema_record.version if schema_record else 1,
            "dynamic_schema": schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
            "raw_materials": raw_materials,
            "source_ids": [],
            "analysis_results": dict(db_task.analysis_results or {}) if start_from in ("critic", "reporter") else {},
            "critic_feedback": list(db_task.critic_feedback or []) if start_from == "reporter" else [],
            "suggested_schema_extensions": [],
            "task_events": [],
            "progress": db_task.progress or 40,
            "module_updates": [],
            "retry_counts": {},
        }

    try:
        async def publish_collector_progress(payload: dict[str, Any]):
            await publish_event(task_id, "collector_log", payload, run_id=run_id)

        # ── Emit synthetic end events for skipped earlier phases ──
        if emit_prerequisite_logs and start_from in ("collector",):
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "start", "message": "Skipped (completed before collection)."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "end", "message": "Completed before collection."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Skipped (schema already prepared)."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Schema already prepared."}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 30, "stage": "SCHEMA_REVIEW"}, run_id=run_id)
        elif emit_prerequisite_logs and start_from in ("analyzer",):
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "start", "message": "Skipped (already completed for current task)."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "end", "message": "Completed before analysis resume."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Skipped (schema already prepared)."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Schema already prepared."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "start", "message": "Skipped (using collected materials from current task state)."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Collected materials loaded from current task state."}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 65, "stage": "ANALYZING"}, run_id=run_id)

        # ── COLLECTOR PHASE ──
        if start_from in ("collector",):
            await guard_active(task_id, run_id)
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "start", "message": "Starting data collection for all competitors."}, run_id=run_id)
            state = await collector_node(state, on_progress=publish_collector_progress)
            await guard_active(task_id, run_id)
            materials = state.get("raw_materials") or []
            competitor_counts = {}
            status_counts = {}
            for m in materials:
                comp = m.get("competitor", "unknown")
                competitor_counts[comp] = competitor_counts.get(comp, 0) + 1
                status = m.get("validation_status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            material_sample = [{
                "competitor": m.get("competitor"),
                "schema_field_name": m.get("schema_field_name"),
                "status": m.get("validation_status"),
                "value": m.get("extracted_value", {}).get("value", "")[:200] if m.get("extracted_value") else "",
                "source_url": m.get("source_url"),
                "quote": (m.get("quote_text") or "")[:200],
                "degraded_reason": m.get("degraded_reason"),
            } for m in materials[:6]]
            await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "debug", "message": f"Collector returned {len(materials)} materials: {competitor_counts}, status: {status_counts}, saving to DB...", "output_json": {"total": len(materials), "per_competitor": competitor_counts, "per_status": status_counts, "sample": material_sample}}, run_id=run_id)

            # ── Save collection results (separate from checkpoint to minimize tasks row lock) ──
            await guard_active(task_id, run_id)
            async with async_session() as session:
                task = await _with_timeout(task_id, run_id, "update_task_state", update_task_state(session, task_id, state="COLLECTING", progress=60))
                task.current_collection_run_id = run_id
                await _with_timeout(task_id, run_id, "save_source_materials", save_source_materials(session, task_id, materials, collection_run_id=run_id))
                material_ids = [m.get("id") for m in materials if m.get("id")]
                task.current_material_ids = material_ids
                await _with_timeout(task_id, run_id, "commit(collection)", session.commit())

            # ── Post-collection snapshot (separate session, non-fatal on failure) ──
            async with async_session() as ckpt_session:
                await _checkpoint_timeout(task_id, run_id, "write_checkpoint(post_collection)", write_checkpoint(
                    ckpt_session, task_id, "post_collection", "COLLECTING",
                    f"Collection complete: {len(materials)} materials across {len(competitor_counts)} competitors",
                    {
                        "competitors": (state.get("task_context") or {}).get("competitors", []),
                        "progress": 60,
                        "dynamic_schema": state.get("dynamic_schema", {}),
                        "state": "COLLECTING",
                        "collection_run_id": run_id,
                        "raw_material_ids": material_ids,
                        "material_count": len(materials),
                        "source_stats": source_stats(materials),
                        "sample_materials": material_sample,
                        "task_intent": (state.get("task_context") or {}).get("task_intent", {}),
                    },
                ))
                await _checkpoint_timeout(task_id, run_id, "commit(post_collection_checkpoint)", ckpt_session.commit())

            await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "debug", "message": "DB save complete."}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Data collection completed."}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"}, run_id=run_id)
            await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60}, run_id=run_id)
            await publish_event(task_id, "raw_materials_updated", {"data": materials, "source_stats": source_stats(materials)}, run_id=run_id)

            # ── Advance to ANALYZING (timeout-protected, won't hang) ──
            await guard_active(task_id, run_id)
            async with async_session() as session:
                await _with_timeout(task_id, run_id, "update_task_state(analyzing)", update_task_state(session, task_id, state="ANALYZING", progress=65))
                await _with_timeout(task_id, run_id, "commit(analyzing)", session.commit())
            await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 65}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 65, "stage": "ANALYZING"}, run_id=run_id)
        else:
            if start_from == "analyzer":
                await publish_event(task_id, "progress_update", {"progress": 65, "stage": "ANALYZING"}, run_id=run_id)
                await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 65}, run_id=run_id)
            else:
                await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"}, run_id=run_id)
                await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60}, run_id=run_id)

        if not await is_current_run(task_id, run_id):
            return

        # ── ANALYZER PHASE ──
        if start_from in ("collector", "analyzer"):
            await guard_active(task_id, run_id)
            await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "start", "message": "Starting comparative analysis."}, run_id=run_id)
            state = await analyzer_node(state)
            await guard_active(task_id, run_id)
            analysis = state.get("analysis_results") or {}
            async with async_session() as session:
                task = await _with_timeout(task_id, run_id, "update_task_state", update_task_state(session, task_id, state="ANALYZING", progress=90))
                task.analysis_results = analysis
                for module_id in ("comparison", "swot", "report"):
                    content = analysis.get(module_id, {}) if isinstance(analysis, dict) else {}
                    await _with_timeout(task_id, run_id, f"save_analysis_module({module_id})", save_analysis_module(
                        session, task_id,
                        module_id=module_id, module_type=module_id,
                        content=content if isinstance(content, dict) else {"items": content},
                        evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
                    ))
                await session.commit()
            await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": "Analysis completed."}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 90, "stage": "ANALYZING"}, run_id=run_id)
            await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 90}, run_id=run_id)
            await publish_event(task_id, "analysis_progress", {"module_id": "analysis", "data": analysis}, run_id=run_id)
            execution_mode = (state.get("task_context") or {}).get("execution_mode")
            if execution_mode != "auto":
                await guard_active(task_id, run_id)
                async with async_session() as session:
                    await _with_timeout(task_id, run_id, "update_task_state(analysis_review)", update_task_state(session, task_id, state="ANALYSIS_REVIEW", progress=90))
                    await _with_timeout(task_id, run_id, "commit(analysis_review)", session.commit())
                await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "wait", "message": "Analysis is ready. Waiting for manual confirmation before Critic."}, run_id=run_id)
                await publish_event(task_id, "task_state_changed", {"state": "ANALYSIS_REVIEW", "progress": 90}, run_id=run_id)
                return
        else:
            if start_from != "critic":
                await publish_event(task_id, "progress_update", {"progress": 90, "stage": "ANALYZING"}, run_id=run_id)
                await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 90}, run_id=run_id)

        if not await is_current_run(task_id, run_id):
            return

        # ── CRITIC PHASE ──
        if start_from in ("collector", "analyzer", "critic"):
            await guard_active(task_id, run_id)
            async with async_session() as session:
                await update_task_state(session, task_id, state="CRITIQUING", progress=95)
                await session.commit()
            await publish_event(task_id, "progress_update", {"progress": 95, "stage": "CRITIQUING"}, run_id=run_id)
            await publish_event(task_id, "task_state_changed", {"state": "CRITIQUING", "progress": 95}, run_id=run_id)
            await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "start", "message": "Starting critic quality evaluation."}, run_id=run_id)
            state = await critic_node(state)
            state, calibration_outcome = await run_schema_calibration(task_id, run_id, state)
            if calibration_outcome == "waiting_for_user":
                return

        if not await is_current_run(task_id, run_id):
            return

        # ── REPORTER PHASE ──
        if start_from in ("collector", "analyzer", "critic", "reporter"):
            await guard_active(task_id, run_id)
            await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "start", "message": "Generating final structured report."}, run_id=run_id)
            state = await reporter_node(state)
            await guard_active(task_id, run_id)
            await publish_event(task_id, "analysis_progress", {"module_id": "report", "data": state.get("analysis_results") or {}}, run_id=run_id)

            feedback = state.get("critic_feedback") or []
            await guard_active(task_id, run_id)
            async with async_session() as session:
                task = await _with_timeout(task_id, run_id, "update_task_state(COMPLETED)", update_task_state(session, task_id, state="COMPLETED", progress=100))
                task.analysis_results = state.get("analysis_results") or {}
                task.critic_feedback = feedback
                task.final_report = task.analysis_results.get("report", {})
                task.completed_at = datetime.utcnow()
                await _with_timeout(task_id, run_id, "save_quality_feedback", save_quality_feedback(session, task_id, feedback))
                await session.commit()
            await guard_active(task_id, run_id)
            await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "end", "message": "Critic evaluation completed."}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"}, run_id=run_id)
            await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100}, run_id=run_id)
            await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"}, run_id=run_id)
    except (StaleRunError, asyncio.CancelledError):
        return
    except Exception as exc:
        if not await is_current_run(task_id, run_id):
            return
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True}, run_id=run_id)


async def run_schema_calibration(task_id: str, run_id: str, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    suggestions = state.get("suggested_schema_extensions") or []
    feedback = state.get("critic_feedback") or []
    needs_intervention = len(suggestions) > 0 or len(feedback) > 0
    if not needs_intervention:
        return state, "none"

    context = state.get("task_context") or {}
    execution_mode = context.get("execution_mode", "step_by_step")
    if execution_mode != "auto":
        import sys; print("[CALIBRATION] acquiring session...", file=sys.stderr, flush=True)
        await guard_active(task_id, run_id)
        async with async_session() as session:
            await update_task_state(session, task_id, state="NEEDS_INTERVENTION", progress=95)
            await add_intervention(session, task_id, "schema_extension_request", {"suggestions": suggestions, "feedback_count": len(feedback)})
            if feedback:
                await save_quality_feedback(session, task_id, feedback)
            print("[CALIBRATION] update + intervention + feedback done, committing...", file=sys.stderr, flush=True)
            await session.commit()
        print("[CALIBRATION] DB done, publishing events...", file=sys.stderr, flush=True)
        await publish_event(
            task_id,
            "debug_log",
            {
                "agent": "Critic",
                "event": "end",
                "message": "Critic evaluation completed; waiting for user review.",
            },
            run_id=run_id,
        )
        await publish_event(
            task_id,
            "schema_extension_request",
            {
                "suggested_schema_extensions": suggestions,
                "feedback_count": len(feedback),
                "message": "Critic found quality issues to review. Open Critic Review panel.",
            },
            run_id=run_id,
        )
        print("[CALIBRATION] publishing task_state_changed NEEDS_INTERVENTION...", flush=True)
        await publish_event(task_id, "task_state_changed", {"state": "NEEDS_INTERVENTION", "progress": 95, "suggested_schema_extensions": suggestions, "feedback_count": len(feedback)}, run_id=run_id)
        print("[CALIBRATION] events published, returning waiting_for_user", flush=True)
        return state, "waiting_for_user"

    calibration_count = int(state.get("retry_counts", {}).get("schema_calibration", 0))
    if calibration_count >= 1:
        return state, "skipped"

    updated_schema, added_fields = merge_schema_extensions(state.get("dynamic_schema", {}), suggestions)
    if not added_fields:
        return state, "none"

    retry_counts = state.get("retry_counts", {})
    retry_counts["schema_calibration"] = calibration_count + 1
    state["retry_counts"] = retry_counts
    state["dynamic_schema"] = updated_schema
    context["collection_scope_field_ids"] = [field["id"] for field in added_fields if field.get("id")]
    state["task_context"] = context

    await guard_active(task_id, run_id)
    async with async_session() as session:
        await save_schema(session, task_id, updated_schema, created_by="critic", status="active")
        await update_task_state(session, task_id, state="SCHEMA_CALIBRATING", progress=92)
        await session.commit()
    await publish_event(
        task_id,
        "schema_extended",
        {
            "dynamic_schema": updated_schema,
            "added_fields": added_fields,
            "stats": count_schema_stats(updated_schema),
        },
        run_id=run_id,
    )
    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_CALIBRATING", "progress": 92}, run_id=run_id)

    previous_materials = list(state.get("raw_materials") or [])
    await guard_active(task_id, run_id)
    incremental_state = await collector_node(state)
    await guard_active(task_id, run_id)
    new_materials = incremental_state.get("raw_materials") or []
    state["raw_materials"] = previous_materials + new_materials
    context.pop("collection_scope_field_ids", None)
    state["task_context"] = context

    async with async_session() as session:
        task = await update_task_state(session, task_id, state="ANALYZING", progress=96)
        collection_run_id = task.current_collection_run_id or run_id
        task.current_collection_run_id = collection_run_id
        await save_source_materials(session, task_id, new_materials, collection_run_id=collection_run_id)
        new_ids = [m.get("id") for m in new_materials if m.get("id")]
        current_ids = list(task.current_material_ids or [])
        current_ids.extend(item for item in new_ids if item not in current_ids)
        task.current_material_ids = current_ids
        await session.commit()
    await publish_event(task_id, "raw_materials_updated", {"data": state["raw_materials"], "source_stats": source_stats(state["raw_materials"])}, run_id=run_id)

    await guard_active(task_id, run_id)
    state = await analyzer_node(state)
    await guard_active(task_id, run_id)
    analysis = state.get("analysis_results") or {}
    async with async_session() as session:
        task = await update_task_state(session, task_id, state="ANALYZING", progress=98)
        task.analysis_results = analysis
        for module_id in ("comparison", "swot", "report"):
            content = analysis.get(module_id, {}) if isinstance(analysis, dict) else {}
            await save_analysis_module(
                session,
                task_id,
                module_id=module_id,
                module_type=module_id,
                content=content if isinstance(content, dict) else {"items": content},
                evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
            )
        await session.commit()
    await publish_event(task_id, "analysis_progress", {"module_id": "analysis", "data": analysis, "calibrated": True}, run_id=run_id)

    state = await critic_node(state)
    return state, "applied"


async def calibration_confirm(task_id: str, run_id: str):
    """User confirmed schema extensions: delegate to unified retry pipeline."""
    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                return

            result = await session.execute(
                select(InterventionLogRecord)
                .where(InterventionLogRecord.task_id == task_id, InterventionLogRecord.action_type == "schema_extension_request")
                .order_by(desc(InterventionLogRecord.created_at))
                .limit(1)
            )
            intervention = result.scalar_one_or_none()
            if not intervention:
                await publish_event(task_id, "debug_log", {"agent": "Calibration", "event": "warning", "message": "No schema_extension_request intervention found, aborting calibration."}, run_id=run_id)
                return
            suggestions = (intervention.payload or {}).get("suggestions", [])

        if not suggestions:
            await calibration_reject(task_id, run_id)
            return

        await run_critic_retry(task_id, run_id, confirmed_extensions=suggestions)
    except (StaleRunError, asyncio.CancelledError):
        return
    except Exception as exc:
        if not await is_current_run(task_id, run_id):
            return
        import logging
        logging.error(f"Error in calibration_confirm: {exc}")
        await publish_event(task_id, "debug_log", {"agent": "Calibration", "event": "error", "message": f"calibration_confirm failed: {exc}"}, run_id=run_id)
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True}, run_id=run_id)


async def calibration_reject(task_id: str, run_id: str):
    """User rejected schema extensions: continue to reporter directly."""
    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                return
            schema_record = await latest_schema(session, task_id)
            dynamic_schema = schema_record.schema_json if schema_record else (db_task.dynamic_schema or {})
            material_ids = db_task.current_material_ids or []
            if material_ids:
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    material_ids=material_ids,
                    collection_run_id=db_task.current_collection_run_id,
                    schema=dynamic_schema,
                )
            else:
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    collection_run_id=db_task.current_collection_run_id,
                    schema=dynamic_schema,
                )
            if not raw_materials:
                raw_materials = db_task.raw_materials or []

        state = {
            "task_id": task_id,
            "task_context": {
                "domain": db_task.domain,
                "competitors": db_task.competitors or [],
                "execution_mode": db_task.execution_mode,
                "analysis_goal": db_task.analysis_goal or "",
                "task_intent": db_task.task_intent or {},
            },
            "dynamic_schema": dynamic_schema,
            "raw_materials": raw_materials,
            "analysis_results": db_task.analysis_results or {},
            "critic_feedback": db_task.critic_feedback or [],
        }

        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "start", "message": "Generating final structured report."}, run_id=run_id)
        state = await reporter_node(state)
        await guard_active(task_id, run_id)
        report_analysis = state.get("analysis_results") or {}
        async with async_session() as session:
            await guard_active(task_id, run_id)
            task = await update_task_state(session, task_id, state="COMPLETED", progress=100)
            task.analysis_results = report_analysis
            task.final_report = report_analysis.get("report", {})
            task.completed_at = datetime.utcnow()
            report_content = report_analysis.get("report", {})
            await save_analysis_module(session, task_id, module_id="report", module_type="report",
                                       content=report_content if isinstance(report_content, dict) else {"items": report_content},
                                       evidence_refs=report_analysis.get("evidence_refs", []) if isinstance(report_analysis, dict) else [])
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "end", "message": "Structured report generated."}, run_id=run_id)
        await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"}, run_id=run_id)
        await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100}, run_id=run_id)
        await publish_event(task_id, "analysis_progress", {"module_id": "report", "data": report_analysis}, run_id=run_id)
        await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"}, run_id=run_id)
    except (StaleRunError, asyncio.CancelledError):
        return
    except Exception as exc:
        if not await is_current_run(task_id, run_id):
            return
        import logging
        logging.error(f"Error in calibration_reject: {exc}")
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True}, run_id=run_id)


async def regenerate_schema(task_id: str, run_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            return
        latest = await latest_schema(session, task_id)
        predefined_schema = []
        if latest and isinstance(latest.schema_json, dict):
            for fields in latest.schema_json.values():
                if isinstance(fields, list):
                    predefined_schema.extend(field for field in fields if isinstance(field, dict))
        state = {
            "task_id": task_id,
            "task_context": {
                "domain": db_task.domain,
                "competitors": db_task.competitors or [],
                "execution_mode": db_task.execution_mode,
                "predefined_schema": predefined_schema,
                "analysis_goal": db_task.analysis_goal or "",
                "task_intent": db_task.task_intent or {},
            },
            "schema_version": latest.version if latest else 1,
            "dynamic_schema": {},
            "raw_materials": [],
            "source_ids": [],
            "analysis_results": {},
            "critic_feedback": [],
            "suggested_schema_extensions": [],
            "task_events": [],
            "progress": 10,
            "module_updates": [],
            "retry_counts": {},
        }
    await guard_active(task_id, run_id)
    await publish_task_intent_debug(task_id, run_id, state.get("task_context", {}).get("task_intent"))
    updated_state = await orchestrator_node(state)
    await guard_active(task_id, run_id)
    schema_json = updated_state.get("dynamic_schema") or {}
    discovered_competitors = (updated_state.get("task_context") or {}).get("competitors") or []
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if db_task and discovered_competitors:
            db_task.competitors = discovered_competitors
        record = await save_schema(session, task_id, schema_json, created_by="agent", status="active")
        await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=30)
        await session.commit()
    await publish_event(
        task_id,
        "schema_ready",
        {
            "dynamic_schema": schema_json,
            "schema_version": record.version,
            "competitors": discovered_competitors,
            "stats": count_schema_stats(schema_json)
        },
        run_id=run_id,
    )
    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW", "progress": 30}, run_id=run_id)


async def run_critic_retry(
    task_id: str,
    run_id: str,
    confirmed_feedback_ids: list[str] | None = None,
    confirmed_extensions: list[dict[str, Any]] | None = None,
):
    """Unified retry: merge extensions + feedback, determine start node, run incremental pipeline."""
    feedback_ids = confirmed_feedback_ids or []
    extensions = confirmed_extensions or []

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                return
            schema_record = await latest_schema(session, task_id)
            current_schema = schema_record.schema_json if schema_record else (db_task.dynamic_schema or {})
            material_ids = db_task.current_material_ids or []
            if material_ids:
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    material_ids=material_ids,
                    collection_run_id=db_task.current_collection_run_id,
                    schema=current_schema,
                )
            else:
                raw_materials = await load_source_materials(
                    session,
                    task_id,
                    collection_run_id=db_task.current_collection_run_id,
                    schema=current_schema,
                )
            if not raw_materials:
                raw_materials = db_task.raw_materials or []
            existing_analysis = db_task.analysis_results or {}
            existing_critic_feedback = db_task.critic_feedback or []

        await publish_event(task_id, "debug_log", {"agent": "CriticRetry", "event": "start", "message": f"Unified retry: {len(extensions)} extensions + {len(feedback_ids)} feedback items."}, run_id=run_id)

        # Step 1: process extensions → get new field IDs
        extension_field_ids: list[str] = []
        if extensions:
            updated_schema, added_fields = merge_schema_extensions(current_schema, extensions)
            await guard_active(task_id, run_id)
            async with async_session() as session:
                await save_schema(session, task_id, updated_schema, created_by="critic", status="active")
                await session.commit()
            await publish_event(task_id, "debug_log", {
                "agent": "CriticRetry",
                "event": "debug",
                "message": f"Applied {len(added_fields)} schema extension field(s) from {len(extensions)} confirmed suggestion(s).",
                "output_json": {"added_fields": added_fields},
            }, run_id=run_id)
            await publish_event(task_id, "schema_extended", {
                "dynamic_schema": updated_schema,
                "added_fields": added_fields,
                "stats": count_schema_stats(updated_schema),
            }, run_id=run_id)
            current_schema = updated_schema
            extension_field_ids = [f["id"] for f in added_fields if f.get("id")]

        # Step 2: query feedback records, group by action
        retry_collection_fields: list[str] = []
        retry_analysis_context: list[dict[str, Any]] = []
        collection_unmatched_feedback_ids: list[str] = []
        if feedback_ids:
            async with async_session() as session:
                result = await session.execute(
                    select(QualityFeedbackRecord).where(
                        QualityFeedbackRecord.id.in_(feedback_ids),
                        QualityFeedbackRecord.task_id == task_id,
                    )
                )
                feedback_records = list(result.scalars())

            field_index = build_field_index(current_schema)
            for f in feedback_records:
                retry_analysis_context.append({
                    "issue": f.message,
                    "target": f.target_id,
                    "action": f.suggested_action,
                    "module_id": f.module_id,
                    "severity": f.severity,
                    "code": f.code,
                })
                if f.suggested_action == "retry_collection":
                    matched_ids = _match_feedback_field_ids(f, field_index)
                    if matched_ids:
                        retry_collection_fields.extend(matched_ids)
                    else:
                        collection_unmatched_feedback_ids.append(f.id)
                continue
                if f.suggested_action == "retry_collection":
                    msg = f.message or ""
                    target = ""
                    for prefix in ("field_name:", "字段:", "维度:"):
                        if prefix in msg:
                            target = msg.split(prefix)[-1].strip().split(",")[0].strip()
                            break
                    if not target:
                        target = f.target_id or ""
                    for fl in field_index:
                        fn = fl.get("field_name") or fl.get("name") or ""
                        if (target and target in fn) or (target == fl.get("id")):
                            retry_collection_fields.append(fl.get("id") or "")
                elif f.suggested_action in ("retry_analysis", "extend_schema"):
                    retry_analysis_context.append({"issue": f.message, "target": f.target_id})

            await publish_event(task_id, "debug_log", {
                "agent": "CriticRetry",
                "event": "debug",
                "message": (
                    f"Mapped {len(feedback_records)} selected feedback item(s) to "
                    f"{len(set(retry_collection_fields))} collection field(s) and "
                    f"{len(retry_analysis_context)} analysis instruction(s)."
                ),
                "output_json": {
                    "retry_collection_field_ids": list(dict.fromkeys(retry_collection_fields)),
                    "collection_unmatched_feedback_ids": collection_unmatched_feedback_ids,
                    "analysis_instruction_count": len(retry_analysis_context),
                },
            }, run_id=run_id)

        # Step 3: merge collection scope
        all_collection_ids = list(dict.fromkeys(extension_field_ids + retry_collection_fields))
        needs_collection = len(all_collection_ids) > 0

        # Step 4: build state
        task_context: dict[str, Any] = {
            "domain": db_task.domain,
            "competitors": db_task.competitors or [],
            "execution_mode": db_task.execution_mode,
            "analysis_goal": db_task.analysis_goal or "",
            "task_intent": db_task.task_intent or {},
        }
        if needs_collection:
            task_context["collection_scope_field_ids"] = all_collection_ids
            task_context["excluded_source_urls"] = _material_urls(list(raw_materials))

        state: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "task_context": task_context,
            "dynamic_schema": current_schema,
            "raw_materials": list(raw_materials),
            "analysis_results": existing_analysis,
            "critic_feedback": retry_analysis_context + existing_critic_feedback,
        }

        # Step 5: run from earliest node
        if needs_collection:
            async def publish_collector_progress(payload: dict[str, Any]):
                await publish_event(task_id, "collector_log", payload, run_id=run_id)

            async with async_session() as session:
                await guard_active(task_id, run_id)
                await update_task_state(session, task_id, state="COLLECTING", progress=70)
                await session.commit()
            await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 70, "retry": True}, run_id=run_id)
            await publish_event(task_id, "progress_update", {"progress": 70, "stage": "COLLECTING", "retry": True}, run_id=run_id)
            await publish_event(task_id, "debug_log", {
                "agent": "Collector",
                "event": "start",
                "message": f"Retry collecting {len(all_collection_ids)} scoped fields.",
                "output_json": {"collection_scope_field_ids": all_collection_ids},
            }, run_id=run_id)
            await guard_active(task_id, run_id)
            state = await collector_node(state, on_progress=publish_collector_progress)
            await guard_active(task_id, run_id)
            existing_ids = {m.get("id") for m in raw_materials if m.get("id")}
            new_materials_by_id = {
                m.get("id"): m
                for m in (state.get("raw_materials") or [])
                if m.get("id") and m.get("id") not in existing_ids
            }
            new_materials = list(new_materials_by_id.values())
            all_materials = raw_materials + new_materials

            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "debug", "message": f"Collector done, saving {len(new_materials)} new materials to DB..."}, run_id=run_id)
            async with async_session() as session:
                task = await update_task_state(session, task_id, state="ANALYZING", progress=95)
                collection_run_id = task.current_collection_run_id or run_id
                task.current_collection_run_id = collection_run_id
                await save_source_materials(session, task_id, new_materials, collection_run_id=collection_run_id)
                new_ids = [m.get("id") for m in new_materials if m.get("id")]
                current_ids = list(task.current_material_ids or [])
                current_ids.extend(item for item in new_ids if item not in current_ids)
                task.current_material_ids = current_ids
                await session.commit()
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": f"Re-collected {len(new_materials)} materials."}, run_id=run_id)
            await publish_event(task_id, "raw_materials_updated", {"data": all_materials, "source_stats": source_stats(all_materials), "retry": True}, run_id=run_id)
            state["raw_materials"] = all_materials

        # ── Generate scopes from critic feedback + schema extensions ──
        # (lazy import to break circular dependency: analysis_rerun imports publish_event from this module)
        from services.analysis_rerun import RerunContext, affected_modules_for_scopes, normalize_batch_scopes, run_scoped_rerun_with_ctx  # noqa: F811
        from services.critic_scope_mapper import feedback_to_rerun_scopes  # noqa: F811

        existing_analysis = dict(db_task.analysis_results or {})
        analysis_feedback = [
            item for item in retry_analysis_context
            if item.get("action") in ("retry_analysis", "extend_schema")
        ]
        all_scopes = list(feedback_to_rerun_scopes(
            analysis_feedback, existing_analysis, current_schema,
        ))
        # Add dimension scopes for ALL re-collected fields (not just extensions)
        for field_id in all_collection_ids:
            all_scopes.append({
                "type": "dimension", "module_id": "comparison", "dimension_id": field_id,
            })
        normalized_scopes = normalize_batch_scopes(all_scopes, existing_analysis)

        # Fallback: if materials were re-collected but no specific scopes exist,
        # use comparison scope so the merge doesn't discard analyzer output
        if not normalized_scopes:
            normalized_scopes = [{"type": "comparison", "module_id": "comparison"}]
            await publish_event(task_id, "debug_log", {
                "agent": "CriticScopeMapper",
                "event": "info",
                "message": "No specific scopes derived from feedback — falling back to full comparison rerun.",
            }, run_id=run_id, allow_inactive=True)

        # Fallback diagnostic: count scopes that fell back to comparison (imprecise)
        fallback_count = sum(1 for s in normalized_scopes if s.get("type") == "comparison")
        if fallback_count:
            await publish_event(task_id, "debug_log", {
                "agent": "CriticScopeMapper",
                "event": "warning",
                "message": (
                    f"{fallback_count} feedback item(s) fell back to comparison scope "
                    f"(could not map to a specific dimension/competitor). "
                    f"Consider adding more precise target_id to feedback records."
                ),
                "output_json": {"fallback_count": fallback_count},
            }, run_id=run_id, allow_inactive=True)

        await guard_active(task_id, run_id)
        await publish_event(task_id, "debug_log", {
            "agent": "Analyzer", "event": "start",
            "message": f"Re-analyzing with {len(normalized_scopes)} scoped rerun(s).",
            "output_json": {
                "scope_count": len(normalized_scopes),
                "fallback_to_comparison": fallback_count,
                "scopes": normalized_scopes,
            },
        }, run_id=run_id)

        # Build in-memory RerunContext and delegate to the shared core
        ctx = RerunContext(
            task_id=task_id,
            domain=db_task.domain or "",
            competitors=list(db_task.competitors or []),
            execution_mode=db_task.execution_mode or "step_by_step",
            analysis_goal=db_task.analysis_goal,
            analysis_results=existing_analysis,
            raw_materials=list(state.get("raw_materials", [])),
            dynamic_schema=current_schema,
            schema_version=schema_record.version if schema_record else 0,
            task_state="ANALYSIS_REVIEW",
            task_intent=db_task.task_intent or {},
        )
        merged_analysis = await run_scoped_rerun_with_ctx(
            ctx, run_id, normalized_scopes,
            instruction="根据 Critic 质量审查反馈修复分析结果",
        )
        state["analysis_results"] = merged_analysis
        analysis = merged_analysis

        # Persist — only save modules actually touched by the scopes
        affected_modules = affected_modules_for_scopes(normalized_scopes)
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="ANALYZING", progress=97)
            task.analysis_results = analysis
            for module_id in affected_modules:
                content = analysis.get(module_id, {}) if isinstance(analysis, dict) else {}
                await save_analysis_module(
                    session, task_id, module_id=module_id, module_type=module_id,
                    content=content if isinstance(content, dict) else {"items": content},
                    evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
                )
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": f"Analysis completed (scoped retry, affected: {affected_modules})."}, run_id=run_id)
        await guard_active(task_id, run_id)
        await publish_event(task_id, "debug_log", {
            "agent": "CriticRetry",
            "event": "info",
            "message": "Skipping second Critic pass after confirmed feedback; proceeding to Reporter.",
        }, run_id=run_id)
        await publish_event(task_id, "debug_log", {
            "agent": "Critic",
            "event": "end",
            "message": "Critic feedback resolved; no second Critic pass required.",
        }, run_id=run_id)
        await guard_active(task_id, run_id)
        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "start", "message": "Generating final report (retry)."}, run_id=run_id)
        state = await reporter_node(state)
        await guard_active(task_id, run_id)
        report_analysis = state.get("analysis_results") or {}
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="COMPLETED", progress=100)
            task.analysis_results = report_analysis
            task.final_report = report_analysis.get("report", {})
            task.completed_at = datetime.utcnow()
            report_content = report_analysis.get("report", {})
            await save_analysis_module(
                session, task_id, module_id="report", module_type="report",
                content=report_content if isinstance(report_content, dict) else {"items": report_content},
                evidence_refs=report_analysis.get("evidence_refs", []) if isinstance(report_analysis, dict) else [],
            )
            if feedback_ids:
                await resolve_feedback_items(session, task_id, feedback_ids)
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "end", "message": "Report generated (retry)."}, run_id=run_id)
        await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"}, run_id=run_id)
        await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100}, run_id=run_id)
        await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"}, run_id=run_id)
    except (StaleRunError, asyncio.CancelledError):
        return
    except Exception as exc:
        if not await is_current_run(task_id, run_id):
            return
        import logging
        logging.error(f"Error in run_critic_retry: {exc}")
        await publish_event(task_id, "debug_log", {"agent": "CriticRetry", "event": "error", "message": f"run_critic_retry failed: {exc}"}, run_id=run_id)
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True}, run_id=run_id)
