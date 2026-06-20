import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator

from models_db import async_session
from services.repositories import add_event, is_task_run_active, list_events


class EventBroker:
    def __init__(self) -> None:
        self._queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, task_id: str, event_type: str, payload: dict[str, Any], run_id: str | None = None, allow_inactive: bool = False) -> dict[str, Any] | None:
        # If run_id is provided, check if this run is still active (skip stale run events)
        if run_id and not allow_inactive:
            async with async_session() as session:
                if not await is_task_run_active(session, task_id, run_id):
                    return None

        payload = {
            "task_id": task_id,
            "run_id": run_id,
            **payload,
        }

        async with async_session() as session:
            event = await add_event(session, task_id, event_type, payload, run_id=run_id)
            await session.commit()
            data = {"sequence": event.sequence, **payload}
        message = {"event": event_type, "data": data}
        for queue in list(self._queues.get(task_id, set())):
            await queue.put(message)
        return data

    async def stream(self, task_id: str, since: int = 0) -> AsyncIterator[str]:
        async with async_session() as session:
            replay = await list_events(session, task_id, since=since)
        for event in replay:
            data = {"sequence": event.sequence, **(event.payload or {})}
            yield format_sse(event.event_type, data)

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[task_id].add(queue)
        try:
            while True:
                message = await queue.get()
                yield format_sse(message["event"], message["data"])
        finally:
            self._queues[task_id].discard(queue)
            if not self._queues[task_id]:
                self._queues.pop(task_id, None)


def format_sse(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


event_broker = EventBroker()
