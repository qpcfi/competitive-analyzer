# Research: Real End-to-End Backend

## Decision: PostgreSQL is the single durable event and state store

**Rationale**: The user explicitly excludes Redis. The feature requires task
state, event replay, checkpoints, raw materials, analysis results, feedback, and
intervention history to survive reloads and backend restarts. PostgreSQL already
exists in the project and LangGraph checkpointing is already wired toward a
PostgreSQL saver, so extending PostgreSQL tables for `task_events` and workflow
records is the smallest consistent path.

**Alternatives considered**:
- Redis for SSE fan-out/replay: rejected by user requirement.
- In-memory queues only: rejected because reload/reconnect loses events and
  violates the spec.
- Filesystem JSON logs: rejected because task querying, filtering, and
  cross-entity consistency belong in the existing database.

## Decision: Preserve current frontend contract and fix backend compatibility

**Rationale**: The frontend is complete and already calls
`POST /api/v1/tasks`, `GET /api/v1/tasks/{task_id}/stream`,
`PUT /api/v1/tasks/{task_id}/schema`,
`POST /api/v1/tasks/{task_id}/resume`,
`POST /api/v1/tasks/{task_id}/reject_schema`, and
`POST /api/v1/tasks/{task_id}/partial_rerun`. Planning must treat these as the
initial contract and remove mock behavior behind them.

**Alternatives considered**:
- Redesign the frontend API: rejected because the user said the frontend is
  already complete.
- Keep static frontend fallbacks: rejected because the workflow must prove real
  end-to-end execution without mock data.

## Decision: Persist SSE events before publishing them

**Rationale**: Reconnect recovery requires clients to recover recent task
status. Each emitted event should be inserted into `task_events` before being
sent to connected clients. The live stream can still use per-process queues for
active connections, but PostgreSQL is the source of truth for replay and current
state.

**Alternatives considered**:
- Only publish to in-memory queues: rejected due to event loss.
- Poll-only frontend: rejected because current frontend uses SSE and PRD
  requires streaming visibility.

## Decision: Step-by-step mode interrupts after schema generation only for MVP

**Rationale**: The strict P1 flow requires schema review and resume. The current
frontend has schema review controls but not dedicated review screens for every
agent stage. For the first real end-to-end pass, step-by-step mode must block at
schema review, then continue through collection, analysis, and critic while
persisting all checkpoints. Later human intervention can use pause, reject, and
partial rerun endpoints.

**Alternatives considered**:
- Interrupt before every agent: rejected because current frontend would not
  provide a coherent UI for each pause point.
- Auto-run only: rejected by PRD and spec P1 user story.

## Decision: L1 validation produces degraded source records, not raw exceptions

**Rationale**: The PRD requires non-critical source failures to degrade fields
and continue. Collector failures should become records with `status=failed` or
`status=degraded`, retry count, error class, and reason. Critical failures can
move the task to `ERROR` with recoverable state.

**Alternatives considered**:
- Raise exceptions on any failed source: rejected because it blocks the main
  task unnecessarily.
- Silently skip failed sources: rejected because traceability and debugging
  require visible failure reasons.

## Decision: L2 Critic review returns structured module feedback

**Rationale**: Analyzer output must be checked for unsupported conclusions and
contradictions. Feedback must point to affected modules and recommended action
so the UI can show warnings and partial rerun can target a module.

**Alternatives considered**:
- Boolean pass/fail only: rejected because it is not actionable.
- Let the Analyzer self-approve: rejected by the two-layer quality gate.

## Decision: PII redaction runs before model calls

**Rationale**: The constitution and PRD require local redaction before LLM
processing. A shared redaction utility should process task input and collected
text before prompts are built.

**Alternatives considered**:
- Ask the model to ignore PII: rejected because sensitive data would already
  leave local control.
- Redact only final output: rejected because privacy risk occurs before output.

## Decision: Authentication is local-minimal but ownership-ready

**Rationale**: Local validation can run without a full auth provider, but the
data model must include `owner_id` and endpoint checks must centralize ownership
logic so real auth can be added without redesign.

**Alternatives considered**:
- Full auth build in this feature: rejected as outside the user's current scope.
- No owner fields: rejected because constitution requires task ownership path.
