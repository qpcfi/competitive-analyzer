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

from services.web_search import PageEvidence, SearchResult, fetch_public_web_pages, search_public_web

from .state import AgentState

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name)
    if api_key and ChatOpenAI is not None
    else None
)


class CompetitorDiscoveryUnavailable(RuntimeError):
    pass


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
    state["dynamic_schema"] = await enrich_schema_with_public_evidence(normalized_schema, context)
    state["schema_version"] = int(state.get("schema_version", 0)) + 1
    return state


async def generate_complete_plan(context: dict) -> tuple[list[str], dict]:
    domain = str(context.get("domain") or "").strip()
    user_competitors = normalize_competitor_names(context.get("competitors", []))
    user_schema = build_user_schema_from_context(context)

    discovered = await safe_discover_competitors(domain, user_competitors)
    seed_competitors = merge_competitors(user_competitors, discovered)
    if len(seed_competitors) < 3:
        seed_competitors = merge_competitors(seed_competitors, fallback_competitors(domain, 3 - len(seed_competitors)))

    generated_schema: dict = {}
    generated_competitors: list[str] = []
    if llm is not None:
        prompt = build_plan_completion_prompt(domain, seed_competitors, user_schema)
        try:
            res = await llm.ainvoke([make_human_message(prompt)])
            result = parse_plan_completion(str(res.content))
            generated_competitors = normalize_competitor_names(result.get("competitors", []))
            generated_schema = normalize_schema_input(result.get("schema", {}))
        except Exception:
            generated_schema = {}

    competitors = merge_competitors(user_competitors, generated_competitors, seed_competitors)[:5]
    schema = merge_schema_preserving_user(user_schema, generated_schema or build_schema_from_context({**context, "competitors": competitors}))
    return competitors, schema


async def safe_discover_competitors(domain: str, existing: list[str]) -> list[str]:
    if len(existing) >= 3:
        return existing
    try:
        candidates = await discover_competitor_candidates(domain)
    except Exception:
        return []
    existing_keys = {item.lower() for item in existing}
    return [candidate.name for candidate in candidates if candidate.name.lower() not in existing_keys]


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
4. Each generated field must be collectable from public sources or clearly marked as lower feasibility.

