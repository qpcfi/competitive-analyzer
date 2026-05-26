from typing import Dict, TypedDict, Any, List

class AgentState(TypedDict):
    task_id: str
    task_context: Dict[str, Any]
    dynamic_schema: Dict[str, Any]
    schema_version: int
    raw_materials: List[Dict[str, Any]]
    source_ids: List[str]
    analysis_results: Dict[str, Any]
    critic_feedback: List[Dict[str, Any]]
    task_events: List[Dict[str, Any]]
    progress: int
    module_updates: List[Dict[str, Any]]
    retry_counts: Dict[str, int]
