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
    latest_schema,
    resolve_feedback_items,
    save_analysis_module,
    save_quality_feedback,
    save_schema,
    save_source_materials,
    update_task_state,
    write_checkpoint,
)
from services.stats import count_schema_stats, source_stats
from sqlalchemy import select, desc


async def publish_event(task_id: str, event_type: str, data: dict[str, Any]):
    return await event_broker.publish(task_id, event_type, data)


async def event_generator(task_id: str, since: int = 0):
    async for message in event_broker.stream(task_id, since=since):
        yield message


def make_initial_state(req: TaskCreateRequest, task_id: str, schema_version: int = 1) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_context": {
            "domain": req.domain,
            "competitors": req.competitors,
            "execution_mode": req.execution_mode,
            "predefined_schema": req.predefined_schema or [],
            "analysis_goal": req.analysis_goal or "",
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


async def process_initial_pipeline(task_id: str, initial_state: dict[str, Any], *, continue_after_schema: bool = False):
    try:
        from agents.discoverer.node import discoverer_node
        if runner.is_cancelled(task_id):
            return

        await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "start", "message": "Starting competitor discovery and market context gathering."})
        state = await discoverer_node(initial_state)
        await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "end", "message": "Competitors discovered and market context loaded."})
        await publish_event(task_id, "progress_update", {"progress": 15, "stage": "DISCOVERING"})
        
        await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Completing competitors and schema from domain inputs."})
        state = await orchestrator_node(state)
        schema_json = state.get("dynamic_schema") or {}
        discovered_competitors = (state.get("task_context") or {}).get("competitors") or []
        async with async_session() as session:
            task = await get_task(session, task_id)
            if task and discovered_competitors:
                task.competitors = discovered_competitors
            record = await save_schema(session, task_id, schema_json, created_by="agent", status="active")
            await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=30)
            print(f"[SNAPSHOT] writing pre_collection checkpoint for {task_id}...", flush=True)
            await write_checkpoint(
                session, task_id, "pre_collection", "SCHEMA_READY",
                f"Schema ready: {len(discovered_competitors)} competitors, {sum(len(v) if isinstance(v, list) else 0 for v in schema_json.values())} fields",
                {
                    "competitors": discovered_competitors,
                    "progress": 30,
                    "dynamic_schema": schema_json,
                    "state": "SCHEMA_REVIEW",
                    "raw_materials": [],
                },
            )
            await session.commit()
            print(f"[SNAPSHOT] checkpoint committed for {task_id}", flush=True)
        await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Competitor list and schema completed."})
        await publish_event(task_id, "progress_update", {"progress": 30, "stage": "SCHEMA_REVIEW"})
        await publish_event(
            task_id,
            "schema_ready",
            {
                "dynamic_schema": schema_json,
                "schema_version": record.version,
                "competitors": discovered_competitors,
                "stats": count_schema_stats(schema_json),
            },
        )
        await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW", "progress": 30})
        if continue_after_schema:
            async with async_session() as session:
                await update_task_state(session, task_id, state="COLLECTING", progress=40)
                await session.commit()
            await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "previous_state": "SCHEMA_REVIEW", "progress": 40})
            if runner.is_cancelled(task_id):
                return
            await process_agent_pipeline(task_id)
    except Exception as exc:
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True})


