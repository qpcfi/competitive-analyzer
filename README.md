# Competitive Analyzer

Full-stack competitive analysis app with a Next.js frontend, FastAPI backend,
LangGraph workflow, and PostgreSQL persistence. Redis is not required.

## Prerequisites

- Python 3.12+
- Node.js compatible with the checked-in frontend
- PostgreSQL running locally or reachable through environment variables
- Optional: `DEEPSEEK_API_KEY` for model-backed schema/analysis generation

Create the database:

```sql
CREATE DATABASE competitive_analyzer;
```

Default backend connection:

```text
DATABASE_URL=postgresql+asyncpg://postgres:123456@localhost:5432/competitive_analyzer
CHECKPOINT_DATABASE_URL=postgresql://postgres:123456@127.0.0.1:5432/competitive_analyzer
```

## Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The backend creates SQLAlchemy tables on startup and stores LangGraph
checkpoints, task events, schemas, sources, analysis modules, feedback, notes,
exports, and link verification results in PostgreSQL.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Validation

Backend tests:

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests
```

Frontend build:

```powershell
cd frontend
npm run build
```

Main manual flow:

1. Start PostgreSQL and the backend.
2. Start the frontend.
3. Create a task from the task console.
4. Confirm schema generation arrives over SSE.
5. Save or reject the schema, then save and continue.
6. Verify collection, analysis, SWOT, report, debug, export, share, source,
   feedback, notes, force-next, and partial-rerun controls call backend APIs.

See `specs/001-real-e2e-backend/quickstart.md` for the full endpoint and button
coverage checklist.
