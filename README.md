# Agentic Workflow Builder (Unbound Hackathon)

Build and run multi-step AI workflows where the **backend is authoritative** (deterministic validations + retries), and the frontend is a **workflow editor + live execution viewer**.

- Backend: FastAPI + Pydantic v2 + WebSocket event stream
- Frontend: React + TypeScript (CRA)
- LLM provider: Unbound (OpenAI-compatible chat completions)

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

## Deploy

There are a few good hackathon-friendly options. Pick one.

### Option A (Recommended): Backend on Railway + Frontend on Vercel

This is the simplest “works in a demo” deployment for this repo.

#### 1) Deploy the backend to Railway

In Railway:

- New Project → **Deploy from GitHub repo**
- Select this repository
- Configure the service as a monorepo backend:
  - **Root Directory**: `backend`

Railway can deploy either via Dockerfile or Nixpacks:

- **Dockerfile path** (recommended): Railway will detect `backend/Dockerfile` when Root Directory is `backend`
- **Nixpacks path**: set a Start Command:
  - `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Set Railway Variables:

- `UNBOUND_API_KEY` = your Unbound key

After the first deploy, Railway gives you a public URL. Verify:

- `GET https://<railway-backend-url>/health`

Notes:

- WebSockets are required for the live run viewer (`/runs/{run_id}/events`). Railway supports this; the frontend will use `wss://...` automatically.
- CORS is currently permissive (`allow_origins=["*"]`) for hackathon demos.

#### 2) Deploy the frontend to Vercel

In Vercel:

- Import the repo
- Set **Root Directory** = `frontend`
- Set env var:
  - `REACT_APP_API_URL=https://<railway-backend-url>`
- Deploy

The frontend uses `REACT_APP_API_URL` for both REST and WebSocket and will convert `https://...` → `wss://...`.

### Option B (Single VM): run both locally with two processes

- Use a cheap VPS (or any Windows/Linux box)
- Run backend on port 8000
- Serve frontend with `npm run build` + any static host (or keep CRA dev server for demo)

### Option C (Alternative): Backend on Google Cloud Run + Frontend on Vercel

Cloud Run is a great fit for this project because it:

- Runs our existing Dockerized FastAPI backend
- Handles autoscaling and HTTPS for free
- Supports WebSockets (needed for `/runs/{run_id}/events`)

#### 1) Deploy the backend to Cloud Run

Prereqs:

- Install `gcloud` CLI
- `gcloud auth login`
- Pick a `PROJECT_ID` and region (e.g. `us-central1`)

From repo root (PowerShell):

```powershell
$env:PROJECT_ID = "YOUR_PROJECT_ID"
$env:REGION = "us-central1"

gcloud config set project $env:PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# Build the container in Google Cloud
gcloud builds submit --tag "gcr.io/$env:PROJECT_ID/agentic-workflow-backend" .\backend

# Deploy to Cloud Run (allow unauth for hackathon demo)
gcloud run deploy agentic-workflow-backend `
  --image "gcr.io/$env:PROJECT_ID/agentic-workflow-backend" `
  --region $env:REGION `
  --allow-unauthenticated `
  --set-env-vars "UNBOUND_API_KEY=YOUR_UNBOUND_KEY"
```

After deploy, Cloud Run prints a Service URL like:

- `https://agentic-workflow-backend-xxxxx-uc.a.run.app`

Verify:

- `GET https://<cloud-run-url>/health`

#### 2) Deploy the frontend to Vercel

In Vercel:

- Import the repo
- Set **Root Directory** = `frontend`
- Set env var:
  - `REACT_APP_API_URL=https://<cloud-run-url>`
- Deploy

Notes:

- The frontend uses `REACT_APP_API_URL` for both REST and WebSocket. It automatically converts `https://...` → `wss://...`.
- If you see CORS issues, double-check the backend is reachable and that the browser can connect to the Cloud Run URL.

## Troubleshooting

### Runs fail with `ReadError('')` or `getaddrinfo failed`

That’s network/DNS instability between your machine and Unbound.

- Try a different Wi‑Fi / mobile hotspot
- If you’re on a corporate/school network, proxy/SSL inspection can break streaming reads
- DNS fix attempts:
  - `ipconfig /flushdns`
  - switch DNS to `1.1.1.1` or `8.8.8.8`

### “ModuleNotFoundError: No module named 'app'” when running tests

Run from repo root or use the venv python + absolute path:

```powershell
& .\.virtual\Scripts\python.exe -u backend\app\test_llm_client.py
```

## Security Notes

- Never commit `backend/.env` (it contains your API key).
- Rotate your Unbound key if it was pasted into chat/logs.

## Demo Script (2 minutes)

1. Create workflow (2 steps)
2. Add a deterministic validation (e.g. `contains`)
3. Save
4. Run
5. Show WebSocket event log and run status

---

Built for Unbound Hackathon (Feb 5).
