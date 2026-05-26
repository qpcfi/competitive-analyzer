import json
import os
from collections.abc import Iterable

try:
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
except ImportError:
    HumanMessage = None
    ChatOpenAI = None

from services.web_search import SearchResult, search_public_web

from .state import AgentState

api_key = os.environ.get("DEEPSEEK_API_KEY")
llm = (
    ChatOpenAI(api_key=api_key, base_url="https://api.deepseek.com", model="deepseek-v4-pro")
    if api_key and ChatOpenAI is not None
    else None
)


async def orchestrator_node(state: AgentState):
    context = state.get("task_context", {})
    if llm is None:
        schema = build_schema_from_context(context)
    else:
        prompt = f"""
        You are the Orchestrator for a competitive analyzer.
        Domain: {context.get('domain', 'Unknown')}
        Competitors: {context.get('competitors', [])}
        Generate a JSON schema of comparison dimensions for these competitors.
        Return ONLY valid JSON format.
        Example format:
        {{
          "Core Profile": [{{"name": "Product Name", "type": "text"}}]
        }}
        """
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        try:
            import re

            content = res.content
            match = re.search(r"\{.*\}", content, re.DOTALL)
            schema = json.loads(match.group(0) if match else content)
        except Exception:
            schema = build_schema_from_context(context)

    normalized_schema = ensure_schema_metadata(schema)
    state["dynamic_schema"] = await enrich_schema_with_public_evidence(normalized_schema, context)
    state["schema_version"] = int(state.get("schema_version", 0)) + 1
    return state


def build_schema_from_context(context: dict) -> dict:
    predefined = context.get("predefined_schema") or []
    base_fields = [
        {"name": "Product Name", "type": "text", "required": True, "source": "official"},
        {"name": "Company", "type": "text", "required": True, "source": "official"},
        {"name": "Pricing", "type": "text", "required": False, "source": "public_web"},
        {"name": "Key Capabilities", "type": "list", "required": False, "source": "public_web"},
    ]
    fields = []
    for item in predefined:
        if isinstance(item, dict) and item.get("name"):
            fields.append({**item, "origin": "user"})
    fields.extend({**field, "origin": "agent"} for field in base_fields)
    return {"Core Profile": fields}


def ensure_schema_metadata(schema: dict) -> dict:
    normalized = {}
    for group_name, fields in schema.items():
        if not isinstance(fields, list):
            continue
        normalized[group_name] = []
        for index, field in enumerate(fields):
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or f"field_{index + 1}")
            stable_group = str(group_name).strip().replace(" ", "_")
            stable_name = field_name.strip().replace(" ", "_")
            normalized[group_name].append(
                {
                    "id": field.get("id") or f"{stable_group}.{stable_name}",
                    "name": field_name,
                    "type": field.get("type") or "text",
                    "required": bool(field.get("required", True)),
                    "source": field.get("source") or "public_web",
                    "origin": field.get("origin") or "agent",
                    "feasibility": field.get("feasibility") or "medium",
                }
            )
    if not normalized:
        return {
            "Core Profile": [
                {
                    "id": "Core_Profile.Product_Name",
                    "name": "Product Name",
                    "type": "text",
                    "required": True,
                    "source": "official",
                    "origin": "system",
                    "feasibility": "high",
                }
            ]
        }
    return normalized


async def enrich_schema_with_public_evidence(schema: dict, context: dict) -> dict:
    competitors = [str(item) for item in context.get("competitors", []) if str(item).strip()]
    domain = str(context.get("domain") or "").strip()
    evidence_sequence = 1
    evidence_snippets: list[str] = []

    for fields in schema.values():
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            queries = build_field_queries(competitors, field.get("name", ""), domain)
            field["recommended_queries"] = queries
            try:
                results = await search_public_web(queries[0] if queries else f"{field.get('name', '')} {domain}", limit=3)
            except Exception as exc:
                field["feasibility"] = "low"
                field["evidence_refs"] = []
                field["degraded_reason"] = f"schema_evidence_search_failed:{exc.__class__.__name__}"
                continue

            accepted = [result for result in results if result.snippet or result.title]
            field["feasibility"] = "high" if accepted else "low"
            field["evidence_refs"] = []
            for result in accepted[:2]:
                evidence_id = f"schemaev_{evidence_sequence}"
                evidence_sequence += 1
                field["evidence_refs"].append(evidence_id)
                evidence_snippets.append(" ".join(part for part in [result.title, result.snippet] if part))
            if not accepted:
                field["degraded_reason"] = "no_schema_evidence_found"

    recommended = build_recommended_fields_from_evidence(evidence_snippets, schema)
    if recommended:
        schema.setdefault("Recommended Dimensions", []).extend(recommended)
    return schema


def build_field_queries(competitors: Iterable[str], field_name: str, domain: str) -> list[str]:
    names = list(competitors)
    if names:
        return [f"{competitor} {field_name} {domain}".strip() for competitor in names]
    return [f"{field_name} {domain}".strip()]


def build_recommended_fields_from_evidence(snippets: list[str], schema: dict) -> list[dict]:
    existing_names = {
        str(field.get("name", "")).lower()
        for fields in schema.values()
        if isinstance(fields, list)
        for field in fields
        if isinstance(field, dict)
    }
    joined = " ".join(snippets).lower()
    candidates = [
        ("SLA", "sla"),
        ("Compliance", "compliance"),
        ("Pricing", "pricing"),
        ("API Limits", "rate limit"),
    ]
    recommendations = []
    for name, keyword in candidates:
        if name.lower() in existing_names:
            continue
        if keyword in joined:
            stable_name = name.replace(" ", "_")
            recommendations.append(
                {
                    "id": f"Recommended_Dimensions.{stable_name}",
                    "name": name,
                    "type": "text",
                    "required": False,
                    "source": "public_web",
                    "origin": "agent",
                    "feasibility": "medium",
                    "evidence_refs": ["schemaev_recommended"],
                    "recommended_queries": [f"<competitor> {name}"],
                }
            )
    return recommendations
