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


@pytest.mark.asyncio
async def test_orchestrator_completes_competitors_and_schema_without_user_inputs(monkeypatch):
    class FakeLLM:
        async def ainvoke(self, messages):
            class Response:
                content = """
                {
                  "competitors": ["AlphaAI", "BetaAI", "GammaAI"],
                  "schema": {
                    "Function Tree": [
                      {"name": "Conversation Ability", "type": "text", "confidence": 0.86}
                    ],
                    "Pricing Model": [
                      {"name": "Entry Price", "type": "text", "confidence": 0.81}
                    ]
                  }
                }
                """

            return Response()

    async def fake_search(query: str, limit: int = 5):
        return [
            orchestrator.SearchResult(
                query=query,
                title="AlphaAI pricing and features",
                url="https://alpha.example/pricing",
                snippet="AlphaAI lists pricing and conversation features for AI teams.",
            )
        ]

    monkeypatch.setattr(orchestrator, "llm", FakeLLM())
    monkeypatch.setattr(orchestrator, "search_public_web", fake_search)

    state = {
        "task_context": {
            "domain": "AI agents",
            "competitors": [],
            "predefined_schema": [],
        },
        "schema_version": 1,
    }

    updated = await orchestrator.orchestrator_node(state)

    assert updated["task_context"]["competitors"] == ["AlphaAI", "BetaAI", "GammaAI"]
    fields = [field for group in updated["dynamic_schema"].values() for field in group]
    assert {field["name"] for field in fields} >= {"Conversation Ability", "Entry Price"}
    assert all(field["origin"] == "agent" for field in fields if field["name"] in {"Conversation Ability", "Entry Price"})


@pytest.mark.asyncio
async def test_orchestrator_preserves_user_inputs_when_completing_plan(monkeypatch):
    class FakeLLM:
        async def ainvoke(self, messages):
            class Response:
                content = """
                {
                  "competitors": ["UserAI", "AgentAI"],
                  "schema": {
                    "User Defined": [
                      {"name": "Deployment", "type": "boolean", "source": "agent_guess"}
                    ],
                    "Pricing Model": [
                      {"name": "Contract Terms", "type": "text"}
                    ]
                  }
                }
                """

            return Response()

    async def fake_search(query: str, limit: int = 5):
        return []

    monkeypatch.setattr(orchestrator, "llm", FakeLLM())
    monkeypatch.setattr(orchestrator, "search_public_web", fake_search)

    state = {
        "task_context": {
            "domain": "AI platforms",
            "competitors": ["UserAI"],
            "predefined_schema": [
                {"name": "Deployment", "type": "text", "source": "official", "required": True},
            ],
        },
        "schema_version": 1,
    }

    updated = await orchestrator.orchestrator_node(state)

    assert updated["task_context"]["competitors"] == ["UserAI", "AgentAI"]
    user_defined = updated["dynamic_schema"]["User Defined"]
    deployment = next(field for field in user_defined if field["name"] == "Deployment")
    assert deployment["type"] == "text"
    assert deployment["source"] == "official"
    assert deployment["origin"] == "user"
    assert any(field["name"] == "Contract Terms" for field in updated["dynamic_schema"]["Pricing Model"])
