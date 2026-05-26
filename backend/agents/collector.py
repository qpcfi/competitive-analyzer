import uuid
from typing import Any

from services.privacy import contains_pii, redact_pii
from services.web_search import SearchResult, search_public_web

from .state import AgentState


async def collector_node(state: AgentState):
    context = state.get("task_context", {})
    competitors = [str(item) for item in context.get("competitors", []) if str(item).strip()]
    schema_fields = flatten_schema_fields(state.get("dynamic_schema", {}))
    task_id = state.get("task_id", "task")

    results: list[dict[str, Any]] = []
    for competitor in competitors:
        for field in schema_fields:
            query = build_collection_query(competitor, field)
            try:
                search_results = await search_public_web(query, limit=3)
                material = build_material_from_search_result(task_id, competitor, field, query, search_results)
            except Exception as exc:
                material = build_degraded_material(task_id, competitor, field, query, f"{exc.__class__.__name__}:{exc}")
            results.append(material)

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


def build_material_from_search_result(
    task_id: str,
    competitor: str,
    field: dict[str, Any],
    query: str,
    search_results: list[SearchResult],
) -> dict[str, Any]:
    accepted = next((item for item in search_results if item.snippet or item.title), None)
    if not accepted:
        return build_degraded_material(task_id, competitor, field, query, "no_search_evidence_found")

    quote = " ".join(part for part in [accepted.title, accepted.snippet] if part)
    pii_redacted = contains_pii(quote)
    redacted = redact_pii(quote)
    return {
        "id": stable_source_id(task_id, competitor, field.get("id", ""), accepted.url),
        "competitor": competitor,
        "schema_field_id": field.get("id"),
        "schema_field_name": field.get("name") or field.get("id"),
        "source_url": accepted.url,
        "source_type": "search_result",
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
