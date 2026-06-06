import pytest
from services.web_search import SearchResult

from agents import collector


@pytest.mark.asyncio
async def test_collector_reports_real_query_progress(monkeypatch):
    async def fake_search(query: str, limit: int = 3):
        return [
            SearchResult(query=query, title="One", url="https://example.com/one", snippet="First result"),
            SearchResult(query=query, title="Two", url="https://example.com/two", snippet="Second result"),
        ]

    progress_events = []

    async def record_progress(payload):
        progress_events.append(payload)

    monkeypatch.setattr("agents.collector.node.search_multi_engine", fake_search)

    state = {
        "task_id": "task_progress",
        "task_context": {"competitors": ["Alpha"]},
        "dynamic_schema": {
            "Core": [
                {"id": "Core.Pricing", "name": "Pricing", "source": "official"},
                {"id": "Core.SLA", "name": "SLA", "source": "official"},
            ]
        },
    }

    await collector.collector_node(state, on_progress=record_progress)

    assert [event["completed"] for event in progress_events] == [1, 2]
    assert all(event["total"] == 2 for event in progress_events)
    assert [event["discovered_results"] for event in progress_events] == [2, 4]
    assert progress_events[0]["status"] == "accepted"
    assert progress_events[0]["url"] == "https://example.com/one"
    assert progress_events[0]["query"] == "Alpha Pricing official"
