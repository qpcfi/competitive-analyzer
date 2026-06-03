import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models_db import (
    AnalysisResultRecord,
    DynamicSchemaRecord,
    InterventionLogRecord,
    LinkVerificationResultRecord,
    QualityFeedbackRecord,
    ReportExportRecord,
    SourceMaterialRecord,
    TaskEventRecord,
    TaskRecord,
    TaskSnapshotRecord,
    UserFeedbackRecord,
    UserNoteRecord,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def get_task(session: AsyncSession, task_id: str) -> TaskRecord | None:
    return await session.get(TaskRecord, task_id)


async def create_task_record(
    session: AsyncSession,
    *,
    task_id: str,
    task_name: str,
    domain: str,
    main_product: str | None = None,
    competitors: list[str],
    execution_mode: str,
) -> TaskRecord:
    now = datetime.utcnow()
    task = TaskRecord(
        id=task_id,
        task_name=task_name,
        domain=domain,
        main_product=main_product,
        competitors=competitors,
        execution_mode=execution_mode,
        state="INITIALIZING",
        progress=0,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    await session.flush()
    return task


async def update_task_state(
    session: AsyncSession,
    task_id: str,
    *,
    state: str | None = None,
    progress: int | None = None,
    error: dict[str, Any] | None = None,
) -> TaskRecord:
    task = await get_task(session, task_id)
    if task is None:
        raise KeyError(task_id)
    if state is not None:
        task.state = state
    if progress is not None:
        task.progress = progress
    if error is not None:
        task.error = error
    task.updated_at = datetime.utcnow()
    return task


async def save_schema(
    session: AsyncSession,
    task_id: str,
    schema_json: dict[str, Any],
    *,
    created_by: str = "agent",
    status: str = "draft",
) -> DynamicSchemaRecord:
    version = await next_schema_version(session, task_id)
    record = DynamicSchemaRecord(
        id=new_id("schema"),
        task_id=task_id,
        version=version,
        status=status,
        schema_json=schema_json,
        field_index=build_field_index(schema_json),
        created_by=created_by,
    )
    session.add(record)
    task = await get_task(session, task_id)
    if task:
        task.dynamic_schema = schema_json
        task.updated_at = datetime.utcnow()
    await session.flush()
    return record


async def latest_schema(session: AsyncSession, task_id: str) -> DynamicSchemaRecord | None:
    result = await session.execute(
        select(DynamicSchemaRecord)
        .where(DynamicSchemaRecord.task_id == task_id)
        .order_by(DynamicSchemaRecord.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def next_schema_version(session: AsyncSession, task_id: str) -> int:
    result = await session.execute(select(func.max(DynamicSchemaRecord.version)).where(DynamicSchemaRecord.task_id == task_id))
    current = result.scalar_one_or_none() or 0
    return int(current) + 1


def build_field_index(schema_json: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for group_name, group_fields in schema_json.items():
        if not isinstance(group_fields, list):
            continue
        for idx, field in enumerate(group_fields):
            if not isinstance(field, dict):
                continue
            field_id = field.get("id") or f"{group_name}.{field.get('name', idx)}"
            fields.append({**field, "id": field_id, "group": group_name})
    return fields


async def add_event(session: AsyncSession, task_id: str, event_type: str, payload: dict[str, Any]) -> TaskEventRecord:
    result = await session.execute(select(func.max(TaskEventRecord.sequence)).where(TaskEventRecord.task_id == task_id))
    sequence = int(result.scalar_one_or_none() or 0) + 1
    event = TaskEventRecord(task_id=task_id, sequence=sequence, event_type=event_type, payload=payload)
    session.add(event)
    await session.flush()
    return event


async def list_events(session: AsyncSession, task_id: str, since: int = 0, limit: int = 100) -> list[TaskEventRecord]:
    result = await session.execute(
        select(TaskEventRecord)
        .where(TaskEventRecord.task_id == task_id, TaskEventRecord.sequence > since)
        .order_by(TaskEventRecord.sequence)
        .limit(limit)
    )
    return list(result.scalars())


async def add_intervention(session: AsyncSession, task_id: str, action_type: str, payload: dict[str, Any]) -> InterventionLogRecord:
    record = InterventionLogRecord(id=new_id("intervention"), task_id=task_id, action_type=action_type, payload=payload)
    session.add(record)
    await session.flush()
    return record


async def save_source_materials(
    session: AsyncSession,
    task_id: str,
    materials: list[dict[str, Any]],
) -> list[SourceMaterialRecord]:
    records: list[SourceMaterialRecord] = []
    for i, material in enumerate(materials):
        record = SourceMaterialRecord(
            id=material.get("id") or new_id("src"),
            task_id=task_id,
            schema_field_id=material.get("schema_field_id"),
            competitor=material.get("competitor") or "",
            source_url=material.get("source_url"),
            source_type=material.get("source_type") or "web",
            quote_text=material.get("quote_text") or material.get("content") or "",
            extracted_value=material.get("extracted_value"),
            agent_node=material.get("agent_node") or "collector",
            access_status=material.get("access_status") or "accessible",
            validation_status=material.get("validation_status") or "accepted",
            trust_status=material.get("trust_status") or "third_party",
            retry_count=int(material.get("retry_count") or 0),
            degraded_reason=material.get("degraded_reason"),
            pii_redacted=bool(material.get("pii_redacted", False)),
            is_noise=bool(material.get("is_noise", False)),
        )
        session.add(record)
        records.append(record)
        if i > 0 and i % 100 == 0:
            await session.flush()
    await session.flush()
    return records


async def save_analysis_module(
    session: AsyncSession,
    task_id: str,
    *,
    module_id: str,
    module_type: str,
    content: dict[str, Any],
    evidence_refs: list[str] | None = None,
    quality_status: str = "pending",
) -> AnalysisResultRecord:
    result = await session.execute(
        select(func.max(AnalysisResultRecord.version)).where(
            AnalysisResultRecord.task_id == task_id,
            AnalysisResultRecord.module_id == module_id,
        )
    )
    version = int(result.scalar_one_or_none() or 0) + 1
    record = AnalysisResultRecord(
        id=new_id("result"),
        task_id=task_id,
        module_id=module_id,
        module_type=module_type,
        version=version,
        content=content,
        evidence_refs=evidence_refs or [],
        quality_status=quality_status,
    )
    session.add(record)
    await session.flush()
    return record


async def save_quality_feedback(
    session: AsyncSession,
    task_id: str,
    feedback_items: list[dict[str, Any]],
) -> list[QualityFeedbackRecord]:
    records: list[QualityFeedbackRecord] = []
    for item in feedback_items:
        record = QualityFeedbackRecord(
            id=item.get("id") or new_id("quality"),
            task_id=task_id,
            level=item.get("level") or "L2",
            target_type=item.get("target_type") or "analysis_result",
            target_id=item.get("target_id") or item.get("module_id") or "analysis",
            module_id=item.get("module_id"),
            severity=item.get("severity") or "warning",
            code=item.get("code") or "quality_review",
            message=item.get("message") or str(item),
            suggested_action=item.get("suggested_action") or "review",
            retry_count=int(item.get("retry_count") or 0),
            resolved=bool(item.get("resolved", False)),
        )
        session.add(record)
        records.append(record)
    await session.flush()
    return records


__all__ = [
    "AnalysisResultRecord",
    "DynamicSchemaRecord",
    "InterventionLogRecord",
    "LinkVerificationResultRecord",
    "QualityFeedbackRecord",
    "ReportExportRecord",
    "SourceMaterialRecord",
    "TaskEventRecord",
    "TaskRecord",
    "TaskSnapshotRecord",
    "UserFeedbackRecord",
    "UserNoteRecord",
    "add_event",
    "add_intervention",
    "build_field_index",
    "create_task_record",
    "get_task",
    "latest_schema",
    "list_events",
    "new_id",
    "save_analysis_module",
    "save_quality_feedback",
    "save_schema",
    "save_source_materials",
    "update_task_state",
]
