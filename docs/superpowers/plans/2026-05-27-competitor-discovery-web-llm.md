# Competitor Discovery Web LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace primitive competitor guessing with evidence-backed discovery that searches the web, fetches page content, and requires an LLM to identify competitors.

**Architecture:** `services.web_search` owns search parsing and public page fetching. `agents.orchestrator` owns discovery orchestration, LLM prompting, JSON parsing, normalization, and failure semantics. `api.routers.discovery` maps discovery failures to HTTP 503 while preserving the frontend response shape.

**Tech Stack:** Python 3.12, FastAPI, httpx, BeautifulSoup, LangChain OpenAI-compatible chat client, pytest, pytest-asyncio.

---

## File Structure

- Modify `backend/services/web_search.py`: add `PageEvidence`, HTML text extraction, and async page fetch helpers.
- Modify `backend/agents/orchestrator.py`: add `CompetitorDiscoveryUnavailable`, candidate parsing, evidence prompt construction, and LLM-required discovery flow.
- Modify `backend/api/routers/discovery.py`: catch discovery unavailability and return 503.
- Modify `backend/main.py`: keep legacy exported `get_competitor_recommendations()` behavior aligned with router tests.
- Modify `backend/tests/unit/test_web_search.py`: test page text extraction and fetch behavior.
- Modify `backend/tests/unit/test_orchestrator_competitor_discovery.py`: test LLM-required, evidence-driven discovery.
- Modify `backend/tests/contract/test_frontend_action_api.py`: test 503 mapping.

---

### Task 1: Add Web Page Evidence Extraction

**Files:**
- Modify: `backend/tests/unit/test_web_search.py`
- Modify: `backend/services/web_search.py`

- [ ] **Step 1: Write failing tests**

Add these tests to `backend/tests/unit/test_web_search.py`:

```python
import httpx
import pytest

from services.web_search import SearchResult, extract_page_text, fetch_public_web_pages, parse_duckduckgo_results


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
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest backend/tests/unit/test_web_search.py -v`

Expected: FAIL because `PageEvidence`, `extract_page_text`, and `fetch_public_web_pages` do not exist.

- [ ] **Step 3: Implement minimal web evidence helpers**

In `backend/services/web_search.py`, add:

```python
@dataclass(slots=True)
class PageEvidence:
    query: str
    search_title: str
    url: str
    snippet: str
    page_title: str
    text: str
    error: str | None = None


def extract_page_text(html: str, max_chars: int = 4000) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


async def fetch_public_web_pages(
    results: list[SearchResult],
    limit: int = 5,
    timeout: float = 12.0,
    max_chars: int = 4000,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[PageEvidence]:
    pages: list[PageEvidence] = []
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, transport=transport) as client:
        for result in results[:limit]:
            try:
                response = await client.get(result.url, headers=headers)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                title_node = soup.select_one("title")
                pages.append(
                    PageEvidence(
                        query=result.query,
                        search_title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        page_title=title_node.get_text(" ", strip=True) if title_node else "",
                        text=extract_page_text(response.text, max_chars=max_chars),
                    )
                )
            except httpx.HTTPError as exc:
                pages.append(
                    PageEvidence(
                        query=result.query,
                        search_title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        page_title="",
                        text="",
                        error=exc.__class__.__name__,
                    )
                )
    return pages
```

Also add `import re` near the top.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest backend/tests/unit/test_web_search.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/web_search.py backend/tests/unit/test_web_search.py
git commit -m "feat: fetch public page evidence"
```

---

### Task 2: Make Competitor Discovery LLM-Required and Evidence-Driven

**Files:**
- Modify: `backend/tests/unit/test_orchestrator_competitor_discovery.py`
- Modify: `backend/agents/orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add these tests:

```python
import pytest


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
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest backend/tests/unit/test_orchestrator_competitor_discovery.py -v`

Expected: FAIL because the exception, page fetch import, and evidence-driven flow do not exist.

- [ ] **Step 3: Implement discovery flow**

In `backend/agents/orchestrator.py`:

- import `PageEvidence` and `fetch_public_web_pages`
- add `CompetitorDiscoveryUnavailable`
- add `CompetitorCandidate`
- add helpers for query building, URL dedupe, prompt building, and candidate parsing
- replace `discover_competitors()` with the LLM-required workflow

