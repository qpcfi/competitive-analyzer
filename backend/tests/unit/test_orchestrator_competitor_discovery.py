import agents.orchestrator as orchestrator
from services.web_search import SearchResult


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
