from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import main


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_reject_schema_returns_regenerating_without_mock_status(monkeypatch):
    task = SimpleNamespace(id="task_1", state="SCHEMA_REVIEW", progress=30)
    published = []

    monkeypatch.setattr(main, "async_session", lambda: FakeSession())

    async def get_task(*args, **kwargs):
        return task

    async def add_intervention(*args, **kwargs):
        return None

    async def update_task_state(*args, **kwargs):
        return task

    async def publish_event(task_id, event_type, payload):
        published.append((event_type, payload))

    monkeypatch.setattr(main, "get_task", get_task)
    monkeypatch.setattr(main, "add_intervention", add_intervention)
    monkeypatch.setattr(main, "update_task_state", update_task_state)
    monkeypatch.setattr(main, "publish_event", publish_event)

    response = await main.reject_schema("task_1", BackgroundTasks())

    assert response == {"status": "regenerating", "state": "SCHEMA_GENERATING"}
    assert "mock" not in str(response).lower()
    assert any(event_type == "task_state_changed" for event_type, _ in published)


@pytest.mark.asyncio
async def test_reject_schema_rejects_invalid_state(monkeypatch):
    task = SimpleNamespace(id="task_1", state="COMPLETED", progress=100)
    monkeypatch.setattr(main, "async_session", lambda: FakeSession())

    async def get_task(*args, **kwargs):
        return task

    monkeypatch.setattr(main, "get_task", get_task)

    with pytest.raises(HTTPException) as exc:
        await main.reject_schema("task_1", BackgroundTasks())

    assert exc.value.status_code == 409
