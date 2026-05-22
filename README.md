# Garant — Telegram Mini App

Escrow-сервис для безопасных сделок между пользователями Telegram.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 (async + asyncpg), PostgreSQL 16, Alembic, Pydantic v2, aiogram 3
- **Frontend**: React 18, TypeScript, Vite, TailwindCSS, Framer Motion, TanStack Query
- **Payments**: AsyncPayments (CryptoBot SDK)

## Quick start — Docker Compose (recommended)

One command brings up the full stack (Postgres + Redis + a one-shot
`migrate` init-service + backend + frontend):

```bash
git clone https://github.com/g2void2-byte/garant.git && cd garant
cp .env.compose.example .env                                  # fill in BOT_TOKEN / CRYPTOBOT_TOKEN for live bot tests
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env      # required (audit §16.2.1)
docker compose up
```

- Backend: <http://localhost:8080> (uvicorn `--reload`)
- Frontend: <http://localhost:5173> (vite hot-reload)
- Postgres: `localhost:5432` (user/db = `garant`; password from `POSTGRES_PASSWORD` in `.env`)
- Redis: `localhost:6379` (set `REDIS_URL=redis://redis:6379/0` in `.env` to enable the P3.5 path)

`alembic upgrade head` runs in the dedicated `migrate` service (which
exits after applying migrations); the backend service waits on it via
`depends_on: service_completed_successfully`. The backend lifespan
only verifies the DB is at the expected head revision before serving
traffic. To rerun migrations manually: `docker compose up migrate`.

### Kubernetes / Helm deploy (V11-M-14)

The compose `migrate` one-shot has a direct analogue in any
orchestrator that supports run-once init containers. The contract is:

1. **One** migration runner per release (an `initContainer` on a
   Deployment, a `Job`, or a Helm `pre-install,pre-upgrade` hook) runs
   `alembic upgrade head` against the production DB. The backend
   `Pod`s do **not** run migrations themselves.
2. The runtime backend container runs `uvicorn backend.app.main:app …`
   without any migration side-effects. The lifespan verifies the DB
   is at the expected head revision (raising
   `MigrationsOutOfSync` if not) but does **not** apply migrations
   when `RUN_ALEMBIC_ON_START=0`.
3. Concurrent Pod restarts during a rolling upgrade are safe because
   the runner holds the Alembic advisory lock
   (`backend.app.db._upgrade_to_head_sync` issues
   `pg_advisory_lock(0xa1eb1c)`) — if two runners race, the second
   waits and then becomes a no-op.

Minimal `Deployment` snippet (Helm values omitted for brevity):

```yaml
spec:
  template:
    spec:
      initContainers:
        - name: alembic-upgrade
          image: ghcr.io/your-org/garant-backend:{{ .Chart.AppVersion }}
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef: { name: garant-env }
      containers:
        - name: backend
          image: ghcr.io/your-org/garant-backend:{{ .Chart.AppVersion }}
          env:
            - { name: RUN_ALEMBIC_ON_START, value: "0" }
            - { name: RUN_BOT, value: "0" }    # bot lives in its own Deployment
          envFrom:
            - secretRef: { name: garant-env }
```

`alembic-upgrade` runs once per Pod scheduling event; combined with
the advisory lock, it is safe even when several Pods of the same
Deployment come up in parallel. For multi-replica deploys prefer a
`pre-install,pre-upgrade` Helm hook `Job` so the migration runs
**once per release** instead of **once per replica**.

Code is bind-mounted, so edits trigger hot-reload without rebuilds. Add `-d` to detach. Use `docker compose logs -f backend` to tail. Use `docker compose down -v` to wipe the Postgres volume.

## Manual setup (without Docker)

```bash
# 1. PostgreSQL
docker run -d --name garant-pg \
  -e POSTGRES_USER=garant -e POSTGRES_PASSWORD=garant -e POSTGRES_DB=garant \
  -p 5432:5432 postgres:16-alpine

# 2. Backend
cp .env.example .env          # fill in BOT_TOKEN, CRYPTOBOT_TOKEN, WEBAPP_URL
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"       # or: uv sync --all-extras (reads uv.lock for pinned transitives)
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
# Schema is applied automatically (alembic upgrade head) at startup.

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # -> http://localhost:5173
```

### Horizontal scale (optional)

