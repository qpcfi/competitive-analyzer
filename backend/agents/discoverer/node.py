import json
import os
import yaml
from collections.abc import Iterable
from dataclasses import dataclass

try:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatPromptTemplate = None
    ChatOpenAI = None

from dotenv import load_dotenv
load_dotenv()

from ..state import AgentState
from core.callbacks import RealtimeDebugCallbackHandler

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, timeout=90)
    if api_key and ChatOpenAI is not None
    else None
)

@dataclass(slots=True)
class CompetitorCandidate:
    name: str
    reason: str
    source_urls: list[str]
    confidence: float = 0.0

async def discoverer_node(state: AgentState):
    context = state.get("task_context", {})
    task_id = state.get("task_id")
    domain = str(context.get("domain") or "").strip()
    user_competitors = normalize_competitor_names(context.get("competitors", []))

    if not user_competitors:
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        discovered_candidates, market_context = await recommend_competitors(domain, user_competitors, callbacks=callbacks)
        context["market_context"] = market_context
        discovered = [c.name for c in discovered_candidates]
        seed_competitors = merge_competitors(user_competitors, discovered)
        if len(seed_competitors) < 3:
            seed_competitors = merge_competitors(seed_competitors, fallback_competitors(domain, 3 - len(seed_competitors)))
        context["competitors"] = seed_competitors[:5]
    else:
        context["competitors"] = user_competitors[:5]

    state["task_context"] = context
    return state


def merge_competitors(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    seen = set()
    for group in groups:
        for name in normalize_competitor_names(group):
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(name)
    return merged


def fallback_competitors(domain: str, count: int) -> list[str]:
    base = domain or "Market"
    suffixes = ["Leader", "Challenger", "Specialist", "Enterprise", "Cloud"]
    return [f"{base} {suffix}" for suffix in suffixes[: max(count, 0)]]


async def recommend_competitors(domain: str, existing: Iterable[str] = (), callbacks=None) -> tuple[list[CompetitorCandidate], str]:
    existing_names = {name.lower() for name in normalize_competitor_names(existing)}
    candidates: list[CompetitorCandidate] = []
    evidence = ""

    if llm is not None and ChatPromptTemplate is not None:
        from services.web_search import search_public_web, fetch_public_web_pages
        from ..shared.router import route_sources
        from ..shared.crawler import crawl_urls
        
        evidence_blocks = []
        snippets = []
        
        try:
            # 1. Try to fetch from curated domain-level sources (e.g. ranking lists)
            routed_sources = await route_sources(domain, "")
            routed_urls = [src["url"] for src in routed_sources if "url" in src]
            
            if routed_urls:
                cached_markdowns = await crawl_urls(routed_urls)
                for index, (url, md) in enumerate(cached_markdowns.items(), start=1):
                    excerpt = md.strip()[:6000] # Cap size to avoid context overflow
                    evidence_blocks.append(
                        "\n".join([
                            f"Curated Source {index}",
                            f"URL: {url}",
                            f"Page excerpt: {excerpt}",
                        ])
                    )
            
            # 2. Fallback or augment with DuckDuckGo search if curated evidence is insufficient
            if not evidence_blocks:
                results = await search_public_web(f"{domain} top competitors alternatives", limit=5)
                snippets = [r.snippet for r in results if r.snippet]
                pages = await fetch_public_web_pages(results, limit=5)
                for index, page in enumerate(pages, start=1):
                    excerpt = (page.text or page.snippet or "").strip()[:2500]
                    evidence_blocks.append(
                        "\n".join(
                            [
                                f"Search Source {index}",
                                f"URL: {page.url}",
                                f"Search title: {page.search_title}",
                                f"Page title: {page.page_title}",
                                f"Search snippet: {page.snippet}",
                                f"Page excerpt: {excerpt}",
                            ]
                        )
                    )
        except Exception as e:
            import logging
            logging.error(f"Data gathering failed in recommend_competitors: {e}")
            
        evidence = "\n\n".join(evidence_blocks)
        
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                PROMPT_CONFIG = yaml.safe_load(f)

            prompt_template = ChatPromptTemplate.from_messages([
                ("system", PROMPT_CONFIG["discoverer_agent"]["system_prompt"]),
                ("human", PROMPT_CONFIG["discoverer_agent"]["human_template"])
            ])
            
            chain = prompt_template | llm
            
            config = {"callbacks": callbacks} if callbacks else None
            res = await chain.ainvoke({
                "domain": domain,
                "evidence": evidence
            }, config=config)
            
            parsed = json.loads(extract_json_array(str(res.content)))
            parsed_candidates = parsed if isinstance(parsed, list) else []
            for item in parsed_candidates:
                names = normalize_competitor_names([item.get("name", "")])
                if not names:
                    continue
                name = names[0]
                candidates.append(
                    CompetitorCandidate(
                        name=name,
                        reason=str(item.get("reason") or "").strip(),
                        source_urls=[str(url).strip() for url in item.get("source_urls", []) if str(url).strip()],
                        confidence=float(item.get("confidence") or 0.0),
                    )
                )
        except Exception as e:
            import logging
            logging.error(f"LLM extraction failed in recommend_competitors: {e}")
            raise RuntimeError(f"大模型在提取竞品时发生异常: {e}\n(证据片段或网络可能存在问题，或者大模型未能按照指定格式输出。)") from e

    filtered: list[CompetitorCandidate] = []
    seen = set(existing_names)
    for candidate in candidates:
        lowered = candidate.name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        filtered.append(candidate)
        
    if filtered:
        return filtered[:5], evidence

    return [
        CompetitorCandidate(name=name, reason="Generated fallback candidate from the analysis domain.", source_urls=[], confidence=0.2)
        for name in fallback_competitors(domain, 3)
        if name.lower() not in existing_names
    ], evidence

def extract_json_array(content: str) -> str:
    start = content.find("[")
    end = content.rfind("]")
    if start >= 0 and end > start:
        return content[start : end + 1]
    return content

def normalize_competitor_names(values: Iterable[object]) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for value in values:
        name = str(value).strip().strip('"').strip("'")
        if not name or len(name) > 80:
            continue
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(name)
    return normalized