Return ONLY valid JSON:
{{
  "competitors": ["existing or generated competitor"],
  "schema": {{
    "Core Profile": [
      {{"name": "Product Name", "type": "text", "required": true, "source": "official", "origin": "agent", "feasibility": "high", "reason": "why this field is useful"}}
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


async def discover_competitors(domain: str) -> list[str]:
    candidates = await discover_competitor_candidates(domain)
    return [candidate.name for candidate in candidates[:3]]


async def recommend_competitors(domain: str, existing: Iterable[str] = ()) -> list[CompetitorCandidate]:
    existing_names = {name.lower() for name in normalize_competitor_names(existing)}
    try:
        candidates = await discover_competitor_candidates(domain)
    except CompetitorDiscoveryUnavailable:
        candidates = await discover_competitor_candidates_from_search(domain)
    except Exception:
        candidates = await discover_competitor_candidates_from_search(domain)

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


async def discover_competitor_candidates_from_search(domain: str) -> list[CompetitorCandidate]:
    results: list[SearchResult] = []
    for query in build_competitor_search_queries(domain):
        try:
            results.extend(await search_public_web(query, limit=5))
        except Exception:
            continue

    names = extract_competitor_names_from_search_results(results, domain)
    if not names:
        names = infer_names_from_search_results(results)

    candidates: list[CompetitorCandidate] = []
    seen = set()
    for name in names:
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        supporting = [result.url for result in results if name.lower() in f"{result.title} {result.snippet}".lower()]
        candidates.append(
            CompetitorCandidate(
                name=name,
                reason="Identified from public search result titles/snippets.",
                source_urls=supporting[:2],
                confidence=0.45 if supporting else 0.25,
            )
        )
    return candidates[:5]


async def discover_competitor_candidates(domain: str) -> list[CompetitorCandidate]:
    domain = str(domain or "").strip()
    if not domain:
        return []
    if llm is None:
        raise CompetitorDiscoveryUnavailable("LLM is required for competitor discovery")

    results: list[SearchResult] = []
    for query in build_competitor_search_queries(domain):
        try:
            results.extend(await search_public_web(query, limit=4))
        except Exception:
            continue

    deduped_results = dedupe_search_results_by_url(results)
    try:
        pages = await fetch_public_web_pages(deduped_results, limit=6)
    except Exception as exc:
        raise CompetitorDiscoveryUnavailable("Web page fetching failed for competitor discovery") from exc

    usable_pages = [page for page in pages if page.text or page.snippet]
    if not usable_pages:
        raise CompetitorDiscoveryUnavailable("No usable web evidence found for competitor discovery")

    prompt = build_competitor_discovery_prompt(domain, usable_pages)
    try:
        res = await llm.ainvoke([make_human_message(prompt)])
        candidates = parse_competitor_candidates(str(res.content))
    except Exception as exc:
        raise CompetitorDiscoveryUnavailable("LLM competitor discovery failed") from exc

    if not candidates:
        raise CompetitorDiscoveryUnavailable("No competitors found in model output")
    return candidates[:3]


def build_competitor_search_queries(domain: str) -> list[str]:
    return [
        f"{domain} competitors products",
        f"{domain} alternatives",
        f"{domain} market vendors",
    ]


def make_human_message(content: str):
    if HumanMessage is not None:
        return HumanMessage(content=content)
    return SimpleNamespace(content=content)


def dedupe_search_results_by_url(results: Iterable[SearchResult]) -> list[SearchResult]:
    deduped: list[SearchResult] = []
    seen = set()
    for result in results:
        url = str(result.url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(result)
    return deduped


def build_competitor_discovery_prompt(domain: str, pages: Iterable[PageEvidence]) -> str:
    evidence_blocks = []
    for index, page in enumerate(pages, start=1):
        excerpt = (page.text or page.snippet or "").strip()[:2500]
        evidence_blocks.append(
            "\n".join(
                [
                    f"Source {index}",
                    f"URL: {page.url}",
                    f"Search title: {page.search_title}",
                    f"Page title: {page.page_title}",
                    f"Search snippet: {page.snippet}",
                    f"Page excerpt: {excerpt}",
                ]
            )
        )

    evidence_text = "\n\n".join(evidence_blocks)
    return f"""
You are identifying real competitor products or companies for a competitive-analysis task.
Domain: {domain}

Use only the public web evidence below. Do not invent names. Exclude article titles,
ranking pages, repositories, categories, and generic market descriptions.

Return ONLY a JSON array. Each item must have:
- name: short product or company name
- reason: one concise evidence-backed reason
- source_urls: URLs that support the candidate
- confidence: number from 0 to 1

Evidence:
{evidence_text}
"""


def parse_competitor_candidates(content: str) -> list[CompetitorCandidate]:
    parsed = json.loads(extract_json_array(content))
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
        if not is_plausible_competitor_name(name) or name.lower() in seen:
            continue
        seen.add(name.lower())
        normalized.append(name[:80])
    return normalized


MODEL_NAME_PATTERN = re.compile(
    r"GPT-4o|GPT-\d+(?:\.\d+)?|Claude\s*\d+(?:\.\d+)?|Gemini\s*\d+(?:\.\d+)?|"
    r"DeepSeek[-\s]?[A-Za-z0-9.]+|Qwen[-\s]?[A-Za-z0-9.]+|Llama\s*\d+(?:\.\d+)?|"
    r"GLM[-\s]?\d+(?:\.\d+)?|Kimi|Doubao|豆包|ERNIE(?:\s*Bot)?|文心一言|通义千问|"
    r"Hunyuan|混元|Grok[-\s]?\d*|Mistral(?:\s+[A-Za-z0-9.]+)?|Command\s+R\+?|"
    r"Yi[-\s]?\d*(?:\.\d+)?|MiniMax|abab\d+(?:\.\d+)?",
    re.IGNORECASE,
)

PAGE_TITLE_KEYWORDS = (
    "leaderboard",
    "ranking",
    "rankings",
    "rank",
    "top ",
    "top-",
    "top20",
    "top 20",
    "榜单",
    "排行",
    "排名",
    "测评",
    "评测",
    "综合排名",
    "github",
)


def extract_competitor_names_from_search_results(results: Iterable[SearchResult], domain: str) -> list[str]:
    candidates: list[str] = []
    for result in results:
        evidence_text = " ".join(part for part in [result.title, result.snippet] if part)
        candidates.extend(match.group(0) for match in MODEL_NAME_PATTERN.finditer(evidence_text))

        # Titles from search engines are often pages, rankings, or repositories.
        # Use them only as a last-mile candidate when they already look like a product name.
        title_candidate = clean_search_title(result.title)
        if title_candidate:
            candidates.append(title_candidate)

    return normalize_competitor_names(candidates)


def infer_names_from_search_results(results: Iterable[SearchResult]) -> list[str]:
    candidates: list[str] = []
    stop_prefixes = ("best ", "top ", "compare ", "comparison ", "alternatives ")
    for result in results:
        title = clean_search_title(result.title)
        if not title:
            continue
        compact = re.sub(r"\b(alternatives|competitors|reviews|pricing|comparison|best|top)\b", "", title, flags=re.IGNORECASE)
        compact = re.sub(r"\s+", " ", compact).strip(" :,-|")
        if compact and not compact.lower().startswith(stop_prefixes):
            candidates.append(compact)
    return normalize_competitor_names(candidates)


def clean_search_title(title: str) -> str:
    title = str(title or "").strip()
    if not title:
        return ""
    return re.split(r"\s*[\-|_|｜|]\s*", title, maxsplit=1)[0].strip()


def is_plausible_competitor_name(name: str) -> bool:
    name = str(name or "").strip()
    lowered = name.lower()
    if not name or len(name) > 40:
        return False
    if "/" in name or "\\" in name:
        return False
    if re.search(r"20\d{2}\s*年?", name):
        return False
    if any(keyword in lowered for keyword in PAGE_TITLE_KEYWORDS):
        return False
    if any(keyword in name for keyword in ("全球", "综合", "网址", "网站", "产品清单", "大模型")):
        return False
    return True


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
