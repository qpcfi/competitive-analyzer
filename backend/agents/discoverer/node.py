import json
import os
import yaml
from collections.abc import Iterable
from dataclasses import dataclass, asdict

try:
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    ChatPromptTemplate = None

from dotenv import load_dotenv
load_dotenv()

from ..state import AgentState
from ..shared.llm import create_chat_llm
from core.callbacks import RealtimeDebugCallbackHandler

llm = create_chat_llm(timeout=90)


@dataclass(slots=True)
class CompetitorCandidate:
    name: str
    reason: str
    source_urls: list[str]
    confidence: float = 0.0
    candidate_type: str = "unknown"
    entity_type_fit: bool = True
    goal_relevance: float = 0.0
    reject_reason: str = ""


@dataclass(slots=True)
class DiscoveryScope:
    target_entity_type: str
    domain_boundary: str
    analysis_focus: str
    positive_signals: list[str]
    excluded_entity_types: list[str]
    search_terms: list[str]
    exclusion_terms: list[str]


async def discoverer_node(state: AgentState):
    context = state.get("task_context", {})
    task_id = state.get("task_id")
    domain = str(context.get("domain") or "").strip()
    analysis_goal = str(context.get("analysis_goal") or "").strip()
    user_competitors = normalize_competitor_names(context.get("competitors", []))

    if not user_competitors:
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        discovered_candidates, market_context, scope = await recommend_competitors(
            domain, user_competitors, analysis_goal=analysis_goal, callbacks=callbacks
        )
        context["market_context"] = market_context
        context["discovery_scope"] = asdict(scope)
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


async def build_discovery_scope(domain: str, analysis_goal: str, callbacks=None) -> DiscoveryScope:
    """Use LLM to analyze domain + goal and build a structured DiscoveryScope."""
    if not analysis_goal:
        return fallback_discovery_scope(domain, analysis_goal)

    if llm is not None and ChatPromptTemplate is not None:
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            prompt_template = ChatPromptTemplate.from_messages([
                ("system", config["scope_analyzer"]["system_prompt"]),
                ("human", config["scope_analyzer"]["human_template"]),
            ])

            chain = prompt_template | llm
            chain_config = {"callbacks": callbacks} if callbacks else None
            res = await chain.ainvoke({
                "domain": domain,
                "analysis_goal": analysis_goal,
            }, config=chain_config)

            parsed = json.loads(extract_json_object(str(res.content)))
            return DiscoveryScope(
                target_entity_type=str(parsed.get("target_entity_type") or "").strip(),
                domain_boundary=domain,
                analysis_focus=analysis_goal,
                positive_signals=[str(s).strip() for s in parsed.get("positive_signals", []) if s],
                excluded_entity_types=[str(s).strip() for s in parsed.get("excluded_entity_types", []) if s],
                search_terms=[str(s).strip() for s in parsed.get("search_terms", []) if s],
                exclusion_terms=[str(s).strip() for s in parsed.get("exclusion_terms", []) if s],
            )
        except Exception as e:
            import logging
            logging.error(f"build_discovery_scope LLM failed: {e}")

    return fallback_discovery_scope(domain, analysis_goal)


def fallback_discovery_scope(domain: str, analysis_goal: str) -> DiscoveryScope:
    """Return a conservative scope that excludes generic non-competitor entity types."""
    return DiscoveryScope(
        target_entity_type="",
        domain_boundary=domain,
        analysis_focus=analysis_goal,
        positive_signals=[],
        excluded_entity_types=[
            "media", "directory", "consulting_firm",
            "service_provider", "saas_vendor", "marketing_agency",
            "website_builder", "ranking_page",
        ],
        search_terms=[f"{domain} top competitors alternatives"],
        exclusion_terms=[],
    )


def is_accepted_candidate(candidate: CompetitorCandidate) -> bool:
    """Check whether a candidate should be kept after scope-based filtering."""
    if not candidate.entity_type_fit:
        return False
    rejected_types = {
        "service_provider", "marketing_agency", "website_builder",
        "saas_vendor", "media", "directory", "consulting_firm", "ranking_page",
    }
    if candidate.candidate_type in rejected_types:
        return False
    if not candidate.name or candidate.confidence < 0.35:
        return False
    return True


