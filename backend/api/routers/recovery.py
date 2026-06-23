from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from core import runtime
from core.runtime import runner
from models_db import SourceMaterialRecord, async_session
from schemas import PartialRerunRequest
from services.analysis_rerun import run_incremental_analysis_rerun
from services.pipeline import (
    process_agent_pipeline,
    publish_event,
    calibration_confirm,
    calibration_reject,
)
from services.repositories import add_intervention, get_task, invalidate_task_run, new_run_id, resolve_all_pending_feedback, set_task_run, update_task_state
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
        old_run_id = db_task.active_run_id
        await invalidate_task_run(session, task_id)
        await update_task_state(session, task_id, state="PAUSED")
        await session.commit()
    runner.cancel(task_id, old_run_id)
    await publish_event(task_id, "task_state_changed", {"state": "PAUSED"}, run_id=old_run_id, allow_inactive=True)
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
async def partial_rerun(task_id: str, req: PartialRerunRequest):
    scope = req.scope or {}

    if not scope.get("type"):
        raise HTTPException(status_code=400, detail="scope.type is required")

    instruction = req.instruction or ""

    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                raise HTTPException(status_code=404, detail="Task not found")

            if db_task.state not in ("ANALYSIS_REVIEW", "PAUSED", "COMPLETED"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot rerun while task is {db_task.state}. "
                           f"Allowed: ANALYSIS_REVIEW, PAUSED, COMPLETED",
                )
            if not db_task.analysis_results:
                raise HTTPException(status_code=409, detail="No analysis results to rerun")
            if not db_task.raw_materials:
                raise HTTPException(status_code=409, detail="No collected materials available")

            await set_task_run(session, task_id, run_id)
            await session.commit()
    except HTTPException:
        runner.release(task_id, run_id)
        raise
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: run_incremental_analysis_rerun(task_id, run_id, scope, instruction)):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    return {"status": "rerunning", "scope": scope, "state": "ANALYSIS_REVIEW", "run_id": run_id}


@router.post("/api/v1/tasks/{task_id}/terminate")
async def terminate_task(task_id: str):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        old_run_id = db_task.active_run_id
        await invalidate_task_run(session, task_id)
        await add_intervention(session, task_id, "terminate", {"previous_state": db_task.state})
        await update_task_state(session, task_id, state="ERROR", error={"message": "Task terminated by user", "type": "UserTerminated"})
        db_task.analysis_results = {}
        db_task.final_report = {}
        db_task.raw_materials = []
        db_task.critic_feedback = []
        await resolve_all_pending_feedback(session, task_id)
        await session.commit()
    runner.cancel(task_id, old_run_id)
    await publish_event(task_id, "task_state_changed", {"state": "ERROR", "terminated": True}, run_id=old_run_id, allow_inactive=True)
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "terminate", "message": "Task terminated by user."}, run_id=old_run_id, allow_inactive=True)
    return {"status": "terminated"}


@router.post("/api/v1/tasks/{task_id}/continue-analysis")
async def continue_analysis(task_id: str):
    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                raise HTTPException(status_code=404, detail="Task not found")
            if db_task.state not in ("COLLECTING", "PAUSED", "ERROR"):
                raise HTTPException(status_code=409, detail=f"Cannot continue analysis while task is {db_task.state}")
            if db_task.state == "COLLECTING" and db_task.active_run_id:
                raise HTTPException(status_code=409, detail="Collection pipeline is still active; analysis will start automatically.")

            # Verify materials exist via source_materials table (not the raw_materials JSON column,
            # which is no longer populated after the switch to dedicated table + collection_run_id).
            material_ids = db_task.current_material_ids or []
            has_materials = False
            if material_ids:
                result = await session.execute(
                    select(SourceMaterialRecord.id).where(
                        SourceMaterialRecord.task_id == task_id,
                        SourceMaterialRecord.id.in_(material_ids),
                    ).limit(1)
                )
                has_materials = result.scalar_one_or_none() is not None
                if not has_materials:
                    # 旧快照的 ID 可能不存在于 source_materials 表，降级查全部
                    result = await session.execute(
                        select(SourceMaterialRecord.id).where(
                            SourceMaterialRecord.task_id == task_id,
                        ).limit(1)
                    )
                    has_materials = result.scalar_one_or_none() is not None
            elif db_task.current_collection_run_id:
                result = await session.execute(
                    select(SourceMaterialRecord.id).where(
                        SourceMaterialRecord.task_id == task_id,
                        SourceMaterialRecord.collection_run_id == db_task.current_collection_run_id,
                    ).limit(1)
                )
                has_materials = result.scalar_one_or_none() is not None
            else:
                # Fallback: check if any source material exists for this task
                result = await session.execute(
                    select(SourceMaterialRecord.id).where(
                        SourceMaterialRecord.task_id == task_id,
                    ).limit(1)
                )
                has_materials = result.scalar_one_or_none() is not None
            if not has_materials:
                raise HTTPException(status_code=409, detail="No collected materials to analyze. Collect data first.")

            await add_intervention(session, task_id, "continue_analysis", {"previous_state": db_task.state})
            await update_task_state(session, task_id, state="ANALYZING", progress=65)
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: process_agent_pipeline(task_id, run_id, start_from="analyzer")):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    await publish_event(task_id, "debug_log", {"agent": "System", "event": "continue", "message": "Continuing analysis from collected materials."}, run_id=run_id)
    await publish_event(task_id, "task_state_changed", {"state": "ANALYZING", "progress": 65}, run_id=run_id)
    return {"status": "continuing", "state": "ANALYZING", "run_id": run_id}


@router.post("/api/v1/tasks/{task_id}/continue-critic")
async def continue_critic(task_id: str):
    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                raise HTTPException(status_code=404, detail="Task not found")
            if db_task.state != "ANALYSIS_REVIEW":
                raise HTTPException(status_code=409, detail=f"Cannot continue critic while task is {db_task.state}")
            if not db_task.analysis_results:
                raise HTTPException(status_code=409, detail="No analysis results to review. Run analysis first.")
            await add_intervention(session, task_id, "continue_critic", {"previous_state": db_task.state})
            await update_task_state(session, task_id, state="CRITIQUING", progress=95)
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: process_agent_pipeline(task_id, run_id, start_from="critic")):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    await publish_event(task_id, "debug_log", {"agent": "System", "event": "continue", "message": "Continuing Critic from reviewed analysis."}, run_id=run_id)
    await publish_event(task_id, "task_state_changed", {"state": "CRITIQUING", "progress": 95}, run_id=run_id)
    return {"status": "continuing", "state": "CRITIQUING", "run_id": run_id}


@router.post("/api/v1/tasks/{task_id}/calibration")
async def calibration_action(task_id: str, req: Request):
    body = await req.json()
    action = body.get("action", "")
    if action not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'confirm' or 'reject'")

    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            db_task = await get_task(session, task_id)
            if not db_task:
                raise HTTPException(status_code=404, detail="Task not found")
            if db_task.state not in ("NEEDS_INTERVENTION",):
                raise HTTPException(status_code=409, detail=f"Cannot calibrate while task is {db_task.state}")
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    if not runner.start_claimed(task_id, run_id, lambda: calibration_confirm(task_id, run_id) if action == "confirm" else calibration_reject(task_id, run_id)):
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    return {"status": "calibrating", "action": action, "state": "PROCESSING", "run_id": run_id}
