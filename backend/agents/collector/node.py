import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from services.privacy import contains_pii, redact_pii
from services.web_search import PageEvidence, SearchResult, search_multi_engine, rerank_search_results
from .retrieval import process_page

try:
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    HumanMessage = None
    ChatOpenAI = None
    ChatPromptTemplate = None

import yaml
from ..state import AgentState
from core.callbacks import RealtimeDebugCallbackHandler

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, timeout=30)
    if api_key and ChatOpenAI is not None
    else None
)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


import asyncio
from services.events import event_broker
from ..shared.router import route_sources, auto_save_to_knowledge_base
from ..shared.crawler import crawl_urls

async def run_collector_for_skill(state: AgentState, skill_filter: str, on_progress: ProgressCallback | None = None):
    context = state.get("task_context", {})
    domain = context.get("domain", "unknown domain")
    competitors = [str(item) for item in context.get("competitors", []) if str(item).strip()]
    schema_fields = flatten_schema_fields(state.get("dynamic_schema", {}))
    
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
        routed_urls = [src["url"] for src in routed_sources if "url" in src]
        
        # Crawl and cache Markdown
        cached_markdowns = await crawl_urls(routed_urls)
        cached_hits = sum(1 for v in cached_markdowns.values() if v)
        if routed_sources:
            await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] {competitor}: {cached_hits}/{len(routed_sources)} knowledge_base URLs crawled successfully"})
        else:
            await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] {competitor}: no knowledge_base URLs configured, will skip to DuckDuckGo"})
        
        for field in schema_fields:
            query = build_collection_query(competitor, field)
            material = None
            callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
            
            # 1. Try to extract from curated URLs first
            for src in routed_sources:
                url = src["url"]
                markdown_content = cached_markdowns.get(url)
                if not markdown_content:
                    continue

                # Create a pseudo PageEvidence for the LLM extraction
                pseudo_page = PageEvidence(
                    query=query, search_title=src.get("name", ""), url=url, snippet="", page_title="", text=markdown_content
                )

                extracted_material = await build_material_from_pages(
                    task_id, competitor, field, query, [pseudo_page], callbacks=callbacks, strict_not_found=True, source_stage="curated"
                )

                if extracted_material and extracted_material.get("extracted_value", {}).get("value") != "NOT_FOUND":
                    material = extracted_material
                    break  # Found it!
                else:
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[curated] NOT_FOUND: {src.get('name', url)} → {query}"})
                    
            # 2. Fallback to DuckDuckGo search + Crawl4ai fetching
            if not material:
                await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[fallback] curated sources exhausted for {field.get('name') or field.get('id')}, searching DuckDuckGo..."})
                try:
                    search_results = await search_multi_engine(query, limit=10)
                    discovered_results += len(search_results)
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[search] Multi-engine returned {len(search_results)} results for: {query}"})
                    search_results = rerank_search_results(query, search_results)
                    await event_broker.publish(task_id, "debug_log", {"agent": agent_name, "event": "debug", "message": f"[search] Reranked results for: {query}"})

                    # Use Crawl4ai to fetch pages as clean Markdown (JS rendering, anti-bot)
                    search_urls = [r.url for r in search_results[:3]]
                    crawled_markdowns = await crawl_urls(search_urls)

                    for sr in search_results:
                        md = crawled_markdowns.get(sr.url)
                        if not md:
                            continue
                        pseudo_page = PageEvidence(
                            query=query, search_title=sr.title, url=sr.url,
                            snippet=sr.snippet, page_title="", text=md,
                        )
                        material = await build_material_from_pages(
                            task_id, competitor, field, query, [pseudo_page],
                            callbacks=callbacks, strict_not_found=False, source_stage="search",
                        )
                        if material and material.get("validation_status") != "degraded":
                            # Fire-and-forget: save discovered URL to knowledge_base
                            asyncio.ensure_future(
                                auto_save_to_knowledge_base(
                                    url=sr.url,
                                    competitor=competitor,
                                    skill=skill_filter,
                                    field_name=field.get("name") or field.get("id"),
                                )
                            )
                            break

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
            if on_progress:
                if asyncio.iscoroutinefunction(on_progress):
                    await on_progress(payload)
                else:
                    on_progress(payload)
            else:
                await event_broker.publish(task_id, "collector_log", payload)

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
            fields.append({**field, "id": field_id, "group": group_name})
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
    accepted = next((item for item in pages if item.text or item.snippet), None)
    if not accepted:
        if strict_not_found:
            return None
        return build_degraded_material(task_id, competitor, field, query, "no_search_evidence_found")

    _text = (accepted.text or accepted.snippet or "").strip()
    excerpt = process_page(_text, query, max_chars=12000)
    extracted_value = excerpt
    is_not_found = False

    # Perform information extraction using LLM if available
    if llm is not None and excerpt and ChatPromptTemplate is not None:
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
            res = await chain.ainvoke({
                "competitor": competitor,
                "field_name": field.get("name") or field.get("id"),
                "field_reason": field.get("reason") or "N/A",
                "excerpt": excerpt
            }, config=config)
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
        "id": stable_source_id(task_id, competitor, field.get("id", ""), accepted.url),
        "competitor": competitor,
        "schema_field_id": field.get("id"),
        "schema_field_name": field.get("name") or field.get("id"),
        "source_url": accepted.url,
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
