import os
import sys
from pathlib import Path
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import asyncio

# Configure uvicorn log format with timestamps (module-level for reload subprocess)
from uvicorn.config import LOGGING_CONFIG as _uvicorn_log_config
_uvicorn_log_config["formatters"]["default"]["fmt"] = "%(asctime)s [%(levelname)s] %(message)s"
_uvicorn_log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
_uvicorn_log_config["formatters"]["access"]["fmt"] = "%(asctime)s [%(levelname)s] %(client_addr)s - %(request_line)s %(status_code)s"
_uvicorn_log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=True)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agents.graph import workflow
from agents.discoverer.node import recommend_competitors
from api.routers import discovery, feedback, recovery, reports, schema, sources, survey, tasks
from api.routers.discovery import get_competitor_recommendations
from api.routers.feedback import record_feedback, save_note
from api.routers.recovery import force_next, partial_rerun, pause_task
from api.routers.reports import export_report, get_report, share_report, verify_links
from api.routers.schema import update_schema
from api.routers.sources import (
    add_source_material,
    apply_intervention,
    get_source_material,
    list_source_materials,
    refetch_source_material,
    update_source_trust,
)
from api.routers.tasks import create_task, get_task_status, list_snapshots, list_task_events, list_tasks, restore_snapshot, stream_task
from core import runtime
from models_db import async_session, init_db
from schemas import SchemaUpdateRequest
from services.pipeline import event_generator, publish_event
from services.repositories import add_intervention, get_task, save_schema, update_task_state
from services.stats import count_schema_stats
from agents.shared.llm import get_llm_config, mask_secret

try:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool
except ImportError:
    PostgresSaver = None
    ConnectionPool = None


app = FastAPI(title="Competitive Analyzer API")
GENERATED_DIR = Path(__file__).resolve().parent / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    discovery.router,
    tasks.router,
    schema.router,
    sources.router,
    survey.router,
    feedback.router,
    reports.router,
    recovery.router,
):
    app.include_router(router)


@app.on_event("startup")
async def on_startup():
    global app_auto, app_step, pool, checkpointer
    await init_db()

    if ConnectionPool is not None and PostgresSaver is not None:
        runtime.pool = ConnectionPool(
            os.environ.get("CHECKPOINT_DATABASE_URL", "postgresql://postgres:123456@127.0.0.1:5432/competitive_analyzer"),
            max_size=20,
            kwargs={"autocommit": True},
        )

        runtime.checkpointer = PostgresSaver(runtime.pool)
        runtime.checkpointer.setup()

        runtime.app_auto = workflow.compile(checkpointer=runtime.checkpointer)
        runtime.app_step = workflow.compile(checkpointer=runtime.checkpointer, interrupt_before=["collector_company", "collector_product", "collector_business", "collector_technical", "analyzer", "critic"])
    else:
        runtime.app_auto = workflow.compile()
        runtime.app_step = workflow.compile(interrupt_before=["collector_company", "collector_product", "collector_business", "collector_technical", "analyzer", "critic"])

    app_auto = runtime.app_auto
    app_step = runtime.app_step
    pool = runtime.pool
    checkpointer = runtime.checkpointer


@app.on_event("shutdown")
async def on_shutdown():
    if runtime.pool:
        runtime.pool.close()


app_auto = runtime.app_auto
app_step = runtime.app_step
pool = runtime.pool
checkpointer = runtime.checkpointer


async def get_competitor_recommendations(
    domain: str = Query(..., min_length=1),
    existing: list[str] = Query(default=[]),
):
    normalized_domain = domain.strip()
    if not normalized_domain:
        raise HTTPException(status_code=400, detail="domain is required")

    existing_names = {item.strip().lower() for item in existing if item.strip()}
    items = []
    seen = set(existing_names)
    candidates, _ = await recommend_competitors(normalized_domain, existing)
    for candidate in candidates:
        normalized_name = str(candidate.name).strip()
        lowered = normalized_name.lower()
        if not normalized_name or lowered in seen:
            continue
        seen.add(lowered)
        items.append(
            {
                "name": normalized_name,
                "reason": f"基于公开网页信号，{normalized_name} 与 {normalized_domain} 存在竞品相关性。",
            }
        )
    return {"items": items}


@app.get("/api/v1/debug/llm-config")
async def debug_llm_config():
    config = get_llm_config()
    return {
        "api_key": mask_secret(config.get("api_key")),
        "base_url": config.get("base_url"),
        "model": config.get("model"),
        "display_name": os.environ.get("LLM_DISPLAY_NAME"),
    }


async def update_schema(task_id: str, req: SchemaUpdateRequest):
    async with async_session() as session:
        db_task = await get_task(session, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        if db_task.state not in {"SCHEMA_REVIEW", "SCHEMA_GENERATING", "INITIALIZING", "PAUSED"}:
            raise HTTPException(status_code=409, detail=f"Cannot edit schema while task is {db_task.state}")
        record = await save_schema(session, task_id, req.dynamic_schema, created_by="user", status="draft")
        await add_intervention(session, task_id, "schema_update", {"schema_version": record.version})
        await update_task_state(session, task_id, state="SCHEMA_REVIEW", progress=max(db_task.progress or 0, 30))
        await session.commit()

    if app_step is not None:
        config = {"configurable": {"thread_id": task_id}}
        try:
            app_step.update_state(config, {"dynamic_schema": req.dynamic_schema, "schema_version": record.version})
        except Exception:
            pass
    await publish_event(task_id, "schema_ready", {"dynamic_schema": req.dynamic_schema, "schema_version": record.version, "stats": count_schema_stats(req.dynamic_schema)})
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "info", "message": "Schema draft saved."})
    return {"status": "updated", "schema_version": record.version, "state": "SCHEMA_REVIEW"}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