async def process_graph_events(task_id: str, graph, initial_state, config):
    if graph is None:
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": "Workflow is not initialized", "recoverable": True})
        return

    try:
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, state in event.items():
                if node_name == "discoverer":
                    discovered_competitors = (state.get("task_context") or {}).get("competitors") or []
                    async with async_session() as session:
                        task = await get_task(session, task_id)
                        if task and discovered_competitors:
                            task.competitors = discovered_competitors
                            await session.commit()
                    await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "end", "message": "Competitors discovered successfully."})
                    await publish_event(task_id, "progress_update", {"progress": 15, "stage": "DISCOVERING"})
                    await publish_event(task_id, "task_state_changed", {"state": "DISCOVERING", "progress": 15})

                elif node_name == "orchestrator":
                    schema_json = state.get("dynamic_schema") or {}
                    schema_version = state.get("schema_version", 1)
                    async with async_session() as session:
                        await save_schema(session, task_id, schema_json, created_by="agent", status="active")
                        await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=30)
                        await session.commit()
                    await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Schema generated successfully."})
                    await publish_event(task_id, "token_update", {"total_used": 1500, "budget": 50000, "estimated_remaining": 48500})
                    await publish_event(task_id, "progress_update", {"progress": 30, "stage": "SCHEMA_REVIEW"})
                    await publish_event(
                        task_id,
                        "schema_ready",
                        {
                            "dynamic_schema": schema_json,
                            "schema_version": schema_version,
                            "competitors": (state.get("task_context") or {}).get("competitors") or [],
                            "stats": count_schema_stats(schema_json)
                        },
                    )
                    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW", "progress": 30})

                elif node_name.startswith("collector_"):
                    materials = state.get("raw_materials") or []
                    async with async_session() as session:
                        await save_source_materials(session, task_id, materials)
                        task = await update_task_state(session, task_id, state="COLLECTING", progress=60)
                        task.raw_materials = materials
                        await session.commit()
                    await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"})
                    await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60})
                    await publish_event(task_id, "raw_materials_updated", {"data": materials, "source_stats": source_stats(materials)})

                elif node_name == "analyzer":
                    analysis = state.get("analysis_results") or {}
                    async with async_session() as session:
                        task = await update_task_state(session, task_id, state="ANALYZING", progress=90)
                        task.analysis_results = analysis
                        for module_id in ("comparison", "swot"):
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
                    await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": "Analysis completed."})
                    await publish_event(task_id, "progress_update", {"progress": 90, "stage": "ANALYZING"})
                    await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 90})
                    await publish_event(task_id, "analysis_progress", {"module_id": "analysis", "data": analysis})
                    await publish_event(task_id, "token_update", {"total_used": 8500, "budget": 50000, "estimated_remaining": 41500})

                elif node_name == "critic":
                    feedback = state.get("critic_feedback") or []
                    async with async_session() as session:
                        task = await update_task_state(session, task_id, state="CRITIQUING", progress=95)
                        task.critic_feedback = feedback
                        await save_quality_feedback(session, task_id, feedback)
                        await session.commit()
                    await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "end", "message": "Critic evaluation completed."})
                    await publish_event(task_id, "progress_update", {"progress": 95, "stage": "CRITIQUING"})
                    await publish_event(task_id, "task_state_changed", {"state": "CRITIQUING", "progress": 95})

                elif node_name == "reporter":
                    analysis = state.get("analysis_results") or {}
                    async with async_session() as session:
                        task = await update_task_state(session, task_id, state="COMPLETED", progress=100)
                        task.analysis_results = analysis
                        task.final_report = analysis.get("report", {})
                        task.completed_at = datetime.utcnow()
                        content = analysis.get("report", {})
                        await save_analysis_module(
                            session,
                            task_id,
                            module_id="report",
                            module_type="report",
                            content=content if isinstance(content, dict) else {"items": content},
                            evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
                        )
                        await session.commit()
                    await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "end", "message": "Structured report generated."})
                    await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"})
                    await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100})
                    await publish_event(task_id, "analysis_progress", {"module_id": "report", "data": analysis})
                    await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"})

    except Exception as exc:
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True})


async def _with_timeout(task_id: str, label: str, coro):
    """Run a coro with 30s timeout, publishing debug events on success/failure."""
    try:
        result = await asyncio.wait_for(coro, timeout=30)
        return result
    except asyncio.TimeoutError:
        await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "error", "message": f"[TIMEOUT] {label} timed out after 30s"})
        raise


