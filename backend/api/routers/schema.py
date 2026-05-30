import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core import runtime
from models_db import async_session
from schemas import SchemaUpdateRequest
from services.pipeline import process_agent_pipeline, publish_event, regenerate_schema
from services.repositories import add_intervention, get_task, latest_schema, save_schema, update_task_state
from services.stats import count_schema_stats

router = APIRouter()


@router.get("/api/v1/tasks/{task_id}/schema/advice")
async def schema_advice(task_id: str, field_id: str):
    async with async_session() as session:
        schema_record = await latest_schema(session, task_id)
        if not schema_record:
            raise HTTPException(status_code=404, detail="Schema not found")
        field = next((item for item in schema_record.field_index or [] if item.get("id") == field_id), None)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    name = field.get("name", field_id)
    return {
        "field_id": field_id,
        "reason": f"{name} helps compare competitors on a user-visible dimension.",
        "recommended_queries": [f"<competitor> {name}", f"<competitor> {name} official"],
        "source_types": [field.get("source", "public_web"), "official"],
        "examples": [name],
    }


@router.put("/api/v1/tasks/{task_id}/schema")
async def update_schema(task_id: str, req: SchemaUpdateRequest):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in {"SCHEMA_REVIEW", "SCHEMA_GENERATING", "INITIALIZING", "PAUSED"}:
            raise HTTPException(status_code=409, detail=f"Cannot edit schema while task is {db_task.state}")
        record = await save_schema(session, task_id, req.dynamic_schema, created_by="user", status="draft")
        await add_intervention(session, task_id, "schema_update", {"schema_version": record.version})
        await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=max(db_task.progress or 0, 30))
        await session.commit()

    if runtime.app_step is not None:
        config = {"configurable": {"thread_id": task_id}}
        try:
            runtime.app_step.update_state(config, {"dynamic_schema": req.dynamic_schema, "schema_version": record.version})
        except Exception:
            pass
    await publish_event(
        task_id, 
        "schema_ready", 
        {
            "dynamic_schema": req.dynamic_schema, 
            "schema_version": record.version, 
            "competitors": db_task.competitors or [],
            "stats": count_schema_stats(req.dynamic_schema)
        }
    )
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "info", "message": "Schema draft saved."})
    return {"status": "updated", "schema_version": record.version, "state": "SCHEMA_REVIEW"}


@router.post("/api/v1/tasks/{task_id}/reject_schema")
async def reject_schema(task_id: str, background_tasks: BackgroundTasks):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in {"SCHEMA_REVIEW", "SCHEMA_GENERATING", "INITIALIZING"}:
            raise HTTPException(status_code=409, detail=f"Cannot reject schema while task is {db_task.state}")
        await add_intervention(session, task_id, "schema_reject", {"previous_state": db_task.state})
        await update_task_state(session, task_id, state="SCHEMA_GENERATING", progress=10)
        await session.commit()

    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_GENERATING", "progress": 10})
    await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Regenerating schema after user rejection"})
    asyncio.create_task(regenerate_schema(task_id))
    return {"status": "regenerating", "state": "SCHEMA_GENERATING"}


@router.post("/api/v1/tasks/{task_id}/resume")
async def resume_task(task_id: str, background_tasks: BackgroundTasks):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in {"SCHEMA_REVIEW", "PAUSED"}:
            raise HTTPException(status_code=409, detail=f"Cannot resume task while task is {db_task.state}")
        schema_record = await latest_schema(session, task_id)
        await add_intervention(session, task_id, "schema_confirm", {"schema_version": schema_record.version if schema_record else None})
        await update_task_state(session, task_id, state="COLLECTING", progress=40)
        await session.commit()

    await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "previous_state": "SCHEMA_REVIEW", "progress": 40})
    await publish_event(task_id, "progress_update", {"progress": 40, "stage": "COLLECTING"})
    asyncio.create_task(process_agent_pipeline(task_id))
    return {"status": "resumed", "state": "COLLECTING"}
