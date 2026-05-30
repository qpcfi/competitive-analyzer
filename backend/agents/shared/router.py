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
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name)
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

async def route_sources(domain: str, competitor: str) -> list[dict[str, Any]]:
    sources = load_knowledge_base()
    if not sources:
        return []

    # 1. Hard Filtering
    hard_filtered = []
    for src in sources:
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
Your task is to select which data sources are potentially relevant for a given domain and competitor.
Only select sources that have a high likelihood of containing information about the requested domain.
Return a JSON array of integers representing the 'id' of the selected sources.
If no sources are relevant, return an empty array: []
Do not return anything else except the JSON array.
"""
    
    human_prompt = f"""Domain: {domain}
Competitor: {competitor}

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
