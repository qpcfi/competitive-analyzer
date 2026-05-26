import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from sqlalchemy import func, select

from agents.graph import workflow
from agents.analyzer import analyzer_node
from agents.collector import collector_node
from agents.critic import critic_node
from agents.orchestrator import orchestrator_node
from models_db import (
    LinkVerificationResultRecord,
    ReportExportRecord,
    SourceMaterialRecord,
    TaskEventRecord,
    TaskRecord,
    TaskSnapshotRecord,
    UserFeedbackRecord,
    UserNoteRecord,
    async_session,
    init_db,
)
from schemas import (
    FeedbackRequest,
    InterventionRequest,
    NoteRequest,
    SchemaUpdateRequest,
    SourceMaterialCreateRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    TrustUpdateRequest,
)
from services.events import event_broker
from services.repositories import (
    add_intervention,
    create_task_record,
    get_task,
    latest_schema,
    save_analysis_module,
    save_quality_feedback,
    save_schema,
    save_source_materials,
    update_task_state,
    new_id,
)

app = FastAPI(title="Competitive Analyzer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pool = None
checkpointer = None
app_auto = None
app_step = None


@app.on_event("startup")
async def on_startup():
    global pool, checkpointer, app_auto, app_step
    await init_db()

    pool = ConnectionPool(
        os.environ.get("CHECKPOINT_DATABASE_URL", "postgresql://postgres:123456@127.0.0.1:5432/competitive_analyzer"),
        max_size=20,
        kwargs={"autocommit": True},
    )

    checkpointer = PostgresSaver(pool)
    checkpointer.setup()

    app_auto = workflow.compile(checkpointer=checkpointer)
    app_step = workflow.compile(checkpointer=checkpointer, interrupt_before=["collector", "analyzer", "critic"])


@app.on_event("shutdown")
async def on_shutdown():
    if pool:
        pool.close()


async def publish_event(task_id: str, event_type: str, data: dict[str, Any]):
    return await event_broker.publish(task_id, event_type, data)


async def event_generator(task_id: str, since: int = 0):
    async for message in event_broker.stream(task_id, since=since):
        yield message


def count_schema_stats(schema: dict[str, Any]) -> dict[str, int]:
    fields = [field for group in schema.values() if isinstance(group, list) for field in group if isinstance(field, dict)]
    return {
        "total_fields": len(fields),
        "user_defined": len([field for field in fields if field.get("origin") == "user"]),
        "agent_supplement": len([field for field in fields if field.get("origin") != "user"]),
    }


def source_stats(materials: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "accepted": len([item for item in materials if item.get("validation_status") == "accepted"]),
        "degraded": len([item for item in materials if item.get("validation_status") == "degraded"]),
        "failed": len([item for item in materials if item.get("access_status") == "failed"]),
        "blocked": len([item for item in materials if item.get("access_status") == "blocked"]),
    }


async def process_graph_events(task_id: str, graph, initial_state, config):
    if graph is None:
        await publish_event(task_id, "task_failed", {"state": "ERROR", "message": "Workflow is not initialized", "recoverable": True})
        return

    try:
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, state in event.items():
                if node_name == "orchestrator":
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
                        {"dynamic_schema": schema_json, "schema_version": schema_version, "stats": count_schema_stats(schema_json)},
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
                    await publish_event(task_id, "token_update", {"total_used": 8500, "budget": 50000, "estimated_remaining": 41500})

                elif node_name == "critic":
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
            "task_events": [],
            "progress": db_task.progress or 40,
            "module_updates": [],
            "retry_counts": {},
        }

    try:
        state = await collector_node(state)
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
        "task_events": [],
        "progress": 0,
        "module_updates": [],
        "retry_counts": {},
    }


