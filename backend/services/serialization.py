from typing import Any

from models_db import SourceMaterialRecord, SurveyArtifactRecord, SurveyCampaignRecord, SurveyResponseRecord, TaskRecord


def serialize_task(db_task: TaskRecord) -> dict[str, Any]:
    return {
        "task_id": db_task.id,
        "task_name": db_task.task_name,
        "domain": db_task.domain,
        "main_product": db_task.main_product,
        "competitors": db_task.competitors or [],
        "execution_mode": db_task.execution_mode,
        "analysis_goal": db_task.analysis_goal or "",
        "task_intent": db_task.task_intent or {},
        "state": db_task.state,
        "progress": db_task.progress or 0,
        "run_id": db_task.active_run_id,
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
        "schema_field_id": source.schema_field_id,
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


def serialize_survey_campaign(campaign: SurveyCampaignRecord, artifacts: list[SurveyArtifactRecord] | None = None) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "task_id": campaign.task_id,
        "status": campaign.status,
        "platform": campaign.platform,
        "objective": campaign.objective,
        "target_persona": campaign.target_persona,
        "response_count": campaign.response_count or 0,
        "external_survey_id": campaign.external_survey_id,
        "survey_url": campaign.survey_url,
        "channels": campaign.channels or [],
        "artifacts": [serialize_survey_artifact(item) for item in artifacts or []],
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
    }


def serialize_survey_artifact(artifact: SurveyArtifactRecord) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "campaign_id": artifact.campaign_id,
        "type": artifact.type,
        "content_json": artifact.content_json or {},
        "status": artifact.status,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }


def serialize_survey_response(response: SurveyResponseRecord) -> dict[str, Any]:
    return {
        "id": response.id,
        "campaign_id": response.campaign_id,
        "source": response.source,
        "external_response_id": response.external_response_id,
        "respondent_meta_json": response.respondent_meta_json or {},
        "response_json": response.response_json or {},
        "pii_redacted": response.pii_redacted,
        "created_at": response.created_at.isoformat() if response.created_at else None,
    }
