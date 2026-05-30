import json
import os
import re
import yaml
from collections.abc import Iterable
from dataclasses import dataclass
from types import SimpleNamespace

try:
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    HumanMessage = None
    ChatOpenAI = None
    ChatPromptTemplate = None

from dotenv import load_dotenv
load_dotenv()


from ..state import AgentState
from ..schemas import PlanCompletionResult, CompetitorRecommendationResult
from core.callbacks import RealtimeDebugCallbackHandler

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
    task_id = state.get("task_id")
    competitors, schema = await generate_complete_plan(context, task_id)
    context["competitors"] = competitors
    state["task_context"] = context

    normalized_schema = ensure_schema_metadata(schema)
    state["dynamic_schema"] = normalized_schema
    state["schema_version"] = int(state.get("schema_version", 0)) + 1
    return state


async def generate_complete_plan(context: dict, task_id: str = None) -> tuple[list[str], dict]:
    domain = str(context.get("domain") or "").strip()
    user_competitors = normalize_competitor_names(context.get("competitors", []))
    user_schema = build_user_schema_from_context(context)

    seed_competitors = list(user_competitors)

    generated_schema: dict = {}
    generated_competitors: list[str] = []
    if llm is not None and ChatPromptTemplate is not None:
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
            with open(prompt_path, "r", encoding="utf-8") as f:
                PROMPT_CONFIG = yaml.safe_load(f)
                
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", PROMPT_CONFIG["orchestrator_agent"]["plan_completion"]["system_prompt"]),
                ("human", PROMPT_CONFIG["orchestrator_agent"]["plan_completion"]["human_template"])
            ])
            
            chain = prompt_template | llm
            
            callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
            config = {"callbacks": callbacks} if callbacks else None
            response = await chain.ainvoke({
                "domain": domain,
                "competitors": json.dumps(seed_competitors, ensure_ascii=False),
                "user_schema": json.dumps(user_schema, ensure_ascii=False),
                "market_context": context.get("market_context") or "No additional context."
            }, config=config)
            
            content = str(response.content)
            match = re.search(r"\{.*\}", content, re.DOTALL)
            result = json.loads(match.group(0) if match else content)
            
            generated_competitors = normalize_competitor_names(result.get("competitors", []))
            generated_schema = normalize_schema_input(result.get("schema_def", result.get("schema", {})))
        except Exception as e:
            import logging
            logging.error(f"Error in generate_complete_plan: {e}")
            generated_schema = {}

    competitors = seed_competitors[:5]

    schema = merge_schema_preserving_user(user_schema, generated_schema or build_schema_from_context({**context, "competitors": competitors}))
    return competitors, schema


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
                "skill_category": field.get("skill_category") or "general",
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