async def process_agent_pipeline(task_id: str, start_from: str = "collector", snapshot_data: dict[str, Any] | None = None):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            return
        schema_record = await latest_schema(session, task_id)

        if snapshot_data and "raw_materials" in snapshot_data:
            raw_materials = snapshot_data["raw_materials"]
        elif start_from != "collector":
            raw_materials = list(db_task.raw_materials or [])
        else:
            raw_materials = []

        state = {
            "task_id": task_id,
            "task_context": {
                "domain": db_task.domain,
                "competitors": db_task.competitors or [],
                "execution_mode": db_task.execution_mode,
                "predefined_schema": [],
                "analysis_goal": db_task.analysis_goal or "",
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
            await publish_event(task_id, "collector_log", payload)

        # ── Emit synthetic end events for skipped earlier phases ──
        if start_from in ("collector",):
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "start", "message": "Skipped (restored from snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "end", "message": "Completed (restored from snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Skipped (restored from snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Completed (restored from snapshot)."})
            await publish_event(task_id, "progress_update", {"progress": 30, "stage": "SCHEMA_REVIEW"})
        elif start_from in ("analyzer",):
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "start", "message": "Skipped (restored from post-collection snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Discoverer", "event": "end", "message": "Completed (restored from post-collection snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Skipped (restored from post-collection snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Completed (restored from post-collection snapshot)."})
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "start", "message": "Skipped (data already collected, using snapshot materials)."})
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Completed (materials restored from snapshot)."})
            await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"})

        # ── COLLECTOR PHASE ──
        if start_from in ("collector",):
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "start", "message": "Starting data collection for all competitors."})
            state = await collector_node(state, on_progress=publish_collector_progress)
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
            await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "debug", "message": f"Collector returned {len(materials)} materials: {competitor_counts}, status: {status_counts}, saving to DB...", "output_json": {"total": len(materials), "per_competitor": competitor_counts, "per_status": status_counts, "sample": material_sample}})
            async with async_session() as session:
                task = await _with_timeout(task_id, "update_task_state", update_task_state(session, task_id, state="COLLECTING", progress=60))
                task.raw_materials = materials
                await _with_timeout(task_id, "save_source_materials", save_source_materials(session, task_id, materials))

                # ── Post-collection snapshot ──
                await write_checkpoint(
                    session, task_id, "post_collection", "COLLECTING",
                    f"Collection complete: {len(materials)} materials across {len(competitor_counts)} competitors",
                    {
                        "competitors": (state.get("task_context") or {}).get("competitors", []),
                        "progress": 60,
                        "dynamic_schema": state.get("dynamic_schema", {}),
                        "state": "COLLECTING",
                        "raw_materials": materials,
                    },
                )

                await session.commit()
            await publish_event(task_id, "debug_log", {"agent": "Pipeline", "event": "debug", "message": "DB save complete."})
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Data collection completed."})
            await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"})
            await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60})
            await publish_event(task_id, "raw_materials_updated", {"data": materials, "source_stats": source_stats(materials)})
        else:
            await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"})
            await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60})

        if runner.is_cancelled(task_id):
            return

        # ── ANALYZER PHASE ──
        if start_from in ("collector", "analyzer"):
            await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "start", "message": "Starting comparative analysis."})
            state = await analyzer_node(state)
            analysis = state.get("analysis_results") or {}
            async with async_session() as session:
                task = await _with_timeout(task_id, "update_task_state", update_task_state(session, task_id, state="ANALYZING", progress=90))
                task.analysis_results = analysis
                for module_id in ("comparison", "swot", "report"):
                    content = analysis.get(module_id, {}) if isinstance(analysis, dict) else {}
                    await _with_timeout(task_id, f"save_analysis_module({module_id})", save_analysis_module(
                        session, task_id,
                        module_id=module_id, module_type=module_id,
                        content=content if isinstance(content, dict) else {"items": content},
                        evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
                    ))
                await session.commit()
            await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": "Analysis completed."})
            await publish_event(task_id, "progress_update", {"progress": 90, "stage": "ANALYZING"})
            await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 90})
            await publish_event(task_id, "analysis_progress", {"module_id": "analysis", "data": analysis})
        else:
            await publish_event(task_id, "progress_update", {"progress": 90, "stage": "ANALYZING"})
            await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 90})

        if runner.is_cancelled(task_id):
            return

        # ── CRITIC PHASE ──
        if start_from in ("collector", "analyzer", "critic"):
            await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "start", "message": "Starting critic quality evaluation."})
            state = await critic_node(state)
            state, calibration_outcome = await run_schema_calibration(task_id, state)
            if calibration_outcome == "waiting_for_user":
                return

        if runner.is_cancelled(task_id):
            return

        # ── REPORTER PHASE ──
        if start_from in ("collector", "analyzer", "critic", "reporter"):
            await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "start", "message": "Generating final structured report."})
            state = await reporter_node(state)
            await publish_event(task_id, "analysis_progress", {"module_id": "report", "data": state.get("analysis_results") or {}})

            feedback = state.get("critic_feedback") or []
            async with async_session() as session:
                task = await _with_timeout(task_id, "update_task_state(COMPLETED)", update_task_state(session, task_id, state="COMPLETED", progress=100))
                task.analysis_results = state.get("analysis_results") or {}
                task.critic_feedback = feedback
                task.final_report = task.analysis_results.get("report", {})
                task.completed_at = datetime.utcnow()
                await _with_timeout(task_id, "save_quality_feedback", save_quality_feedback(session, task_id, feedback))
                await session.commit()
            await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "end", "message": "Critic evaluation completed."})
            await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"})
            await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100})
            await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"})
    except Exception as exc:
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True})


