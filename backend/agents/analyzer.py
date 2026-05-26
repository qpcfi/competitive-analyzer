import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from .state import AgentState

api_key = os.environ.get("DEEPSEEK_API_KEY")
llm = (
    ChatOpenAI(api_key=api_key, base_url="https://api.deepseek.com", model="deepseek-v4-pro")
    if api_key
    else None
)

async def analyzer_node(state: AgentState):
    schema = state.get("dynamic_schema", {})
    materials = state.get("raw_materials", [])
    if llm is None:
        state["analysis_results"] = build_deterministic_analysis(state)
        return state
    
    prompt = f"""
    Analyze the following competitors based on the schema and provided raw materials.
    Schema: {json.dumps(schema, ensure_ascii=False)}
    Raw Materials: {json.dumps(materials, ensure_ascii=False)}
    
    Output a structured JSON containing the comparison and a SWOT analysis.
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        import re
        content = res.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
        else:
            result = json.loads(content)
    except Exception:
        result = build_deterministic_analysis(state)
        
    state["analysis_results"] = result
    return state


def build_deterministic_analysis(state: AgentState) -> dict:
    materials = state.get("raw_materials", [])
    competitors = state.get("task_context", {}).get("competitors", [])
    comparison = []
    for competitor in competitors:
        evidence = [item for item in materials if item.get("competitor") == competitor]
        comparison.append(
            {
                "competitor": competitor,
                "summary": evidence[0].get("quote_text", "")[:240] if evidence else "",
                "status": "degraded" if evidence and evidence[0].get("validation_status") == "degraded" else "accepted",
                "evidence_refs": [item.get("id") for item in evidence if item.get("id")],
            }
        )
    evidence_refs = [item.get("id") for item in materials if item.get("id")]
    return {
        "comparison": comparison,
        "swot": {
            "strengths": [{"text": "Public information is available for comparison.", "evidence_refs": evidence_refs[:2]}],
            "weaknesses": [{"text": "Some fields may require manual verification.", "evidence_refs": evidence_refs[:2]}],
            "opportunities": [{"text": "Use verified sources to refine positioning.", "evidence_refs": evidence_refs[:2]}],
            "threats": [{"text": "Source gaps can reduce confidence.", "evidence_refs": evidence_refs[:2]}],
        },
        "report": {
            "summary": "Analysis generated from collected public source materials.",
            "findings": comparison,
            "recommendations": ["Review degraded sources before publishing."],
            "source_appendix": materials,
        },
        "evidence_refs": evidence_refs,
    }
