import asyncio
import os
from dataclasses import dataclass
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

# ── Tavily client (optional, no crash if key is missing) ──
_tavily_client = None
_tavily_api_key = os.environ.get("TAVILY_API_KEY")
if _tavily_api_key:
    try:
        from tavily import TavilyClient

        _tavily_client = TavilyClient(api_key=_tavily_api_key)
    except ImportError:
        pass

@dataclass(slots=True)
class SearchResult:
    query: str
    title: str
    url: str
    snippet: str


@dataclass(slots=True)
class PageEvidence:
    query: str
    search_title: str
    url: str
    snippet: str
    page_title: str
    text: str
    error: str | None = None


def parse_duckduckgo_results(html: str, query: str, limit: int = 5) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    for node in soup.select(".result"):
        link = node.select_one(".result__a")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        href = _normalize_duckduckgo_href(link.get("href", ""))
        snippet_node = node.select_one(".result__snippet")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
        if title and href:
            results.append(SearchResult(query=query, title=title, url=href, snippet=snippet))
        if len(results) >= limit:
            break
    return results


async def search_public_web(query: str, limit: int = 5, timeout: float = 15.0) -> list[SearchResult]:
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(search_url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    return parse_duckduckgo_results(response.text, query=query, limit=limit)


def extract_page_text(html: str, max_chars: int = 50000) -> str:
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
    max_chars: int = 50000,
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


def _normalize_duckduckgo_href(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target)
    return href


# ── Tavily search ──

async def search_tavily(query: str, limit: int = 5) -> list[SearchResult]:
    """Search via Tavily API. Returns empty list if Tavily is unavailable."""
    if _tavily_client is None:
        return []
    loop = asyncio.get_running_loop()

    def _sync_search():
        return _tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=limit,
        )

    try:
        response = await loop.run_in_executor(None, _sync_search)
        results = response if isinstance(response, dict) else {}
        return [
            SearchResult(
                query=query,
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in results.get("results", [])
            if r.get("url")
        ]
    except Exception:
        return []


# ── Multi-engine search (Tavily + DuckDuckGo) ──

async def search_multi_engine(
    query: str, limit: int = 5, timeout: float = 15.0
) -> list[SearchResult]:
    """Run Tavily and DuckDuckGo in parallel, deduplicate by URL.

    Priority: Tavily → DuckDuckGo
    """
    ddg_coro = search_public_web(query, limit=limit, timeout=timeout)
    tavily_coro = search_tavily(query, limit=limit)

    ddg_results, tavily_results = await asyncio.gather(
        ddg_coro, tavily_coro, return_exceptions=True
    )

    if isinstance(ddg_results, Exception):
        ddg_results = []
    if isinstance(tavily_results, Exception):
        tavily_results = []

    seen_urls: set[str] = set()
    merged: list[SearchResult] = []

    for r in tavily_results + ddg_results:
        normalized = r.url.rstrip("/").lower()
        if normalized in seen_urls or not r.url:
            continue
        seen_urls.add(normalized)
        merged.append(r)
        if len(merged) >= limit:
            break

    return merged[:limit]
