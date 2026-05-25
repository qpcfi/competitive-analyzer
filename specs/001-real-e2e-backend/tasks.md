# Tasks: Real End-to-End Backend

**Input**: Design documents from `/specs/001-real-e2e-backend/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api-and-events.md, quickstart.md

**Tests**: Required by constitution and spec. Contract tests are required for all new/changed API and SSE payloads. Integration tests are required for state transitions, reconnect replay, quality gates, evidence propagation, privacy, and real frontend-to-backend validation.

**Organization**: Tasks are grouped by user story so each story can be independently implemented and validated.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other tasks in the same phase if dependencies are met
- **[Story]**: User-story label for story phases only
- Every task includes exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare project structure, dependency baseline, and test layout.

- [ ] T001 Remove Redis from runtime dependencies and add missing PostgreSQL/checkpoint/test dependencies in `backend/requirements.txt`
- [ ] T002 [P] Create backend test package directories and init files under `backend/tests/contract/`, `backend/tests/integration/`, and `backend/tests/unit/`
- [ ] T003 [P] Add backend pytest configuration for async FastAPI tests in `backend/pytest.ini`
- [ ] T004 [P] Add frontend end-to-end test directory and placeholder config in `frontend/tests/e2e/real_e2e_backend.spec.ts`
- [ ] T005 [P] Document local environment variables for database and model providers in `backend/.env.example`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core persistence, eventing, state contracts, and safety utilities that all user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T006 Expand PostgreSQL ORM models for Task, DynamicSchema, SourceMaterial, AnalysisResult, QualityFeedback, TaskEvent, InterventionLog, TaskSnapshot, UserFeedback, UserNote, ReportExport, and LinkVerificationResult in `backend/models_db.py`
- [ ] T007 Create repository helpers for task CRUD, schema versions, events, snapshots, source materials, analysis results, feedback, notes, and exports in `backend/services/repositories.py`
- [ ] T008 Create persisted SSE event publisher with per-task sequence numbers and replay support in `backend/services/events.py`
- [ ] T009 Replace in-memory-only task event assumptions with PostgreSQL-backed event publishing integration points in `backend/main.py`
- [ ] T010 Define request/response Pydantic models for task, schema, source, feedback, note, export, share, and rerun contracts in `backend/schemas.py`
- [ ] T011 Add shared task state enums and state-transition guard helpers in `backend/services/state_machine.py`
- [ ] T012 Add PII redaction utility and unit-testable patterns for email, phone, and identity-like values in `backend/services/privacy.py`
- [ ] T013 Add public-source access policy and robots/access-check utility with timeout/degraded results in `backend/services/access_policy.py`
- [ ] T014 Update LangGraph AgentState to carry task events, schema version, source IDs, quality feedback, progress, and module update metadata in `backend/agents/state.py`
- [ ] T015 Add common JSON extraction/validation helpers for model outputs in `backend/services/llm_json.py`
- [ ] T016 [P] Add unit tests for state-transition guards in `backend/tests/unit/test_state_machine.py`
- [ ] T017 [P] Add unit tests for PII redaction in `backend/tests/unit/test_privacy.py`
- [ ] T018 [P] Add unit tests for access-policy degraded outcomes in `backend/tests/unit/test_access_policy.py`

**Checkpoint**: Persistence, event replay, state guards, and safety utilities are ready for all stories.

---

## Phase 3: User Story 1 - Start a Real Competitive Analysis Task (Priority: P1)

**Goal**: A user can submit the existing frontend task form and see a real persisted task produce schema-generation progress over SSE.

**Independent Test**: Submit a valid task from `TaskConsole`, receive a task ID, open `/stream`, and see persisted `task_state_changed`, `progress_update`, `debug_log`, and `schema_ready` events for the same task.

### Tests for User Story 1

- [ ] T019 [P] [US1] Add contract tests for `POST /api/v1/tasks`, `GET /api/v1/tasks/{task_id}`, and task validation errors in `backend/tests/contract/test_task_lifecycle_api.py`
- [ ] T020 [P] [US1] Add contract tests for initial SSE replay and live events in `backend/tests/contract/test_task_stream_events.py`
- [ ] T021 [P] [US1] Add integration test for task creation through schema-ready state with persisted events in `backend/tests/integration/test_task_schema_generation.py`
- [ ] T022 [P] [US1] Add frontend e2e test for task submit and schema-ready UI update in `frontend/tests/e2e/real_e2e_backend.spec.ts`

### Implementation for User Story 1

- [ ] T023 [US1] Implement task creation request validation, unique competitor normalization, task persistence, and initial state events in `backend/main.py`
- [ ] T024 [US1] Persist predefined schema input and task metadata through repository helpers in `backend/services/repositories.py`
- [ ] T025 [US1] Update Orchestrator schema generation to produce stable field IDs, field metadata, source expectations, and non-mock fallback errors in `backend/agents/orchestrator.py`
- [ ] T026 [US1] Persist generated dynamic schema versions and schema-ready event payloads in `backend/main.py`
- [ ] T027 [US1] Implement `GET /api/v1/tasks/{task_id}` current-state response in `backend/main.py`
- [ ] T028 [US1] Implement `GET /api/v1/tasks/{task_id}/stream?since=` with persisted replay before live events in `backend/main.py`
- [ ] T029 [US1] Replace `TASK_QUEUES` direct publishing with `backend/services/events.py` while preserving live delivery in `backend/main.py`
- [ ] T030 [US1] Wire `TaskConsole` predefined schema controls into task creation payload or a truthful disabled state in `frontend/src/components/views/TaskConsole.tsx`
- [ ] T031 [US1] Add frontend stream reconnect/current task recovery handling in `frontend/src/app/page.tsx`

**Checkpoint**: User Story 1 can be validated independently from the frontend through schema readiness.

---

## Phase 4: User Story 2 - Review Schema and Continue the Real Workflow (Priority: P1)

**Goal**: A user can save/reject/confirm schema in the existing schema editor and resume the same real task into collection, analysis, quality review, and completion.

**Independent Test**: Start a step-by-step task, save one schema edit, confirm it, and verify collection, analysis, quality, and completion events continue for the same task without mock responses.

### Tests for User Story 2

- [ ] T032 [P] [US2] Add contract tests for `PUT /api/v1/tasks/{task_id}/schema`, `POST /resume`, and invalid state responses in `backend/tests/contract/test_schema_resume_api.py`
- [ ] T033 [P] [US2] Add contract tests for `POST /reject_schema` returning non-mock regeneration state in `backend/tests/contract/test_schema_reject_api.py`
- [ ] T034 [P] [US2] Add integration test for schema edit persistence and resume from checkpoint in `backend/tests/integration/test_schema_resume_flow.py`
- [ ] T035 [P] [US2] Add integration test for schema rejection/regeneration without `mock` or `mocked` statuses in `backend/tests/integration/test_schema_regeneration_flow.py`
- [ ] T036 [P] [US2] Extend frontend e2e test for schema save, reject, and save-and-continue controls in `frontend/tests/e2e/real_e2e_backend.spec.ts`

### Implementation for User Story 2

- [ ] T037 [US2] Implement schema draft persistence with versioning and intervention log writes in `backend/main.py`
- [ ] T038 [US2] Update LangGraph checkpoint usage so `POST /resume` continues from schema review instead of restarting in `backend/main.py`
- [ ] T039 [US2] Implement real `POST /reject_schema` regeneration path and remove `regenerating_mocked` from `backend/main.py`
- [ ] T040 [US2] Update Collector to generate source records with source URL, quote/extracted content, access status, trust status, retry count, and PII redaction flag in `backend/agents/collector.py`
- [ ] T041 [US2] Implement L1 validation and degraded source handling before raw materials enter shared task state in `backend/agents/collector.py`
- [ ] T042 [US2] Update Analyzer output to match frontend comparison, SWOT, and report module shape with evidence refs in `backend/agents/analyzer.py`
- [ ] T043 [US2] Update Critic to return structured L2 feedback by module with suggested actions and retry/degrade decisions in `backend/agents/critic.py`
- [ ] T044 [US2] Persist collection, analysis, quality feedback, token, progress, and completion events during graph execution in `backend/main.py`
- [ ] T045 [US2] Update `SchemaEditor` to render active schema data when available and show truthful loading/empty states otherwise in `frontend/src/components/views/SchemaEditor.tsx`

**Checkpoint**: User Story 2 can be validated independently from schema review through task completion.

---

## Phase 5: User Story 3 - Inspect Evidence-Backed Results and Debug Progress (Priority: P2)

**Goal**: A user can inspect collection logs, source evidence, comparison data, SWOT, reports, exports, debug telemetry, history, and all existing frontend buttons backed by real backend data.

**Independent Test**: Complete a task, navigate every existing result/debug/report/drawer surface, and verify no static task data or mock-only behavior remains.

### Tests for User Story 3

- [ ] T046 [P] [US3] Add contract tests for history, snapshots, source-material list/detail, schema advice, report, export, share, verify-links, feedback, and notes endpoints in `backend/tests/contract/test_frontend_action_api.py`
- [ ] T047 [P] [US3] Add contract tests for source/refetch/trust/intervention endpoint payloads in `backend/tests/contract/test_source_intervention_api.py`
- [ ] T048 [P] [US3] Add integration test verifying every final analysis claim has evidence refs or degraded status in `backend/tests/integration/test_evidence_traceability.py`
- [ ] T049 [P] [US3] Add integration test for persisted debug/token/progress events and reconnect replay after disconnect in `backend/tests/integration/test_event_reconnect_replay.py`
- [ ] T050 [P] [US3] Extend frontend e2e test to cover history, debug, source drawer, intervention drawer, schema advice drawer, report, export, share, and verify-links controls in `frontend/tests/e2e/real_e2e_backend.spec.ts`

### Implementation for User Story 3

- [ ] T051 [US3] Implement `GET /api/v1/tasks` history listing with snapshot counts in `backend/main.py`
- [ ] T052 [US3] Implement `GET /api/v1/tasks/{task_id}/snapshots` and `POST /restore_snapshot` in `backend/main.py`
- [ ] T053 [US3] Implement source material list/detail/add/refetch/trust endpoints in `backend/main.py`
- [ ] T054 [US3] Implement source intervention apply endpoint with source add/remove/restore semantics in `backend/main.py`
- [ ] T055 [US3] Implement field-level schema advice endpoint from schema metadata in `backend/main.py`
- [ ] T056 [US3] Implement feedback and note endpoints with persistence and event emission in `backend/main.py`
- [ ] T057 [US3] Implement report endpoint and export endpoints for JSON, Markdown, and PDF-ready response handling in `backend/main.py`
- [ ] T058 [US3] Implement report share-token and verify-links endpoints in `backend/main.py`
- [ ] T059 [US3] Replace static collection logs/statistics/snapshots with real props or endpoint data in `frontend/src/components/views/InfoDashboard.tsx`
- [ ] T060 [US3] Wire pause and force-next dashboard buttons to backend endpoints with loading/error states in `frontend/src/components/views/InfoDashboard.tsx`
- [ ] T061 [US3] Replace static comparison/focus data with `analysisResults` modules and evidence-aware source actions in `frontend/src/components/views/CompetitorAnalysis.tsx`
- [ ] T062 [US3] Wire credible/suspicious feedback and note buttons to backend endpoints in `frontend/src/components/views/CompetitorAnalysis.tsx`
- [ ] T063 [US3] Replace static SWOT cards and Critic alert with backend analysis/quality feedback data in `frontend/src/components/views/SWOTAnalysis.tsx`
- [ ] T064 [US3] Wire SWOT refresh, rerun, and export buttons to backend-backed actions or truthful disabled states in `frontend/src/components/views/SWOTAnalysis.tsx`
- [ ] T065 [US3] Replace static structured report and source appendix with backend report data in `frontend/src/components/views/StructuredReport.tsx`
- [ ] T066 [US3] Wire PDF, Markdown, JSON export, share report, and verify-all-links buttons to backend endpoints in `frontend/src/components/views/StructuredReport.tsx`
- [ ] T067 [US3] Replace static source drawer, intervention drawer, schema advice drawer, and rerun drawer content with backend data/actions in `frontend/src/components/layout/RightDrawer.tsx`
- [ ] T068 [US3] Replace `Sidebar` history/debug no-op behavior with real navigation or truthful disabled states in `frontend/src/components/layout/Sidebar.tsx`
- [ ] T069 [US3] Remove user-visible Mock/static-task labels from debug panel and result views in `frontend/src/app/page.tsx`

**Checkpoint**: User Story 3 can be validated independently by exercising every existing frontend surface against real backend data.

---

## Phase 6: User Story 4 - Recover from Failures and Run Targeted Updates (Priority: P3)

**Goal**: A user can recover from degraded collection, review quality feedback, force safe transitions, and rerun targeted modules without losing prior state.

**Independent Test**: Force a collection or quality failure, verify degraded/manual-intervention state, submit partial rerun, and confirm only the target module changes.

### Tests for User Story 4

- [ ] T070 [P] [US4] Add contract tests for `POST /force_next`, `POST /partial_rerun`, and failure-state payloads in `backend/tests/contract/test_recovery_rerun_api.py`
- [ ] T071 [P] [US4] Add integration test for non-critical source failure degrading and continuing task flow in `backend/tests/integration/test_degraded_collection_flow.py`
- [ ] T072 [P] [US4] Add integration test for L2 feedback retry limits and `NEEDS_INTERVENTION` state in `backend/tests/integration/test_quality_feedback_retry_limits.py`
- [ ] T073 [P] [US4] Add integration test for partial rerun preserving unrelated module evidence and versions in `backend/tests/integration/test_partial_rerun_versions.py`
- [ ] T074 [P] [US4] Extend frontend e2e test for degraded source display, force-next, partial rerun, and module update events in `frontend/tests/e2e/real_e2e_backend.spec.ts`

### Implementation for User Story 4

- [ ] T075 [US4] Add graph routing for retry, degrade, manual intervention, and safe terminal states in `backend/agents/graph.py`
- [ ] T076 [US4] Implement bounded retry counters for collection, analysis, and critic decisions in `backend/services/state_machine.py`
- [ ] T077 [US4] Implement `POST /api/v1/tasks/{task_id}/force_next` with state guard and intervention logging in `backend/main.py`
- [ ] T078 [US4] Implement `POST /api/v1/tasks/{task_id}/partial_rerun` to create a new module version and emit `module_updated` in `backend/main.py`
- [ ] T079 [US4] Persist quality feedback resolution/degradation decisions in `backend/services/repositories.py`
- [ ] T080 [US4] Add frontend degraded/manual-intervention states to collection, comparison, SWOT, and report views in `frontend/src/components/views/InfoDashboard.tsx`
- [ ] T081 [US4] Add frontend partial-rerun progress handling for `module_updated` events in `frontend/src/app/page.tsx`

**Checkpoint**: User Story 4 can be validated independently using failure and rerun scenarios.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final verification, cleanup, and documentation alignment across all stories.

- [ ] T082 [P] Remove obsolete mock comments, static task data fallbacks, and `href="#"` actions from frontend files under `frontend/src/`
- [ ] T083 [P] Remove hardcoded default API secrets and document environment-based configuration in `backend/agents/orchestrator.py`, `backend/agents/analyzer.py`, and `backend/agents/critic.py`
- [ ] T084 [P] Add quickstart validation notes for all backend endpoints and frontend button coverage in `specs/001-real-e2e-backend/quickstart.md`
- [ ] T085 Run backend unit, contract, and integration tests from `backend/tests/`
- [ ] T086 Run frontend lint/build and Playwright real end-to-end validation from `frontend/tests/e2e/real_e2e_backend.spec.ts`
- [ ] T087 Verify `backend/requirements.txt` contains no Redis dependency and backend starts without a Redis service
- [ ] T088 Verify no user-visible `mock`, `mocked`, static example task result, or silent no-op remains in `frontend/src/` and `backend/`
- [ ] T089 Update `README.md` with real PostgreSQL-only full-stack startup and validation commands

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; establishes task creation and schema-ready SSE.
- **User Story 2 (Phase 4)**: Depends on User Story 1; resumes the same task into collection/analysis/completion.
- **User Story 3 (Phase 5)**: Depends on User Story 2; fills all result, drawer, report, history, and debug frontend surfaces.
- **User Story 4 (Phase 6)**: Depends on User Story 2 and can run partly in parallel with User Story 3 after shared result/event contracts are stable.
- **Polish (Phase 7)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1**: MVP foundation for real frontend task startup.
- **US2**: Requires US1 persisted task and schema state.
- **US3**: Requires US2 real analysis/result data.
- **US4**: Requires US2 state machine and quality feedback; integrates with US3 UI surfaces where applicable.

### Within Each User Story

- Contract/integration/frontend tests first.
- Backend data/service changes before endpoints.
- Endpoints before frontend wiring.
- Frontend wiring before e2e validation.
- Each checkpoint must pass before moving to the next priority story.

## Parallel Opportunities

- Setup tasks T002-T005 can run in parallel.
- Foundational tests T016-T018 can run after their corresponding utilities are drafted.
- US1 contract tests T019-T020 can run in parallel with frontend test drafting T022.
- US2 contract/integration tests T032-T036 can run in parallel before implementation.
- US3 endpoint groups T051-T058 can be split by history/sources/report/feedback after repositories exist.
- US3 frontend view rewrites T059-T069 can be split by component after endpoint contracts are implemented.
- US4 tests T070-T074 can be drafted in parallel with graph/state-machine implementation.

## Parallel Example: User Story 3

```bash
# Contract tests can be drafted together:
Task: "Add contract tests for history, snapshots, source-material list/detail, schema advice, report, export, share, verify-links, feedback, and notes endpoints in backend/tests/contract/test_frontend_action_api.py"
Task: "Add contract tests for source/refetch/trust/intervention endpoint payloads in backend/tests/contract/test_source_intervention_api.py"

