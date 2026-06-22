import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from agents.analyzer import swot_generator_node
from core.runtime import runner
from models_db import SourceMaterialRecord, TaskEventRecord, TaskRecord, TaskSnapshotRecord, async_session
from schemas import TaskCreateRequest, TaskCreateResponse
from services.pipeline import event_generator, make_initial_state, process_initial_pipeline, publish_event
from services.repositories import add_intervention, create_task_record, get_task, latest_schema, new_run_id, resolve_all_pending_feedback, save_schema, set_task_run, update_task_state
from services.serialization import serialize_task, serialize_source

router = APIRouter()


def _schema_field_names(schema: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    if not isinstance(schema, dict):
        return names
    for group_name, fields in schema.items():
        if not isinstance(fields, list):
            continue
        for index, field in enumerate(fields):
            if not isinstance(field, dict):
                continue
            field_id = field.get("id") or f"{group_name}.{field.get('name', index)}"
            names[str(field_id)] = str(field.get("name") or field_id)
    return names


async def _load_snapshot_materials(session, task_id: str, snap_data: dict, schema: dict | None) -> list[dict]:
    raw_materials = snap_data.get("raw_materials")
    if isinstance(raw_materials, list) and raw_materials:
        return raw_materials

    raw_ids = snap_data.get("raw_material_ids") or []
    material_ids = [str(item) for item in raw_ids if str(item).strip()]
    if not material_ids:
        return []

    result = await session.execute(
        select(SourceMaterialRecord).where(
            SourceMaterialRecord.task_id == task_id,
            SourceMaterialRecord.id.in_(material_ids),
        )
    )
    records_by_id = {record.id: record for record in result.scalars()}
    field_names = _schema_field_names(schema or {})
    materials: list[dict] = []
    for material_id in material_ids:
        record = records_by_id.get(material_id)
        if not record:
            continue
        item = serialize_source(record)
        item["schema_field_name"] = field_names.get(record.schema_field_id or "", record.schema_field_id)
        item["source_stage"] = record.source_stage
        item["skill"] = record.skill
        materials.append(item)
    return materials


@router.post("/api/v1/tasks", response_model=TaskCreateResponse)
async def create_task(req: TaskCreateRequest, background_tasks: BackgroundTasks):
    if not runner.has_capacity():
        raise HTTPException(status_code=409, detail="A pipeline is already running. Wait for it to complete or pause it first.")
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    run_id = new_run_id()

    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="A pipeline is already running. Wait for it to complete or pause it first.")

    try:
        async with async_session() as session:
            await create_task_record(
                session,
                task_id=task_id,
                task_name=req.task_name or f"{req.domain}_{datetime.now().strftime('%Y%m%d')}",
                domain=req.domain,
                main_product=req.main_product,
                competitors=req.competitors,
                execution_mode=req.execution_mode,
                analysis_goal=req.analysis_goal,
                task_intent={},
            )
            if req.predefined_schema:
                await save_schema(session, task_id, {"User Defined": req.predefined_schema}, created_by="user", status="draft")
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: process_initial_pipeline(task_id, run_id, make_initial_state(req, task_id, run_id), continue_after_schema=req.execution_mode == "auto")):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    asyncio.create_task(publish_event(task_id, "task_state_changed", {"state": "SCHEMA_GENERATING", "previous_state": "INITIALIZING", "progress": 10}, run_id=run_id))
    asyncio.create_task(publish_event(task_id, "progress_update", {"progress": 10, "stage": "SCHEMA_GENERATING"}, run_id=run_id))

    return {"task_id": task_id, "run_id": run_id, "state": "INITIALIZING", "stream_url": f"/api/v1/tasks/{task_id}/stream"}


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
                    "run_id": task.active_run_id,
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

    if runner.active_count() > 0:
        raise HTTPException(status_code=409, detail="Cannot restore snapshot while a backend task is running. Wait for it to complete or terminate it first.")

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
                analysis_goal=task.analysis_goal,
                task_intent=snap_data.get("task_intent", task.task_intent or {}),
            )
            await update_task_state(session, clone_id, state=snapshot.state, progress=snap_data.get("progress", 0))
            if snap_data.get("dynamic_schema"):
                await save_schema(session, clone_id, snap_data["dynamic_schema"], created_by="agent", status="active")
            await session.commit()
            return {"task_id": clone_id, "state": snapshot.state}

        # post_collection restore: go to COLLECTING, preserve materials, wait for user to click "继续分析"
        restored_schema_record = None
        restored_schema = snap_data.get("dynamic_schema") if isinstance(snap_data, dict) else None

        if checkpoint_id == "post_collection" or snapshot.state == "COLLECTING":
            task.state = "COLLECTING"
            task.progress = snap_data.get("progress", 60)
            task.competitors = snap_data.get("competitors", task.competitors or [])
            task.task_intent = snap_data.get("task_intent", task.task_intent or {})
            if isinstance(restored_schema, dict):
                restored_schema_record = await save_schema(session, task_id, restored_schema, created_by="snapshot", status="active")
            restored_materials = await _load_snapshot_materials(session, task_id, snap_data, restored_schema if isinstance(restored_schema, dict) else task.dynamic_schema or {})
            task.raw_materials = restored_materials or list(task.raw_materials or [])
            task.analysis_results = {}
            task.critic_feedback = []
            task.error = None
            task.final_report = {}
            task.completed_at = None
            task.active_run_id = None
            await resolve_all_pending_feedback(session, task_id)
            await add_intervention(session, task_id, "restore_snapshot", {"checkpoint_id": checkpoint_id, "type": "post_collection"})
            await session.commit()

        else:
            # restore mode: go back to SCHEMA_REVIEW, let user confirm schema before collector
            task.state = "SCHEMA_REVIEW"
            task.progress = snap_data.get("progress", 30)
            task.competitors = snap_data.get("competitors", task.competitors or [])
            task.task_intent = snap_data.get("task_intent", task.task_intent or {})
            if isinstance(restored_schema, dict):
                restored_schema_record = await save_schema(session, task_id, restored_schema, created_by="snapshot", status="active")
            task.raw_materials = snap_data.get("raw_materials", [])
            task.analysis_results = {}
            task.critic_feedback = []
            task.error = None
            task.final_report = {}
            task.completed_at = None
            task.active_run_id = None
            await resolve_all_pending_feedback(session, task_id)
            await add_intervention(session, task_id, "restore_snapshot", {"checkpoint_id": checkpoint_id})
            await session.commit()

    if checkpoint_id == "post_collection" or snapshot.state == "COLLECTING":
        restore_event = await publish_event(task_id, "snapshot_restored", {
            "task_id": task_id,
            "state": "COLLECTING",
            "progress": 60,
            "restored_from": checkpoint_id,
            "snapshot_type": "post_collection",
            "schema_version": restored_schema_record.version if restored_schema_record else None,
            "dynamic_schema": restored_schema if isinstance(restored_schema, dict) else {},
            "competitors": snap_data.get("competitors", []),
            "non_run_event": True,
        }, allow_inactive=True)
        cutoff_sequence = restore_event.get("sequence") if restore_event else None

        return {"task_id": task_id, "state": "COLLECTING", "restored": True, "event_cutoff_sequence": cutoff_sequence}

    restore_event = await publish_event(task_id, "snapshot_restored", {
        "task_id": task_id,
        "state": "SCHEMA_REVIEW",
        "progress": 30,
        "restored_from": checkpoint_id,
        "snapshot_type": "schema",
        "dynamic_schema": restored_schema if isinstance(restored_schema, dict) else {},
        "schema_version": restored_schema_record.version if restored_schema_record else None,
        "competitors": snap_data.get("competitors", []),
        "non_run_event": True,
    }, allow_inactive=True)
    cutoff_sequence = restore_event.get("sequence") if restore_event else None
    return {"task_id": task_id, "state": "SCHEMA_REVIEW", "restored": True, "event_cutoff_sequence": cutoff_sequence}


@router.post("/api/v1/tasks/{task_id}/generate-swot")
async def generate_swot(task_id: str):
    if runner.is_active(task_id):
        raise HTTPException(status_code=409, detail="Cannot generate SWOT while a pipeline is running for this task.")

    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state in ("COLLECTING", "ANALYZING", "CRITIQUING", "SCHEMA_GENERATING", "SCHEMA_CALIBRATING"):
            raise HTTPException(status_code=409, detail="Cannot generate SWOT while task is in a running state.")
        schema_record = await latest_schema(session, task_id)
        task_context = {
            "domain": db_task.domain or "",
            "competitors": db_task.competitors or [],
            "execution_mode": db_task.execution_mode or "",
            "analysis_goal": db_task.analysis_goal or "",
            "task_intent": db_task.task_intent or {},
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

    await publish_event(task_id, "analysis_progress", {"module_id": "swot", "data": {"swot": swot}, "non_run_event": True})
    return {"swot": swot}
