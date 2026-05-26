from dataclasses import dataclass
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup


@dataclass(slots=True)
class SearchResult:
    query: str
    title: str
    url: str
    snippet: str


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
