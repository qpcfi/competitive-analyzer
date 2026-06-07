import httpx
import pytest

from services.web_search import SearchResult, extract_page_text, fetch_public_web_pages, parse_duckduckgo_results, rerank_search_results


def test_parse_duckduckgo_results_extracts_title_url_and_snippet():
    html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://example.com/pricing">Example Pricing</a>
          <a class="result__snippet">Official pricing and feature details.</a>
        </div>
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fvendor.com%2Fdocs">Vendor Docs</a>
          <div class="result__snippet">Technical documentation for API limits.</div>
        </div>
      </body>
    </html>
    """

    results = parse_duckduckgo_results(html, query="example pricing")

    assert [item.title for item in results] == ["Example Pricing", "Vendor Docs"]
    assert [item.url for item in results] == ["https://example.com/pricing", "https://vendor.com/docs"]
    assert results[0].snippet == "Official pricing and feature details."
    assert results[1].query == "example pricing"


def test_extract_page_text_removes_scripts_styles_and_limits_text():
    html = """
    <html>
      <head>
        <title>Vendor Comparison</title>
        <style>.hidden { display: none; }</style>
        <script>window.bad = true;</script>
      </head>
      <body>
        <nav>Home Pricing Login</nav>
        <main>
          <h1>Vendor Comparison</h1>
          <p>Alpha, Beta, and Gamma provide enterprise AI search products.</p>
        </main>
      </body>
    </html>
    """

    text = extract_page_text(html, max_chars=80)

    assert "window.bad" not in text
    assert "display: none" not in text
    assert "Alpha, Beta, and Gamma" in text
    assert len(text) <= 80


@pytest.mark.asyncio
async def test_fetch_public_web_pages_returns_page_evidence(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><title>Alternatives</title><body><main>Alpha and Beta compete in AI search.</main></body></html>",
            request=request,
        )

    transport = httpx.MockTransport(handler)
    results = [
        SearchResult(
            query="AI search alternatives",
            title="AI Search Alternatives",
            url="https://example.com/alternatives",
            snippet="A list of AI search vendors.",
        )
    ]

    pages = await fetch_public_web_pages(results, limit=2, transport=transport)

    assert len(pages) == 1
    assert pages[0].url == "https://example.com/alternatives"
    assert pages[0].search_title == "AI Search Alternatives"
    assert pages[0].page_title == "Alternatives"
    assert "Alpha and Beta compete" in pages[0].text
    assert pages[0].error is None


def test_rerank_search_results_returns_empty_for_empty_input():
    assert rerank_search_results("test", []) == []


def test_rerank_search_results_fallback_when_no_model(monkeypatch):
    """Confirm no crash when sentence-transformers is not installed."""
    monkeypatch.setattr("services.web_search._get_reranker", lambda: None)
    results = [
        SearchResult(query="ai", title="A", url="https://a.com", snippet="snippet a"),
        SearchResult(query="ai", title="B", url="https://b.com", snippet="snippet b"),
    ]
    out = rerank_search_results("ai", results)
    assert len(out) == 2
    # falls back to original order
    assert out[0].url == "https://a.com"
    assert out[1].url == "https://b.com"


def test_rerank_search_results_top_k(monkeypatch):
    monkeypatch.setattr("services.web_search._get_reranker", lambda: None)
    results = [
        SearchResult(query="ai", title="A", url="https://a.com", snippet="a"),
        SearchResult(query="ai", title="B", url="https://b.com", snippet="b"),
        SearchResult(query="ai", title="C", url="https://c.com", snippet="c"),
    ]
    out = rerank_search_results("ai", results, top_k=2)
    assert len(out) == 2
