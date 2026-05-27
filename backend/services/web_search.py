from dataclasses import dataclass
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup


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