async def run_schema_calibration(task_id: str, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    suggestions = state.get("suggested_schema_extensions") or []
    feedback = state.get("critic_feedback") or []
    needs_intervention = len(suggestions) > 0 or len(feedback) > 0
    if not needs_intervention:
        return state, "none"

    context = state.get("task_context") or {}
    execution_mode = context.get("execution_mode", "step_by_step")
    if execution_mode != "auto":
        import sys; print("[CALIBRATION] acquiring session...", file=sys.stderr, flush=True)
        async with async_session() as session:
            await update_task_state(session, task_id, state="NEEDS_INTERVENTION", progress=95)
            await add_intervention(session, task_id, "schema_extension_request", {"suggestions": suggestions, "feedback_count": len(feedback)})
            if feedback:
                await save_quality_feedback(session, task_id, feedback)
            print("[CALIBRATION] update + intervention + feedback done, committing...", file=sys.stderr, flush=True)
            await session.commit()
        print("[CALIBRATION] DB done, publishing events...", file=sys.stderr, flush=True)
        await publish_event(task_id, "debug_log", {"agent": "Calibration", "event": "debug", "message": f"Intervention saved, {len(suggestions)} extensions + {len(feedback)} feedback items pending user review."})
        await publish_event(
            task_id,
            "schema_extension_request",
            {
                "suggested_schema_extensions": suggestions,
                "feedback_count": len(feedback),
                "message": "Critic found quality issues to review. Open Critic Review panel.",
            },
        )
        print("[CALIBRATION] publishing task_state_changed NEEDS_INTERVENTION...", flush=True)
        await publish_event(task_id, "task_state_changed", {"state": "NEEDS_INTERVENTION", "progress": 95, "suggested_schema_extensions": suggestions, "feedback_count": len(feedback)})
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
    )
    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_CALIBRATING", "progress": 92})

    previous_materials = list(state.get("raw_materials") or [])
    incremental_state = await collector_node(state)
    new_materials = incremental_state.get("raw_materials") or []
    state["raw_materials"] = previous_materials + new_materials
    context.pop("collection_scope_field_ids", None)
    state["task_context"] = context

    async with async_session() as session:
        task = await update_task_state(session, task_id, state="ANALYZING", progress=96)
        task.raw_materials = state["raw_materials"]
        await save_source_materials(session, task_id, new_materials)
        await session.commit()
    await publish_event(task_id, "raw_materials_updated", {"data": state["raw_materials"], "source_stats": source_stats(state["raw_materials"])})

    state = await analyzer_node(state)
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
    await publish_event(task_id, "analysis_progress", {"module_id": "analysis", "data": analysis, "calibrated": True})

    state = await critic_node(state)
    return state, "applied"


