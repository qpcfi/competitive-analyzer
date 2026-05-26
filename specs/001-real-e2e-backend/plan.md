# Implementation Plan: Real End-to-End Backend

**Branch**: `001-real-e2e-backend` | **Date**: 2026-05-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-real-e2e-backend/spec.md`

## Summary

Implement the backend work needed for the completed frontend to run a real
competitive-analysis workflow from task creation through schema review,
collection, L1/L2 quality gates, analysis, evidence-backed report rendering,
debug telemetry, stream reconnect, and targeted rerun. Remove mock-only
behavior and Redis dependency expectations; PostgreSQL is the durable store for
tasks, checkpoints, events, raw materials, analysis results, feedback, and
interventions.

## Technical Context

**Language/Version**: Python 3.12+ backend; TypeScript 5 frontend on Node.js
20-compatible runtime

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy async, asyncpg,
psycopg/psycopg-pool, LangGraph, langgraph-checkpoint-postgres, LangChain
OpenAI-compatible client, Playwright/httpx/BeautifulSoup for collection,
sse-starlette or StreamingResponse for SSE, Next.js 16.2.6, React 19.2.4,
Ant Design 6.4.3, ECharts 6.1.0

**Storage**: PostgreSQL only for feature state, task events, reconnect buffers,
LangGraph checkpoints, raw materials, analysis results, quality feedback, and
intervention logs. Redis is out of scope and must be removed from runtime
requirements for this feature.

**Testing**: Backend pytest + pytest-asyncio/httpx AsyncClient for API,
database, state transitions, and SSE contracts; frontend build/lint plus
Playwright end-to-end validation against real backend and PostgreSQL.

**Target Platform**: Local web application stack: backend on
`http://localhost:8000`, completed frontend on `http://localhost:3000`,
PostgreSQL database `competitive_analyzer`.

**Project Type**: Web application with existing Next.js frontend and FastAPI
backend.

**Performance Goals**: Active SSE task-state updates visible in the frontend
within 5 seconds for 95% of state changes; standard 3-competitor task completes
within 2 hours under normal external service conditions; reconnect recovers
current task state and relevant recent events in 95% of validation runs.

**Constraints**: Existing frontend integration points must keep working;
frontend work is limited to removing mock labels/static placeholders and
adapting only where required for real data. No Redis service. No user-visible
mock data or `*_mocked` responses in the validated workflow. Every final claim
must retain evidence or explicit degraded status. External sources and model
calls must use bounded retry/degrade behavior.

**Scale/Scope**: Single-user/local validation first, with data model fields for
future owner enforcement. One concurrent local task is the minimum supported
validation target; implementation must not prevent multiple persisted tasks.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Schema-driven traceability**: PASS. The plan requires `source_materials`
  records and evidence references on comparison values, SWOT items, report
  recommendations, and degraded markers. Dynamic schema field IDs are persisted
  and used to link collected evidence to rendered results.
- **Orchestrated state and human control**: PASS. Task states, checkpoint IDs,
  schema review gates, resume, reject/regenerate, pause, and partial rerun are
  modeled in PostgreSQL and LangGraph checkpoints. SSE emits state transitions
  and module updates.
- **Two-layer quality gates**: PASS. L1 collection validation covers required
  fields, schema types, source URL/access status, non-empty evidence, retry
  count, and degraded fallback. L2 Critic review covers unsupported claims,
  contradictions, malformed output, retry routing, and manual intervention.
- **Observable agent execution**: PASS. `task_events` persist state changes,
  debug logs, progress, token estimates, errors, and module updates for live SSE
  and reconnect replay. Debug mode can read node input/output summaries.
- **Compliance and privacy**: PASS. Collection records robots/access-policy
  decisions and redacts common PII before model processing. Owner fields are
  included so access control can be enforced without schema redesign.
- **Verification plan**: PASS. Contracts include REST and SSE payloads.
  Validation includes backend contract tests, integration tests for state
  transitions/checkpoints/quality gates, privacy tests, and Playwright real
  frontend-to-backend smoke test.

**Post-Design Re-check**: PASS. `data-model.md`, `contracts/api-and-events.md`,
and `quickstart.md` preserve the above gates with no justified violations.

## Project Structure

### Documentation (this feature)

