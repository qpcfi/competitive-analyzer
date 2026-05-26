import pytest

from agents import collector


@pytest.mark.asyncio
async def test_collector_collects_each_competitor_schema_field(monkeypatch):
    async def fake_search(query: str, limit: int = 3):
        return [
            collector.SearchResult(
                query=query,
                title=f"Result for {query}",
                url=f"https://evidence.example/{query.replace(' ', '-')}",
                snippet=f"Evidence snippet for {query}.",
            )
        ]

    monkeypatch.setattr(collector, "search_public_web", fake_search)

    state = {
        "task_id": "task_test",
        "task_context": {"competitors": ["Alpha", "Beta"]},
        "dynamic_schema": {
            "Core": [
                {"id": "Core.Pricing", "name": "Pricing", "source": "official"},
                {"id": "Core.SLA", "name": "SLA", "source": "official"},
            ]
        },
    }

    updated = await collector.collector_node(state)
    materials = updated["raw_materials"]

    assert len(materials) == 4
    assert {(item["competitor"], item["schema_field_id"]) for item in materials} == {
        ("Alpha", "Core.Pricing"),
        ("Alpha", "Core.SLA"),
        ("Beta", "Core.Pricing"),
        ("Beta", "Core.SLA"),
    }
    assert all(item["validation_status"] == "accepted" for item in materials)
    assert all(item["quote_text"].startswith("Result for") for item in materials)