Core code shape:

```python
class CompetitorDiscoveryUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class CompetitorCandidate:
    name: str
    reason: str
    source_urls: list[str]
    confidence: float = 0.0
```

```python
async def discover_competitors(domain: str) -> list[str]:
    candidates = await discover_competitor_candidates(domain)
    return [candidate.name for candidate in candidates[:3]]
```

```python
async def discover_competitor_candidates(domain: str) -> list[CompetitorCandidate]:
    domain = str(domain or "").strip()
    if not domain:
        return []
    if llm is None:
        raise CompetitorDiscoveryUnavailable("LLM is required for competitor discovery")

    results = []
    for query in build_competitor_search_queries(domain):
        try:
            results.extend(await search_public_web(query, limit=4))
        except Exception:
            continue

    deduped_results = dedupe_search_results_by_url(results)
    pages = await fetch_public_web_pages(deduped_results, limit=6)
    usable_pages = [page for page in pages if page.text or page.snippet]
    if not usable_pages:
        raise CompetitorDiscoveryUnavailable("No usable web evidence found for competitor discovery")

    prompt = build_competitor_discovery_prompt(domain, usable_pages)
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        candidates = parse_competitor_candidates(str(response.content))
    except Exception as exc:
        raise CompetitorDiscoveryUnavailable("LLM competitor discovery failed") from exc

    if not candidates:
        raise CompetitorDiscoveryUnavailable("No competitors found in model output")
    return candidates[:3]
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest backend/tests/unit/test_orchestrator_competitor_discovery.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/orchestrator.py backend/tests/unit/test_orchestrator_competitor_discovery.py
git commit -m "feat: discover competitors from web evidence"
```

---

### Task 3: Map Discovery Failures to HTTP 503

**Files:**
- Modify: `backend/tests/contract/test_frontend_action_api.py`
- Modify: `backend/api/routers/discovery.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing route test**

Add this test:

```python
import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_competitor_recommendations_returns_503_when_discovery_unavailable(monkeypatch):
    async def fake_discover_competitors(domain: str):
        raise main.CompetitorDiscoveryUnavailable("LLM is required for competitor discovery")

    monkeypatch.setattr(main, "discover_competitors", fake_discover_competitors)

    with pytest.raises(HTTPException) as exc:
        await main.get_competitor_recommendations(domain="AI search tools", existing=[])

    assert exc.value.status_code == 503
    assert "LLM is required" in exc.value.detail
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest backend/tests/contract/test_frontend_action_api.py -v`

Expected: FAIL because the route does not catch `CompetitorDiscoveryUnavailable`.

- [ ] **Step 3: Implement route mapping**

In both `backend/api/routers/discovery.py` and the legacy function in
`backend/main.py`, import `CompetitorDiscoveryUnavailable` and wrap discovery:

```python
try:
    discovered = await discover_competitors(normalized_domain)
except CompetitorDiscoveryUnavailable as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from exc
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest backend/tests/contract/test_frontend_action_api.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api/routers/discovery.py backend/main.py backend/tests/contract/test_frontend_action_api.py
git commit -m "fix: report competitor discovery unavailability"
```

---

### Task 4: Run Focused Regression

**Files:**
- Verify only.

- [ ] **Step 1: Run focused unit and contract tests**

Run:

```bash
python -m pytest backend/tests/unit/test_web_search.py backend/tests/unit/test_orchestrator_competitor_discovery.py backend/tests/contract/test_frontend_action_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader backend test set if environment allows**

Run:

```bash
python -m pytest backend/tests/unit backend/tests/contract -v
```

Expected: PASS, or document any unrelated environment/database failures.

- [ ] **Step 3: Check git status**

Run: `git status --short -uno`

Expected: no tracked changes after commits.

---

## Self-Review

- Spec coverage: LLM-required behavior is covered in Task 2 and Task 3. Search, page fetch, cleaned evidence, bounded fetch, and partial page failure support are covered in Task 1 and Task 2. Existing route response shape is preserved in Task 3.
- Completion-marker scan: no unresolved markers remain.
- Type consistency: `SearchResult`, `PageEvidence`, `CompetitorCandidate`, and `CompetitorDiscoveryUnavailable` are introduced before downstream usage.
