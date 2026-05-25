# Quickstart: Real End-to-End Backend

This validates the completed frontend against the real backend and PostgreSQL.
No Redis service is required.

## 1. Start PostgreSQL

Create the database if it does not exist:

```sql
CREATE DATABASE competitive_analyzer;
```

Use the local connection expected by the current project unless overridden by
environment configuration:

```text
postgresql://postgres:123456@localhost:5432/competitive_analyzer
```

## 2. Start the Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Expected startup behavior:
- Database tables are created or migrated.
- LangGraph PostgreSQL checkpoint tables are available.
- Runtime does not require Redis.
- Backend exposes `http://localhost:8000/api/v1/tasks`.

## 3. Start the Completed Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## 4. Run the Main End-to-End Scenario

1. In the task console, keep or enter:
   - Domain: `AI大模型`
   - Competitors: `GPT-4o`, `Claude 3.5`, `Gemini 1.5`
   - Execution mode: step-by-step
2. Submit the task.
3. Verify the UI receives a task ID and opens the SSE stream.
4. Wait for schema readiness.
5. Save the schema draft.
6. Click save and continue.
7. Verify collection, analysis, token, debug, and completion events update the
   existing frontend.
8. Verify comparison, SWOT, and structured report views show task data with
   evidence or degraded markers.

## 5. Reconnect Validation

1. Start a task and wait until schema review or collection.
2. Reload the browser.
3. Reopen or restore the current task.
4. Verify current task state and recent relevant events are recovered from
   persisted data.

## 6. Failure and Degraded Source Validation

1. Use a competitor or source that is expected to fail or be blocked.
2. Verify the task records failed/degraded status instead of silently dropping
   the data.
3. Verify the main task continues when enough alternate evidence exists.
4. Verify final visible results mark degraded fields explicitly.

## 7. Schema Reject and Rerun Validation

1. Start a step-by-step task.
2. Reject the generated schema.
3. Verify the response is `regenerating`, not `regenerating_mocked`.
4. Confirm the regenerated schema can be saved and resumed.
5. From a module action, submit a partial rerun instruction.
6. Verify only the target module updates and existing evidence remains linked.

## 8. Privacy Validation

1. Submit input containing sample emails or phone numbers.
2. Collect a page or fixture containing common personal data patterns.
3. Verify model-processing inputs use redacted text.
4. Verify debug records do not expose unredacted sensitive values.

## 9. Success Criteria Check

The validation run passes when:
- The frontend completes task creation through final report without mock data.
- No response or visible label contains mock-only status for task data.
- Every final claim has evidence or degraded status.
- Stream reconnect recovers current task state.
- Redis is not required for startup or runtime.

## 10. Frontend Button/API Coverage Check

Run this checklist against the completed frontend. Each item must either call a
real backend endpoint/event or display a truthful disabled/empty state. No item
may silently do nothing or show mock data.

- Task submit creates a persisted task and starts SSE.
- Schema save draft persists a schema version.
- Schema reject returns `regenerating`, not any mock status.
- Schema save and continue resumes the same task.
- Sidebar history loads persisted tasks.
- Sidebar debug opens persisted debug/task state instead of returning early.
- Information dashboard logs, statistics, and snapshots come from backend data.
- Pause collection calls a backend pause endpoint.
- Force next node calls a backend controlled-transition endpoint.
- Source icons open source evidence for the selected claim.
- Refetch source calls the backend and emits an update event.
- Mark source untrusted/credible/suspicious persists feedback.
- Data intervention lists, adds, removes, and applies source changes.
- Schema advice drawer loads field-level advice from backend schema metadata.
- Partial rerun submits target module, instruction, and scope to backend.
- Competitor focus data comes from analysis results, not static arrays.
- SWOT cards and Critic feedback come from analysis results and quality feedback.
- Refresh/rerun/export buttons call backend endpoints.
- Report content and source appendix come from final report data.
- PDF, Markdown, JSON export buttons return real files or truthful pending/error
  states.
- Share report creates a backend share token/link.
- Verify all links records link verification results.
- Trust feedback and notes are persisted and visible after reload.
- Browser reload and SSE reconnect do not lose the current task state.
