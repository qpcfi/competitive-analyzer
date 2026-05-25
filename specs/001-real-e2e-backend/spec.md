# Feature Specification: Real End-to-End Backend

**Feature Branch**: `001-real-e2e-backend`

**Created**: 2026-05-25

**Status**: Draft

**Input**: User description: "请你根据三份文档和constitution撰写spec。目前不需要redis，用postgreSQL代替。注意，前端已经完成，不再需要mock，务必保证前后端全链路实际跑通"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start a Real Competitive Analysis Task (Priority: P1)

A product manager opens the completed dashboard, enters an analysis domain and
competitors, starts a task, and sees the task move from creation into schema
generation with real progress events instead of placeholder or mock responses.

**Why this priority**: Without a real task lifecycle, the completed frontend
cannot deliver any business value or prove that the backend is connected.

**Independent Test**: From the existing task-configuration view, submit a valid
analysis request and verify that the UI receives a task identifier, opens the
event stream, shows progress, and displays generated schema data for the same
task without manual backend intervention.

**Acceptance Scenarios**:

1. **Given** the backend service and project data store are running, **When** a
   user submits a task with one domain and at least two competitors, **Then** the
   UI receives a task identifier and begins showing live task events for that
   identifier.
2. **Given** a task has started, **When** schema generation completes, **Then**
   the schema review view receives the active dynamic schema and the task state
   is saved for later resume.
3. **Given** task creation fails due to invalid input or unavailable services,
   **When** the user submits the task, **Then** the UI receives a clear failure
   response and no phantom task appears in history or live progress.

---

### User Story 2 - Review Schema and Continue the Real Workflow (Priority: P1)

A business analyst reviews the generated schema in the existing schema editor,
edits or confirms it, and resumes the same task so collection, quality checks,
analysis, and report generation proceed against persisted task state.

**Why this priority**: The product requires step-by-step control at schema
review and cannot be considered end-to-end unless resume moves the real task
forward.

**Independent Test**: Start a step-by-step task, wait for schema review, update
one schema field from the frontend, confirm the schema, and verify collection
and analysis events continue for the same task without restarting from scratch.

**Acceptance Scenarios**:

1. **Given** a task is waiting for schema review, **When** the user saves schema
   edits, **Then** the edited schema becomes the active schema for subsequent
   collection and analysis.
2. **Given** a reviewed schema is confirmed, **When** the user resumes the task,
   **Then** the next workflow stages emit collection, analysis, quality, and
   completion events for the same task.
3. **Given** the user rejects the generated schema, **When** regeneration is
   requested, **Then** the system performs a real regeneration or returns a
   recoverable status that lets the user retry without mock wording or dead-end
   behavior.

---

### User Story 3 - Inspect Evidence-Backed Results and Debug Progress (Priority: P2)

A product manager, analyst, or researcher watches collection and analysis
progress, opens report sections, and verifies that visible claims include
evidence, source information, quality status, and debug telemetry.

**Why this priority**: The core product promise is trusted competitive analysis,
not just generated text.

**Independent Test**: Complete a task using the existing frontend and verify
that collected materials, analysis results, SWOT content, report content,
progress, token usage, and debug logs are populated from the task execution
rather than static example data.

**Acceptance Scenarios**:

1. **Given** a task is collecting source data, **When** sources are accepted,
   degraded, or skipped, **Then** the information dashboard updates with the
   current source records and quality status.
2. **Given** an analysis result is rendered, **When** the user inspects a claim,
   **Then** the claim can be traced to source evidence, acquisition time,
   responsible agent, and trust or degraded status.
3. **Given** debug mode is enabled, **When** the task runs, **Then** the debug
   panel shows live agent events, progress, token usage estimates, and stored
   state snapshots for the current task.

---

### User Story 4 - Recover from Failures and Run Targeted Updates (Priority: P3)

A user can recover from failed collection, review quality feedback, and request
a targeted rerun for a selected module without losing completed task state or
blocking unrelated results.

**Why this priority**: Competitive research involves unreliable external data
and model outputs; users need bounded recovery rather than stalled workflows.

**Independent Test**: Force one source or module to fail, verify that the task
records a degraded status and continues where allowed, then submit a targeted
rerun instruction and confirm only the affected result is updated.

**Acceptance Scenarios**:

1. **Given** a non-critical source cannot be collected, **When** retry limits
   are reached, **Then** the field or module is marked degraded and the main
   task continues.
