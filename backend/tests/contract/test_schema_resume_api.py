from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import main
from schemas import SchemaUpdateRequest


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_update_schema_returns_version_and_review_state(monkeypatch):
    task = SimpleNamespace(id="task_1", state="SCHEMA_REVIEW", progress=30)
    record = SimpleNamespace(version=2)
    published = []

    monkeypatch.setattr(main, "async_session", lambda: FakeSession())

    async def get_task(*args, **kwargs):
        return task

    monkeypatch.setattr(main, "get_task", get_task)

    async def save_schema(*args, **kwargs):
        return record

    async def add_intervention(*args, **kwargs):
        return None

    async def update_task_state(*args, **kwargs):
        return task

    async def publish_event(task_id, event_type, payload):
        published.append((event_type, payload))

    monkeypatch.setattr(main, "save_schema", save_schema)
    monkeypatch.setattr(main, "add_intervention", add_intervention)
    monkeypatch.setattr(main, "update_task_state", update_task_state)
    monkeypatch.setattr(main, "publish_event", publish_event)
    monkeypatch.setattr(main, "app_step", None)

    response = await main.update_schema("task_1", SchemaUpdateRequest(dynamic_schema={"Core": []}))

    assert response == {"status": "updated", "schema_version": 2, "state": "SCHEMA_REVIEW"}
    assert any(event_type == "schema_ready" for event_type, _ in published)


@pytest.mark.asyncio
async def test_resume_rejects_invalid_state(monkeypatch):
    task = SimpleNamespace(id="task_1", state="COMPLETED", progress=100)
    monkeypatch.setattr(main, "async_session", lambda: FakeSession())

    async def get_task(*args, **kwargs):
        return task

    monkeypatch.setattr(main, "get_task", get_task)

    with pytest.raises(HTTPException) as exc:
        await main.resume_task("task_1", BackgroundTasks())

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_contract_returns_collecting(monkeypatch):
    task = SimpleNamespace(id="task_1", state="SCHEMA_REVIEW", progress=30)
    schema = SimpleNamespace(version=3)
    published = []

    monkeypatch.setattr(main, "async_session", lambda: FakeSession())

    async def get_task(*args, **kwargs):
        return task

    async def latest_schema(*args, **kwargs):
        return schema

    monkeypatch.setattr(main, "get_task", get_task)
    monkeypatch.setattr(main, "latest_schema", latest_schema)

    async def add_intervention(*args, **kwargs):
        return None

    async def update_task_state(*args, **kwargs):
        return task

    async def publish_event(task_id, event_type, payload):
        published.append((event_type, payload))

    monkeypatch.setattr(main, "add_intervention", add_intervention)
    monkeypatch.setattr(main, "update_task_state", update_task_state)
    monkeypatch.setattr(main, "publish_event", publish_event)
    monkeypatch.setattr(main, "app_step", None)

    response = await main.resume_task("task_1", BackgroundTasks())

    assert response == {"status": "resumed", "state": "COLLECTING"}
    assert ("task_state_changed", {"state": "COLLECTING", "previous_state": "SCHEMA_REVIEW", "progress": 40}) in published
