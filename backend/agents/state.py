from typing import Dict, TypedDict, Any, List

class AgentState(TypedDict):
    task_id: str
    task_context: Dict[str, Any]
    dynamic_schema: Dict[str, Any]
    raw_materials: List[Dict[str, Any]]
    analysis_results: Dict[str, Any]
    critic_feedback: List[str]
