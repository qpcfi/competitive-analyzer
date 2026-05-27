import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from core import runtime
from models_db import TaskEventRecord, TaskRecord, TaskSnapshotRecord, async_session
from schemas import TaskCreateRequest, TaskCreateResponse
from services.pipeline import event_generator, make_initial_state, process_graph_events, publish_event, regenerate_schema
from services.repositories import add_intervention, create_task_record, get_task, save_schema, update_task_state
from services.serialization import serialize_task

router = APIRouter()


@router.post("/api/v1/tasks", response_model=TaskCreateResponse)
async def create_task(req: TaskCreateRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        await create_task_record(
            session,
            task_id=task_id,
            task_name=req.task_name or f"{req.domain}_{datetime.now().strftime('%Y%m%d')}",
            domain=req.domain,
            competitors=req.competitors,
            execution_mode=req.execution_mode,
        )
        if req.predefined_schema:
            await save_schema(session, task_id, {"User Defined": req.predefined_schema}, created_by="user", status="draft")
        await session.commit()

    config = {"configurable": {"thread_id": task_id}}
    asyncio.create_task(publish_event(task_id, "task_state_changed", {"state": "SCHEMA_GENERATING", "previous_state": "INITIALIZING", "progress": 10}))
    asyncio.create_task(publish_event(task_id, "progress_update", {"progress": 10, "stage": "SCHEMA_GENERATING"}))
    asyncio.create_task(publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Starting schema generation"}))
    if req.execution_mode == "step_by_step":
        asyncio.create_task(regenerate_schema(task_id))
    else:
        asyncio.create_task(process_graph_events(task_id, runtime.app_auto, make_initial_state(req, task_id), config))

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
        if body.get("mode") == "clone":
            clone_id = f"task_{uuid.uuid4().hex[:8]}"
            await create_task_record(
                session,
                task_id=clone_id,
                task_name=f"{task.task_name} copy",
                domain=task.domain,
                competitors=task.competitors or [],
                execution_mode=task.execution_mode,
            )
            await update_task_state(session, clone_id, state=snapshot.state, progress=task.progress or 0)
            await session.commit()
            return {"task_id": clone_id, "state": snapshot.state}
        task.state = snapshot.state
        task.dynamic_schema = (snapshot.snapshot_data or {}).get("dynamic_schema", task.dynamic_schema)
        task.raw_materials = (snapshot.snapshot_data or {}).get("raw_materials", task.raw_materials)
        task.analysis_results = (snapshot.snapshot_data or {}).get("analysis_results", task.analysis_results)
        await add_intervention(session, task_id, "restore_snapshot", {"checkpoint_id": checkpoint_id})
        await session.commit()
    await publish_event(task_id, "task_state_changed", {"state": snapshot.state})
    return {"task_id": task_id, "state": snapshot.state}
