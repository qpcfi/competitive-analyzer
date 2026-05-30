from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .discoverer import discoverer_node
from .orchestrator import orchestrator_node
from .collector import (
    collector_general_node,
    collector_product_feature_node,
    collector_business_pricing_node,
    collector_technical_spec_node
)
from .analyzer import analyzer_node
from .critic import critic_node
from .reporter import reporter_node

def human_review_node(state: AgentState):
    state["needs_human_review"] = True
    state["is_approved"] = False
    
    results = state.get("analysis_results", {})
    if isinstance(results, dict) and "report" in results:
        report = results["report"]
        if isinstance(report, dict):
            disclaimer = "系统在多次尝试后无法完全提取所有指标。本报告由 AI 生成，目前状态为低置信度草稿，请人工跟进缺失维度后发布。"
            report["summary"] = disclaimer + "\n\n" + report.get("summary", "")
            results["report"] = report
            state["analysis_results"] = results
            
    return state

def route_after_orchestrator(state: AgentState) -> list[str]:
    # Parallel Map-Reduce fan-out
    return [
        "collector_general",
        "collector_product_feature",
        "collector_business_pricing",
        "collector_technical_spec"
    ]

def route_after_critic(state: AgentState) -> str:
    feedback = state.get("critic_feedback", [])
    retry_counts = state.get("retry_counts", {})
    
    total_retries = sum(retry_counts.values()) if isinstance(retry_counts, dict) else 0
        
    for item in feedback:
        if not isinstance(item, dict):
            continue
        action = item.get("suggested_action")
        if action == "retry_collection":
            # Target specific collector based on field category
            failed_dimension = str(item.get("failed_dimension", "")).lower()
            if "技术" in failed_dimension or "technical" in failed_dimension:
                return "collector_technical_spec"
            if "定价" in failed_dimension or "business" in failed_dimension:
                return "collector_business_pricing"
            if "特性" in failed_dimension or "功能" in failed_dimension or "feature" in failed_dimension:
                return "collector_product_feature"
            return "collector_general"
            
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

workflow = StateGraph(AgentState)

workflow.add_node("discoverer", discoverer_node)
workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("collector_general", collector_general_node)
workflow.add_node("collector_product_feature", collector_product_feature_node)
workflow.add_node("collector_business_pricing", collector_business_pricing_node)
workflow.add_node("collector_technical_spec", collector_technical_spec_node)
workflow.add_node("analyzer", analyzer_node)
workflow.add_node("critic", critic_node)
workflow.add_node("reporter", reporter_node)
workflow.add_node("human_review", human_review_node)

workflow.add_edge(START, "discoverer")
workflow.add_edge("discoverer", "orchestrator")

workflow.add_conditional_edges(
    "orchestrator", 
    route_after_orchestrator,
    {
        "collector_general": "collector_general",
        "collector_product_feature": "collector_product_feature",
        "collector_business_pricing": "collector_business_pricing",
        "collector_technical_spec": "collector_technical_spec"
    }
)

workflow.add_edge("collector_general", "analyzer")
workflow.add_edge("collector_product_feature", "analyzer")
workflow.add_edge("collector_business_pricing", "analyzer")
workflow.add_edge("collector_technical_spec", "analyzer")

workflow.add_edge("analyzer", "critic")

workflow.add_conditional_edges(
    "critic",
    route_after_critic,
    {
        "collector_general": "collector_general",
        "collector_product_feature": "collector_product_feature",
        "collector_business_pricing": "collector_business_pricing",
        "collector_technical_spec": "collector_technical_spec",
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
