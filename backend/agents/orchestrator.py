import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import SimpleNamespace

try:
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
except ImportError:
    HumanMessage = None
    ChatOpenAI = None

from dotenv import load_dotenv
load_dotenv()


from .state import AgentState

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name)
    if api_key and ChatOpenAI is not None
    else None
)


@dataclass(slots=True)
class CompetitorCandidate:
    name: str
    reason: str
    source_urls: list[str]
    confidence: float = 0.0


async def orchestrator_node(state: AgentState):
    context = state.get("task_context", {})
    competitors, schema = await generate_complete_plan(context)
    context["competitors"] = competitors
    state["task_context"] = context

    normalized_schema = ensure_schema_metadata(schema)
    state["dynamic_schema"] = normalized_schema
    state["schema_version"] = int(state.get("schema_version", 0)) + 1
    return state


async def generate_complete_plan(context: dict) -> tuple[list[str], dict]:
    domain = str(context.get("domain") or "").strip()
    user_competitors = normalize_competitor_names(context.get("competitors", []))
    user_schema = build_user_schema_from_context(context)

    discovered_candidates = await recommend_competitors(domain, user_competitors)
    discovered = [c.name for c in discovered_candidates]
    seed_competitors = merge_competitors(user_competitors, discovered)

    generated_schema: dict = {}
    generated_competitors: list[str] = []
    if llm is not None:
        prompt = build_plan_completion_prompt(domain, seed_competitors, user_schema)
        try:
            res = await llm.ainvoke([make_human_message(prompt)])
            result = parse_plan_completion(str(res.content))
            generated_competitors = normalize_competitor_names(result.get("competitors", []))
            generated_schema = normalize_schema_input(result.get("schema", {}))
        except Exception as e:
            import logging
            logging.error(f"Error in generate_complete_plan: {e}")
            generated_schema = {}

    competitors = merge_competitors(user_competitors, generated_competitors, seed_competitors)[:5]
    if len(competitors) < 3:
        competitors = merge_competitors(competitors, fallback_competitors(domain, 3 - len(competitors)))

    schema = merge_schema_preserving_user(user_schema, generated_schema or build_schema_from_context({**context, "competitors": competitors}))
    return competitors, schema


def build_plan_completion_prompt(domain: str, competitors: list[str], user_schema: dict) -> str:
    return f"""
You are a competitive-analysis architect.
The user's required analysis domain is: {domain}

The user may have provided only partial inputs:
- User/current competitors: {json.dumps(competitors, ensure_ascii=False)}
- User/current knowledge schema: {json.dumps(user_schema, ensure_ascii=False)}

Complete the plan without overriding user-provided content:
1. If the competitor list is missing or too short, add mainstream competitors in the same competitive tier until there are 3-5 total competitors.
2. Complete missing schema dimension groups and fields. Include dimensions that are meaningful for every competitor, such as core profile, feature tree, pricing model, target users, deployment/integration, compliance, ecosystem, and differentiation.
3. Preserve user-provided fields. Only add missing fields. Do not rename or delete existing user fields.

Return ONLY valid JSON:
{{
  "competitors": ["competitor1", "competitor2"],
  "schema": {{
    "Core Profile": [
      {{"name": "Product Name", "type": "text", "required": true, "reason": "why useful"}}
    ]
  }}
}}
"""


def parse_plan_completion(content: str) -> dict:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    parsed = json.loads(match.group(0) if match else content)
    return parsed if isinstance(parsed, dict) else {}


def build_user_schema_from_context(context: dict) -> dict:
    existing = normalize_schema_input(context.get("dynamic_schema", {}))
    predefined = context.get("predefined_schema") or []
    user_fields = []
    for item in predefined:
        if isinstance(item, dict) and item.get("name"):
            user_fields.append({**item, "origin": "user"})
    if user_fields:
        existing.setdefault("User Defined", []).extend(user_fields)
    return existing


