from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import main
from core.runtime import runner
from api.routers.schema import reject_schema, resume_task
from schemas import SchemaUpdateRequest


class FakeDeleteStmt:
    def where(self, *args, **kwargs):
        return self


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def execute(self, *args, **kwargs):
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
async def test_resume_task_returns_collecting_with_run_id(monkeypatch):
    task = SimpleNamespace(id="task_1", state="SCHEMA_REVIEW", progress=30)
    schema = SimpleNamespace(version=3)
    run_id = "run_resume123"
    published = []

    monkeypatch.setattr("api.routers.schema.async_session", lambda: FakeSession())
    monkeypatch.setattr("api.routers.schema.new_run_id", lambda: run_id)

    async def get_task(*args, **kwargs):
        return task

    async def latest_schema(*args, **kwargs):
        return schema

    async def add_intervention(*args, **kwargs):
        return None

    async def update_task_state(*args, **kwargs):
        return task

    async def set_task_run(*args, **kwargs):
        task.active_run_id = run_id

    async def publish_event(task_id, event_type, payload, run_id=None, allow_inactive=False):
        published.append((event_type, payload, run_id))

    monkeypatch.setattr("api.routers.schema.get_task", get_task)
    monkeypatch.setattr("api.routers.schema.latest_schema", latest_schema)
    monkeypatch.setattr("api.routers.schema.add_intervention", add_intervention)
    monkeypatch.setattr("api.routers.schema.update_task_state", update_task_state)
    monkeypatch.setattr("api.routers.schema.set_task_run", set_task_run)
    monkeypatch.setattr("api.routers.schema.publish_event", publish_event)
    monkeypatch.setattr("api.routers.schema.runner.start_claimed", lambda tid, rid, cf: True)
    monkeypatch.setattr("api.routers.schema.SourceMaterialRecord", SimpleNamespace(__table__=SimpleNamespace(delete=lambda: FakeDeleteStmt()), task_id=""))

    response = await resume_task("task_1", BackgroundTasks())

    assert response == {"status": "resumed", "state": "COLLECTING", "run_id": run_id}
    # Events must carry run_id
    task_state_events = [(et, pl, rid) for et, pl, rid in published if et == "task_state_changed"]
    assert len(task_state_events) > 0
    assert task_state_events[0][2] == run_id
    progress_events = [(et, pl, rid) for et, pl, rid in published if et == "progress_update"]
    assert len(progress_events) > 0
    assert progress_events[0][2] == run_id
    # Cleanup: release the claim since the mock doesn't start a real pipeline
    runner.release("task_1", run_id)


@pytest.mark.asyncio
async def test_resume_rejects_invalid_state(monkeypatch):
    task = SimpleNamespace(id="task_1", state="COMPLETED", progress=100)
    monkeypatch.setattr("api.routers.schema.async_session", lambda: FakeSession())
    monkeypatch.setattr("api.routers.schema.new_run_id", lambda: "run_resume123")

    async def get_task(*args, **kwargs):
        return task

    monkeypatch.setattr("api.routers.schema.get_task", get_task)

    with pytest.raises(HTTPException) as exc:
        await resume_task("task_1", BackgroundTasks())

    assert exc.value.status_code == 409
