from datetime import datetime
from typing import Any

from agents.analyzer import analyzer_node
from agents.collector import collector_node
from agents.critic import critic_node
from agents.orchestrator import merge_schema_extensions, orchestrator_node
from models_db import async_session
from schemas import TaskCreateRequest
from services.events import event_broker
from services.repositories import (
    get_task,
    latest_schema,
    save_analysis_module,
    save_quality_feedback,
    save_schema,
    save_source_materials,
    update_task_state,
)
from services.stats import count_schema_stats, source_stats


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
        await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Completing competitors and schema from domain inputs."})
        state = await orchestrator_node(initial_state)
        schema_json = state.get("dynamic_schema") or {}
        discovered_competitors = (state.get("task_context") or {}).get("competitors") or []
        async with async_session() as session:
            task = await get_task(session, task_id)
            if task and discovered_competitors:
                task.competitors = discovered_competitors
            record = await save_schema(session, task_id, schema_json, created_by="agent", status="active")
            await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=30)
            await session.commit()
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

                elif node_name == "collector":
                    materials = state.get("raw_materials") or []
                    async with async_session() as session:
                        await save_source_materials(session, task_id, materials)
                        task = await update_task_state(session, task_id, state="COLLECTING", progress=60)
                        task.raw_materials = materials
                        await session.commit()
                    await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Data collection completed."})
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


async def process_agent_pipeline(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            return
        schema_record = await latest_schema(session, task_id)
        state = {
            "task_id": task_id,
            "task_context": {
                "domain": db_task.domain,
                "competitors": db_task.competitors or [],
                "execution_mode": db_task.execution_mode,
                "predefined_schema": [],
            },
            "schema_version": schema_record.version if schema_record else 1,
            "dynamic_schema": schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
            "raw_materials": [],
            "source_ids": [],
            "analysis_results": {},
            "critic_feedback": [],
            "suggested_schema_extensions": [],
            "task_events": [],
            "progress": db_task.progress or 40,
            "module_updates": [],
            "retry_counts": {},
        }

    try:
        async def publish_collector_progress(payload: dict[str, Any]):
            await publish_event(task_id, "collector_log", payload)

        state = await collector_node(state, on_progress=publish_collector_progress)
        materials = state.get("raw_materials") or []
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="COLLECTING", progress=60)
            task.raw_materials = materials
            await save_source_materials(session, task_id, materials)
            await session.commit()
        await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Data collection completed."})
        await publish_event(task_id, "progress_update", {"progress": 60, "stage": "COLLECTING"})
        await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60})
        await publish_event(task_id, "raw_materials_updated", {"data": materials, "source_stats": source_stats(materials)})

        state = await analyzer_node(state)
        analysis = state.get("analysis_results") or {}
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="ANALYZING", progress=90)
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
        await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": "Analysis completed."})
        await publish_event(task_id, "progress_update", {"progress": 90, "stage": "ANALYZING"})
        await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 90})
        await publish_event(task_id, "analysis_progress", {"module_id": "analysis", "data": analysis})

        state = await critic_node(state)
        state, calibration_outcome = await run_schema_calibration(task_id, state)
        if calibration_outcome == "waiting_for_user":
            return
        feedback = state.get("critic_feedback") or []
        async with async_session() as session:
            task = await update_task_state(session, task_id, state="COMPLETED", progress=100)
            task.critic_feedback = feedback
            task.final_report = (task.analysis_results or {}).get("report", {})
            task.completed_at = datetime.utcnow()
            await save_quality_feedback(session, task_id, feedback)
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
    if not suggestions:
        return state, "none"

    context = state.get("task_context") or {}
    execution_mode = context.get("execution_mode", "step_by_step")
    if execution_mode != "auto":
        async with async_session() as session:
            await update_task_state(session, task_id, state="NEEDS_INTERVENTION", progress=95)
            await session.commit()
        await publish_event(
            task_id,
            "schema_extension_request",
            {
                "suggested_schema_extensions": suggestions,
                "message": "Critic found possible missing dimensions. Confirm or reject before final report.",
            },
        )
        await publish_event(task_id, "task_state_changed", {"state": "NEEDS_INTERVENTION", "progress": 95})
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