def normalize_schema_input(schema: object) -> dict:
    if not isinstance(schema, dict):
        return {}
    normalized: dict[str, list[dict]] = {}
    for group_name, fields in schema.items():
        group = str(group_name or "").strip()
        if not group:
            continue
        if isinstance(fields, dict):
            iterable = [{"name": name, **(value if isinstance(value, dict) else {})} for name, value in fields.items()]
        elif isinstance(fields, list):
            iterable = fields
        else:
            continue
        normalized[group] = []
        for field in iterable:
            if isinstance(field, str):
                normalized[group].append({"name": field, "type": "text"})
            elif isinstance(field, dict) and (field.get("name") or field.get("id")):
                normalized[group].append(dict(field))
        if not normalized[group]:
            normalized.pop(group, None)
    return normalized


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


def merge_schema_preserving_user(user_schema: dict, generated_schema: dict) -> dict:
    merged = normalize_schema_input(generated_schema)
    for group_name, user_fields in normalize_schema_input(user_schema).items():
        target = merged.setdefault(group_name, [])
        existing_names = {field_key(field) for field in target}
        for field in user_fields:
            key = field_key(field)
            if key in existing_names:
                target[:] = [{**item, **field, "origin": "user"} if field_key(item) == key else item for item in target]
            else:
                target.append({**field, "origin": "user"})
                existing_names.add(key)
    return merged


def field_key(field: dict) -> str:
    return str(field.get("name") or field.get("id") or "").strip().lower()


def fallback_competitors(domain: str, count: int) -> list[str]:
    base = domain or "Market"
    suffixes = ["Leader", "Challenger", "Specialist", "Enterprise", "Cloud"]
    return [f"{base} {suffix}" for suffix in suffixes[: max(count, 0)]]


async def recommend_competitors(domain: str, existing: Iterable[str] = ()) -> list[CompetitorCandidate]:
    existing_names = {name.lower() for name in normalize_competitor_names(existing)}
    candidates: list[CompetitorCandidate] = []
    
    if llm is not None:
        from services.web_search import search_public_web
        snippets = []
        try:
            results = await search_public_web(f"{domain} top competitors alternatives", limit=5)
            for r in results:
                snippets.append(f"Title: {r.title}\nSnippet: {r.snippet}\nURL: {r.url}")
        except Exception as e:
            import logging
            logging.error(f"Search failed in recommend_competitors: {e}")
            
        evidence = "\n\n".join(snippets)
        
        prompt = f"""
You are an expert in competitive analysis.
The user wants to analyze the domain: {domain}

Based on your knowledge AND the following recent search results, provide up to 5 real competitor products or companies in this domain.
Do not include generic terms, just specific entities.

Search Results:
{evidence}

Return ONLY a valid JSON array. Each item must have:
- name: short product or company name
- reason: one concise reason why it is a competitor
- source_urls: [] (add URL from search results if applicable)
- confidence: number from 0 to 1

Example Output:
[
  {{"name": "Competitor A", "reason": "Reason A", "source_urls": ["url1"], "confidence": 0.9}}
]
"""
        try:
            res = await llm.ainvoke([make_human_message(prompt)])
            print("RAW LLM OUTPUT:", repr(res.content))
            candidates = parse_competitor_candidates(str(res.content))
            print("PARSED CANDIDATES:", candidates)
        except Exception as e:
            import logging
            logging.error(f"LLM extraction failed in recommend_competitors: {e}")
            pass

    if not candidates and 'snippets' in locals() and snippets:
        # Fallback: simple extraction from search snippets if LLM fails
        candidates = extract_competitors_from_snippets(domain, snippets)

    filtered: list[CompetitorCandidate] = []
    seen = set(existing_names)
    for candidate in candidates:
        lowered = candidate.name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        filtered.append(candidate)
        
    if filtered:
        return filtered[:5]

    return [
        CompetitorCandidate(name=name, reason="Generated fallback candidate from the analysis domain.", source_urls=[], confidence=0.2)
        for name in fallback_competitors(domain, 3)
        if name.lower() not in existing_names
    ]


