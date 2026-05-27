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
    competitors = [str(item).strip() for item in context.get("competitors", []) if str(item).strip()]
    if not competitors:
        competitors = await discover_competitors(context.get("domain", ""))
        context["competitors"] = competitors
        state["task_context"] = context
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


async def discover_competitors(domain: str) -> list[str]:
    candidates = await discover_competitor_candidates(domain)
    return [candidate.name for candidate in candidates[:3]]


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
    max_fields = 8
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