@app.post("/api/v1/tasks", response_model=TaskCreateResponse)
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
    background_tasks.add_task(publish_event, task_id, "task_state_changed", {"state": "SCHEMA_GENERATING", "previous_state": "INITIALIZING", "progress": 10})
    background_tasks.add_task(publish_event, task_id, "progress_update", {"progress": 10, "stage": "SCHEMA_GENERATING"})
    background_tasks.add_task(publish_event, task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Starting schema generation"})
    if req.execution_mode == "step_by_step":
        background_tasks.add_task(regenerate_schema, task_id)
    else:
        background_tasks.add_task(process_graph_events, task_id, app_auto, make_initial_state(req, task_id), config)

    return {"task_id": task_id, "state": "INITIALIZING", "stream_url": f"/api/v1/tasks/{task_id}/stream"}


@app.get("/api/v1/tasks/{task_id}/stream")
async def stream_task(task_id: str, since: int = Query(0, ge=0)):
    return StreamingResponse(event_generator(task_id, since=since), media_type="text/event-stream")


@app.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        return serialize_task(db_task)


def serialize_task(db_task: TaskRecord) -> dict[str, Any]:
    return {
        "task_id": db_task.id,
        "task_name": db_task.task_name,
        "domain": db_task.domain,
        "competitors": db_task.competitors or [],
        "execution_mode": db_task.execution_mode,
        "state": db_task.state,
        "progress": db_task.progress or 0,
        "dynamic_schema": db_task.dynamic_schema or {},
        "raw_materials": db_task.raw_materials or [],
        "analysis_results": db_task.analysis_results or {},
        "critic_feedback": db_task.critic_feedback or [],
        "updated_at": db_task.updated_at.isoformat() if db_task.updated_at else None,
    }


def serialize_source(source: SourceMaterialRecord) -> dict[str, Any]:
    return {
        "id": source.id,
        "competitor": source.competitor,
        "source_url": source.source_url,
        "source_type": source.source_type,
        "quote_text": source.quote_text,
        "extracted_value": source.extracted_value,
        "fetch_timestamp": source.fetch_timestamp.isoformat() if source.fetch_timestamp else None,
        "agent_node": source.agent_node,
        "access_status": source.access_status,
        "validation_status": source.validation_status,
        "trust_status": source.trust_status,
        "retry_count": source.retry_count,
        "degraded_reason": source.degraded_reason,
        "pii_redacted": source.pii_redacted,
        "is_noise": source.is_noise,
        "metadata": {},
    }


@app.get("/api/v1/tasks")
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


@app.get("/api/v1/tasks/{task_id}/events")
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


@app.get("/api/v1/tasks/{task_id}/snapshots")
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


@app.post("/api/v1/tasks/{task_id}/restore_snapshot")
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


@app.get("/api/v1/tasks/{task_id}/source-materials")
async def list_source_materials(task_id: str):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(select(SourceMaterialRecord).where(SourceMaterialRecord.task_id == task_id))
        items = [serialize_source(source) for source in result.scalars()]
    return {"items": items}


@app.get("/api/v1/tasks/{task_id}/source-materials/{source_id}")
async def get_source_material(task_id: str, source_id: str):
    async with async_session() as session:
        source = await session.get(SourceMaterialRecord, source_id)
        if not source or source.task_id != task_id:
            raise HTTPException(status_code=404, detail="Source material not found")
        return serialize_source(source)


@app.post("/api/v1/tasks/{task_id}/source-materials")
async def add_source_material(task_id: str, req: SourceMaterialCreateRequest):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        record = SourceMaterialRecord(
            id=new_id("src"),
            task_id=task_id,
            competitor=req.competitor or "",
            source_url=req.source_url,
            source_type="user_added",
            quote_text=req.reason or "",
            access_status="queued",
            validation_status="pending",
            trust_status="third_party",
        )
        session.add(record)
        await add_intervention(session, task_id, "source_add", {"source_id": record.id, "source_url": req.source_url})
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "source_add", "message": f"Queued source {req.source_url}"})
    return {"status": "queued", "source_id": record.id}


@app.post("/api/v1/tasks/{task_id}/source-materials/{source_id}/refetch")
async def refetch_source_material(task_id: str, source_id: str):
    async with async_session() as session:
        source = await session.get(SourceMaterialRecord, source_id)
        if not source or source.task_id != task_id:
            raise HTTPException(status_code=404, detail="Source material not found")
        source.access_status = "queued"
        source.retry_count = (source.retry_count or 0) + 1
        await add_intervention(session, task_id, "source_refetch", {"source_id": source_id})
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "source_refetch", "message": f"Queued refetch for {source_id}"})
    return {"status": "refetching", "source_id": source_id}


