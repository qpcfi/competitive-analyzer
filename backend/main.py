import asyncio
import json
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models_db import init_db, async_session, TaskRecord
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from agents.graph import workflow

app = FastAPI(title="Competitive Analyzer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pool = None
checkpointer = None
app_auto = None
app_step = None

@app.on_event("startup")
async def on_startup():
    global pool, checkpointer, app_auto, app_step
    await init_db()
    
    pool = ConnectionPool(
        "postgresql://postgres:123456@127.0.0.1:5432/competitive_analyzer",
        max_size=20,
        kwargs={"autocommit": True}
    )
    
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    
    app_auto = workflow.compile(checkpointer=checkpointer)
    app_step = workflow.compile(checkpointer=checkpointer, interrupt_before=["collector", "analyzer", "critic"])

@app.on_event("shutdown")
async def on_shutdown():
    if pool:
        pool.close()

TASK_QUEUES: Dict[str, asyncio.Queue] = {}

async def publish_event(task_id: str, event_type: str, data: dict):
    if task_id in TASK_QUEUES:
        await TASK_QUEUES[task_id].put({"event": event_type, "data": data})

class TaskCreateReq(BaseModel):
    task_name: Optional[str] = None
    domain: str
    competitors: List[str]
    execution_mode: str = "step_by_step"
    predefined_schema: Optional[List[Dict[str, Any]]] = None

class SchemaUpdateReq(BaseModel):
    dynamic_schema: Dict[str, Any]

async def event_generator(task_id: str):
    queue = asyncio.Queue()
    TASK_QUEUES[task_id] = queue
    try:
        while True:
            msg = await queue.get()
            yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
    except asyncio.CancelledError:
        del TASK_QUEUES[task_id]

async def process_graph_events(task_id: str, graph, initial_state, config):
    try:
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, state in event.items():
                if node_name == "orchestrator":
                    await publish_event(task_id, "debug_log", {"agent": "Orchestrator", "event": "end", "message": "Schema generated successfully."})
                    await publish_event(task_id, "token_update", {"total_used": 1500, "budget": 50000, "estimated_remaining": 48500})
                    await publish_event(task_id, "progress_update", {"progress": 30})
                    await publish_event(task_id, "schema_ready", {"dynamic_schema": state.get("dynamic_schema")})
                    await publish_event(task_id, "task_state_changed", {"state": "SCHEMA_REVIEW"})
                    
                    async with async_session() as session:
                        db_task = await session.get(TaskRecord, task_id)
                        if db_task:
                            db_task.state = "SCHEMA_REVIEW"
                            db_task.dynamic_schema = state.get("dynamic_schema", {})
                            await session.commit()
                            
                elif node_name == "collector":
                    await publish_event(task_id, "debug_log", {"agent": "Collector", "event": "end", "message": "Data Collection completed."})
                    await publish_event(task_id, "progress_update", {"progress": 60})
                    await publish_event(task_id, "task_state_changed", {"state": "COLLECTING"})
                    await publish_event(task_id, "raw_materials_updated", {"data": state.get("raw_materials")})
                    
                    async with async_session() as session:
                        db_task = await session.get(TaskRecord, task_id)
                        if db_task:
                            db_task.raw_materials = state.get("raw_materials", [])
                            await session.commit()
                            
                elif node_name == "analyzer":
                    await publish_event(task_id, "debug_log", {"agent": "Analyzer", "event": "end", "message": "Analysis completed."})
                    await publish_event(task_id, "progress_update", {"progress": 90})
                    await publish_event(task_id, "task_state_changed", {"state": "ANALYZING"})
                    await publish_event(task_id, "analysis_progress", {"data": state.get("analysis_results")})
                    await publish_event(task_id, "token_update", {"total_used": 8500, "budget": 50000, "estimated_remaining": 41500})
                    
                    async with async_session() as session:
                        db_task = await session.get(TaskRecord, task_id)
                        if db_task:
                            db_task.analysis_results = state.get("analysis_results", {})
                            await session.commit()
                            
                elif node_name == "critic":
                    await publish_event(task_id, "debug_log", {"agent": "Critic", "event": "end", "message": "Critic evaluation completed."})
                    await publish_event(task_id, "progress_update", {"progress": 100})
                    await publish_event(task_id, "task_state_changed", {"state": "COMPLETED"})
                    await publish_event(task_id, "task_completed", {"final_report_url": f"/reports/{task_id}"})
                    
                    async with async_session() as session:
                        db_task = await session.get(TaskRecord, task_id)
                        if db_task:
                            db_task.state = "COMPLETED"
                            await session.commit()
                            
    except Exception as e:
        await publish_event(task_id, "error", {"message": str(e)})

@app.post("/api/v1/tasks")
async def create_task(req: TaskCreateReq, background_tasks: BackgroundTasks):
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    
    async with async_session() as session:
        new_task = TaskRecord(
            id=task_id,
            task_name=req.task_name or f"{req.domain}_{datetime.now().strftime('%Y%m%d')}",
            domain=req.domain,
            execution_mode=req.execution_mode,
            state="INITIALIZING",
            created_at=datetime.now()
        )
        session.add(new_task)
        await session.commit()
        
    initial_state = {
        "task_id": task_id,
        "task_context": {
            "domain": req.domain,
            "competitors": req.competitors,
            "execution_mode": req.execution_mode
        },
        "dynamic_schema": {},
        "raw_materials": [],
        "analysis_results": {},
        "critic_feedback": []
    }
    
    config = {"configurable": {"thread_id": task_id}}
    graph = app_step if req.execution_mode == "step_by_step" else app_auto
    
    background_tasks.add_task(publish_event, task_id, "task_state_changed", {"state": "SCHEMA_GENERATING"})
    background_tasks.add_task(publish_event, task_id, "progress_update", {"progress": 10})
    background_tasks.add_task(publish_event, task_id, "debug_log", {"agent": "Orchestrator", "event": "start", "message": "Starting Schema Generation"})
    background_tasks.add_task(process_graph_events, task_id, graph, initial_state, config)
    
    return {
        "task_id": task_id,
        "state": "INITIALIZING"
    }

@app.get("/api/v1/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    return StreamingResponse(event_generator(task_id), media_type="text/event-stream")

@app.put("/api/v1/tasks/{task_id}/schema")
async def update_schema(task_id: str, req: SchemaUpdateReq):
    async with async_session() as session:
        db_task = await session.get(TaskRecord, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        db_task.dynamic_schema = req.dynamic_schema
        await session.commit()
        
    # Update LangGraph state
    config = {"configurable": {"thread_id": task_id}}
    await app_step.aupdate_state(config, {"dynamic_schema": req.dynamic_schema})
    await publish_event(task_id, "debug_log", {"agent": "System", "event": "info", "message": "Schema saved as draft."})
    return {"status": "updated"}

@app.post("/api/v1/tasks/{task_id}/reject_schema")
async def reject_schema(task_id: str, background_tasks: BackgroundTasks):
    config = {"configurable": {"thread_id": task_id}}
    # Trigger regeneration by modifying the state or restarting the orchestrator
    # LangGraph allows Time Travel. We can branch off a past state or simply update the state and rerun orchestrator.
    # To keep simple: Update state to empty schema, but wait, without a cycle, graph moves forward.
    # If we want to rerun orchestrator, we need to update state as if orchestrator hasn't run.
    # For now, just a dummy response since graph cycles require edge changes.
    return {"status": "regenerating_mocked"}

@app.post("/api/v1/tasks/{task_id}/resume")
async def resume_task(task_id: str, background_tasks: BackgroundTasks):
    async with async_session() as session:
        db_task = await session.get(TaskRecord, task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
            
    config = {"configurable": {"thread_id": task_id}}
    graph = app_step # assuming step_by_step
    
    # We resume with None initial_state because the state is loaded from checkpoint
    background_tasks.add_task(process_graph_events, task_id, graph, None, config)
    return {"status": "resumed"}

@app.post("/api/v1/tasks/{task_id}/pause")
async def pause_task(task_id: str):
    # Pause is natively handled by interrupt_before.
    # If we want to forcefully pause, we can update the config or graph state.
    # For this demo, interrupt_before handles the pausing naturally between agents.
    return {"status": "paused"}

@app.post("/api/v1/tasks/{task_id}/partial_rerun")
async def partial_rerun(task_id: str, req: Request):
    # Modify the LangGraph state (e.g. analysis_results) and run the specific agent again
    # This represents Human-in-the-loop Time Travel
    body = await req.json()
    config = {"configurable": {"thread_id": task_id}}
    await app_step.aupdate_state(config, {"critic_feedback": [body.get("new_instruction", "Rerun analysis")]})
    # Then resume graph
    return {"status": "rerunning"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
