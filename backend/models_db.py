import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, text
from datetime import datetime

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:123456@localhost:5432/competitive_analyzer",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True, connect_args={"command_timeout": 60})
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class TaskRecord(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True)
    task_name = Column(String)
    domain = Column(String)
    main_product = Column(String, nullable=True)
    competitors = Column(JSON, default=list)
    execution_mode = Column(String)
    state = Column(String)
    progress = Column(Integer, default=0)
    current_checkpoint_id = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)
    error = Column(JSON, nullable=True)
    dynamic_schema = Column(JSON, default={})
    raw_materials = Column(JSON, default=[])
    analysis_results = Column(JSON, default={})
    critic_feedback = Column(JSON, default=[])
    final_report = Column(JSON, default={})
    created_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class DynamicSchemaRecord(Base):
    __tablename__ = "dynamic_schemas"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    version = Column(Integer, default=1)
    status = Column(String, default="draft")
    schema_json = Column(JSON, default={})
    field_index = Column(JSON, default=[])
    created_by = Column(String, default="agent")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class SourceMaterialRecord(Base):
    __tablename__ = "source_materials"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    schema_field_id = Column(String, nullable=True)
    competitor = Column(String)
    source_url = Column(Text, nullable=True)
    source_type = Column(String, default="unknown")
    quote_text = Column(Text, default="")
    extracted_value = Column(JSON, nullable=True)
    fetch_timestamp = Column(DateTime, default=datetime.utcnow)
    agent_node = Column(String, default="collector")
    access_status = Column(String, default="not_checked")
    validation_status = Column(String, default="pending")
    trust_status = Column(String, default="third_party")
    retry_count = Column(Integer, default=0)
    degraded_reason = Column(Text, nullable=True)
    pii_redacted = Column(Boolean, default=False)
    is_noise = Column(Boolean, default=False)
    source_stage = Column(String, default="search")


class AnalysisResultRecord(Base):
    __tablename__ = "analysis_results"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    module_id = Column(String, index=True)
    module_type = Column(String)
    version = Column(Integer, default=1)
    content = Column(JSON, default={})
    evidence_refs = Column(JSON, default=[])
    quality_status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class QualityFeedbackRecord(Base):
    __tablename__ = "quality_feedback"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    level = Column(String)
    target_type = Column(String)
    target_id = Column(String)
    module_id = Column(String, nullable=True)
    severity = Column(String, default="warning")
    code = Column(String)
    message = Column(Text)
    suggested_action = Column(String)
    retry_count = Column(Integer, default=0)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class TaskEventRecord(Base):
    __tablename__ = "task_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    sequence = Column(Integer, index=True)
    event_type = Column(String)
    payload = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)


class InterventionLogRecord(Base):
    __tablename__ = "intervention_logs"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    action_type = Column(String)
    payload = Column(JSON, default={})
    actor_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaskSnapshotRecord(Base):
    __tablename__ = "task_snapshots"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    checkpoint_id = Column(String)
    state = Column(String)
    summary = Column(Text)
    snapshot_data = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)


class UserFeedbackRecord(Base):
    __tablename__ = "user_feedback"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    target_type = Column(String)
    target_id = Column(String)
    feedback = Column(String)
    comment = Column(Text, nullable=True)
    actor_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserNoteRecord(Base):
    __tablename__ = "user_notes"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    target_type = Column(String)
    target_id = Column(String)
    note = Column(Text)
    actor_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ReportExportRecord(Base):
    __tablename__ = "report_exports"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    format = Column(String)
    status = Column(String, default="pending")
    file_path = Column(Text, nullable=True)
    share_token = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LinkVerificationResultRecord(Base):
    __tablename__ = "link_verification_results"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), index=True)
    source_material_id = Column(String, nullable=True)
    source_url = Column(Text)
    reachable = Column(Boolean, default=False)
    status_code = Column(Integer, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow)
    error = Column(Text, nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_name VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS domain VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS main_product VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS competitors JSON DEFAULT '[]'::json"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS execution_mode VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS state VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS current_checkpoint_id VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id VARCHAR"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error JSON"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS dynamic_schema JSON DEFAULT '{}'::json"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS raw_materials JSON DEFAULT '[]'::json"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS analysis_results JSON DEFAULT '{}'::json"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS critic_feedback JSON DEFAULT '[]'::json"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS final_report JSON DEFAULT '{}'::json"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"))
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"))
            await conn.execute(text("ALTER TABLE source_materials ADD COLUMN IF NOT EXISTS source_stage VARCHAR DEFAULT 'search'"))
