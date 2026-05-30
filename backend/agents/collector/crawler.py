from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from typing import Optional

async def crawl_urls(urls: list[str]) -> dict[str, str]:
    """
    Crawls a list of URLs and returns a dictionary mapping the URL to its Markdown content.
    Uses Crawl4ai for asynchronous, LLM-friendly extraction.
    """
    if not urls:
        return {}

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
    )
    
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS, # To ensure we get fresh data, but BYPASS can be slow. Since we cache in memory per task run, BYPASS is fine here.
        word_count_threshold=10,
        exclude_external_links=True,
        remove_overlay_elements=True,
    )

    results = {}
    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Crawl concurrently
        # However, for simplicity and stability, we'll await them sequentially or use a simple gather
        # crawl4ai arun supports sequential directly in a loop
        for url in urls:
            try:
                result = await crawler.arun(url=url, config=run_config)
                if result.success and result.markdown:
                    results[url] = result.markdown
            except Exception as e:
                print(f"Failed to crawl {url}: {e}")
                
    return results
