from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .discoverer import discoverer_node
from .orchestrator import orchestrator_node
from .collector import collector_node
from .analyzer import analyzer_node
from .critic import critic_node
from .reporter import reporter_node

def human_review_node(state: AgentState):
    # Just mark the state as needing human review
    state["needs_human_review"] = True
    state["is_approved"] = False
    
    # Prepend a disclaimer to the analysis results if it's a dict
    results = state.get("analysis_results", {})
    if isinstance(results, dict) and "report" in results:
        report = results["report"]
        if isinstance(report, dict):
            disclaimer = "系统在多次尝试后无法完全提取所有指标。本报告由 AI 生成，目前状态为低置信度草稿，请人工跟进缺失维度后发布。"
            report["summary"] = disclaimer + "\n\n" + report.get("summary", "")
            results["report"] = report
            state["analysis_results"] = results
            
    return state

workflow = StateGraph(AgentState)

workflow.add_node("discoverer", discoverer_node)
workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("collector", collector_node)
workflow.add_node("analyzer", analyzer_node)
workflow.add_node("critic", critic_node)
workflow.add_node("reporter", reporter_node)
workflow.add_node("human_review", human_review_node)

workflow.add_edge(START, "discoverer")
workflow.add_edge("discoverer", "orchestrator")
workflow.add_edge("orchestrator", "collector")
workflow.add_edge("collector", "analyzer")
workflow.add_edge("analyzer", "critic")

def route_after_critic(state: AgentState) -> str:
    feedback = state.get("critic_feedback", [])
    retry_counts = state.get("retry_counts", {})
    
    total_retries = sum(retry_counts.values()) if isinstance(retry_counts, dict) else 0
        
    for item in feedback:
        if not isinstance(item, dict):
            continue
        action = item.get("suggested_action")
        if action == "retry_collection":
            return "collector"
        if action == "extend_schema":
            return "orchestrator"
        if action == "retry_analysis":
            return "analyzer"

    return "reporter"

def route_after_reporter(state: AgentState) -> str:
    retry_counts = state.get("retry_counts", {})
    total_retries = sum(retry_counts.values()) if isinstance(retry_counts, dict) else 0
    if total_retries >= 3:
        return "human_review"
    return END

workflow.add_conditional_edges(
    "critic",
    route_after_critic,
    {
        "collector": "collector",
        "orchestrator": "orchestrator",
        "analyzer": "analyzer",
        "reporter": "reporter"
    }
)

workflow.add_conditional_edges(
    "reporter",
    route_after_reporter,
    {
        "human_review": "human_review",
        END: END
    }
)

workflow.add_edge("human_review", END)

# Note: The app compilation with the checkpointer will happen in main.py
# where the AsyncPostgresSaver pool is managed.
