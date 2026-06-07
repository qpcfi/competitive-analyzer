import json
import os
import re
import yaml
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    ChatOpenAI = None
    HumanMessage = None
    ChatPromptTemplate = None
from ..shared.analysis_angles import VALID_ANGLE_KEYS
from ..state import AgentState
from ..schemas import CriticResult
from core.callbacks import RealtimeDebugCallbackHandler

api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
llm = (
    ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, timeout=90)
    if api_key and ChatOpenAI is not None
    else None
)

async def critic_node(state: AgentState):
    analysis_results = state.get("analysis_results", {})
    schema = state.get("dynamic_schema", {})
    materials = state.get("raw_materials", [])
    if llm is None or ChatPromptTemplate is None:
        state["critic_feedback"] = build_structured_feedback(analysis_results)
        state["suggested_schema_extensions"] = build_deterministic_schema_extensions(schema, materials)
        return state
    
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            PROMPT_CONFIG = yaml.safe_load(f)
    except Exception:
        state["critic_feedback"] = build_structured_feedback(analysis_results)
        state["suggested_schema_extensions"] = build_deterministic_schema_extensions(schema, materials)
        return state

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", PROMPT_CONFIG["critic_agent"]["system_prompt"]),
        ("human", PROMPT_CONFIG["critic_agent"]["human_template"])
    ])

    chain = prompt_template | llm
    
    try:
        task_id = state.get("task_id")
        task_context = state.get("task_context") or {}
        analysis_goal = task_context.get("analysis_goal") or ""
        selected_angles = (analysis_results or {}).get("selected_angles") or []
        callbacks = [RealtimeDebugCallbackHandler(task_id)] if task_id else None
        config = {"callbacks": callbacks} if callbacks else None
        response = await chain.ainvoke({
            "schema": json.dumps(schema, ensure_ascii=False),
            "materials": json.dumps(materials, ensure_ascii=False),
            "analysis_results": json.dumps(analysis_results, ensure_ascii=False),
            "analysis_goal": analysis_goal,
            "selected_angles_json": json.dumps(selected_angles, ensure_ascii=False),
        }, config=config)
        
        content = str(response.content)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group(0) if match else content)
    except Exception as e:
        import logging
        logging.error(f"Error in critic_node: {e}")
        parsed = {"feedback": build_structured_feedback(analysis_results), "suggested_schema_extensions": []}
        
    if isinstance(parsed, list):
        feedback = parsed
        suggested_schema_extensions = []
    elif isinstance(parsed, dict):
        feedback = normalize_critic_feedback(parsed.get("feedback") or [])
        suggested_schema_extensions = normalize_schema_extensions(parsed.get("suggested_schema_extensions") or [])
    else:
        feedback = build_structured_feedback(analysis_results)
        suggested_schema_extensions = []

    if feedback and isinstance(feedback[0], str):
        feedback = [
            {
                "level": "L2",
                "target_type": "analysis_result",
                "target_id": "analysis",
                "module_id": "analysis",
                "severity": "warning",
                "code": "critic_message",
                "message": item,
                "suggested_action": "retry_analysis",
                "retry_count": 0,
            }
            for item in feedback
        ]
        
    state["critic_feedback"] = feedback
    state["suggested_schema_extensions"] = suggested_schema_extensions
    retry_counts = state.get("retry_counts", {})
    for item in feedback:
        action = item.get("suggested_action")
        if action in ("retry_analysis", "retry_collection", "extend_schema"):
            retry_counts[action] = int(retry_counts.get(action, 0)) + 1
    state["retry_counts"] = retry_counts
    return state


def build_structured_feedback(analysis_results: dict) -> list[dict]:
    comparison = analysis_results.get("comparison") if isinstance(analysis_results, dict) else None
    if not comparison:
        return [
            {
                "level": "L2",
                "target_type": "analysis_result",
                "target_id": "comparison",
                "module_id": "comparison",
                "severity": "warning",
                "code": "missing_comparison",
                "message": "Comparison module has no usable results.",
                "suggested_action": "retry_collection",
                "retry_count": 0,
            }
        ]
    degraded = [item for item in comparison if item.get("status") == "degraded"]
    if degraded:
        return [
            {
                "level": "L2",
                "target_type": "source_material",
                "target_id": item.get("competitor", "unknown"),
                "module_id": "comparison",
                "severity": "warning",
                "code": "degraded_source",
                "message": f"{item.get('competitor', 'Unknown')} has degraded source coverage.",
                "suggested_action": "retry_collection",
                "retry_count": 0,
            }
            for item in degraded
        ]
    return []


