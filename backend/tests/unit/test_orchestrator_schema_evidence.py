import pytest

from agents import orchestrator


@pytest.mark.asyncio
async def test_orchestrator_attaches_web_evidence_to_user_fields_and_recommendations(monkeypatch):
    async def fake_search(query: str, limit: int = 5):
        return [
            orchestrator.SearchResult(
                query=query,
                title="Vendor API limits",
                url="https://vendor.example/docs/api-limits",
                snippet="The API supports documented rate limits, pricing tiers, SLA, and compliance controls.",
            )
        ]

    monkeypatch.setattr(orchestrator, "llm", None)
    monkeypatch.setattr(orchestrator, "search_public_web", fake_search)

    state = {
        "task_context": {
            "domain": "enterprise AI API",
            "competitors": ["VendorA", "VendorB"],
            "predefined_schema": [
                {"name": "API rate limits", "type": "text", "source": "official"},
            ],
        },
        "schema_version": 1,
    }

    updated = await orchestrator.orchestrator_node(state)
    fields = [field for group in updated["dynamic_schema"].values() for field in group]

    user_field = next(field for field in fields if field["name"] == "API rate limits")
    assert user_field["feasibility"] == "high"
    assert user_field["evidence_refs"] == ["schemaev_1"]
    assert user_field["recommended_queries"] == [
        "VendorA API rate limits enterprise AI API",
        "VendorB API rate limits enterprise AI API",
    ]

    recommended_names = {field["name"] for field in fields if field["origin"] == "agent"}
    assert "SLA" in recommended_names
    assert "Compliance" in recommended_names
