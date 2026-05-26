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
    if llm is None:
        state["critic_feedback"] = build_structured_feedback(analysis_results)
        return state
    
    prompt = f"""
    You are a Critic Agent. Evaluate the following analysis results for completeness and hallucination.
    If there are issues, output a JSON list of strings (feedback). If perfect, output an empty list [].
    
    Analysis: {json.dumps(analysis_results, ensure_ascii=False)}
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        import re
        content = res.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            feedback = json.loads(match.group(0))
        else:
            feedback = json.loads(content)
    except Exception:
        feedback = build_structured_feedback(analysis_results)
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
