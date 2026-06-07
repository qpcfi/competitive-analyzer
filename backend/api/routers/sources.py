from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from core.runtime import runner
from models_db import SourceMaterialRecord, async_session
from schemas import InterventionRequest, SourceMaterialCreateRequest, TrustUpdateRequest
from services.pipeline import publish_event
from services.repositories import add_intervention, get_task, new_id
from services.serialization import serialize_source

router = APIRouter()


@router.get("/api/v1/tasks/{task_id}/source-materials")
async def list_source_materials(task_id: str):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        result = await session.execute(select(SourceMaterialRecord).where(SourceMaterialRecord.task_id == task_id))
        items = [serialize_source(source) for source in result.scalars()]
    return {"items": items}


@router.get("/api/v1/tasks/{task_id}/source-materials/{source_id}")
async def get_source_material(task_id: str, source_id: str):
    async with async_session() as session:
        source = await session.get(SourceMaterialRecord, source_id)
        if not source or source.task_id != task_id:
            raise HTTPException(status_code=404, detail="Source material not found")
        return serialize_source(source)


@router.post("/api/v1/tasks/{task_id}/source-materials")
async def add_source_material(task_id: str, req: SourceMaterialCreateRequest):
    if runner.is_running(task_id):
        raise HTTPException(status_code=409, detail="Cannot add source material while pipeline is running")
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


@router.post("/api/v1/tasks/{task_id}/source-materials/{source_id}/refetch")
async def refetch_source_material(task_id: str, source_id: str):
    if runner.is_running(task_id):
        raise HTTPException(status_code=409, detail="Cannot refetch while pipeline is running")
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


@router.post("/api/v1/tasks/{task_id}/source-materials/{source_id}/trust")
async def update_source_trust(task_id: str, source_id: str, req: TrustUpdateRequest):
    if runner.is_running(task_id):
        raise HTTPException(status_code=409, detail="Cannot update trust while pipeline is running")
    async with async_session() as session:
        source = await session.get(SourceMaterialRecord, source_id)
        if not source or source.task_id != task_id:
            raise HTTPException(status_code=404, detail="Source material not found")
        source.trust_status = req.trust_status
        await add_intervention(session, task_id, "source_trust_update", {"source_id": source_id, "trust_status": req.trust_status, "reason": req.reason})
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "source_trust_update", "message": f"Updated trust for {source_id}"})
    return {"status": "updated", "source_id": source_id, "trust_status": req.trust_status}


@router.post("/api/v1/tasks/{task_id}/interventions")
async def apply_intervention(task_id: str, req: InterventionRequest):
    if runner.is_running(task_id):
        raise HTTPException(status_code=409, detail="Cannot apply intervention while pipeline is running")
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
