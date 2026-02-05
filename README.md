# Agentic Workflow Builder (Unbound Hackathon)

Build and run multi-step AI workflows where the **backend is authoritative** (deterministic validations + retries), and the frontend is a **workflow editor + live execution viewer**.

- Backend: FastAPI + Pydantic v2 + WebSocket event stream
- Frontend: React + TypeScript (CRA)
- LLM provider: Unbound 

## Demo Features

- Create / edit / delete workflows
- Sequential step execution (by `step.order`)
- Deterministic completion checks per step (e.g. `contains`, `regex_match`, `json_valid`, `python_syntax`, `test_exec`, optional `llm_judge`)
- Retry budget per step (`max_retries`)
- Live progress via WebSocket (`/runs/{run_id}/events`)
- Execution history via REST (`/runs`, `/runs/{run_id}`)

## Repo Structure

- `backend/` – FastAPI API + orchestrator + validators + Unbound client
- `frontend/` – React UI (workflow builder + execution viewer)
- `scripts/` – local smoke tests and probes

## Prerequisites

- Python 3.11+ recommended (works with 3.13 in this repo)
- Node.js 18+ (Node 16 may work but is not recommended)
- An Unbound API key

## Quickstart (Local)

### 1) Backend

From repo root:

```powershell
# (optional) activate the existing venv used in this repo
.\.virtual\Scripts\Activate

# install deps (safe to re-run)
python -m pip install -r backend\requirements.txt

# create your local env file
Copy-Item backend\.env.example backend\.env
# edit backend\.env and set UNBOUND_API_KEY=...

cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify:

- `GET http://127.0.0.1:8000/health`

### 2) Frontend

In a new terminal from repo root:

```powershell
cd frontend
npm install

# point the UI at your backend (Windows PowerShell)
$env:REACT_APP_API_URL = "http://127.0.0.1:8000"

npm start
```

Open:

- `http://localhost:3000`

## Environment Variables

Backend (loaded from `backend/.env`):

- `UNBOUND_API_KEY` (required)

Frontend:

- `REACT_APP_API_URL` (optional, default `http://localhost:8000`)

## API Overview

Base URL: `http://127.0.0.1:8000`

### REST

- `GET /health`
- `GET /workflows`
- `POST /workflows`
- `GET /workflows/{workflow_id}`
- `PUT /workflows/{workflow_id}`
- `DELETE /workflows/{workflow_id}`
- `POST /workflows/{workflow_id}/run`
- `GET /runs`
- `GET /runs/{run_id}`

### WebSocket

- `WS /runs/{run_id}/events`

Event payloads are `ExecutionEvent` objects (see `backend/app/models.py`).

## Smoke Tests

### End-to-end create → run → poll

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\api_smoke_test.ps1
```

### Direct Unbound connectivity probe

```powershell
.\.virtual\Scripts\python.exe -u scripts\httpx_unbound_probe.py
```


Built for Unbound Hackathon (Feb 5).
