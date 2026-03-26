# Inbox Concierge

React + FastAPI + PostgreSQL + OpenAI (`gpt-4o-mini`) inbox classifier with Google OAuth and Gmail read-only access.

## Prerequisites

- Docker (for Postgres) or any PostgreSQL 16 instance
- Python 3.11+
- Node 20+

## Configuration

Copy [`.env.example`](.env.example) to `.env` at the repo root (or `backend/.env`) and set:

- `DATABASE_URL` — e.g. `postgresql+asyncpg://inbox:inbox@127.0.0.1:5432/inbox_concierge` (empty falls back to this default)
- `SESSION_SECRET` — at least 32 random characters
- `TOKEN_ENCRYPTION_KEY` — Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `OAUTH_REDIRECT_URI` — full URL of the API callback, e.g. `http://localhost:8000/api/auth/google/callback` (must match Google Cloud Console **Authorized redirect URIs**)
- `FRONTEND_ORIGIN` — URL where users load the SPA (post-login redirect); see workflows below
- `CORS_ALLOW_ORIGINS` — optional comma-separated extra origins allowed for CORS; `FRONTEND_ORIGIN` is always included
- `OPENAI_API_KEY`

Copy [`frontend/.env.example`](frontend/.env.example) to `frontend/.env` when using **split dev** (see below).

**Consistency:** Use the same hostname for the API in `OAUTH_REDIRECT_URI`, in `VITE_API_BASE_URL` (split dev), and in Google Console (e.g. prefer `localhost` or `127.0.0.1` consistently).

Google Cloud Console: OAuth client **Web application**, authorized redirect URI = `OAUTH_REDIRECT_URI`.

## Database

```bash
docker compose up -d
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://inbox:inbox@127.0.0.1:5432/inbox_concierge
alembic upgrade head
```

## Local development (choose one)

### A. Single origin (recommended, matches production)

Build the UI and serve it from FastAPI on one port.

```bash
cd frontend && npm install && npm run build:copy
cd ../backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` (or your chosen host). Do **not** set `VITE_API_BASE_URL` in `frontend/.env` for this flow.

Set in `.env`:

- `FRONTEND_ORIGIN=http://localhost:8000`
- `OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback` (aligned with Google Console)

### B. Split dev (Vite HMR on :5173)

Run API and Vite together; the browser calls the API **directly** (no dev-server proxy).

**Backend** (terminal 1):

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (terminal 2):

```bash
cd frontend && npm install
cp .env.example .env   # then ensure VITE_API_BASE_URL matches your API, e.g. http://localhost:8000
npm run dev
```

Open `http://localhost:5173`.

Set in root `.env`:

- `FRONTEND_ORIGIN=http://localhost:5173`
- `OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback` (API host must match `VITE_API_BASE_URL`)
- Optionally `CORS_ALLOW_ORIGINS=http://127.0.0.1:5173` if you use `127.0.0.1` for Vite instead of `localhost`

## Production (single origin)

```bash
cd frontend && npm run build:copy
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Set `FRONTEND_ORIGIN` and `CORS_ALLOW_ORIGINS` to your public site URL(s).

## Deploy on Google Cloud Run

The repo includes a root [`Dockerfile`](Dockerfile) that builds the frontend into `backend/static` and runs FastAPI on `$PORT` (Cloud Run). Migrations run on container start via [`backend/docker-entrypoint.sh`](backend/docker-entrypoint.sh).

**Step-by-step guide (first-time GCP, GUI-first):** [docs/DEPLOY_GCP.md](docs/DEPLOY_GCP.md)

## Tests

```bash
cd backend && source .venv/bin/activate && pytest -q
```