# Frontend components can be wired in parallel after backend contracts are stable:
Task: "Replace static comparison/focus data with analysisResults modules and evidence-aware source actions in frontend/src/components/views/CompetitorAnalysis.tsx"
Task: "Replace static structured report and source appendix with backend report data in frontend/src/components/views/StructuredReport.tsx"
Task: "Replace static source drawer, intervention drawer, schema advice drawer, and rerun drawer content with backend data/actions in frontend/src/components/layout/RightDrawer.tsx"
```

## Implementation Strategy

### MVP First (US1 + US2)

1. Complete Setup and Foundational phases.
2. Complete US1 so the frontend can create a persisted task and receive schema-ready SSE.
3. Complete US2 so schema review, save, reject, resume, collection, analysis, quality review, and completion are real.
4. Validate the main flow from frontend task submission to completion before expanding coverage.

### Full Frontend Coverage

1. Complete US3 to replace all static result/debug/report/drawer/history surfaces.
2. Complete US4 to handle degraded sources, manual intervention, safe force-next, and partial rerun.
3. Run the Quickstart section 10 button/API coverage checklist.

### Final Verification

1. Run backend tests.
2. Run frontend lint/build.
3. Run Playwright against real backend and PostgreSQL.
4. Search for remaining mock/static/no-op behavior and fix any findings.

## Notes

- [P] tasks operate on separate files or can be drafted before dependent implementation.
- All user-story tasks include a `[US#]` label.
- All contract and integration tests are required because the constitution requires API/SSE and full workflow verification.
- The frontend must not silently drop any existing button or menu action; unsupported actions need truthful disabled states with no mock data.
