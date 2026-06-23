import json
import os
import re
import yaml
from collections.abc import Iterable
from dataclasses import dataclass
from types import SimpleNamespace

try:
    from langchain_core.messages import HumanMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    HumanMessage = None
    ChatPromptTemplate = None

from dotenv import load_dotenv
load_dotenv()


from ..state import AgentState
from ..schemas import PlanCompletionResult, CompetitorRecommendationResult
from ..shared.llm import create_chat_llm
from core.callbacks import RealtimeDebugCallbackHandler

llm = create_chat_llm(timeout=90)


def field_key(field: dict) -> str:
    """Normalize a schema field dict to a comparable key (lowercased name)."""
    return (field.get("name") or field.get("id") or "").lower().strip()


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
            task_intent = context.get("task_intent") or {}

            response = await chain.ainvoke({
                "domain": domain,
                "competitors": json.dumps(seed_competitors, ensure_ascii=False),
                "user_schema": json.dumps(user_schema, ensure_ascii=False),
                "market_context": context.get("market_context") or "No additional context.",
                "analysis_goal": context.get("analysis_goal") or "通用竞品分析",
                "task_intent": json.dumps(task_intent, ensure_ascii=False),
            }, config=config)
            
            content = str(response.content)
            match = re.search(r"\{.*\}", content, re.DOTALL)
            result = json.loads(match.group(0) if match else content)
            
            generated_competitors = normalize_competitor_names(result.get("competitors", []))
            generated_schema = normalize_schema_input(result.get("schema_def", result.get("schema", {})))
            generated_schema = align_schema_with_task_intent(generated_schema, task_intent)
        except Exception as e:
            import logging
            logging.error(f"Error in generate_complete_plan: {e}")
            generated_schema = {}

    competitors = merge_competitors(seed_competitors, generated_competitors)[:5]

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
                normalized[group].append({"name": field})
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
            user_name = field.get("name", "")
            if key in existing_names:
                target[:] = [
                    {
                        **item,
                        **field,
                        "origin": "user",
                        "skill_category": field.get("skill_category") or item.get("skill_category"),
                        "axis": field.get("axis") or item.get("axis") or group_name,
                        "description": field.get("description") or item.get("description") or user_name,
                    }
                    if field_key(item) == key else item
                    for item in target
                ]
            else:
                target.append({
                    **field,
                    "origin": "user",
                    "axis": field.get("axis") or group_name,
                    "description": field.get("description") or user_name,
                })
                existing_names.add(key)
    return merged


def align_schema_with_task_intent(schema: dict, task_intent: dict | None) -> dict:
    """Set axis on primary-group fields from task_intent.primary_axes names."""
    normalized = normalize_schema_input(schema)
    axis_map = _normalize_task_axes(task_intent)
    if not normalized or not axis_map:
        return normalized

    aligned: dict[str, list[dict]] = {}
    for group_name, fields in normalized.items():
        matched_axis = axis_map.get(group_name.lower())
        aligned[group_name] = []
        for field in fields:
            item = dict(field)
            if matched_axis:
                item["axis"] = matched_axis
            else:
                item["axis"] = item.get("axis") or group_name
            aligned[group_name].append(item)
    return aligned


def _normalize_task_axes(task_intent: dict | None) -> dict[str, str]:
    """Return {lowercase_name: display_name} for each primary axis."""
    if not isinstance(task_intent, dict):
        return {}
    axes = task_intent.get("primary_axes") or []
    result: dict[str, str] = {}
    for axis in axes if isinstance(axes, list) else []:
        if isinstance(axis, dict):
            name = str(axis.get("name") or "").strip()
        else:
            name = str(axis or "").strip()
        if name:
            result[name.lower()] = name
    return result




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
    task_intent = context.get("task_intent") or {}
    target = (task_intent or {}).get("target_object", "")

    identity_group = _identity_fallback_fields(target)
    primary_groups = _primary_fallback_groups(_normalize_task_axes(task_intent), target)
    auxiliary_group = _auxiliary_fallback_fields()

    schema: dict[str, list[dict]] = {}
    for group_name, fields in identity_group:
        schema[group_name] = fields
    for group_name, fields in primary_groups:
        # avoid duplicate group names
        suffix = 1
        base = group_name
        while group_name in schema:
            suffix += 1
            group_name = f"{base}{suffix}"
        schema[group_name] = fields
    for group_name, fields in auxiliary_group:
        if group_name not in schema:
            schema[group_name] = fields

    # Merge predefined user fields
    if predefined:
        for item in predefined:
            if isinstance(item, dict) and item.get("name"):
                schema.setdefault("User Defined", []).append({**item, "origin": "user"})

    return schema


def _identity_fallback_fields(target: str) -> list[tuple[str, list[dict]]]:
    fields = [
        {"name": "企业/品牌名称", "source": "official", "skill_category": "company", "axis": "对象识别", "description": "采集企业或品牌名称，用于对象标识和竞品区分"},
        {"name": "官方网站", "source": "official", "skill_category": "company", "axis": "对象识别", "description": "采集官方网站地址，用于验证企业身份和获取一手信息"},
        {"name": "所属细分领域", "source": "public_web", "skill_category": "company", "axis": "对象识别", "description": f"采集{target or '企业'}所属的具体细分领域，用于定位竞争范围"},
    ]
    return [("对象识别", fields)]


