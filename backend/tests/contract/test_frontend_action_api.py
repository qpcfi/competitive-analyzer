import pytest
from fastapi import HTTPException

import main


def route_methods(path: str) -> set[str]:
    methods = set()
    for route in main.app.routes:
        if getattr(route, "path", None) == path:
            methods.update(route.methods or [])
    return methods


def test_frontend_action_routes_are_registered():
    expected = {
        "/api/v1/tasks": "GET",
        "/api/v1/tasks/{task_id}/snapshots": "GET",
        "/api/v1/tasks/{task_id}/restore_snapshot": "POST",
        "/api/v1/tasks/{task_id}/schema/advice": "GET",
        "/api/v1/tasks/{task_id}/feedback": "POST",
        "/api/v1/tasks/{task_id}/notes": "POST",
        "/api/v1/tasks/{task_id}/report": "GET",
        "/api/v1/tasks/{task_id}/export": "GET",
        "/api/v1/tasks/{task_id}/share": "POST",
        "/api/v1/tasks/{task_id}/verify_links": "POST",
        "/api/v1/tasks/{task_id}/events": "GET",
        "/api/v1/competitor-recommendations": "GET",
    }

    for path, method in expected.items():
        assert method in route_methods(path), path


def test_schema_and_source_event_payload_stats_are_contract_shaped():
    schema = {"Core": [{"origin": "user"}, {"origin": "agent"}]}
    materials = [
        {"validation_status": "accepted", "access_status": "accessible"},
        {"validation_status": "degraded", "access_status": "blocked"},
    ]

    assert main.count_schema_stats(schema) == {"total_fields": 2, "user_defined": 1, "agent_supplement": 1}
    assert main.source_stats(materials) == {"accepted": 1, "degraded": 1, "failed": 0, "blocked": 1}


async def test_competitor_recommendations_filter_existing_names(monkeypatch):
    async def fake_discover_competitors(domain: str):
        assert domain == "AI search tools"
        return ["GPT-4o", "Claude 3.5", "Perplexity"]

    monkeypatch.setattr(main, "discover_competitors", fake_discover_competitors)

    payload = await main.get_competitor_recommendations(
        domain="AI search tools",
        existing=["gpt-4o"],
    )

    assert payload["items"] == [
        {
            "name": "Claude 3.5",
            "reason": "基于公开网页信号，Claude 3.5 与 AI search tools 存在竞品相关性。",
        },
        {
            "name": "Perplexity",
            "reason": "基于公开网页信号，Perplexity 与 AI search tools 存在竞品相关性。",
        },
    ]


@pytest.mark.asyncio
async def test_competitor_recommendations_returns_503_when_discovery_unavailable(monkeypatch):
    async def fake_discover_competitors(domain: str):
        raise main.CompetitorDiscoveryUnavailable("LLM is required for competitor discovery")

    monkeypatch.setattr(main, "discover_competitors", fake_discover_competitors)

    with pytest.raises(HTTPException) as exc:
        await main.get_competitor_recommendations(domain="AI search tools", existing=[])

    assert exc.value.status_code == 503
    assert "LLM is required" in exc.value.detail