def parse_competitor_candidates(content: str) -> list[CompetitorCandidate]:
    try:
        parsed = json.loads(extract_json_array(content))
    except Exception:
        return []
        
    if not isinstance(parsed, list):
        return []

    candidates: list[CompetitorCandidate] = []
    seen = set()
    for item in parsed:
        if isinstance(item, str):
            raw_name = item
            reason = ""
            source_urls: list[str] = []
            confidence = 0.0
        elif isinstance(item, dict):
            raw_name = item.get("name", "")
            reason = str(item.get("reason") or "").strip()
            source_urls = [str(url).strip() for url in item.get("source_urls", []) if str(url).strip()]
            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
        else:
            continue

        names = normalize_competitor_names([raw_name])
        if not names:
            continue
        name = names[0]
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        candidates.append(
            CompetitorCandidate(
                name=name,
                reason=reason,
                source_urls=source_urls,
                confidence=confidence,
            )
        )
    return candidates

def extract_competitors_from_snippets(domain: str, snippets: list[str]) -> list[CompetitorCandidate]:
    candidates: list[CompetitorCandidate] = []
    text = " ".join(snippets)
    words = re.findall(r'[A-Z][a-zA-Z0-9-]{2,15}|\b[\u4e00-\u9fa5]{2,6}\b', text)
    from collections import Counter
    counts = Counter(words)
    domain_words = set(domain.lower().split())
    
    for word, count in counts.most_common(15):
        if count < 2 or word.lower() in domain_words or word.lower() in {"the", "and", "for", "top", "best", "vs", "ai"}:
            continue
        candidates.append(CompetitorCandidate(
            name=word,
            reason=f"Found {count} times in search results for {domain}.",
            source_urls=[],
            confidence=0.5
        ))
        if len(candidates) >= 5:
            break
    return candidates


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
    total_fields = 0
    max_fields = 12
    for group_name, fields in schema.items():
        if not isinstance(fields, list):
            continue
        normalized[group_name] = []
        for index, field in enumerate(fields):
            if total_fields >= max_fields:
                break
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or f"field_{index + 1}")
            stable_group = str(group_name).strip().replace(" ", "_")
            stable_name = field_name.strip().replace(" ", "_")
            normalized_field = {
                "id": field.get("id") or f"{stable_group}.{stable_name}",
                "name": field_name,
                "type": field.get("type") or "text",
                "required": bool(field.get("required", True)),
                "source": field.get("source") or "public_web",
                "origin": field.get("origin") or "agent",
                "feasibility": field.get("feasibility") or "medium",
            }
            for metadata_key in ("confidence", "reason", "evidence", "affected_competitors"):
                if metadata_key in field:
                    normalized_field[metadata_key] = field[metadata_key]
            normalized[group_name].append(normalized_field)
            total_fields += 1
        if not normalized[group_name]:
            normalized.pop(group_name, None)
        if total_fields >= max_fields:
            break
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


def merge_schema_extensions(schema: dict, extensions: list[dict]) -> tuple[dict, list[dict]]:
    updated = normalize_schema_input(schema)
    added_fields: list[dict] = []
    for extension in extensions:
        if not isinstance(extension, dict):
            continue
        confidence = safe_float(extension.get("confidence"), 0.0)
        if confidence < 0.8:
            continue
        group_name = str(extension.get("dimension_group") or extension.get("group") or "Extended Attributes").strip()
        field_name = str(extension.get("new_field") or extension.get("name") or "").strip()
        if not group_name or not field_name:
            continue
        group = updated.setdefault(group_name, [])
        if any(field_key(field) == field_name.lower() for field in group if isinstance(field, dict)):
            continue
        stable_group = group_name.replace(" ", "_")
        stable_name = field_name.replace(" ", "_")
        field = {
            "id": extension.get("field_id") or f"{stable_group}.{stable_name}",
            "name": field_name,
            "type": extension.get("type") or "text",
            "required": False,
            "source": extension.get("source") or "public_web",
            "origin": "critic",
            "feasibility": "medium",
            "confidence": confidence,
            "evidence": extension.get("evidence") or [],
            "affected_competitors": extension.get("affected_competitors") or [],
        }
        group.append(field)
        added_fields.append({**field, "group": group_name})
    return ensure_schema_metadata(updated), added_fields


def safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def make_human_message(content: str):
    if HumanMessage is not None:
        return HumanMessage(content=content)
    return SimpleNamespace(content=content)