async def recommend_competitors(
    domain: str,
    existing: Iterable[str] = (),
    analysis_goal: str = "",
    callbacks=None,
) -> tuple[list[CompetitorCandidate], str, DiscoveryScope]:
    existing_names = {name.lower() for name in normalize_competitor_names(existing)}
    candidates: list[CompetitorCandidate] = []
    evidence = ""

    scope = await build_discovery_scope(domain, analysis_goal, callbacks)

    if llm is not None and ChatPromptTemplate is not None:
        from services.web_search import search_multi_engine, fetch_public_web_pages
        from ..shared.router import route_sources
        from ..shared.crawler import crawl_urls

        evidence_blocks = []

        try:
            # 1. Curated domain-level sources
            routed_sources = await route_sources(domain, "")
            routed_urls = [src["url"] for src in routed_sources if "url" in src]

            if routed_urls:
                cached_markdowns = await crawl_urls(routed_urls)
                for index, (url, md) in enumerate(cached_markdowns.items(), start=1):
                    excerpt = md.strip()[:6000]
                    evidence_blocks.append(
                        "\n".join([
                            f"Curated Source {index}",
                            f"URL: {url}",
                            f"Page excerpt: {excerpt}",
                        ])
                    )

            # 2. Scope-based search
            if not evidence_blocks:
                search_query = scope.search_terms[0] if scope.search_terms else f"{domain} top competitors alternatives"
                results = await search_multi_engine(search_query, limit=5)
                pages = await fetch_public_web_pages(results, limit=5)
                for index, page in enumerate(pages, start=1):
                    excerpt = (page.text or page.snippet or "").strip()[:2500]
                    evidence_blocks.append(
                        "\n".join([
                            f"Search Source {index}",
                            f"URL: {page.url}",
                            f"Search title: {page.search_title}",
                            f"Page title: {page.page_title}",
                            f"Search snippet: {page.snippet}",
                            f"Page excerpt: {excerpt}",
                        ])
                    )
        except Exception as e:
            import logging
            logging.error(f"Data gathering failed in recommend_competitors: {e}")

        evidence = "\n\n".join(evidence_blocks)

        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                PROMPT_CONFIG = yaml.safe_load(f)

            if evidence.strip():
                prompt_template = ChatPromptTemplate.from_messages([
                    ("system", PROMPT_CONFIG["discoverer_agent"]["system_prompt"]),
                    ("human", PROMPT_CONFIG["discoverer_agent"]["human_template"]),
                ])
            else:
                prompt_template = ChatPromptTemplate.from_messages([
                    ("system", PROMPT_CONFIG["discoverer_agent"]["fallback_system_prompt"]),
                    ("human", PROMPT_CONFIG["discoverer_agent"]["human_template"]),
                ])

            chain = prompt_template | llm

            config = {"callbacks": callbacks} if callbacks else None
            res = await chain.ainvoke({
                "domain": domain,
                "discovery_scope": json.dumps(asdict(scope), ensure_ascii=False),
                "analysis_goal": analysis_goal,
                "evidence": evidence,
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
                        source_urls=[str(u).strip() for u in item.get("source_urls", []) if str(u).strip()],
                        confidence=float(item.get("confidence") or 0.0),
                        candidate_type=str(item.get("candidate_type") or "unknown").strip(),
                        entity_type_fit=bool(item.get("entity_type_fit", True)),
                        goal_relevance=float(item.get("goal_relevance") or 0.0),
                        reject_reason=str(item.get("reject_reason") or "").strip(),
                    )
                )
        except Exception as e:
            import logging
            logging.error(f"LLM extraction failed in recommend_competitors: {e}")
            raise RuntimeError(f"澶фā鍨嬪湪鎻愬彇绔炲搧鏃跺彂鐢熷紓甯? {e}\n(璇佹嵁鐗囨鎴栫綉缁滃彲鑳藉瓨鍦ㄩ棶棰橈紝鎴栬€呭ぇ妯″瀷鏈兘鎸夌収鎸囧畾鏍煎紡杈撳嚭銆?") from e

    # Dedup and scope-based filtering
    accepted: list[CompetitorCandidate] = []
    seen = set(existing_names)
    for candidate in candidates:
        lowered = candidate.name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        if is_accepted_candidate(candidate):
            accepted.append(candidate)

    # Correction search when too few candidates pass filtering
    if len(accepted) < 3 and len(candidates) >= 3:
        extra = await _run_correction_search(
            domain, scope, analysis_goal, evidence, existing_names, callbacks
        )
        for c in extra:
            lowered = c.name.lower()
            if lowered not in seen:
                seen.add(lowered)
                accepted.append(c)

    if accepted:
        return accepted[:5], evidence, scope

    return [
        CompetitorCandidate(
            name=name,
            reason="Generated fallback candidate from the analysis domain.",
            source_urls=[],
            confidence=0.2,
        )
        for name in fallback_competitors(domain, 3)
        if name.lower() not in existing_names
    ], evidence, scope


