from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .orchestrator import orchestrator_node
from .collector import collector_node
from .analyzer import analyzer_node
from .critic import critic_node

workflow = StateGraph(AgentState)

workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("collector", collector_node)
workflow.add_node("analyzer", analyzer_node)
workflow.add_node("critic", critic_node)

workflow.add_edge(START, "orchestrator")
workflow.add_edge("orchestrator", "collector")
workflow.add_edge("collector", "analyzer")
workflow.add_edge("analyzer", "critic")
workflow.add_edge("critic", END)

# Note: The app compilation with the checkpointer will happen in main.py
# where the AsyncPostgresSaver pool is managed.