```text
specs/001-real-e2e-backend/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api-and-events.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
backend/
├── main.py                         # Existing FastAPI app and endpoint surface
├── models_db.py                    # PostgreSQL models/session setup
├── requirements.txt                # Runtime dependencies, remove Redis
├── agents/
│   ├── state.py                    # Shared AgentState contract
│   ├── graph.py                    # LangGraph routing and retry/degrade edges
│   ├── orchestrator.py             # Dynamic schema generation/regeneration
│   ├── collector.py                # Public collection + L1 validation
│   ├── analyzer.py                 # Structured analysis output
│   └── critic.py                   # L2 semantic review
└── tests/
    ├── contract/
    ├── integration/
    └── unit/

frontend/
├── src/app/page.tsx                # Existing SSE consumer/debug panel
├── src/components/views/
│   ├── TaskConsole.tsx             # Existing task creation form
│   ├── SchemaEditor.tsx            # Existing schema save/resume/reject calls
│   ├── InfoDashboard.tsx
│   ├── CompetitorAnalysis.tsx
│   ├── SWOTAnalysis.tsx
│   └── StructuredReport.tsx
└── tests/
    └── e2e/
```

**Structure Decision**: Keep the existing two-project layout. Backend changes
extend current modules instead of adding a parallel service. Frontend changes
are narrowly scoped to remove mock labels/static fallback presentation and to
consume real persisted data from existing endpoints/events.

## Frontend/Backend Coordination Matrix

The implementation MUST treat the completed frontend as the contract consumer.
Every current button, menu action, drawer action, static panel, and SSE listener
must either be backed by a real backend endpoint/event or be converted to a
truthful disabled/empty state with no mock data.

| Frontend surface | Current behavior | Required backend support |
|------------------|------------------|--------------------------|
| `TaskConsole` submit | Calls `POST /api/v1/tasks` | Validate request, create task, persist initial state, emit real startup events |
| `TaskConsole` predefined schema controls | Static rows/buttons | Include `predefined_schema` in task creation and return active schema metadata |
| `page.tsx` SSE listeners | Listens for schema/raw/analysis/progress/debug/token/completion | Persist and emit all listed event types with replay support |
| `SchemaEditor` save draft | Calls `PUT /schema` | Persist schema version and intervention log |
| `SchemaEditor` save and continue | Calls `POST /resume` | Resume from schema checkpoint and emit collection/analysis events |
| `SchemaEditor` reject | Calls `POST /reject_schema`, backend returns mocked status today | Regenerate schema or return recoverable non-mock state |
| `Sidebar` history | Currently returns without action | `GET /api/v1/tasks` history plus snapshot restore endpoint |
| `Sidebar` debug | Currently returns without action | Use persisted debug events/state snapshot endpoint or navigate to debug state |
| `InfoDashboard` collection log/statistics/snapshots | Static data | Populate from `task_events`, `source_materials`, and task snapshots |
| `InfoDashboard` pause | Button only | `POST /pause` must pause recoverable state |
| `InfoDashboard` force next node | Button only | `POST /force_next` or equivalent controlled transition with audit log |
| `CompetitorAnalysis` table/focus data | Static data | Use `analysis_results` modules and evidence refs |
| `CompetitorAnalysis` source buttons | Opens static drawer | Source drawer must load selected evidence record |
| `CompetitorAnalysis` rerun/data intervention | Opens drawer only | Partial rerun and source intervention endpoints |
| `CompetitorAnalysis` trust/suspicion/note buttons | Button only | Feedback and note endpoints persisted per claim/source |
| `SWOTAnalysis` cards/Critic alert | Static content | Use `analysis_results.swot` and `quality_feedback` |
| `SWOTAnalysis` refresh/rerun/export | Button only | Refresh current task, partial rerun, and export endpoints |
| `StructuredReport` report/source appendix | Static content | Use final report module and source appendix from backend |
| `StructuredReport` export/share/verify links | Button only | Export, share-link, and link verification endpoints |
| `RightDrawer` source | Static source content | `GET /source-materials/{id}` plus refetch/trust actions |
| `RightDrawer` intervention | Static URL list/actions | List, add, remove, restore, and apply source interventions |
| `RightDrawer` schema advice | Static advice | Return field-level schema advice from schema metadata |
| `RightDrawer` re-run | Button only | Submit partial rerun with scope and instruction |

**Gate**: `/speckit-tasks` MUST generate tasks for every row above. The feature
is not complete until a real frontend run exercises each row or a row is
explicitly marked disabled with a non-mock explanation in the UI.

## Complexity Tracking

No constitution violations.