2. **Given** a quality review finds unsupported conclusions, **When** automatic
   retry limits are reached, **Then** the affected module shows actionable
   feedback and asks for manual intervention.
3. **Given** the user requests a targeted rerun, **When** the rerun completes,
   **Then** the selected module updates while prior task evidence and unrelated
   modules remain available.

---

### Edge Cases

- A user submits fewer than two competitors or an empty analysis domain.
- The browser connects to the event stream after the task has already emitted
  early events.
- The event stream disconnects during collection or analysis.
- Schema review remains pending while the user reloads the page.
- A source is blocked by access policy, times out, or returns unusable content.
- A model response is malformed, unsupported by evidence, or contradicts
  collected source material.
- The completed frontend sends a request shape that differs from backend
  expectations.
- A task is resumed, rejected, paused, or rerun after it has already completed.
- Sensitive user-provided or collected text appears before model processing.

### Evidence, State, and Compliance Requirements *(mandatory when applicable)*

- **Traceability**: Every rendered claim, comparison value, SWOT item, report
  recommendation, and collected source record must retain source URL or source
  identifier, evidence quote or extracted data, acquisition timestamp,
  responsible agent or workflow stage, and trust/degraded status.
- **State Control**: Tasks must persist state across creation, schema
  generation, schema review, collection, analysis, quality review, completion,
  failure, pause, resume, rejection, and targeted rerun. Step-by-step mode must
  wait at review gates; automatic mode must still preserve reviewable snapshots.
- **Quality Gates**: Collection output must pass deterministic validation for
  required fields, schema type compatibility, non-empty evidence, and source
  validity. Analysis output must pass semantic review for evidence support,
  contradiction risk, and unsupported conclusion risk. Retry limits and manual
  intervention states must be visible to the user.
- **Observability**: The existing frontend must receive live events for task
  state changes, schema readiness, raw material updates, analysis progress,
  progress percentage, debug logs, token usage estimates, module updates,
  failures, and completion. Reconnecting clients must be able to recover recent
  task status from persisted task records.
- **Compliance & Privacy**: Collection must respect public-data access policy
  before fetching. User-provided and collected text must be redacted for common
  personal data before model processing. Users must not be able to read or
  mutate tasks they do not own once authentication or ownership data is present.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept task creation from the completed frontend using
  the current task form fields and return a task identifier and initial state.
- **FR-002**: System MUST validate task creation input and reject missing domain,
  fewer than two competitors, unsupported execution mode, and malformed
  predefined schema with clear errors.
- **FR-003**: System MUST persist every task and its current state so page reload,
  stream reconnect, and resume actions continue the same workflow.
- **FR-004**: System MUST generate an editable dynamic schema for the requested
  domain and competitors, including enough field metadata for the existing
  schema editor to render it.
- **FR-005**: Users MUST be able to save schema edits and make those edits the
  active schema for all later collection and analysis.
- **FR-006**: Users MUST be able to confirm a reviewed schema and resume the
  task from the persisted review point.
- **FR-007**: Users MUST be able to reject a schema and receive a real
  regeneration or recoverable retry path without mock-only responses.
- **FR-008**: System MUST collect or ingest source material for each active
  schema dimension and competitor, with explicit accepted, skipped, failed, or
  degraded status per source or field.
- **FR-009**: System MUST run deterministic collection validation before source
  material is accepted into shared task state.
- **FR-010**: System MUST analyze accepted source material into comparison,
  SWOT, and structured-report data that the existing frontend can render.
- **FR-011**: System MUST run semantic quality review before marking analysis
  results final, and must expose quality feedback when results are unsupported
  or contradictory.
- **FR-012**: System MUST publish live events compatible with the existing
  frontend listeners for schema readiness, raw material updates, analysis
  progress, progress updates, debug logs, token usage, and task completion.
- **FR-013**: System MUST replace all user-visible mock behavior in the
  end-to-end workflow with real task state, real persisted data, or explicit
  recoverable error states.
- **FR-014**: System MUST use the project's durable relational store for task
  state, checkpoints, event recovery, source materials, analysis results,
  quality feedback, and intervention logs; no separate Redis service is in
  scope for this feature.
- **FR-015**: System MUST support reconnect recovery by allowing the frontend to
  recover current task status and recently relevant task events after stream
  interruption.
