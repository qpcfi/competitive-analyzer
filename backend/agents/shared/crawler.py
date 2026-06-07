from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
import sys
import asyncio
import httpx
from bs4 import BeautifulSoup
from collections import OrderedDict
from typing import Optional

class BlackboardCache:
    """
    In-memory LRU Cache for the Blackboard pattern.
    Default max_size=2000 is enough to hold 2000 web pages (approx 40MB),
    preventing both memory leaks and redundant Crawl4ai calls.
    """
    def __init__(self, max_size: int = 2000):
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.max_size = max_size

    def get(self, key: str) -> str | None:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def set(self, key: str, value: str):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

# Singleton global cache
_GLOBAL_CACHE = BlackboardCache()

# ── Retry strategies ──────────────────────────────────────────────────────────
# Each retry attempt tries a different strategy to maximise success rate.
_RETRY_STRATEGIES = [
    # 1. Fast default
    {"word_count_threshold": 10, "timeout": 15},
    # 2. Slower with longer timeout
    {"word_count_threshold": 5,  "timeout": 30},
    # 3. Full page, no threshold
    {"word_count_threshold": 3,  "timeout": 45},
]


async def _crawl_with_httpx_fallback(url: str, timeout: float = 15) -> str | None:
    """Lightweight httpx + BeautifulSoup fallback when Crawl4ai fails."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        text = soup.get_text(" ", strip=True)
        import re
        text = re.sub(r"\s+", " ", text).strip()
        return text[:50000]
    except Exception:
        return None


async def _crawl_with_retry(
    url: str,
    attempt: int,
    strategy: dict,
    crawler: AsyncWebCrawler,
) -> str | None:
    """Single Crawl4ai attempt with the given strategy."""
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=strategy.get("word_count_threshold", 10),
        exclude_external_links=True,
        remove_overlay_elements=True,
    )
    try:
        result = await crawler.arun(url=url, config=config)
        if result.success and result.markdown:
            return result.markdown
    except Exception as e:
        print(f"[crawler] attempt {attempt + 1} failed for {url}: {e}")
    return None


async def crawl_urls(urls: list[str], max_retries: int = 2) -> dict[str, str]:
    """
    Crawls a list of URLs and returns a dictionary mapping the URL to its Markdown content.
    Uses Blackboard pattern: checks global memory cache first, and falls back to Crawl4ai if missing.
    Includes retry with exponential backoff and multiple crawling strategies.
    This safely supports Graph checkpoint resumes (it will naturally re-crawl if RAM was wiped).
    """
    if not urls:
        return {}

    results = {}
    urls_to_crawl = []

    # 1. Blackboard Check: Fast Memory Access
    for url in urls:
        cached_md = _GLOBAL_CACHE.get(url)
        if cached_md:
            results[url] = cached_md
        else:
            urls_to_crawl.append(url)

    # 2. Crawl missing URLs with retry
    if urls_to_crawl:
        def _run_crawler_in_thread(urls):
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

            async def _do_crawl():
                thread_results = {}
                browser_config = BrowserConfig(headless=True, verbose=False)

                async with AsyncWebCrawler(config=browser_config) as crawler:
                    for url in urls:
                        md = None

                        # Try Crawl4ai with retry + different strategies
                        for attempt in range(max_retries + 1):
                            strategy_idx = min(attempt, len(_RETRY_STRATEGIES) - 1)
                            strategy = _RETRY_STRATEGIES[strategy_idx]

                            md = await _crawl_with_retry(url, attempt, strategy, crawler)
                            if md:
                                break

                            # Exponential backoff before retry
                            if attempt < max_retries:
                                delay = 2 ** attempt
                                await asyncio.sleep(delay)

                        # Fallback: try httpx + BeautifulSoup if Crawl4ai failed
                        if not md:
                            md = await _crawl_with_httpx_fallback(url)

                        if md:
                            thread_results[url] = md

                return thread_results

            return asyncio.run(_do_crawl())

        loop = asyncio.get_running_loop()
        crawled_results = await loop.run_in_executor(None, _run_crawler_in_thread, urls_to_crawl)

        for url, md in crawled_results.items():
            _GLOBAL_CACHE.set(url, md)
            results[url] = md

    return results