def normalize_critic_feedback(items: list) -> list[dict]:
    """Normalize LLM feedback output to system feedback schema.

    LLM prompt outputs fields like competitor/field_name/issue_type/comment,
    while the system expects level/target_type/target_id/severity/message.
    """
    if not items or not isinstance(items, list):
        return []
    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            if isinstance(item, str):
                normalized.append({
                    "level": "L2",
                    "target_type": "analysis_result",
                    "target_id": "analysis",
                    "module_id": "analysis",
                    "severity": "warning",
                    "code": "critic_message",
                    "message": item,
                    "suggested_action": "retry_analysis",
                    "retry_count": 0,
                })
            continue
        # Determine severity from issue_type
        issue_type = item.get("issue_type") or ""
        severity_map = {
            "missing_evidence": "warning",
            "contradiction": "error",
            "degraded_coverage": "warning",
            "low_quality": "warning",
            "unsupported_claim": "error",
        }
        severity = item.get("severity") or severity_map.get(issue_type, "warning")

        # Build a readable message from the LLM's comment field
        comment = item.get("comment") or item.get("message") or ""
        competitor = item.get("competitor") or ""
        field_name = item.get("field_name") or ""
        if comment:
            message = comment
        elif competitor and field_name:
            message = f"{competitor} {field_name}: {issue_type}"
        else:
            message = str(item)

        # Map suggested_action
        suggested_action = item.get("suggested_action") or "review"

        # Construct target_id from competitor + field
        parts = [p for p in [competitor, field_name] if p]
        target_id = item.get("target_id") or (":".join(parts) if parts else "analysis")

        normalized.append({
            "level": item.get("level") or "L2",
            "target_type": item.get("target_type") or ("source_material" if suggested_action == "retry_collection" else "analysis_result"),
            "target_id": target_id,
            "module_id": item.get("module_id") or field_name or "analysis",
            "severity": severity,
            "code": item.get("code") or issue_type or "quality_review",
            "message": message,
            "suggested_action": suggested_action,
            "retry_count": int(item.get("retry_count", 0)),
            # Preserve original fields for frontend display
            "_competitor": competitor,
            "_field_name": field_name,
            "_issue_type": issue_type,
        })
    return normalized


def normalize_schema_extensions(items: list[dict]) -> list[dict]:
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("new_field") or item.get("name") or "").strip()
        if not field_name:
            continue
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append(
            {
                "dimension_group": str(item.get("dimension_group") or item.get("group") or "Extended Attributes").strip(),
                "new_field": field_name,
                "confidence": max(0.0, min(confidence, 1.0)),
                "evidence": [str(value) for value in item.get("evidence", []) if str(value).strip()][:5],
                "affected_competitors": [str(value) for value in item.get("affected_competitors", []) if str(value).strip()][:5],
            }
        )
    return normalized[:3]


def build_deterministic_schema_extensions(schema: dict, materials: list[dict]) -> list[dict]:
    existing = {
        str(field.get("name") or field.get("id") or "").lower()
        for fields in schema.values()
        if isinstance(fields, list)
        for field in fields
        if isinstance(field, dict)
    }
    quote_text = " ".join(str(item.get("quote_text") or item.get("extracted_value") or "") for item in materials).lower()
    competitors = sorted({str(item.get("competitor")) for item in materials if item.get("competitor")})
    candidates = [
        ("Security and Compliance", "Compliance Certifications", ("soc 2", "iso 27001", "gdpr", "hipaa")),
        ("Developer Ecosystem", "API and SDK Support", ("api", "sdk", "developer")),
        ("Deployment", "Deployment Options", ("cloud", "on-prem", "self-hosted", "private deployment")),
    ]
    suggestions = []
    for group, field, keywords in candidates:
        if field.lower() in existing:
            continue
        if any(keyword in quote_text for keyword in keywords):
            suggestions.append(
                {
                    "dimension_group": group,
                    "new_field": field,
                    "confidence": 0.82,
                    "evidence": [keyword for keyword in keywords if keyword in quote_text][:3],
                    "affected_competitors": competitors[:5],
                }
            )
    return suggestions[:1]
