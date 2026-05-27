from fastapi import APIRouter, HTTPException

from models_db import UserFeedbackRecord, UserNoteRecord, async_session
from schemas import FeedbackRequest, NoteRequest
from services.pipeline import publish_event
from services.repositories import get_task, new_id

router = APIRouter()


@router.post("/api/v1/tasks/{task_id}/feedback")
async def record_feedback(task_id: str, req: FeedbackRequest):
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(UserFeedbackRecord(id=new_id("feedback"), task_id=task_id, **req.model_dump()))
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "feedback", "message": f"Recorded {req.feedback} feedback"})
    return {"status": "recorded"}


@router.post("/api/v1/tasks/{task_id}/notes")
async def save_note(task_id: str, req: NoteRequest):
    note_id = new_id("note")
    async with async_session() as session:
        if not await get_task(session, task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        session.add(UserNoteRecord(id=note_id, task_id=task_id, **req.model_dump()))
        await session.commit()
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "note", "message": "Saved user note"})
    return {"status": "saved", "note_id": note_id}