async def calibration_confirm(task_id: str):
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
                await publish_event(task_id, "debug_log", {"agent": "Calibration", "event": "warning", "message": "No schema_extension_request intervention found, aborting calibration."})
                return
            suggestions = (intervention.payload or {}).get("suggestions", [])

        if not suggestions:
            await calibration_reject(task_id)
            return

        await run_critic_retry(task_id, confirmed_extensions=suggestions)
    except Exception as exc:
        import logging
        logging.error(f"Error in calibration_confirm: {exc}")
        await publish_event(task_id, "debug_log", {"agent": "Calibration", "event": "error", "message": f"calibration_confirm failed: {exc}"})
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True})


async def calibration_reject(task_id: str):
    """User rejected schema extensions: continue to reporter directly."""
    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                return

        await publish_event(task_id, "debug_log", {"agent": "Calibration", "event": "start", "message": "User rejected schema extensions, continuing to reporter."})

        state = {
            "task_id": task_id,
            "task_context": {
                "domain": db_task.domain,
                "competitors": db_task.competitors or [],
                "execution_mode": db_task.execution_mode,
                "analysis_goal": db_task.analysis_goal or "",
            },
            "dynamic_schema": db_task.dynamic_schema or {},
            "raw_materials": db_task.raw_materials or [],
            "analysis_results": db_task.analysis_results or {},
            "critic_feedback": db_task.critic_feedback or [],
        }

        state = await reporter_node(state)
        report_analysis = state.get("analysis_results") or {}
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="COMPLETED", progress=100)
            task.analysis_results = report_analysis
            task.final_report = report_analysis.get("report", {})
            task.completed_at = datetime.utcnow()
            report_content = report_analysis.get("report", {})
            await save_analysis_module(session, task_id, module_id="report", module_type="report",
                                       content=report_content if isinstance(report_content, dict) else {"items": report_content},
                                       evidence_refs=report_analysis.get("evidence_refs", []) if isinstance(report_analysis, dict) else [])
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "end", "message": "Structured report generated."})
        await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"})
        await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100})
        await publish_event(task_id, "analysis_progress", {"module_id": "report", "data": report_analysis})
        await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"})
    except Exception as exc:
        import logging
        logging.error(f"Error in calibration_reject: {exc}")
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True})


async def regenerate_schema(task_id: str):
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
    updated_state = await orchestrator_node(state)
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
        }
    )
    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW", "progress": 30})


