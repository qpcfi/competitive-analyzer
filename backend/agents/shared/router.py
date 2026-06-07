import asyncio
import os
import yaml
from typing import Any
import json

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
except ImportError:
    HumanMessage = None
    SystemMessage = None
    ChatPromptTemplate = None
    ChatOpenAI = None

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, timeout=30)
    if api_key and ChatOpenAI is not None
    else None
)

def load_knowledge_base() -> list[dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "knowledge_base.yaml")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])

async def route_sources(domain: str, competitor: str, skill_filter: str | None = None) -> list[dict[str, Any]]:
    sources = load_knowledge_base()
    if not sources:
        return []

    # 1. Hard Filtering
    hard_filtered = []
    for src in sources:
        # Skill filter: if source specifies skills, must match; if no skills field, apply to all
        src_skills = src.get("skills")
        if skill_filter and src_skills:
            if skill_filter not in src_skills:
                continue
        target_competitors = src.get("competitors")
        if target_competitors:
            # If target competitors are specified, the current competitor must match one of them
            if competitor and any(competitor.lower() in target.lower() or target.lower() in competitor.lower() for target in target_competitors):
                hard_filtered.append(src)
        else:
            # General domain source, applicable to any competitor
            hard_filtered.append(src)

    if not hard_filtered:
        return []

    if llm is None:
        # Fallback to returning all hard filtered if LLM is not available
        return hard_filtered

    # 2. Soft Filtering (Semantic Routing)
    # Ask LLM to select relevant sources based on description and tags
    sources_json = json.dumps([{
        "id": i,
        "name": src.get("name"),
        "description": src.get("description"),
        "tags": src.get("tags")
    } for i, src in enumerate(hard_filtered)], ensure_ascii=False)

    system_prompt = """You are a highly accurate routing agent.
Your task is to select which data sources are potentially relevant for a given domain, competitor, and analysis dimension.
Only select sources that have a high likelihood of containing information about the requested domain and dimension.
Return a JSON array of integers representing the 'id' of the selected sources.
If no sources are relevant, return an empty array: []
Do not return anything else except the JSON array.
"""

    human_prompt = f"""Domain: {domain}
Competitor: {competitor}
Analysis Dimension: {skill_filter or "general"}

Available Sources:
{sources_json}

Which source IDs are relevant? Return only the JSON array."""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt)
        ])
        
        content = response.content.strip()
        # Clean up markdown code block if present
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        selected_ids = json.loads(content)
        
        final_sources = []
        for src_id in selected_ids:
            if 0 <= src_id < len(hard_filtered):
                final_sources.append(hard_filtered[src_id])
                
        return final_sources
    except Exception as e:
        print(f"Error in semantic routing: {e}")
        # Graceful fallback: return all hard-filtered on error
        return hard_filtered


# ── Auto-save discovered URLs to knowledge_base.yaml ──

_AUTOSAVE_LOCK = asyncio.Lock()


async def auto_save_to_knowledge_base(
    url: str,
    competitor: str,
    skill: str,
    field_name: str,
    description: str | None = None,
) -> bool:
    """Append a discovered URL to knowledge_base.yaml in a sub-thread.

    Returns True if saved, False if skipped (duplicate or error).
    Runs sync I/O in run_in_executor to avoid blocking the event loop.
    """
    async with _AUTOSAVE_LOCK:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _sync_append_to_kb, url, competitor, skill, field_name, description
        )


def _sync_append_to_kb(
    url: str,
    competitor: str,
    skill: str,
    field_name: str,
    description: str | None = None,
) -> bool:
    """Synchronous: read → check duplicate → append → write.

    Call from run_in_executor only — not async-safe.
    """
    path = os.path.join(os.path.dirname(__file__), "knowledge_base.yaml")
    if not os.path.exists(path):
        print(f"[autosave] knowledge_base.yaml not found at {path}")
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        print(f"[autosave] read error: {e}")
        return False

    data = yaml.safe_load(raw) or {}
    sources = data.get("sources", [])
    norm_url = url.rstrip("/").lower()
    for src in sources:
        if isinstance(src, dict) and src.get("url", "").rstrip("/").lower() == norm_url:
            return False  # duplicate, skip

    name = description or f"auto: {competitor} {field_name}"
    desc = description or f"Auto-discovered from {competitor} {field_name} analysis"
    new_entry = (
        f'  - url: "{url}"\n'
        f'    name: "{name}"\n'
        f'    description: "{desc}"\n'
        f'    skills: ["{skill}"]\n'
        f'    tags: ["auto-discovered"]\n'
        f'    competitors: ["{competitor}"]\n'
    )

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + new_entry)
        print(f"[autosave] saved: {url}")
        return True
    except OSError as e:
        print(f"[autosave] write error: {e}")
        return False
