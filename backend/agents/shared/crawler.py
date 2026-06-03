from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
import sys
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

async def crawl_urls(urls: list[str]) -> dict[str, str]:
    """
    Crawls a list of URLs and returns a dictionary mapping the URL to its Markdown content.
    Uses Blackboard pattern: checks global memory cache first, and falls back to Crawl4ai if missing.
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

    # 2. Fallback: Crawl missing URLs
    if urls_to_crawl:
        def _run_crawler_in_thread(urls):
            import asyncio
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                
            async def _do_crawl():
                thread_results = {}
                browser_config = BrowserConfig(
                    headless=True,
                    verbose=False,
                )
                
                run_config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS, # Blackboard handles the cache
                    word_count_threshold=10,
                    exclude_external_links=True,
                    remove_overlay_elements=True,
                )

                async with AsyncWebCrawler(config=browser_config) as crawler:
                    for url in urls:
                        try:
                            result = await crawler.arun(url=url, config=run_config)
                            if result.success and result.markdown:
                                thread_results[url] = result.markdown
                        except Exception as e:
                            print(f"Failed to crawl {url}: {e}")
                return thread_results
                
            return asyncio.run(_do_crawl())

        import asyncio
        loop = asyncio.get_running_loop()
        crawled_results = await loop.run_in_executor(None, _run_crawler_in_thread, urls_to_crawl)
        
        for url, md in crawled_results.items():
            _GLOBAL_CACHE.set(url, md)
            results[url] = md
                
    return results
