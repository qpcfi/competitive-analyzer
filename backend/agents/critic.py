import json
import os
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
except ImportError:
    ChatOpenAI = None
    HumanMessage = None
from .state import AgentState

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
    if llm is None:
        state["critic_feedback"] = build_structured_feedback(analysis_results)
        state["suggested_schema_extensions"] = build_deterministic_schema_extensions(schema, materials)
        return state
    
    prompt = f"""
    You are a Critic Agent for a schema-driven competitive analysis workflow.
    Evaluate the analysis for unsupported claims, contradictions, degraded coverage,
    and missing schema dimensions discovered during collection.

    Return ONLY JSON with this shape:
    {{
      "feedback": [
        {{
          "level": "L2",
          "target_type": "analysis_result",
          "target_id": "analysis",
          "module_id": "analysis",
          "severity": "warning|error",
          "code": "short_code",
          "message": "specific issue",
          "suggested_action": "review|manual_review|retry_analysis",
          "retry_count": 0
        }}
      ],
      "suggested_schema_extensions": [
        {{
          "dimension_group": "Feature Tree",
          "new_field": "Open source license support",
          "confidence": 0.0,
          "evidence": ["brief evidence from supplied materials"],
          "affected_competitors": ["name"]
        }}
      ]
    }}

    Only suggest schema extensions when multiple competitors share a meaningful
    attribute that is absent from the current schema, or when one competitor has
    a strong differentiator that belongs under Extended Attributes. Suggestions
    must be evidence-backed and confidence must be 0-1.

    Current schema: {json.dumps(schema, ensure_ascii=False)}
    Raw materials: {json.dumps(materials, ensure_ascii=False)}
    Analysis: {json.dumps(analysis_results, ensure_ascii=False)}
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        import re
        content = res.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        parsed = json.loads(match.group(0) if match else content)
    except Exception:
        parsed = {"feedback": build_structured_feedback(analysis_results), "suggested_schema_extensions": []}
    if isinstance(parsed, list):
        feedback = parsed
        suggested_schema_extensions = []
    elif isinstance(parsed, dict):
        feedback = parsed.get("feedback") or []
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
                "suggested_action": "review",
                "retry_count": 0,
            }
            for item in feedback
        ]
        
    state["critic_feedback"] = feedback
    state["suggested_schema_extensions"] = suggested_schema_extensions
    retry_counts = state.get("retry_counts", {})
    if any(item.get("suggested_action") == "retry_analysis" for item in feedback):
        retry_counts["analysis"] = int(retry_counts.get("analysis", 0)) + 1
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
                "suggested_action": "retry_analysis",
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
                "suggested_action": "manual_review",
                "retry_count": 0,
            }
            for item in degraded
        ]
    return []


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
