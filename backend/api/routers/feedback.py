from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.runtime import runner
from models_db import async_session
from schemas import FeedbackApplyRequest, FeedbackRequest, NoteRequest
from services.pipeline import (
    publish_event,
    run_critic_retry,
)
from services.repositories import (
    get_pending_feedback,
    get_task,
    new_run_id,
    resolve_feedback_items,
    set_task_run,
)
from services.state_machine import can_transition

router = APIRouter()


class CriticApplyRequest(BaseModel):
    confirmed_feedback_ids: list[str] = []
    rejected_feedback_ids: list[str] = []
    confirmed_extensions: list[dict] = []


@router.post("/api/v1/tasks/{task_id}/feedback")
async def record_feedback(task_id: str, req: FeedbackRequest):
    from models_db import UserFeedbackRecord
    from services.repositories import new_id
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(UserFeedbackRecord(id=new_id("feedback"), task_id=task_id, **req.model_dump()))
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "feedback", "message": f"Recorded {req.feedback} feedback"})
    return {"status": "recorded"}


@router.post("/api/v1/tasks/{task_id}/notes")
async def save_note(task_id: str, req: NoteRequest):
    from models_db import UserNoteRecord
    from services.repositories import new_id
    note_id = new_id("note")
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(UserNoteRecord(id=note_id, task_id=task_id, **req.model_dump()))
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "note", "message": "Saved user note"})
    return {"status": "saved", "note_id": note_id}


@router.post("/api/v1/tasks/{task_id}/critic/apply")
async def apply_critic_retry(task_id: str, req: CriticApplyRequest):
    """Unified endpoint: user confirms/rejects critic suggestions and starts retry pipeline."""
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if not can_transition(db_task.state, "ANALYZING"):
            raise HTTPException(status_code=409, detail=f"Cannot apply feedback while task is {db_task.state}")

    rejected = req.rejected_feedback_ids
    if rejected:
        async with async_session() as session:
            await resolve_feedback_items(session, task_id, rejected)
            await session.commit()

    confirmed_ids = req.confirmed_feedback_ids
    confirmed_extensions = req.confirmed_extensions

    has_feedback = len(confirmed_ids) > 0
    has_extensions = len(confirmed_extensions) > 0

    if not has_feedback and not has_extensions:
        return {"status": "skipped", "reason": "nothing to apply"}

    run_id = new_run_id()
    if not runner.claim(task_id, run_id):
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    try:
        async with async_session() as session:
            await set_task_run(session, task_id, run_id)
            await session.commit()
    except Exception:
        runner.release(task_id, run_id)
        raise

    started = runner.start_claimed(task_id, run_id, lambda: run_critic_retry(
        task_id,
        run_id,
        confirmed_feedback_ids=confirmed_ids,
        confirmed_extensions=confirmed_extensions if has_extensions else None,
    ))

    if not started:
        runner.release(task_id, run_id)
        raise HTTPException(status_code=409, detail="Pipeline already running for this task")

    return {
        "status": "applied",
        "confirmed_feedback": len(confirmed_ids),
        "confirmed_extensions": len(confirmed_extensions),
        "rejected": len(rejected),
        "run_id": run_id,
    }


@router.post("/api/v1/tasks/{task_id}/feedback/apply")
async def apply_feedback_only(task_id: str, req: FeedbackApplyRequest):
    """Simple mark-resolved without retry pipeline (used when calibration_confirm already handles pipeline)."""
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")

    if req.rejected_feedback_ids:
        async with async_session() as session:
            await resolve_feedback_items(session, task_id, req.rejected_feedback_ids)
            await session.commit()

    if req.confirmed_feedback_ids:
        async with async_session() as session:
            await resolve_feedback_items(session, task_id, req.confirmed_feedback_ids)
            await session.commit()

    return {"status": "resolved", "confirmed": len(req.confirmed_feedback_ids), "rejected": len(req.rejected_feedback_ids)}


@router.get("/api/v1/tasks/{task_id}/feedback/pending")
async def list_pending_feedback(task_id: str):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        items = await get_pending_feedback(session, task_id)
    return {
        "feedback": [
            {
                "id": item.id,
                "level": item.level,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "severity": item.severity,
                "message": item.message,
                "suggested_action": item.suggested_action,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]
    }
