import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from agents.analyzer import swot_generator_node
from core.runtime import runner
from models_db import TaskEventRecord, TaskRecord, TaskSnapshotRecord, async_session
from schemas import TaskCreateRequest, TaskCreateResponse
from services.pipeline import event_generator, make_initial_state, process_initial_pipeline, publish_event
from services.repositories import add_intervention, create_task_record, get_task, latest_schema, save_schema, update_task_state
from services.serialization import serialize_task

router = APIRouter()


@router.post("/api/v1/tasks", response_model=TaskCreateResponse)
async def create_task(req: TaskCreateRequest, background_tasks: BackgroundTasks):
    if runner.is_any_running():
        raise HTTPException(status_code=409, detail="A pipeline is already running. Wait for it to complete or pause it first.")
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        await create_task_record(
            session,
            task_id=task_id,
            task_name=req.task_name or f"{req.domain}_{datetime.now().strftime('%Y%m%d')}",
            domain=req.domain,
            main_product=req.main_product,
            competitors=req.competitors,
            execution_mode=req.execution_mode,
        )
        if req.predefined_schema:
            await save_schema(session, task_id, {"User Defined": req.predefined_schema}, created_by="user", status="draft")
        await session.commit()

    asyncio.create_task(publish_event(task_id, "task_state_changed", {"state": "SCHEMA_GENERATING", "previous_state": "INITIALIZING", "progress": 10}))
    asyncio.create_task(publish_event(task_id, "progress_update", {"progress": 10, "stage": "SCHEMA_GENERATING"}))
    runner.start(task_id, lambda: process_initial_pipeline(task_id, make_initial_state(req, task_id), continue_after_schema=req.execution_mode == "auto"))

    return {"task_id": task_id, "state": "INITIALIZING", "stream_url": f"/api/v1/tasks/{task_id}/stream"}


@router.get("/api/v1/tasks")
async def list_tasks(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), state: str | None = None, q: str | None = None):
    async with async_session() as session:
        stmt = select(TaskRecord)
        count_stmt = select(func.count()).select_from(TaskRecord)
        if state:
            stmt = stmt.where(TaskRecord.state == state)
            count_stmt = count_stmt.where(TaskRecord.state == state)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(TaskRecord.task_name.ilike(pattern))
            count_stmt = count_stmt.where(TaskRecord.task_name.ilike(pattern))
        total = int((await session.execute(count_stmt)).scalar_one() or 0)
        result = await session.execute(stmt.order_by(TaskRecord.updated_at.desc()).offset((page - 1) * limit).limit(limit))
        tasks = list(result.scalars())
        items = []
        for task in tasks:
            snapshot_count = int(
                (
                    await session.execute(
                        select(func.count()).select_from(TaskSnapshotRecord).where(TaskSnapshotRecord.task_id == task.id)
                    )
                ).scalar_one()
                or 0
            )
            items.append(
                {
                    "task_id": task.id,
                    "task_name": task.task_name,
                    "domain": task.domain,
                    "main_product": task.main_product,
                    "state": task.state,
                    "progress": task.progress or 0,
                    "snapshot_count": snapshot_count,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                }
            )
    return {"items": items, "page": page, "limit": limit, "total": total}


@router.get("/api/v1/tasks/{task_id}/stream")
async def stream_task(task_id: str, since: int = Query(0, ge=0)):
    return StreamingResponse(event_generator(task_id, since=since), media_type="text/event-stream")


@router.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        return serialize_task(db_task)


