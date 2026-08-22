# DelayGuard

DelayGuard is an enterprise operations dashboard that predicts which service requests are likely to breach an SLA, explains the measurable reasons, identifies the bottleneck, and recommends the next action.

## MVP flow

Register or sign in, choose **Load demo data**, then open the dashboard. The generated dataset contains 1,000 requests and includes `REQ-1042`, a Revenue request in Document Verification with an engine-calculated 86.0% CRITICAL risk and ESCALATE recommendation.

## Stack

- React, Vite, TypeScript, React Router, TanStack Query, Recharts-ready frontend, Lucide React
- FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Argon2 password hashing, JWT
- Docker Compose for PostgreSQL, backend, and frontend

## Run with Docker

```bash
docker compose up --build
```

Open `http://localhost`. The API is at `http://localhost:8000`; interactive API docs are at `/docs`. Set a strong `JWT_SECRET` for anything beyond local development.

## Run locally

1. Copy `.env.example` to `.env` and provide PostgreSQL credentials.
2. Install backend dependencies with `pip install -r backend/requirements.txt`.
3. Start the API with `uvicorn app.main:app --app-dir backend --reload`.
4. Install frontend dependencies with `npm install --prefix frontend`.
5. Start Vite with `npm run dev --prefix frontend`.

Startup creates the SQLAlchemy tables for the hackathon path. Alembic is configured in `alembic.ini`; generate and apply revisions for production migration workflows.

## Implemented API

`GET /health`, auth register/login/me, protected demo data loading, paginated and searchable requests, request detail/analyze, CSV upload validation, dashboard aggregates, and bottleneck/department analytics. All application responses use `{success, data}` on success; FastAPI validation/auth errors use proper HTTP status codes.

## Testing

```bash
pytest backend/tests
```

The mandatory engine coverage includes SLA breach precedence, weighted risk classification, critical recommendation, and invalid CSV handling. Load-test guidance for 100, 500, and 1,000 concurrent users is in `load-tests/README.md`; benchmark results depend on infrastructure and are intentionally not claimed here.

## Screenshots

Add presentation screenshots here after running the Docker stack.

## Future scope

Versioned Alembic revisions, background CSV jobs for very large files, per-user tenancy, richer analytics charts, and optional external AI explanation enhancement can be layered onto the working deterministic MVP without making AI a runtime dependency.
