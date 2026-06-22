import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core import runtime
from core.runtime import runner
from models_db import SourceMaterialRecord, async_session
from schemas import SchemaUpdateRequest
from services.pipeline import process_agent_pipeline, publish_event, regenerate_schema
from services.repositories import add_intervention, get_task, latest_schema, new_run_id, save_schema, set_task_run, update_task_state
from services.state_machine import can_transition
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
    source = field.get("source") or "public_web"
    reason = (
        field.get("reason")
        or field.get("description")
        or f"{name} 是用于横向比较竞品的关键维度，可帮助判断不同竞品在该能力或业务特征上的差异。"
    )
    source_types = list(dict.fromkeys([source, "official" if source != "official" else "public_web"]))
    return {
        "field_id": field_id,
        "reason": reason,
        "recommended_queries": [
            f"<competitor> {name}",
            f"<competitor> {name} 官方",
            f"<competitor> {name} 公开资料",
        ],
        "source_types": source_types,
        "examples": [name],
    }


@router.put("/api/v1/tasks/{task_id}/schema")
async def update_schema(task_id: str, req: SchemaUpdateRequest):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in ("SCHEMA_REVIEW", "PAUSED"):
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
    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                raise HTTPException(status_code=404, detail="Task not found")
            if not can_transition(db_task.state, "SCHEMA_GENERATING"):
                raise HTTPException(status_code=409, detail=f"Cannot reject schema while task is {db_task.state}")
            await add_intervention(session, task_id, "schema_reject", {"previous_state": db_task.state})
            await update_task_state(session, task_id, state="SCHEMA_GENERATING", progress=10)
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: regenerate_schema(task_id, run_id)):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_GENERATING", "progress": 10}, run_id=run_id)
    await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Regenerating schema after user rejection"}, run_id=run_id)
    return {"status": "regenerating", "state": "SCHEMA_GENERATING", "run_id": run_id}


@router.post("/api/v1/tasks/{task_id}/resume")
async def resume_task(task_id: str, background_tasks: BackgroundTasks):
    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                raise HTTPException(status_code=404, detail="Task not found")
            if not can_transition(db_task.state, "COLLECTING"):
                raise HTTPException(status_code=409, detail=f"Cannot resume task while task is {db_task.state}")
            # 清除上次采集的旧数据，重新开始
            db_task.raw_materials = []
            db_task.analysis_results = {}
            db_task.critic_feedback = []
            db_task.error = None
            await session.execute(
                SourceMaterialRecord.__table__.delete().where(SourceMaterialRecord.task_id == task_id)
            )
            schema_record = await latest_schema(session, task_id)
            await add_intervention(session, task_id, "schema_confirm", {"schema_version": schema_record.version if schema_record else None})
            await update_task_state(session, task_id, state="COLLECTING", progress=40)
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: process_agent_pipeline(task_id, run_id)):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "previous_state": "SCHEMA_REVIEW", "progress": 40}, run_id=run_id)
    await publish_event(task_id, "progress_update", {"progress": 40, "stage": "COLLECTING"}, run_id=run_id)
    return {"status": "resumed", "state": "COLLECTING", "run_id": run_id}
