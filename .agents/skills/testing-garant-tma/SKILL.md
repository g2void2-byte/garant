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
EOF
```

Note: `ADMIN_TOTP_BYPASS` is NOT a `Settings` field — it's read directly from `os.environ` in `backend/app/auth_2fa.py`. If you `set -a; source .env; set +a` and `.env` contains `ADMIN_TOTP_BYPASS=...`, the pydantic `Settings` constructor rejects the extra and uvicorn exits with `Extra inputs are not permitted`. Export it inline instead: `ADMIN_TOTP_BYPASS=localtestbypass uvicorn ...`.

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

## PIN setup over HTTP

`/api/pin/login` does NOT exist on the router. The endpoints in `backend/app/routers/pin.py` are `/setup` (first time only, 4xx on a user that already has a PIN), `/check` (verify existing PIN — the right path for subsequent sessions), `/change`, `/reset/request`, `/reset/confirm`, `/status`. All return `{ token: "<jwt>" }` which goes in the `X-Pin-Token` header for PIN-gated endpoints. `STRONG_TEST_PIN` is `3741` (the production blacklist in `backend.app.pin.COMMON_PINS` rejects 1234/1111/0000/etc).

```bash
# first time:
BPIN=$(curl -sS -H "Authorization: tma $BUYER" -H "Content-Type: application/json" \
  -d '{"pin":"3741"}' http://localhost:8080/api/pin/setup \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
# subsequent sessions (user already has a PIN):
BPIN=$(curl -sS -H "Authorization: tma $BUYER" -H "Content-Type: application/json" \
  -d '{"pin":"3741"}' http://localhost:8080/api/pin/check \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
```

## Funding a buyer's wallet for deal tests

The seeded currencies are `USD`, `UAH`, `RUB` (no `USDT` unless you migrate). Either pick one of the three for the test deal, or `INSERT INTO currencies`. Cheapest path to give the buyer spendable balance is direct SQL — mirrors `services_wallet.get_or_create_balance` — because the production deposit flow requires a CryptoBot callback:

```bash
docker exec garant-pg psql -U garant -d garant -c \
  "INSERT INTO user_balances (user_id, currency_id, amount, locked) \
   VALUES (1, 1, 100, 0) \
   ON CONFLICT (user_id, currency_id) DO UPDATE SET amount=100;"
```

## Creating a deal via the API

`POST /api/deals` schema is `DealCreate` in `backend/app/schemas.py` — the field is `counterparty` (not `counterparty_username`), `description` (not `conditions`), and `role` is `Literal["buyer"]` (the caller is always the buyer; the seller can't open a deal). Common 422 hits when porting from older docs:

```bash
curl -sS -X POST -H "Authorization: tma $BUYER" -H "X-Pin-Token: $BPIN" \
  -H "Content-Type: application/json" \
  -d '{"counterparty":"testseller","amount":10,"currency_code":"USD",
       "description":"e2e","role":"buyer","pay_commission":"buyer"}' \
  http://localhost:8080/api/deals
```

## Testing real-time / WebSocket-driven UI updates (item 22 pattern)

When the thing under test is a *passive* UI flip (the other party's tab updates without a reload), the cleanest setup is **one visible window as the OBSERVER + `curl` as the ACTOR**. This:

- removes the client-side mutation as a confound — the only thing that can flip the visible page is the backend's WS frame,
- avoids juggling two Chrome windows on a 1024×768 desktop,
- works even when Chrome's CDP endpoint can't see the incognito context.

### Recipe

1. **Boot backend + frontend** (Option A or B above). Note the Chrome devtools endpoint at `http://localhost:29229` — Playwright connects there over CDP.
2. **Seed both users** via `/api/me` + `/api/pin/setup` (or `/check`) and cache the PIN tokens to `/tmp/bpin` and `/tmp/spin`.
3. **Create the deal via curl** and stash the id. Drive it to the precondition state (e.g. seller `/accept` so it's `in_progress`) via curl too. This is *setup* — don't record it.
4. **Put the visible Chrome window into the OBSERVER role** by swapping `localStorage.dev_init_data` and clearing `garant.pin_token`/`garant.pin_token_expires` via Playwright-over-CDP:

   ```js
   // setObserver.mjs
   import { chromium } from "playwright";
   const browser = await chromium.connectOverCDP("http://localhost:29229");
   const page = browser.contexts()[0].pages()
     .find(p => p.url().startsWith("http://localhost:5173"));
   await page.evaluate((init) => {
     localStorage.setItem("dev_init_data", init);
     localStorage.removeItem("garant.pin_token");
     localStorage.removeItem("garant.pin_token_expires");
   }, OBSERVER_INIT);
   await page.goto("http://localhost:5173/deals/<id>");
   process.exit(0);  // do NOT call browser.close() — it sometimes hangs the
                     // attached CDP session forever.
   ```

   Then enter the PIN through the GUI (the page-load triggers a re-PIN prompt because we just cleared the token). The OBSERVER window is now sitting on `/deals/<id>` and rendering the precondition state.

5. **Start the recording** and annotate `setup`.
6. **Fire the ACTOR's mutation via curl** while the OBSERVER window stays visible. Take a screenshot immediately after. The WS round-trip is sub-second; the page-age counter at the bottom of `DealDetailPage` keeps running across the flip — that's the no-reload proof.

### Adversarial framing

The item-22 fix introduced a 10-second `useDeal` `refetchInterval` for non-terminal statuses. Any assertion you write should ideally fire under ≈3 s of the ACTOR's curl so a passing test rules out the poll path and proves the WS path. If your screenshot lands at 4–9 s post-curl, the poll could be what flipped it — redo with a tighter window.

### Why not two Chrome windows side-by-side

Two Chrome windows works in principle (normal + incognito = separate `localStorage` namespaces) but:

- Chrome's remote-debugging endpoint at port 29229 does NOT expose incognito contexts — `browser.contexts()` over CDP returns only the regular one. So you can't drive the incognito window through Playwright; you'd have to fall back to the GUI for it.
- A `browser.newContext()` call over CDP creates a non-visible context (headless within the attached browser). That's fine for backend-style scripting but invisible to your screen recording.
- On a 1024×768 desktop, two side-by-side windows are cramped and the recording is hard to read.

If you genuinely need both perspectives visible at once (e.g. concurrent typing in two chat windows), use one window for one side and a second `playwright.launch()` browser (NOT CDP-attached) for the other — but for *any* test where only one side is the passive observer, the single-window pattern above is strictly simpler and just as decisive.

## Status labels used in assertions

`frontend/src/pages/deals/DealDetailPage.tsx` is the source of truth for the human-readable status badge:

| backend status | UI text | CSS class |
| --- | --- | --- |
| `pending_confirmation` | Ожидает подтверждения | text-accent |
| `pending_payment` | Ожидает оплаты | text-accent |
| `in_progress` | В работе | text-success |
| `pending_cancellation` | Запрошена отмена | text-accent |
| `arbitration` | В арбитраже | text-accent |
| `completed` | Завершена | text-success |
| `cancelled` | Отменена | text-danger |
| `cancelled_for_inactivity` | Отменена за неактивность | text-danger |
| `resolved_for_buyer` | Решено в пользу покупателя | text-success |
| `resolved_for_seller` | Решено в пользу продавца | text-success |

`in_progress` and `completed` share `text-success`, so a colour-only assertion is insufficient between them — always assert on the visible text.