For multi-worker / multi-replica deployments, run Redis and point the backend at it:

```bash
docker run -d --name garant-redis -p 6379:6379 redis:7-alpine
# then in .env:
REDIS_URL=redis://localhost:6379/0
```

This makes WS notifications fan out across all backend instances (via `PUBLISH` on the `ws:notifications` channel) and replaces the in-process rate-limit counters with shared Redis counters. The backend stays functional if Redis goes down — it logs a warning and falls back to in-process state.

## Database migrations

We use **Alembic** for schema changes. The app runs `alembic upgrade head`
automatically on startup, but you can also run it manually:

```bash
source .venv/bin/activate
alembic upgrade head                              # apply pending migrations
alembic revision --autogenerate -m "add foo"      # generate a new migration
alembic history                                   # list applied revisions
alembic downgrade -1                              # revert one step
```

Migrations live in `alembic/versions/`. Review autogenerated files — Alembic
does not detect column-rename or data-migration intent.

## Dependency lockfile (V12-L4)

`uv.lock` pins the **transitive** dependency tree. The direct `==` pins
in `pyproject.toml` only cover the libraries we import directly;
without a lockfile, transitive minor / patch bumps leaked silently
between builds. CI gates the lockfile via `uv lock --check`, so every
change to `pyproject.toml` must be paired with a refreshed `uv.lock`:

```bash
# After editing pyproject.toml (e.g. adding a dep or bumping a pin):
uv lock                       # regenerates uv.lock against pyproject.toml
git add pyproject.toml uv.lock
```

`pip install -e ".[dev]"` continues to work for local dev and is what
CI / `backend/Dockerfile.dev` currently use — the lockfile is purely a
*contract* for now. Migrating the installer to `uv sync --frozen` is
tracked as a follow-up.

## Content Security Policy (M-5)

The backend serves a strict CSP on every HTTP response — no
`'unsafe-inline'`, no `'unsafe-eval'`, no nonces. Inline `<style>` /
`<script>` markup is forbidden by ESLint at the lint stage and by
`tests/test_csp_policy.py` at the test stage. Adding a frontend
dependency that injects inline styles or scripts (Framer Motion,
emotion, styled-components default mode, third-party analytics
loaders) requires a policy decision, not a workaround.

The full contract — directive-by-directive rationale, contributor
rules, and the telemetry path through `/api/csp-report` — lives in
[`docs/csp-policy.md`](docs/csp-policy.md).

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | Telegram Bot API token |
| `CRYPTOBOT_TOKEN` | — | CryptoBot API token |
| `WEBAPP_URL` | `http://localhost:5173` | Public URL of the frontend |
| `WEBAPP_PORT` | `8080` | Backend listen port |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS origins (comma-separated) |
| `DATABASE_URL` | `postgresql+asyncpg://garant:garant@localhost:5432/garant` | SQLAlchemy async DB URL |
| `REDIS_URL` | _empty_ | Optional. When set (e.g. `redis://localhost:6379/0`), WebSocket broadcasts go through Redis pub/sub and the rate limiter uses Redis counters. Empty keeps everything in-process. |
| `RUN_BOT` | `1` | Start aiogram polling (set `0` to disable) |
| `ALLOW_UNSIGNED_INIT_DATA` | `0` | Accept unsigned initData (dev only!) |

## Project structure

```
garant/
├── backend/app/           # FastAPI + SQLAlchemy backend
│   ├── main.py            # App entrypoint + lifespan
│   ├── config.py          # pydantic-settings
│   ├── db.py              # async engine + session
│   ├── models.py          # SQLAlchemy 2 models
│   ├── schemas.py         # Pydantic DTOs
│   ├── security.py        # Telegram initData HMAC verification
│   ├── deps.py            # FastAPI dependencies
│   ├── services.py        # Escrow business logic
│   ├── notifier.py        # Push notifications + WS broadcast
│   ├── ws.py              # WebSocket connection manager
│   ├── seed.py            # Categories + settings seeder
│   ├── routers/           # HTTP route modules
│   └── bot/               # Aiogram bot (thin /start handler)
└── frontend/              # React + Vite + Tailwind
    └── src/
        ├── api/           # ky client, hooks, types
        ├── components/    # UI + domain components
        ├── pages/         # Route pages
        ├── lib/           # Utilities (tg, format, ws)
        └── App.tsx        # Router + providers
```
