from typing import Any

from models_db import SourceMaterialRecord, TaskRecord


def serialize_task(db_task: TaskRecord) -> dict[str, Any]:
    return {
        "task_id": db_task.id,
        "task_name": db_task.task_name,
        "domain": db_task.domain,
        "competitors": db_task.competitors or [],
        "execution_mode": db_task.execution_mode,
        "state": db_task.state,
        "progress": db_task.progress or 0,
        "dynamic_schema": db_task.dynamic_schema or {},
        "raw_materials": db_task.raw_materials or [],
        "analysis_results": db_task.analysis_results or {},
        "critic_feedback": db_task.critic_feedback or [],
        "updated_at": db_task.updated_at.isoformat() if db_task.updated_at else None,
    }


def serialize_source(source: SourceMaterialRecord) -> dict[str, Any]:
    return {
        "id": source.id,
        "competitor": source.competitor,
        "source_url": source.source_url,
        "source_type": source.source_type,
        "quote_text": source.quote_text,
        "extracted_value": source.extracted_value,
        "fetch_timestamp": source.fetch_timestamp.isoformat() if source.fetch_timestamp else None,
        "agent_node": source.agent_node,
        "access_status": source.access_status,
        "validation_status": source.validation_status,
        "trust_status": source.trust_status,
        "retry_count": source.retry_count,
        "degraded_reason": source.degraded_reason,
        "pii_redacted": source.pii_redacted,
        "is_noise": source.is_noise,
        "metadata": {},
    }
