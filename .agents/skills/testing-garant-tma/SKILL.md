---
name: testing-garant-tma
description: Test the Garant escrow Telegram Mini App end-to-end. Use when verifying backend API, frontend UI, deal state machine, or notification flow changes.
---

# Testing Garant TMA

## Devin Secrets Needed

- `BOT_TOKEN` — Telegram bot token (optional, only for bot integration tests)
- `CRYPTOBOT_TOKEN` — CryptoBot SDK token (optional, only for deposit/payment tests)

Without these tokens, use `ALLOW_UNSIGNED_INIT_DATA=1` and `RUN_BOT=0` for local dev testing.

## Local Dev Setup

### Option A: Docker Compose (recommended)

One command brings up Postgres + Redis + backend + frontend with hot-reload:

```bash
cp .env.compose.example .env   # optional: edit BOT_TOKEN / CRYPTOBOT_TOKEN for live tests
docker compose up
```

- Backend: <http://localhost:8080> (uvicorn `--reload`, alembic on boot)
- Frontend: <http://localhost:5173> (vite hot-reload)
- Postgres: `localhost:5432` (user/pass/db = `garant`)
- Redis: `localhost:6379` — empty `REDIS_URL` keeps it in-process; set to `redis://redis:6379/0` in `.env` to exercise P3.5 pub/sub + Redis rate-limit

Code is bind-mounted, so edits trigger hot-reload without rebuilds. `docker compose down -v` wipes the Postgres volume.

#### Injecting test-only env vars (e.g. `ADMIN_TOTP_BYPASS`)

The committed `docker-compose.yml` does **not** forward `ADMIN_TOTP_BYPASS`, `ENVIRONMENT`, or many other test-only knobs into the backend container — only `ALLOW_UNSIGNED_INIT_DATA`. Putting them in `.env` is not enough on its own. Drop a `docker-compose.override.yml` next to it (gitignored — both `*.env.local` and `.env` are already covered by the existing `.gitignore`):

```yaml
# docker-compose.override.yml — local testing only, do NOT commit
services:
  backend:
    environment:
      ADMIN_TOTP_BYPASS: ${ADMIN_TOTP_BYPASS:-localtestbypass}
      ENVIRONMENT: ${ENVIRONMENT:-development}
```

`docker compose` auto-merges `docker-compose.override.yml` into the main file. With this in place, `ADMIN_TOTP_BYPASS=<value>` in `.env` reaches the container and the admin TOTP gate accepts `X-Totp-Code: <value>`.

### Option B: Manual (without Docker)

#### 1. Start PostgreSQL

```bash
docker run -d --name garant-pg \
  -e POSTGRES_USER=garant -e POSTGRES_PASSWORD=garant -e POSTGRES_DB=garant \
  -p 5432:5432 postgres:16-alpine
```

#### 2. Create `.env` file

```bash
cat > .env << 'EOF'
BOT_TOKEN=0000000000:FAKE
CRYPTOBOT_TOKEN=000000:FAKE
WEBAPP_URL=http://localhost:5173
WEBAPP_PORT=8080
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8080
DATABASE_URL=postgresql+asyncpg://garant:garant@localhost:5432/garant
RUN_BOT=0
ALLOW_UNSIGNED_INIT_DATA=1
ADMIN_TOTP_BYPASS=localtestbypass
EOF
```

#### 3. Start backend

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

On startup the backend runs `alembic upgrade head` (creates 17 tables) and
seeds 16 categories + 10 currencies + default app settings.

#### 4. Start frontend

```bash
cd frontend && VITE_API_URL=http://localhost:8080 npm run dev
```

Frontend runs on port 5173 by default.

### Option C: Frontend-only with in-browser fetch mock (for pure visual recordings)

When the sandbox can't start `dockerd` (it sometimes can't — `service docker start` is a no-op and `sudo dockerd` exits with `process with PID 1017 is still running` even though `docker ps` returns no containers) and you only need to record a purely-visual UI change (no real deal flow / wallet / API behaviour), skip the backend entirely:

