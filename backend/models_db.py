import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, String, JSON, DateTime

DATABASE_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/competitive_analyzer"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class TaskRecord(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True)
    task_name = Column(String)
    domain = Column(String)
    execution_mode = Column(String)
    state = Column(String)
    dynamic_schema = Column(JSON, default={})
    raw_materials = Column(JSON, default=[])
    analysis_results = Column(JSON, default={})
    final_report = Column(JSON, default={})
    created_at = Column(DateTime)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
