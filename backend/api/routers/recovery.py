from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from core import runtime
from core.runtime import runner
from models_db import async_session
from services.pipeline import (
    process_agent_pipeline,
    publish_event,
    calibration_confirm,
    calibration_reject,
)
from services.repositories import add_intervention, get_task, save_analysis_module, update_task_state
from services.state_machine import can_transition

router = APIRouter()


@router.post("/api/v1/tasks/{task_id}/pause")
async def pause_task(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if not can_transition(db_task.state, "PAUSED"):
            raise HTTPException(status_code=409, detail=f"Cannot pause task while it is {db_task.state}")
        await add_intervention(session, task_id, "pause", {"previous_state": db_task.state})
        await update_task_state(session, task_id, state="PAUSED")
        await session.commit()
    runner.cancel(task_id)
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
        if not next_state or not can_transition(db_task.state, next_state):
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
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if runner.is_running(task_id):
            raise HTTPException(status_code=409, detail="Cannot rerun while pipeline is active. Pause the task first.")
        if not can_transition(db_task.state, "ANALYZING"):
            raise HTTPException(status_code=409, detail=f"Cannot rerun while task is {db_task.state}")
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


@router.post("/api/v1/tasks/{task_id}/terminate")
async def terminate_task(task_id: str):
    runner.cancel(task_id)
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        await add_intervention(session, task_id, "terminate", {"previous_state": db_task.state})
        await update_task_state(session, task_id, state="ERROR", error={"message": "Task terminated by user", "type": "UserTerminated"})
        db_task.analysis_results = {}
        db_task.final_report = {}
        db_task.raw_materials = []
        db_task.critic_feedback = []
        await session.commit()
    await publish_event(task_id, "task_state_changed", {"state": "ERROR", "terminated": True})
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "terminate", "message": "Task terminated by user."})
    return {"status": "terminated"}


@router.post("/api/v1/tasks/{task_id}/continue-analysis")
async def continue_analysis(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in ("COLLECTING", "PAUSED", "ERROR"):
            raise HTTPException(status_code=409, detail=f"Cannot continue analysis while task is {db_task.state}")
        raw_materials = list(db_task.raw_materials or [])
        if not raw_materials:
            raise HTTPException(status_code=409, detail="No collected materials to analyze. Collect data first.")
        await add_intervention(session, task_id, "continue_analysis", {"previous_state": db_task.state})
        await update_task_state(session, task_id, state="COLLECTING", progress=60)
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "continue", "message": "Continuing analysis from post-collection state."})
    await publish_event(task_id, "task_state_changed", {"state": "COLLECTING", "progress": 60})
    if not runner.start(task_id, lambda: process_agent_pipeline(task_id, start_from="analyzer")):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")
    return {"status": "continuing", "state": "ANALYZING"}


@router.post("/api/v1/tasks/{task_id}/calibration")
async def calibration_action(task_id: str, req: Request):
    body = await req.json()
    action = body.get("action", "")
    if action not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'confirm' or 'reject'")
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in ("NEEDS_INTERVENTION",):
            raise HTTPException(status_code=409, detail=f"Cannot calibrate while task is {db_task.state}")
    started = runner.start(task_id, lambda: calibration_confirm(task_id) if action == "confirm" else calibration_reject(task_id))
    if not started:
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")
    return {"status": "calibrating", "action": action, "state": "PROCESSING"}
