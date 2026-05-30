from typing import Dict, TypedDict, Any, List, Annotated

def merge_materials(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not existing:
        return new
    existing_map = {item["id"]: item for item in existing if "id" in item}
    for item in new:
        if "id" in item:
            existing_map[item["id"]] = item
    return list(existing_map.values())

def merge_strings(existing: List[str], new: List[str]) -> List[str]:
    if not existing:
        return new
    s = set(existing)
    s.update(new)
    return list(s)

class AgentState(TypedDict):
    task_id: str
    task_context: Dict[str, Any]
    dynamic_schema: Dict[str, Any]
    schema_version: int
    raw_materials: Annotated[List[Dict[str, Any]], merge_materials]
    source_ids: Annotated[List[str], merge_strings]
    analysis_results: Dict[str, Any]
    critic_feedback: List[Dict[str, Any]]
    suggested_schema_extensions: List[Dict[str, Any]]
    task_events: List[Dict[str, Any]]
    progress: int
    module_updates: List[Dict[str, Any]]
    retry_counts: Dict[str, int]