@app.post("/api/v1/tasks/{task_id}/source-materials/{source_id}/trust")
async def update_source_trust(task_id: str, source_id: str, req: TrustUpdateRequest):
    async with async_session() as session:
        source = await session.get(SourceMaterialRecord, source_id)
        if not source or source.task_id != task_id:
            raise HTTPException(status_code=404, detail="Source material not found")
        source.trust_status = req.trust_status
        await add_intervention(session, task_id, "source_trust_update", {"source_id": source_id, "trust_status": req.trust_status, "reason": req.reason})
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "source_trust_update", "message": f"Updated trust for {source_id}"})
    return {"status": "updated", "source_id": source_id, "trust_status": req.trust_status}


@app.post("/api/v1/tasks/{task_id}/interventions")
async def apply_intervention(task_id: str, req: InterventionRequest):
    affected = 0
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        for source_id in req.remove_source_ids:
            source = await session.get(SourceMaterialRecord, source_id)
            if source and source.task_id == task_id:
                source.is_noise = True
                affected += 1
        for source_id in req.restore_noise_ids:
            source = await session.get(SourceMaterialRecord, source_id)
            if source and source.task_id == task_id:
                source.is_noise = False
                affected += 1
        for url in req.add_urls:
            session.add(
                SourceMaterialRecord(
                    id=new_id("src"),
                    task_id=task_id,
                    competitor="",
                    source_url=url,
                    source_type="user_added",
                    access_status="queued",
                    validation_status="pending",
                    trust_status="third_party",
                )
            )
            affected += 1
        await add_intervention(session, task_id, "source_intervention", req.model_dump())
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "intervention", "message": f"Applied source intervention to {affected} sources"})
    return {"status": "applied", "affected_sources": affected}


@app.get("/api/v1/tasks/{task_id}/schema/advice")
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


@app.post("/api/v1/tasks/{task_id}/feedback")
async def record_feedback(task_id: str, req: FeedbackRequest):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(UserFeedbackRecord(id=new_id("feedback"), task_id=task_id, **req.model_dump()))
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "feedback", "message": f"Recorded {req.feedback} feedback"})
    return {"status": "recorded"}


@app.post("/api/v1/tasks/{task_id}/notes")
async def save_note(task_id: str, req: NoteRequest):
    note_id = new_id("note")
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(UserNoteRecord(id=note_id, task_id=task_id, **req.model_dump()))
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "note", "message": "Saved user note"})
    return {"status": "saved", "note_id": note_id}


@app.get("/api/v1/tasks/{task_id}/report")
async def get_report(task_id: str):
    async with async_session() as session:
        task = await get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        report = task.final_report or (task.analysis_results or {}).get("report") or {
            "summary": "",
            "findings": [],
            "recommendations": [],
            "source_appendix": task.raw_materials or [],
        }
    return {"task_id": task_id, "report": report}


@app.get("/api/v1/tasks/{task_id}/export")
async def export_report(task_id: str, format: str = Query("json", pattern="^(pdf|markdown|json)$")):
    report_response = await get_report(task_id)
    report = report_response["report"]
    async with async_session() as session:
        session.add(ReportExportRecord(id=new_id("export"), task_id=task_id, format=format, status="completed"))
        await session.commit()
    if format == "json":
        return JSONResponse(report)
    if format == "markdown":
        body = f"# Competitive Analysis Report\n\n{report.get('summary', '')}\n"
        for item in report.get("recommendations", []):
            body += f"\n- {item}"
        return PlainTextResponse(body, media_type="text/markdown")
    body = f"PDF-ready report for {task_id}\n\n{report.get('summary', '')}"
    return PlainTextResponse(body, media_type="application/pdf")


@app.post("/api/v1/tasks/{task_id}/share")
async def share_report(task_id: str):
    token = new_id("report")
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(ReportExportRecord(id=new_id("export"), task_id=task_id, format="share", status="completed", share_token=token))
        await session.commit()
    return {"share_url": f"http://localhost:3000/share/{token}", "expires_at": None}


@app.post("/api/v1/tasks/{task_id}/verify_links")
async def verify_links(task_id: str):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(select(SourceMaterialRecord).where(SourceMaterialRecord.task_id == task_id))
        sources = list(result.scalars())
        checks = []
        for source in sources:
            reachable = bool(source.source_url) and source.access_status not in {"blocked", "failed"}
            record = LinkVerificationResultRecord(
                id=new_id("link"),
                task_id=task_id,
                source_material_id=source.id,
                source_url=source.source_url or "",
                reachable=reachable,
            )
            session.add(record)
            checks.append({"source_id": source.id, "source_url": source.source_url, "reachable": reachable})
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "verify_links", "message": f"Checked {len(checks)} source links"})
    return {"status": "checked", "results": checks}


