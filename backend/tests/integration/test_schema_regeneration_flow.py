import pytest

from agents.orchestrator import orchestrator_node


@pytest.mark.asyncio
async def test_schema_regeneration_produces_real_schema_state_without_mock_status():
    state = {
        "task_id": "task_1",
        "task_context": {"domain": "AI assistants", "competitors": ["Alpha", "Beta"], "predefined_schema": []},
        "schema_version": 1,
        "dynamic_schema": {},
        "raw_materials": [],
        "source_ids": [],
        "analysis_results": {},
        "critic_feedback": [],
        "task_events": [],
        "progress": 10,
        "module_updates": [],
        "retry_counts": {},
    }

    updated = await orchestrator_node(state)

    assert updated["schema_version"] == 2
    assert updated["dynamic_schema"]
    assert "mock" not in str(updated["dynamic_schema"]).lower()
    assert "mocked" not in str(updated["dynamic_schema"]).lower()
