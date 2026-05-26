# Quickstart: Real End-to-End Backend

This validates the completed frontend against the real backend and PostgreSQL.
No Redis service is required.

## 1. Start PostgreSQL

Create the database if it does not exist:

```sql
CREATE DATABASE competitive_analyzer;
```

Default local connections:

```text
DATABASE_URL=postgresql+asyncpg://postgres:123456@localhost:5432/competitive_analyzer
CHECKPOINT_DATABASE_URL=postgresql://postgres:123456@127.0.0.1:5432/competitive_analyzer
```

## 2. Start the Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Expected behavior:
- Database tables are created on startup.
- LangGraph checkpoint tables are available in PostgreSQL.
- Runtime does not require Redis.
- Backend exposes `http://localhost:8000/api/v1/tasks`.

## 3. Start the Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## 4. Main End-to-End Scenario

1. In the task console, keep or enter:
   - Domain: `AI models`
   - Competitors: `GPT-4o`, `Claude 3.5`, `Gemini 1.5`
   - Execution mode: step-by-step
2. Submit the task.
3. Verify the UI receives a task ID and opens the SSE stream.
4. Wait for schema readiness.
5. Save the schema draft.
6. Click save and continue.
7. Verify collection, analysis, token, debug, and completion events update the frontend.
8. Verify comparison, SWOT, and report views show task data with evidence or degraded markers.

## 5. Reconnect Validation

1. Start a task and wait until schema review or collection.
2. Reload the browser.
3. Verify current task state and recent events are recovered from persisted data.

## 6. Failure and Recovery Validation

1. Use a source expected to fail or be blocked.
2. Verify degraded status is recorded instead of silently dropping data.
3. Use pause and force-next from the dashboard.
4. Submit a partial rerun from an analysis/SWOT action.
5. Verify a `module_updated` event is received and prior evidence remains linked.

## 7. Frontend Button/API Coverage

Each item must either call a backend endpoint/event or show a truthful disabled/empty state:

- Task submit: `POST /api/v1/tasks`
- Schema save draft: `PUT /api/v1/tasks/{task_id}/schema`
- Schema reject: `POST /api/v1/tasks/{task_id}/reject_schema`
- Schema continue: `POST /api/v1/tasks/{task_id}/resume`
- SSE reconnect: `GET /api/v1/tasks/{task_id}/stream?since=`
- History: `GET /api/v1/tasks`
- Snapshots: `GET /snapshots`, `POST /restore_snapshot`
- Pause: `POST /pause`
- Force next: `POST /force_next`
- Sources: `GET/POST /source-materials`, `GET /source-materials/{source_id}`
- Source refetch/trust: `POST /refetch`, `POST /trust`
- Interventions: `POST /interventions`
- Schema advice: `GET /schema/advice`
- Feedback and notes: `POST /feedback`, `POST /notes`
- Report/export/share/verify: `GET /report`, `GET /export`, `POST /share`, `POST /verify_links`
- Partial rerun: `POST /partial_rerun`

## 8. Automated Validation

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests
```

```powershell
cd frontend
npm run build
```
