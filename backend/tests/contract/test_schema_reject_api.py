from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from core.runtime import runner
from api.routers.schema import reject_schema


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_reject_schema_returns_regenerating_with_run_id(monkeypatch):
    task = SimpleNamespace(id="task_1", state="SCHEMA_REVIEW", progress=30)
    run_id = "run_test123"
    published = []

    monkeypatch.setattr("api.routers.schema.async_session", lambda: FakeSession())
    monkeypatch.setattr("api.routers.schema.new_run_id", lambda: run_id)

    async def get_task(*args, **kwargs):
        return task

    async def add_intervention(*args, **kwargs):
        return None

    async def update_task_state(*args, **kwargs):
        return task

    async def set_task_run(*args, **kwargs):
        task.active_run_id = run_id

    async def publish_event(task_id, event_type, payload, run_id=None, allow_inactive=False):
        published.append((event_type, payload, run_id))

    monkeypatch.setattr("api.routers.schema.get_task", get_task)
    monkeypatch.setattr("api.routers.schema.add_intervention", add_intervention)
    monkeypatch.setattr("api.routers.schema.update_task_state", update_task_state)
    monkeypatch.setattr("api.routers.schema.set_task_run", set_task_run)
    monkeypatch.setattr("api.routers.schema.publish_event", publish_event)
    monkeypatch.setattr("api.routers.schema.runner.start_claimed", lambda tid, rid, cf: True)

    response = await reject_schema("task_1", BackgroundTasks())

    assert response == {"status": "regenerating", "state": "SCHEMA_GENERATING", "run_id": run_id}
    # Events must carry run_id
    assert all(rid == run_id for _, _, rid in published if rid is not None)
    # task_state_changed must carry run_id
    assert any(et == "task_state_changed" for et, _, _ in published)
    # Cleanup: release the claim since the mock doesn't start a real pipeline
    runner.release("task_1", run_id)


@pytest.mark.asyncio
async def test_reject_schema_rejects_invalid_state(monkeypatch):
    task = SimpleNamespace(id="task_1", state="COMPLETED", progress=100)
    monkeypatch.setattr("api.routers.schema.async_session", lambda: FakeSession())
    monkeypatch.setattr("api.routers.schema.new_run_id", lambda: "run_test123")

    async def get_task(*args, **kwargs):
        return task

    monkeypatch.setattr("api.routers.schema.get_task", get_task)

    with pytest.raises(HTTPException) as exc:
        await reject_schema("task_1", BackgroundTasks())

    assert exc.value.status_code == 409
