import json
import os

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from .state import AgentState

api_key = os.environ.get("DEEPSEEK_API_KEY")
llm = (
    ChatOpenAI(api_key=api_key, base_url="https://api.deepseek.com", model="deepseek-v4-pro")
    if api_key
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

    state["dynamic_schema"] = ensure_schema_metadata(schema)
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
