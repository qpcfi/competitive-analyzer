import agents.orchestrator as orchestrator
import pytest
from services.web_search import SearchResult


@pytest.mark.asyncio
async def test_discover_competitors_requires_llm(monkeypatch):
    monkeypatch.setattr(orchestrator, "llm", None)

    with pytest.raises(orchestrator.CompetitorDiscoveryUnavailable, match="LLM"):
        await orchestrator.discover_competitors("AI search tools")


@pytest.mark.asyncio
async def test_discover_competitors_uses_fetched_page_evidence(monkeypatch):
    captured = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            captured["prompt"] = messages[0].content

            class Response:
                content = """
                [
                  {
                    "name": "Perplexity",
                    "reason": "The evidence describes Perplexity as an AI search product.",
                    "source_urls": ["https://example.com/ai-search"],
                    "confidence": 0.91
                  },
                  {
                    "name": "LLM Leaderboard",
                    "reason": "This is a ranking page, not a product.",
                    "source_urls": ["https://example.com/ranking"],
                    "confidence": 0.4
                  }
                ]
                """

            return Response()

    async def fake_search(query: str, limit: int = 5):
        return [
            orchestrator.SearchResult(
                query=query,
                title="AI Search Alternatives",
                url="https://example.com/ai-search",
                snippet="Perplexity and You.com appear in this market.",
            ),
            orchestrator.SearchResult(
                query=query,
                title="Duplicate",
                url="https://example.com/ai-search",
                snippet="Duplicate URL should not be fetched twice.",
            ),
        ]

    async def fake_fetch(results, limit: int = 5):
        captured["fetched_urls"] = [result.url for result in results]
        return [
            orchestrator.PageEvidence(
                query=results[0].query,
                search_title=results[0].title,
                url=results[0].url,
                snippet=results[0].snippet,
                page_title="AI Search Alternatives",
                text="Perplexity, You.com, and Glean are AI search competitors for enterprise teams.",
            )
        ]

    monkeypatch.setattr(orchestrator, "llm", FakeLLM())
    monkeypatch.setattr(orchestrator, "search_public_web", fake_search)
    monkeypatch.setattr(orchestrator, "fetch_public_web_pages", fake_fetch)

    names = await orchestrator.discover_competitors("AI search tools")

    assert names == ["Perplexity"]
    assert captured["fetched_urls"] == ["https://example.com/ai-search"]
    assert "Perplexity, You.com, and Glean" in captured["prompt"]


def test_extracts_competitor_names_from_search_evidence_instead_of_page_titles():
    results = [
        SearchResult(
            query="AI大模型 competitors products",
            title="Poetrynan/In",
            url="https://github.com/Poetrynan/In",
            snippet="Collected notes mentioning GPT-4o, Claude 3.5, Gemini 1.5, and DeepSeek-V3.",
        ),
        SearchResult(
            query="AI大模型 competitors products",
            title="LLM Leaderboard",
            url="https://example.com/leaderboard",
            snippet="Qwen-Max, Llama 3, Kimi and GLM-4 appear in recent model comparisons.",
        ),
        SearchResult(
            query="AI大模型 competitors products",
            title="2025年全球AI大模型综合排名（Top 20）",
            url="https://example.com/top-20",
            snippet="A ranking article lists GPT-4o, Claude 3.5, Gemini 1.5, DeepSeek-V3.",
        ),
    ]

    names = orchestrator.extract_competitor_names_from_search_results(results, "AI大模型")

    assert names[:3] == ["GPT-4o", "Claude 3.5", "Gemini 1.5"]
    assert "Poetrynan/In" not in names
    assert "LLM Leaderboard" not in names
    assert "2025年全球AI大模型综合排名（Top 20）" not in names


def test_normalize_competitor_names_filters_page_titles_and_repository_paths():
    names = orchestrator.normalize_competitor_names(
        [
            "Poetrynan/In",
            "LLM Leaderboard",
            "2025年全球AI大模型综合排名（Top 20）",
            "DeepSeek-V3",
            "Qwen-Max",
        ]
    )

    assert names == ["DeepSeek-V3", "Qwen-Max"]