async def _run_correction_search(
    domain: str,
    scope: DiscoveryScope,
    analysis_goal: str,
    evidence: str,
    existing_names: set[str],
    callbacks=None,
) -> list[CompetitorCandidate]:
    """Re-search with targeted queries when initial candidates were mostly filtered out."""
    if llm is None or ChatPromptTemplate is None:
        return []

    queries = []
    if scope.target_entity_type:
        queries.append(f"{scope.target_entity_type} leading companies")
    if scope.domain_boundary:
        queries.append(f"{scope.domain_boundary} top companies brands")
    if scope.search_terms:
        queries.extend(scope.search_terms[:2])

    if not queries:
        return []

    from services.web_search import search_multi_engine, fetch_public_web_pages

    new_blocks = []
    try:
        results = await search_multi_engine("; ".join(queries[:3]), limit=5)
        pages = await fetch_public_web_pages(results, limit=5)
        for index, page in enumerate(pages, start=1):
            excerpt = (page.text or page.snippet or "").strip()[:2500]
            if not excerpt:
                continue
            new_blocks.append(
                "\n".join([
                    f"Correction Source {index}",
                    f"URL: {page.url}",
                    f"Search title: {page.search_title}",
                    f"Page title: {page.page_title}",
                    f"Search snippet: {page.snippet}",
                    f"Page excerpt: {excerpt}",
                ])
            )
    except Exception as e:
        import logging
        logging.error(f"Correction search failed: {e}")
        return []

    if not new_blocks:
        return []

    new_evidence = "\n\n".join(new_blocks)
    combined_evidence = (evidence + "\n\n" + new_evidence) if evidence else new_evidence

    try:
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)

        prompt_template = ChatPromptTemplate.from_messages([
            ("system", PROMPT_CONFIG["discoverer_agent"]["system_prompt"]),
            ("human", PROMPT_CONFIG["discoverer_agent"]["human_template"]),
        ])

        chain = prompt_template | llm
        config = {"callbacks": callbacks} if callbacks else None
        res = await chain.ainvoke({
            "domain": domain,
            "discovery_scope": json.dumps(asdict(scope), ensure_ascii=False),
            "analysis_goal": analysis_goal,
            "evidence": combined_evidence,
        }, config=config)

        parsed = json.loads(extract_json_array(str(res.content)))
        parsed_candidates = parsed if isinstance(parsed, list) else []

        accepted: list[CompetitorCandidate] = []
        seen = set(existing_names)
        for item in parsed_candidates:
            names = normalize_competitor_names([item.get("name", "")])
            if not names:
                continue
            name = names[0]
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)

            candidate = CompetitorCandidate(
                name=name,
                reason=str(item.get("reason") or "").strip(),
                source_urls=[str(u).strip() for u in item.get("source_urls", []) if str(u).strip()],
                confidence=float(item.get("confidence") or 0.0),
                candidate_type=str(item.get("candidate_type") or "unknown").strip(),
                entity_type_fit=bool(item.get("entity_type_fit", True)),
                goal_relevance=float(item.get("goal_relevance") or 0.0),
                reject_reason=str(item.get("reject_reason") or "").strip(),
            )
            if is_accepted_candidate(candidate):
                accepted.append(candidate)

        return accepted
    except Exception as e:
        import logging
        logging.error(f"Correction LLM extraction failed: {e}")
        return []


def extract_json_array(content: str) -> str:
    start = content.find("[")
    end = content.rfind("]")
    if start >= 0 and end > start:
        return content[start : end + 1]
    return content


def extract_json_object(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
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
