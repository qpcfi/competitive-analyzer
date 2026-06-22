import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from services.privacy import contains_pii, redact_pii
from services.web_search import PageEvidence, SearchResult, search_multi_engine, rerank_search_results
from .retrieval import process_page

try:
    from langchain_core.messages import HumanMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    HumanMessage = None
    ChatPromptTemplate = None

import yaml
from ..state import AgentState
from ..shared.llm import create_chat_llm
from core.callbacks import RealtimeDebugCallbackHandler

llm = create_chat_llm(timeout=30)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


import asyncio
from services.events import event_broker
from ..shared.router import route_sources, auto_save_to_knowledge_base
from ..shared.crawler import crawl_urls


def normalize_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        path = parts.path.rstrip("/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))
    except Exception:
        return raw.rstrip("/")


async def publish_debug(task_id: str, payload: dict[str, Any], timeout: float = 5.0) -> None:
    try:
        await asyncio.wait_for(event_broker.publish(task_id, "debug_log", payload), timeout=timeout)
    except Exception:
        return


async def emit_progress(task_id: str, payload: dict[str, Any], on_progress: ProgressCallback | None = None, timeout: float = 5.0) -> None:
    try:
        if on_progress:
            result = on_progress(payload)
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout)
        else:
            await asyncio.wait_for(event_broker.publish(task_id, "collector_log", payload), timeout=timeout)
    except Exception:
        await publish_debug(task_id, {
            "agent": "Collector",
            "event": "warning",
            "message": f"Progress event timed out or failed for: {payload.get('query')}",
        })


async def crawl_urls_with_timeout(task_id: str, urls: list[str], label: str, timeout: float = 75.0) -> dict[str, str]:
    if not urls:
        return {}
    try:
        return await asyncio.wait_for(crawl_urls(urls), timeout=timeout)
    except asyncio.TimeoutError:
        await publish_debug(task_id, {
            "agent": "Collector",
            "event": "warning",
            "message": f"Crawl timed out for {label}; continuing with available fallback paths.",
            "output_json": {"url_count": len(urls), "timeout_seconds": timeout},
        })
        return {}
    except Exception as exc:
        await publish_debug(task_id, {
            "agent": "Collector",
            "event": "warning",
            "message": f"Crawl failed for {label}: {exc.__class__.__name__}",
        })
        return {}