1. **Temporary, gitignored, dev-only** mock module at `frontend/src/dev/mockApi.ts` that monkey-patches `window.fetch`. It only handles GETs the page actually fires on mount; everything else falls through to the original `fetch`.

   Endpoints that ProfilePage / SearchPage / UserProfilePage need to mock (minimum set):
   - `GET /api/pin/status` — return `{has_pin: false, attempts_left: 5, locked_until: null, max_attempts: 5, session_ttl_seconds: 3600}`
   - `GET /api/me` — return a `UserCardDto`-shaped object (`id`, `user_id`, `username`, `display_name`, `photo_url=null`, `admin=0`, `prefix=null`, `is_admin=false`, all the booleans/counts/sums, `description`, `forums=[]`, `country`)
   - `GET /api/users` — return an array of `UserCardDto`
   - `GET /api/users/:u` — return one `UserCardDto`
   - `GET /api/services`, `GET /api/reviews`, `GET /api/categories`, `GET /api/notifications`, `GET /api/notifications/counters`, `GET /api/support/admins`, `GET /api/support/arbiters`, `GET /api/deals`, `GET /api/maintenance` — mostly empty arrays / zero counters / `{enabled: false}`

   See `frontend/src/api/types.ts` (`UserCardDto`, `PinStatusDto`, `NotificationCountersDto`) for exact shapes — mock objects must include every field the UI reads or things will silently render `undefined`.

2. Wire it from `main.tsx` behind a double guard:

   ```ts
   if (
     import.meta.env.DEV &&
     typeof window !== "undefined" &&
     window.localStorage.getItem("use_mock_api") === "1"
   ) {
     import("./dev/mockApi").then(({ installMockApi }) => installMockApi());
   }
   ```

3. **`PinGate` won't unlock just from `has_pin: false`** — it checks `hasValidPinToken()` from `frontend/src/lib/pin.ts` (reads `garant.pin_token` + `garant.pin_token_expires` from localStorage). Inject a long-lived dev token before loading any authenticated page:

   ```js
   localStorage.setItem("use_mock_api", "1");
   localStorage.setItem("dev_init_data", 'user=%7B%22id%22%3A1%2C%22username%22%3A%22u%22%7D&auth_date=1700000000&hash=dev');
   localStorage.setItem("garant.pin_token", "dev-mock-token");
   localStorage.setItem("garant.pin_token_expires", new Date(Date.now() + 86400000).toISOString());
   window.dispatchEvent(new Event("garant:pin-token-changed"));
   location.assign("/profile");
   ```

4. **Always revert before exiting test mode**: `git checkout -- frontend/src/main.tsx && rm -rf frontend/src/dev`. Don't commit either the mock module or the dynamic import — they're test-mode-only.

5. **Limits**: form submits, mutations, WebSocket frames, and any flow that depends on backend state transitions will NOT work — the mock returns `{ok: true}` for non-GET requests as a stub. Only use this approach for visual / typography / layout regressions, never for behaviour testing.

## Authentication for Testing

### Backend (curl)

Use fake init data in the `Authorization` header:

```bash
# Buyer user (tg_user_id=111)
BUYER_INIT='user=%7B%22id%22%3A111%2C%22first_name%22%3A%22TestBuyer%22%2C%22username%22%3A%22testbuyer%22%7D&auth_date=1700000000&hash=dev'
curl -H "Authorization: tma $BUYER_INIT" http://localhost:8080/api/me

# Seller user (tg_user_id=222)
SELLER_INIT='user=%7B%22id%22%3A222%2C%22first_name%22%3A%22TestSeller%22%2C%22username%22%3A%22testseller%22%7D&auth_date=1700000000&hash=dev'
curl -H "Authorization: tma $SELLER_INIT" http://localhost:8080/api/me
```

Users are auto-created on first API call.

#### Admin user + TOTP bypass

```bash
# 1. Auto-provision via /api/me, then promote.
ADMIN_INIT='user=%7B%22id%22%3A333%2C%22first_name%22%3A%22admin%22%2C%22username%22%3A%22admin%22%7D'
curl -H "Authorization: tma $ADMIN_INIT" http://localhost:8080/api/me
docker exec garant-postgres-1 psql -U garant -d garant -c \
  "UPDATE users SET is_admin=true, totp_enabled=true, totp_secret='UNUSEDBYPASS' WHERE tg_user_id=333;"

# 2. Drive admin endpoints with X-Totp-Code: <ADMIN_TOTP_BYPASS value>.
#    The literal must match exactly what's in the backend container env
#    (see "Injecting test-only env vars" above).
curl -X POST http://localhost:8080/api/admin/wallets/1/adjust \
  -H "Authorization: tma $ADMIN_INIT" \
  -H "X-Totp-Code: localtestbypass" \
  -H "Content-Type: application/json" \
  -d '{"currency_code":"USDT","amount":50,"reason":"smoke"}'
```

### Frontend (browser)

Set `localStorage.dev_init_data` in the browser console before refreshing:

```javascript
localStorage.setItem('dev_init_data', 'user=%7B%22id%22%3A111%2C%22first_name%22%3A%22TestBuyer%22%2C%22username%22%3A%22testbuyer%22%7D&auth_date=1700000000&hash=dev');
```

Then refresh the page. Without this, API calls from the frontend might return 422 (missing Authorization header).