- **FR-016**: System MUST support targeted module rerun requests and preserve
  unchanged evidence and results outside the rerun scope.
- **FR-017**: System MUST expose clear task failure, retry, degraded, and manual
  intervention states to the existing frontend.
- **FR-018**: System MUST record debug telemetry for each workflow stage,
  including stage name, status, timing, token estimate when available, retry
  count, and error class when applicable.
- **FR-019**: System MUST apply public-data access checks and record blocked,
  allowed, timeout, and degraded decisions for collection attempts.
- **FR-020**: System MUST redact common personal data from user input and
  collected text before model processing.
- **FR-021**: System MUST maintain compatibility with the completed frontend's
  existing screens and integration points; frontend changes in this feature are
  limited to removing mock labels or adapting only where required for real data.
- **FR-022**: System MUST provide a repeatable validation path proving that a
  user can run the completed frontend against the backend from task creation to
  final report without mock data.
- **FR-023**: System MUST provide backend support for every existing frontend
  button, menu action, drawer action, and API call, or the frontend must present
  a truthful disabled/empty state instead of silently doing nothing.
- **FR-024**: System MUST replace static frontend analysis, source, SWOT,
  report, history, debug, and drawer content with backend-provided task data or
  explicit loading, empty, or error states.
- **FR-025**: System MUST support report export, report sharing, source link
  verification, source refetch, source trust updates, user notes, task history,
  and snapshot restore because these actions already exist in the completed
  frontend surface.

### Key Entities *(include if feature involves data)*

- **Task**: A user-created competitive analysis workflow with task name, domain,
  competitors, execution mode, current state, progress, timestamps, and owner
  context when available.
- **Dynamic Schema**: The active set of comparison dimensions, groups, fields,
  field types, required status, source expectations, user edits, and feasibility
  notes that controls collection and rendering.
- **Source Material**: A collected or user-added evidence record with source
  location, quote or extracted value, acquisition time, responsible workflow
  stage, validation status, trust status, and degraded reason when applicable.
- **Analysis Result**: Structured comparison, SWOT, and report content produced
  from accepted source material, including links back to evidence and quality
  feedback.
- **Quality Feedback**: Deterministic or semantic validation output describing
  missing fields, invalid evidence, unsupported claims, contradictions, retry
  decisions, and manual intervention instructions.
- **Task Event**: A persisted live-update record that describes state changes,
  progress, raw-material updates, analysis progress, debug logs, token usage,
  module updates, failures, and completion.
- **Intervention Log**: A record of user actions such as schema edits, source
  removals, source additions, pause/resume, rejection, and targeted reruns.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can complete a standard task with 3 competitors from the
  existing frontend through final report in 2 hours or less under normal service
  conditions.
- **SC-002**: 100% of final visible claims, comparison values, SWOT items, and
  report recommendations include accessible evidence or an explicit degraded
  marker.
- **SC-003**: 95% of task state changes appear in the frontend within 5 seconds
  during an active connection.
- **SC-004**: After a browser reload during schema review, collection, or
  analysis, the user can recover the current task state and continue in at least
  95% of validation runs.
- **SC-005**: The end-to-end validation run contains zero user-visible mock
  labels, mock-only responses, or static example results presented as task data.
- **SC-006**: Non-critical source failures do not prevent task completion in at
  least 90% of validation runs where enough alternate evidence is available.
- **SC-007**: Schema confirmation, source collection, analysis output, quality
  feedback, and final report data remain consistent for the same task across
  page reload and stream reconnect.
- **SC-008**: Common personal data patterns in input or collected text are
  redacted before model processing in 100% of privacy validation samples.

## Assumptions

- The existing frontend is the primary user interface and is already complete
  enough for the end-to-end workflow; this feature focuses on making the backend
  fulfill that frontend contract with real data.
- The durable project data store for this feature is PostgreSQL; Redis or any
  separate event broker/cache is out of scope.
- External collection uses publicly accessible sources only and may degrade
  individual fields when sources are unavailable, blocked, or low quality.
- Authentication and task ownership may be minimal in local validation, but the
  data model and access behavior must not block adding ownership enforcement.
- Model providers, network access, and public websites can fail; the workflow
  must expose retry, degraded, or manual-intervention states instead of hanging.
- Existing frontend mock labels or placeholder text may be adjusted only where
  needed to avoid presenting mock content during real end-to-end runs.
