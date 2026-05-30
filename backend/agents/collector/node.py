import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from services.privacy import contains_pii, redact_pii
from services.web_search import PageEvidence, SearchResult, fetch_public_web_pages, search_public_web

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
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name)
    if api_key and ChatOpenAI is not None
    else None
)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def collector_node(state: AgentState, on_progress: ProgressCallback | None = None):
    context = state.get("task_context", {})
    competitors = [str(item) for item in context.get("competitors", []) if str(item).strip()]
    schema_fields = flatten_schema_fields(state.get("dynamic_schema", {}))
    scope_field_ids = {str(item) for item in context.get("collection_scope_field_ids", []) if str(item).strip()}
    if scope_field_ids:
        schema_fields = [field for field in schema_fields if str(field.get("id")) in scope_field_ids]
    task_id = state.get("task_id", "task")

    results: list[dict[str, Any]] = []
    total = len(competitors) * len(schema_fields)
    completed = 0
    discovered_results = 0
    for competitor in competitors:
        for field in schema_fields:
            query = build_collection_query(competitor, field)
            try:
                search_results = await search_public_web(query, limit=3)
                discovered_results += len(search_results)
                
                # Fetch actual web pages for deeper scraping
                pages = await fetch_public_web_pages(search_results, limit=2)
                
                callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
                material = await build_material_from_pages(task_id, competitor, field, query, pages, callbacks=callbacks)
            except Exception as exc:
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
                "completed": completed,
                "total": total,
                "discovered_results": discovered_results,
                "degraded_reason": material.get("degraded_reason"),
            }
            if on_progress:
                import asyncio
                if asyncio.iscoroutinefunction(on_progress):
                    await on_progress(payload)
                else:
                    on_progress(payload)
            else:
                from services.events import event_broker
                await event_broker.publish(task_id, "collector_log", payload)

    state["raw_materials"] = results
    state["source_ids"] = [item["id"] for item in results]
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
) -> dict[str, Any]:
    accepted = next((item for item in pages if item.text or item.snippet), None)
    if not accepted:
        return build_degraded_material(task_id, competitor, field, query, "no_search_evidence_found")

    excerpt = (accepted.text or accepted.snippet or "").strip()[:4000]
    extracted_value = excerpt

    # Perform information extraction using LLM if available
    if llm is not None and excerpt and ChatPromptTemplate is not None:
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                PROMPT_CONFIG = yaml.safe_load(f)
                
            skill_type = field.get("skill_category") or "general"
            skills_config = PROMPT_CONFIG.get("collector_skills", {})
            prompt_config = skills_config.get(skill_type, skills_config.get("general", {}))

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
            if ans and ans != "NOT_FOUND":
                extracted_value = ans
        except Exception:
            pass

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
        "access_status": "failed",
        "validation_status": "degraded",
        "trust_status": "degraded",
        "retry_count": 1,
        "degraded_reason": reason,
        "pii_redacted": False,
    }


def stable_source_id(task_id: str, competitor: str, field_id: str, value: str) -> str:
    return f"src_{uuid.uuid5(uuid.NAMESPACE_URL, f'{task_id}:{competitor}:{field_id}:{value}').hex[:12]}"