async def run_collector_for_skill(state: AgentState, skill_filter: str, on_progress: ProgressCallback | None = None):
    context = state.get("task_context", {})
    domain = context.get("domain", "unknown domain")
    competitors = [str(item) for item in context.get("competitors", []) if str(item).strip()]
    schema_fields = flatten_schema_fields(state.get("dynamic_schema", {}))
    excluded_source_urls = {
        normalize_url(item)
        for item in context.get("excluded_source_urls", [])
        if normalize_url(item)
    }
    
    # Filter fields for this specific collector skill
    schema_fields = [f for f in schema_fields if (f.get("skill_category") or "company") == skill_filter]
    
    scope_field_ids = {str(item) for item in context.get("collection_scope_field_ids", []) if str(item).strip()}
    if scope_field_ids:
        schema_fields = [field for field in schema_fields if str(field.get("id")) in scope_field_ids]
    task_id = state.get("task_id", "task")
    
    agent_name = f"Collector ({skill_filter})"
    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "start", "message": f"Started collecting {skill_filter} dimensions..."})

    if not schema_fields:
        await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "end", "message": f"Skipped {skill_filter} dimensions (no fields).", "latency": 0.1})
        return {"raw_materials": [], "source_ids": []}

    results: list[dict[str, Any]] = []
    total = len(competitors) * len(schema_fields)
    completed = 0
    discovered_results = 0
    
    for competitor in competitors:
        # Route sources for this competitor, filtered by skill
        routed_sources = await route_sources(domain, competitor, skill_filter)
        routed_sources = [
            src for src in routed_sources
            if "url" in src and normalize_url(src.get("url")) not in excluded_source_urls
        ]
        routed_urls = [src["url"] for src in routed_sources if "url" in src]
        
        # Crawl and cache Markdown
        cached_markdowns = await crawl_urls_with_timeout(task_id, routed_urls, f"curated {competitor}/{skill_filter}")
        cached_hits = sum(1 for v in cached_markdowns.values() if v)
        if routed_sources:
            await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] {competitor}: {cached_hits}/{len(routed_sources)} knowledge_base URLs crawled successfully"})
        else:
            await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] {competitor}: no knowledge_base URLs configured, will skip to DuckDuckGo"})
        
        for field in schema_fields:
            query = build_collection_query(competitor, field)
            material = None
            callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
            
            # 1. Try to extract from curated URLs first — all sources merged
            curated_pages = [
                PageEvidence(
                    query=query, search_title=src.get("name", ""),
                    url=src["url"], snippet="", page_title="",
                    text=cached_markdowns[src["url"]],
                )
                for src in routed_sources
                if cached_markdowns.get(src["url"])
            ]
            if curated_pages:
                material = await build_material_from_pages(
                    task_id, competitor, field, query, curated_pages,
                    callbacks=callbacks, strict_not_found=True, source_stage="curated",
                )
                if material and material.get("extracted_value", {}).get("value") == "NOT_FOUND":
                    material = None  # fall through to search
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] All sources NOT_FOUND for: {query}"})
                else:
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] Extracted from {len(curated_pages)} source(s) for: {query}"})
                    
            # 2. Fallback to DuckDuckGo search + Crawl4ai fetching
            if not material:
                await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[fallback] curated sources exhausted for {field.get('name') or field.get('id')}, searching DuckDuckGo..."})
                try:
                    search_results = await search_multi_engine(query, limit=10)
                    discovered_results += len(search_results)
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[search] Multi-engine returned {len(search_results)} results for: {query}"})
                    search_results = rerank_search_results(query, search_results)
                    if excluded_source_urls:
                        before_filter_count = len(search_results)
                        search_results = [
                            result for result in search_results
                            if normalize_url(result.url) not in excluded_source_urls
                        ]
                        skipped_count = before_filter_count - len(search_results)
                        if skipped_count:
                            await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[search] Skipped {skipped_count} previously collected URL(s) for: {query}"})
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[search] Reranked results for: {query}"})

                    # Use Crawl4ai to fetch pages as clean Markdown (JS rendering, anti-bot)
                    search_urls = [r.url for r in search_results[:3]]
                    crawled_markdowns = await crawl_urls_with_timeout(task_id, search_urls, f"search {competitor}/{field.get('name') or field.get('id')}", timeout=60.0)

                    # Collect all crawled search pages
                    search_pages = [
                        PageEvidence(
                            query=query, search_title=sr.title, url=sr.url,
                            snippet=sr.snippet, page_title="", text=crawled_markdowns[sr.url],
                        )
                        for sr in search_results
                        if crawled_markdowns.get(sr.url)
                    ]
                    if search_pages:
                        material = await build_material_from_pages(
                            task_id, competitor, field, query, search_pages,
                            callbacks=callbacks, strict_not_found=False, source_stage="search",
                        )
                        if material and material.get("validation_status") != "degraded":
                            # Fire-and-forget: save ALL discovered URLs to knowledge_base
                            for p in search_pages:
                                asyncio.ensure_future(
                                    auto_save_to_knowledge_base(
                                        url=p.url,
                                        competitor=competitor,
                                        skill=skill_filter,
                                        field_name=field.get("name") or field.get("id"),
                                    )
                                )

                    if not material:
                        material = build_degraded_material(task_id, competitor, field, query, "crawl4ai_all_failed")
                except Exception as exc:
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[search] ERROR: {query} → {exc.__class__.__name__}: {exc}"})
                    material = build_degraded_material(task_id, competitor, field, query, f"{exc.__class__.__name__}:{exc}")
            
            results.append(material)
            completed += 1
            payload = {
                "query": query,
                "url": material.get("source_url") or "",
                "competitor": competitor,
                "schema_field_id": field.get("id"),
                "schema_field_name": field.get("name") or field.get("id"),
                "status": material.get("validation_status"),
                "access_status": material.get("access_status"),
                "source_stage": material.get("source_stage"),
                "completed": completed,
                "total": total,
                "discovered_results": discovered_results,
                "degraded_reason": material.get("degraded_reason"),
                "skill": skill_filter,
            }
            await emit_progress(task_id, payload, on_progress)

    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "end", "message": f"Completed collecting {skill_filter} dimensions.", "latency": 1.5})

    return {
        "raw_materials": results,
        "source_ids": [item["id"] for item in results]
    }

async def collector_company_node(state: AgentState): return await run_collector_for_skill(state, "company")
async def collector_product_node(state: AgentState): return await run_collector_for_skill(state, "product")
async def collector_business_node(state: AgentState): return await run_collector_for_skill(state, "business")
async def collector_technical_node(state: AgentState): return await run_collector_for_skill(state, "technical")

async def collector_node(state: AgentState, on_progress: ProgressCallback | None = None) -> AgentState:
    """Fallback monolithic collector for pipeline.py execution, now running skills in PARALLEL"""
    all_materials = list(state.get("raw_materials") or [])
    all_source_ids = list(state.get("source_ids") or [])
    
    import asyncio
    skills = ["company", "product", "business", "technical"]
    
    results = await asyncio.gather(*[
        run_collector_for_skill(state, skill, on_progress)
        for skill in skills
    ])
    
    for res in results:
        all_materials.extend(res.get("raw_materials", []))
        all_source_ids.extend(res.get("source_ids", []))
        
    state["raw_materials"] = all_materials
    state["source_ids"] = all_source_ids
    return state