def _primary_fallback_groups(axes: dict[str, str], target: str) -> list[tuple[str, list[dict]]]:
    if not axes:
        default_name = target or "核心分析维度"
        desc = f"采集{default_name}的主要运作机制、能力入口和覆盖范围，用于比较竞品在该维度上的差异"
        return [
            (default_name, [
                {"name": f"{default_name}运作机制", "source": "public_web", "skill_category": "business", "axis": default_name, "description": f"采集{default_name}的运作机制和实现方式"},
                {"name": f"{default_name}能力/入口", "source": "public_web", "skill_category": "product", "axis": default_name, "description": f"采集{default_name}相关的能力、功能或服务入口"},
                {"name": f"{default_name}覆盖范围", "source": "public_web", "skill_category": "business", "axis": default_name, "description": f"采集{default_name}的覆盖范围和规模"},
                {"name": f"{default_name}公开证据", "source": "public_web", "skill_category": "technical", "axis": default_name, "description": f"采集关于{default_name}的公开可查信息"},
            ]),
        ]

    groups = []
    for axis_name in axes.values():
        groups.append((axis_name, [
            {"name": f"{axis_name}运作机制", "source": "public_web", "skill_category": "business", "axis": axis_name, "description": f"采集{axis_name}的具体运作机制和实现方式"},
            {"name": f"{axis_name}能力/入口", "source": "public_web", "skill_category": "product", "axis": axis_name, "description": f"采集{axis_name}相关的能力、功能或服务入口"},
            {"name": f"{axis_name}覆盖范围", "source": "public_web", "skill_category": "business", "axis": axis_name, "description": f"采集{axis_name}的覆盖范围和规模"},
            {"name": f"{axis_name}公开证据", "source": "public_web", "skill_category": "technical", "axis": axis_name, "description": f"采集关于{axis_name}的公开可查信息"},
        ]))
    return groups


def _auxiliary_fallback_fields() -> list[tuple[str, list[dict]]]:
    fields = [
        {"name": "主要市场", "source": "public_web", "skill_category": "business", "axis": "辅助背景", "description": "采集主要目标市场和客户群体，用于理解竞争环境和定位差异"},
        {"name": "主要产品类型", "source": "public_web", "skill_category": "product", "axis": "辅助背景", "description": "采集主要产品线或服务类型，用于对比各竞品的产品覆盖面"},
    ]
    return [("辅助背景", fields)]


def ensure_schema_metadata(schema: dict) -> dict:
    normalized = {}
    total_fields = 0
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
            normalized_field = {
                "id": field.get("id") or f"{stable_group}.{stable_name}",
                "name": field_name,
                "source": field.get("source") or "public_web",
                "origin": field.get("origin") or "agent",
                "feasibility": field.get("feasibility") or "medium",
                "skill_category": field.get("skill_category") or "company",
                "axis": field.get("axis") or group_name,
                "description": field.get("description") or field_name,
            }
            for metadata_key in ("confidence", "evidence", "affected_competitors"):
                if metadata_key in field:
                    normalized_field[metadata_key] = field[metadata_key]
            normalized[group_name].append(normalized_field)
            total_fields += 1
        if not normalized[group_name]:
            normalized.pop(group_name, None)
    if not normalized:
        return {
            "对象识别": [
                {
                    "id": "对象识别.企业品牌名称",
                    "name": "企业/品牌名称",
                    "source": "official",
                    "origin": "system",
                    "feasibility": "high",
                    "skill_category": "company",
                    "axis": "对象识别",
                    "description": "企业或品牌名称",
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
        confidence = safe_float(extension.get("confidence"), 1.0)
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
            "source": extension.get("source") or "public_web",
            "origin": "critic",
            "feasibility": "medium",
            "skill_category": extension.get("skill_category") or extension.get("skill") or "company",
            "axis": extension.get("axis") or group_name,
            "description": extension.get("description") or f"采集{field_name}的相关信息",
            "confidence": confidence,
            "evidence": extension.get("evidence") or [],
            "affected_competitors": extension.get("affected_competitors") or [],
        }
        group.append(field)
        added_fields.append({**field, "group": group_name})
    normalized = ensure_schema_metadata(updated)
    added_ids = {field.get("id") for field in added_fields if field.get("id")}
    normalized_added: list[dict] = []
    for group_name, fields in normalized.items():
        if not isinstance(fields, list):
            continue
        for field in fields:
            if isinstance(field, dict) and field.get("id") in added_ids:
                normalized_added.append({**field, "group": group_name})
    return normalized, normalized_added


def safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def make_human_message(content: str):
    if HumanMessage is not None:
        return HumanMessage(content=content)
    return SimpleNamespace(content=content)