@router.get("/api/v1/tasks/{task_id}/events")
async def list_task_events(task_id: str, since: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(
            select(TaskEventRecord)
            .where(TaskEventRecord.task_id == task_id, TaskEventRecord.sequence > since)
            .order_by(TaskEventRecord.sequence)
            .limit(limit)
        )
        events = [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload or {},
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in result.scalars()
        ]
    return {"task_id": task_id, "events": events}


@router.get("/api/v1/tasks/{task_id}/snapshots")
async def list_snapshots(task_id: str):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(
            select(TaskSnapshotRecord).where(TaskSnapshotRecord.task_id == task_id).order_by(TaskSnapshotRecord.created_at.desc())
        )
        snapshots = [
            {
                "checkpoint_id": item.checkpoint_id,
                "state": item.state,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "summary": item.summary,
            }
            for item in result.scalars()
        ]
    return {"task_id": task_id, "snapshots": snapshots}


@router.post("/api/v1/tasks/{task_id}/restore_snapshot")
async def restore_snapshot(task_id: str, req: Request):
    body = await req.json()
    checkpoint_id = body.get("checkpoint_id")

    if runner.is_running(task_id):
        raise HTTPException(status_code=409, detail="Cannot restore snapshot while a pipeline is running. Pause the task first.")

    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(
            select(TaskSnapshotRecord).where(TaskSnapshotRecord.task_id == task_id, TaskSnapshotRecord.checkpoint_id == checkpoint_id)
        )
        snapshot = result.scalar_one_or_none()
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        snap_data = snapshot.snapshot_data or {}
        mode = body.get("mode")

        if mode == "clone":
            clone_id = f"task_{uuid.uuid4().hex[:8]}"
            await create_task_record(
                session,
                task_id=clone_id,
                task_name=f"{task.task_name} copy",
                domain=task.domain,
                main_product=task.main_product,
                competitors=snap_data.get("competitors", task.competitors or []),
                execution_mode=task.execution_mode,
            )
            await update_task_state(session, clone_id, state=snapshot.state, progress=snap_data.get("progress", 0))
            if snap_data.get("dynamic_schema"):
                await save_schema(session, clone_id, snap_data["dynamic_schema"], created_by="agent", status="active")
            await session.commit()
            return {"task_id": clone_id, "state": snapshot.state}

        # restore mode: go back to SCHEMA_REVIEW, let user confirm schema before collector
        task.state = "SCHEMA_REVIEW"
        task.progress = snap_data.get("progress", 30)
        task.competitors = snap_data.get("competitors", task.competitors or [])
        if "dynamic_schema" in snap_data:
            task.dynamic_schema = snap_data["dynamic_schema"]
        task.raw_materials = snap_data.get("raw_materials", [])
        task.analysis_results = {}
        task.critic_feedback = []
        task.error = None
        task.final_report = {}
        task.completed_at = None
        await add_intervention(session, task_id, "restore_snapshot", {"checkpoint_id": checkpoint_id})
        await session.commit()

    restored_schema = snap_data.get("dynamic_schema", {})
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "restore", "message": f"Restored from snapshot {checkpoint_id}, awaiting schema review."})
    await publish_event(task_id, "progress_update", {"progress": 30, "stage": "SCHEMA_REVIEW"})
    await publish_event(task_id, "schema_ready", {
        "dynamic_schema": restored_schema,
        "competitors": snap_data.get("competitors", []),
        "stats": {"restored": True, "checkpoint_id": checkpoint_id},
    })
    await publish_event(task_id, "task_state_changed", {
        "state": "SCHEMA_REVIEW", "progress": 30, "restored_from": checkpoint_id,
    })
    return {"task_id": task_id, "state": "SCHEMA_REVIEW", "restored": True}


@router.post("/api/v1/tasks/{task_id}/generate-swot")
async def generate_swot(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        schema_record = await latest_schema(session, task_id)
        task_context = {
            "domain": db_task.domain or "",
            "competitors": db_task.competitors or [],
            "execution_mode": db_task.execution_mode or "",
            "analysis_goal": db_task.analysis_goal or "",
        }
        state = {
            "task_id": task_id,
            "task_context": task_context,
            "dynamic_schema": schema_record.schema_json if schema_record else (db_task.dynamic_schema or {}),
            "raw_materials": db_task.raw_materials or [],
            "analysis_results": dict(db_task.analysis_results or {}),
            "critic_feedback": list(db_task.critic_feedback or []),
            "suggested_schema_extensions": [],
            "task_events": [],
            "progress": 90,
            "module_updates": [],
            "retry_counts": {},
        }

    state = await swot_generator_node(state)
    swot = (state.get("analysis_results") or {}).get("swot") or {}

    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if db_task:
            results = dict(db_task.analysis_results or {})
            results["swot"] = swot
            db_task.analysis_results = results
            await session.commit()

    await publish_event(task_id, "analysis_progress", {"module_id": "swot", "data": {"swot": swot}})
    return {"swot": swot}