def flatten_schema_fields(schema: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for group_name, group_fields in schema.items():
        if not isinstance(group_fields, list):
            continue
        for field in group_fields:
            if not isinstance(field, dict):
                continue
            field_id = field.get("id") or f"{group_name}.{field.get('name', 'field')}"
            fields.append({
                **field,
                "id": field_id,
                "group": group_name,
                "skill_category": field.get("skill_category") or "company",
            })
    return fields


def build_collection_query(competitor: str, field: dict[str, Any]) -> str:
    field_name = str(field.get("name") or field.get("id") or "").strip()
    source_hint = str(field.get("source") or "public web").strip()
    return f"{competitor} {field_name} {source_hint}".strip()


async def build_material_from_pages(
    task_id: str,
    competitor: str,
    field: dict[str, Any],
    query: str,
    pages: list[PageEvidence],
    callbacks: list = None,
    strict_not_found: bool = False,
    source_stage: str = "search",
) -> dict[str, Any] | None:
    # Collect excerpts from ALL valid pages, not just the first one
    excerpt_parts: list[tuple[PageEvidence, str]] = []
    for p in pages:
        text = (p.text or p.snippet or "").strip()
        if not text:
            continue
        excerpt = process_page(text, query, max_chars=4000)
        if excerpt:
            excerpt_parts.append((p, excerpt))

    if not excerpt_parts:
        if strict_not_found:
            return None
        return build_degraded_material(task_id, competitor, field, query, "no_search_evidence_found")

    # Merge multiple sources with separator
    primary_page = excerpt_parts[0][0]
    if len(excerpt_parts) > 1:
        parts = [f"[{p.url}]\n{ex}" for p, ex in excerpt_parts]
        merged_excerpt = "\n\n---\n\n".join(parts)
    else:
        merged_excerpt = excerpt_parts[0][1]

    extracted_value = merged_excerpt
    is_not_found = False

    # Perform information extraction using LLM if available
    if llm is not None and merged_excerpt and ChatPromptTemplate is not None:
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                PROMPT_CONFIG = yaml.safe_load(f)
                
            skill_type = field.get("skill_category") or "company"
            skills_config = PROMPT_CONFIG.get("collector_skills", {})
            prompt_config = skills_config.get(skill_type, skills_config.get("company", {}))

            if not prompt_config:
                raise ValueError("Missing prompt config")

            prompt_template = ChatPromptTemplate.from_messages([
                ("system", prompt_config.get("system_prompt", "You are an extractor.")),
                ("human", prompt_config.get("human_template", "{excerpt}"))
            ])
            chain = prompt_template | llm
            config = {"callbacks": callbacks} if callbacks else None
            res = await asyncio.wait_for(chain.ainvoke({
                "competitor": competitor,
                "field_name": field.get("name") or field.get("id"),
                "field_reason": field.get("reason") or "N/A",
                "excerpt": merged_excerpt
            }, config=config), timeout=45)
            ans = res.content.strip()
            if ans == "NOT_FOUND":
                is_not_found = True
            elif ans:
                extracted_value = ans
        except Exception:
            pass

    if is_not_found and strict_not_found:
        return None

    pii_redacted = contains_pii(extracted_value)
    redacted = redact_pii(extracted_value)
    
    return {
        "id": stable_source_id(task_id, competitor, field.get("id", ""), primary_page.url),
        "competitor": competitor,
        "schema_field_id": field.get("id"),
        "schema_field_name": field.get("name") or field.get("id"),
        "source_url": primary_page.url,
        "source_urls": [p.url for p, _ in excerpt_parts],
        "source_type": "web_page",
        "quote_text": redacted,
        "extracted_value": {"value": redacted, "query": query},
        "agent_node": "collector",
        "source_stage": source_stage,
        "skill": field.get("skill_category"),
        "access_status": "allowed",
        "validation_status": "accepted" if redacted else "degraded",
        "trust_status": "third_party",
        "retry_count": 0,
        "degraded_reason": None if redacted else "empty_content",
        "pii_redacted": pii_redacted,
    }


def build_degraded_material(task_id: str, competitor: str, field: dict[str, Any], query: str, reason: str) -> dict[str, Any]:
    return {
        "id": stable_source_id(task_id, competitor, field.get("id", ""), query),
        "competitor": competitor,
        "schema_field_id": field.get("id"),
        "schema_field_name": field.get("name") or field.get("id"),
        "source_url": "",
        "source_type": "search_result",
        "quote_text": "",
        "extracted_value": {"query": query, "error": reason},
        "agent_node": "collector",
        "source_stage": "degraded",
        "skill": field.get("skill_category"),
        "access_status": "failed",
        "validation_status": "degraded",
        "trust_status": "degraded",
        "retry_count": 1,
        "degraded_reason": reason,
        "pii_redacted": False,
    }


def stable_source_id(task_id: str, competitor: str, field_id: str, value: str) -> str:
    return f"src_{uuid.uuid5(uuid.NAMESPACE_URL, f'{task_id}:{competitor}:{field_id}:{value}').hex[:12]}"