async def run_critic_retry(
    task_id: str,
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
            raw_materials = db_task.raw_materials or []
            existing_analysis = db_task.analysis_results or {}
            existing_critic_feedback = db_task.critic_feedback or []

        await publish_event(task_id, "debug_log", {"agent": "CriticRetry", "event": "start", "message": f"Unified retry: {len(extensions)} extensions + {len(feedback_ids)} feedback items."})

        # Step 1: process extensions → get new field IDs
        extension_field_ids: list[str] = []
        if extensions:
            updated_schema, added_fields = merge_schema_extensions(current_schema, extensions)
            async with async_session() as session:
                await save_schema(session, task_id, updated_schema, created_by="critic", status="active")
                await session.commit()
            await publish_event(task_id, "schema_extended", {
                "dynamic_schema": updated_schema,
                "added_fields": added_fields,
                "stats": count_schema_stats(updated_schema),
            })
            current_schema = updated_schema
            extension_field_ids = [f["id"] for f in added_fields if f.get("id")]

        # Step 2: query feedback records, group by action
        retry_collection_fields: list[str] = []
        retry_analysis_context: list[dict[str, Any]] = []
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

        # Step 3: merge collection scope
        all_collection_ids = list(dict.fromkeys(extension_field_ids + retry_collection_fields))
        needs_collection = len(all_collection_ids) > 0

        # Step 4: build state
        task_context: dict[str, Any] = {
            "domain": db_task.domain,
            "competitors": db_task.competitors or [],
            "execution_mode": db_task.execution_mode,
            "analysis_goal": db_task.analysis_goal or "",
        }
        if needs_collection:
            task_context["collection_scope_field_ids"] = all_collection_ids

        state: dict[str, Any] = {
            "task_id": task_id,
            "task_context": task_context,
            "dynamic_schema": current_schema,
            "raw_materials": list(raw_materials),
            "analysis_results": existing_analysis,
            "critic_feedback": retry_analysis_context + existing_critic_feedback,
        }

        # Step 5: run from earliest node
        if needs_collection:
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "start", "message": f"Retry collecting {len(all_collection_ids)} scoped fields."})
            state = await collector_node(state)
            existing_ids = {m.get("id") for m in raw_materials if m.get("id")}
            new_materials = [m for m in (state.get("raw_materials") or []) if m.get("id") not in existing_ids]
            all_materials = raw_materials + new_materials

            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "debug", "message": f"Collector done, saving {len(new_materials)} new materials to DB..."})
            async with async_session() as session:
                task = await update_task_state(session, task_id, state="ANALYZING", progress=95)
                task.raw_materials = all_materials
                await save_source_materials(session, task_id, new_materials)
                await session.commit()
            await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": f"Re-collected {len(new_materials)} materials."})
            state["raw_materials"] = all_materials

        await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "start", "message": "Re-analyzing with critic feedback."})
        state = await analyzer_node(state)
        analysis = state.get("analysis_results") or {}
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="ANALYZING", progress=97)
            task.analysis_results = analysis
            for module_id in ("comparison", "swot", "report"):
                content = analysis.get(module_id, {}) if isinstance(analysis, dict) else {}
                await save_analysis_module(
                    session, task_id, module_id=module_id, module_type=module_id,
                    content=content if isinstance(content, dict) else {"items": content},
                    evidence_refs=analysis.get("evidence_refs", []) if isinstance(analysis, dict) else [],
                )
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": "Analysis completed (retry)."})

        state["analysis_results"] = analysis
        await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "start", "message": "Re-critic after retry analysis."})
        state = await critic_node(state)
        new_feedback = state.get("critic_feedback") or []
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="CRITIQUING", progress=98)
            task.critic_feedback = new_feedback
            await save_quality_feedback(session, task_id, new_feedback)
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "end", "message": "Critic done (retry)."})

        state["critic_feedback"] = new_feedback
        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "start", "message": "Generating final report (retry)."})
        state = await reporter_node(state)
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
        await publish_event(task_id, "debug_log", {"agent": "Reporter", "event": "end", "message": "Report generated (retry)."})
        await publish_event(task_id, "progress_update", {"progress": 100, "stage": "COMPLETED"})
        await publish_event(task_id, "task_state_changed", {"state": "COMPLETED", "progress": 100})
        await publish_event(task_id, "task_completed", {"final_report_url": f"/api/v1/tasks/{task_id}/report", "state": "COMPLETED"})
    except Exception as exc:
        import logging
        logging.error(f"Error in run_critic_retry: {exc}")
        await publish_event(task_id, "debug_log", {"agent": "CriticRetry", "event": "error", "message": f"run_critic_retry failed: {exc}"})
        async with async_session() as session:
            try:
                await update_task_state(session, task_id, state="ERROR", error={"message": str(exc), "type": exc.__class__.__name__})
                await session.commit()
            except Exception:
                await session.rollback()
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": str(exc), "error_type": exc.__class__.__name__, "recoverable": True})