@app.put("/api/v1/tasks/{task_id}/schema")
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

    if app_step is not None:
        config = {"configurable": {"thread_id": task_id}}
        try:
            app_step.update_state(config, {"dynamic_schema": req.dynamic_schema, "schema_version": record.version})
        except Exception:
            pass
    await publish_event(task_id, "schema_ready", {"dynamic_schema": req.dynamic_schema, "schema_version": record.version, "stats": count_schema_stats(req.dynamic_schema)})
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "info", "message": "Schema draft saved."})
    return {"status": "updated", "schema_version": record.version, "state": "SCHEMA_REVIEW"}


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
            "task_events": [],
            "progress": 10,
            "module_updates": [],
            "retry_counts": {},
        }
    updated_state = await orchestrator_node(state)
    schema_json = updated_state.get("dynamic_schema") or {}
    async with async_session() as session:
        record = await save_schema(session, task_id, schema_json, created_by="agent", status="active")
        await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=30)
        await session.commit()
    await publish_event(task_id, "schema_ready", {"dynamic_schema": schema_json, "schema_version": record.version, "stats": count_schema_stats(schema_json)})
    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW", "progress": 30})


@app.post("/api/v1/tasks/{task_id}/reject_schema")
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
    background_tasks.add_task(regenerate_schema, task_id)
    return {"status": "regenerating", "state": "SCHEMA_GENERATING"}


@app.post("/api/v1/tasks/{task_id}/resume")
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
    background_tasks.add_task(process_agent_pipeline, task_id)
    return {"status": "resumed", "state": "COLLECTING"}


@app.post("/api/v1/tasks/{task_id}/pause")
async def pause_task(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        await add_intervention(session, task_id, "pause", {"previous_state": db_task.state})
        await update_task_state(session, task_id, state="PAUSED")
        await session.commit()
    await publish_event(task_id, "task_state_changed", {"state": "PAUSED"})
    return {"status": "paused", "state": "PAUSED"}


@app.post("/api/v1/tasks/{task_id}/force_next")
async def force_next(task_id: str, req: Request):
    body = await req.json()
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        next_state_by_current = {
            "SCHEMA_REVIEW": "COLLECTING",
            "PAUSED": "COLLECTING",
            "NEEDS_INTERVENTION": "ANALYZING",
            "COLLECTING": "ANALYZING",
            "ANALYZING": "COMPLETED",
        }
        next_state = next_state_by_current.get(db_task.state)
        if not next_state:
            raise HTTPException(status_code=409, detail=f"Cannot force next from {db_task.state}")
        await add_intervention(session, task_id, "force_next", {"reason": body.get("reason", "User accepted current state"), "from": db_task.state, "to": next_state})
        await update_task_state(session, task_id, state=next_state)
        await session.commit()
    await publish_event(task_id, "task_state_changed", {"state": next_state})
    return {"status": "advanced", "state": next_state}


@app.post("/api/v1/tasks/{task_id}/partial_rerun")
async def partial_rerun(task_id: str, req: Request):
    body = await req.json()
    config = {"configurable": {"thread_id": task_id}}
    if app_step is not None:
        try:
            app_step.update_state(config, {"critic_feedback": [body.get("new_instruction", "Rerun analysis")]})
        except Exception:
            pass
    module_id = body.get("target_module", "analysis")
    new_content = {"instruction": body.get("new_instruction", ""), "status": "rerun_requested"}
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        record = await save_analysis_module(
            session,
            task_id,
            module_id=module_id,
            module_type=module_id.split(".")[0],
            content=new_content,
            evidence_refs=[],
            quality_status="pending",
        )
        await add_intervention(session, task_id, "partial_rerun", body)
        await update_task_state(session, task_id, state="ANALYZING")
        await session.commit()
    await publish_event(task_id, "module_updated", {"module_id": module_id, "new_content": new_content, "version": record.version, "updated_at": datetime.utcnow().isoformat()})
    return {"status": "rerunning", "module_id": module_id, "state": "ANALYZING"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
