# Backend API Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the backend API surface out of `backend/main.py` while preserving all existing routes and frontend contracts.

**Architecture:** `main.py` becomes app assembly only. Route handlers move into focused `APIRouter` modules, shared serializers/stats move into service helpers, and workflow globals move into a small runtime module imported by route handlers.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, LangGraph, pytest/httpx contract tests.

---

### Task 1: Shared Helpers

**Files:**
- Create: `backend/core/runtime.py`
- Create: `backend/services/stats.py`
- Create: `backend/services/serialization.py`

- [x] Move mutable workflow runtime values (`pool`, `checkpointer`, `app_auto`, `app_step`) into `backend/core/runtime.py`.
- [x] Move `count_schema_stats` and `source_stats` into `backend/services/stats.py`.
- [x] Move `serialize_task` and `serialize_source` into `backend/services/serialization.py`.

### Task 2: Workflow Pipeline

**Files:**
- Create: `backend/services/pipeline.py`
- Modify: `backend/main.py`

- [x] Move `publish_event`, `event_generator`, `make_initial_state`, `process_graph_events`, `process_agent_pipeline`, and `regenerate_schema` into `backend/services/pipeline.py`.
- [x] Update imports to use the helper modules from Task 1.

### Task 3: Routers

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/routers/__init__.py`
- Create: `backend/api/routers/discovery.py`
- Create: `backend/api/routers/tasks.py`
- Create: `backend/api/routers/schema.py`
- Create: `backend/api/routers/sources.py`
- Create: `backend/api/routers/feedback.py`
- Create: `backend/api/routers/reports.py`
- Modify: `backend/main.py`

- [x] Move each existing `@app.*` route into the matching `APIRouter`.
- [x] Keep every path, response shape, status code, and event publication behavior unchanged.
- [x] Register all routers from `main.py`.

### Task 4: Verification

**Files:**
- No source changes expected unless tests expose regressions.

- [x] Run backend contract tests for task lifecycle, schema, source intervention, frontend actions, and stream events.
- [x] Run backend unit tests for affected helpers if available.
- [x] Fix any import, route registration, or behavior regressions without changing public API paths.
