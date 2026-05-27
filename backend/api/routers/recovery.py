from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from core import runtime
from models_db import async_session
from services.pipeline import publish_event
from services.repositories import add_intervention, get_task, save_analysis_module, update_task_state

router = APIRouter()


@router.post("/api/v1/tasks/{task_id}/pause")
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


@router.post("/api/v1/tasks/{task_id}/force_next")
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


@router.post("/api/v1/tasks/{task_id}/partial_rerun")
async def partial_rerun(task_id: str, req: Request):
    body = await req.json()
    config = {"configurable": {"thread_id": task_id}}
    if runtime.app_step is not None:
        try:
            runtime.app_step.update_state(config, {"critic_feedback": [body.get("new_instruction", "Rerun analysis")]})
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
