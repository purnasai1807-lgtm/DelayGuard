# DelayGuard deployment

## Architecture

The repository uses a React/Vite frontend, FastAPI backend, and PostgreSQL database. The frontend can be deployed to Vercel. The backend can be deployed to any Python-capable HTTPS host, such as Azure App Service, Container Apps, Render, Railway, or Fly.io. PostgreSQL must be a managed database in production.

## Backend variables

Configure these only on the backend host:

- `DATABASE_URL`: managed PostgreSQL URL, including SSL options required by the provider
- `JWT_SECRET`: long random signing secret
- `CORS_ORIGINS`: comma-separated HTTPS frontend origins
- `MAX_UPLOAD_SIZE`: maximum upload bytes
- `AI_API_KEY`: optional; deterministic engines work without it

Run migrations from the backend release environment:

```bash
alembic -c alembic.ini upgrade head
```

Start with a production process manager:

```bash
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Verify `GET /health` and `GET /docs` before connecting the frontend. Load demo data through an authenticated `POST /api/demo-data/load` call.

## Frontend on Vercel

Set the Vercel project root to `frontend`. Configure:

- `VITE_API_BASE_URL`: the public HTTPS backend URL, without a trailing slash

Build command: `npm run build`.

`frontend/vercel.json` rewrites React Router paths to `/index.html`. Do not put `DATABASE_URL`, `JWT_SECRET`, or `AI_API_KEY` in Vercel frontend variables.

## Docker

For local full-stack verification:

```bash
docker compose up --build
```

The frontend is served on port 80 and the API on port 8000. These local ports are development-only and must not be used as production API values.

## Verification

Run:

```bash
pytest -q backend/tests
npm run build --prefix frontend
```

Then verify health, registration/login, `/api/auth/me`, demo loading, request CRUD, status history, notes, notifications, dashboard, analytics, and CSV upload against the deployed HTTPS backend.

## Current status

GitHub source and local Docker deployment are prepared. Public cloud deployment requires credentials for the chosen backend host, Vercel, and managed PostgreSQL. No production URLs are recorded until those services are provisioned and independently verified.
