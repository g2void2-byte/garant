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

### Frontend (browser)

Set `localStorage.dev_init_data` in the browser console before refreshing:

```javascript
localStorage.setItem('dev_init_data', 'user=%7B%22id%22%3A111%2C%22first_name%22%3A%22TestBuyer%22%2C%22username%22%3A%22testbuyer%22%7D&auth_date=1700000000&hash=dev');
```

Then refresh the page. Without this, API calls from the frontend might return 422 (missing Authorization header).

### PinGate on first visit

`PinGate` wraps the entire app, so a fresh user with no PIN sees the "Создайте PIN" screen before any route renders. To unlock during testing:

1. Click 4 digits (e.g. `1`, `2`, `3`, `4`) to set the PIN.
2. The screen switches to "Подтвердите PIN" — click the same 4 digits again to confirm.
3. The SPA now renders the requested route.

If you re-create the DB between tests, you need to repeat PIN setup. The PIN is stored server-side in the `pin_hash` column on `users`.

## Setting User Balance for Deal Testing

Deal creation requires buyer balance >= amount + commission (default 5%). Set
balance directly with `psql` (inside the running postgres container):

```bash
docker exec -i garant-pg psql -U garant -d garant -c \
  "UPDATE users SET balance=200 WHERE tg_user_id=111"
```

## Deal State Machine

```
wait_confirm → (both confirm) → confirmed → (buyer completes) → success
                                           → (either arbitrates) → arbitrage
             → (cancel before both confirm) → failed (refund)
```

### Key Guards
- Only buyer can complete a deal
- Cancel only allowed before both sides confirm
- Can't arbitrate a completed (success/failed) deal
- Can't double-confirm from the same side
- Can't create deal with yourself

### Balance Math (commission paid by buyer)
- Deal sum=100, commission=5% → buyer frozen=105, buyer balance -= 105
- On complete: seller gets 100, buyer frozen -= 105
- On cancel: buyer gets 105 refunded

## Key API Endpoints

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/health` | GET | Health check |
| `/api/me` | GET | Current user profile |
| `/api/categories` | GET | List seeded categories |
| `/api/users` | GET | Search users (query params: q, filter) |
| `/api/services` | GET/POST | List/create services |
| `/api/services/{id}` | GET | Service detail (owner card + comments/rating aggregates) |
| `/api/services/{id}/comments` | GET/POST | List or create public comments (rating 1-5 optional) |
| `/api/services/{id}/comments/{cid}` | DELETE | Delete (author, service owner, or admin) |
| `/api/deals` | GET/POST | List/create deals |
| `/api/deals/{id}/confirm` | POST | Confirm deal |
| `/api/deals/{id}/complete` | POST | Complete deal (buyer only) |
| `/api/deals/{id}/cancel` | POST | Cancel deal |
| `/api/deals/{id}/arbitrate` | POST | Arbitrate (query param: reason) |
| `/api/notifications` | GET | List notifications |
| `/api/notifications/counters` | GET | Notification counts |
| `/api/notifications/read-all` | POST | Mark all notifications read |
| `/api/payments/deposit/invoice` | POST | CryptoBot invoice (needs real token) |
| `/api/payments/webhook/cryptobot` | POST | CryptoBot webhook (HMAC-SHA256 signed) |
| `/api/wallet/withdrawals` | POST | **Requires PIN session** (X-Pin-Token header) |
| `/api/pin/setup` | POST | Set initial PIN (`{"pin":"1234","confirm":"1234"}`) |
| `/api/pin/check` | POST | Verify PIN (`{"pin":"1234"}`) → returns JWT token |
| `/api/pin/change` | POST | Change PIN (requires current PIN) |
| `/api/pin/reset/request` | POST | Request PIN reset code (sent via bot DM) |
| `/api/pin/reset/confirm` | POST | Confirm PIN reset with code |
| `/api/pin/status` | GET | Check PIN setup/lock status |
| `/api/admin/services` | GET | Admin list services (**requires AdminUser**) |
| `/api/admin/services/{id}/moderate` | POST | Moderate service (**requires AdminUser + TotpUser**) |
| `/api/admin/withdrawals/{id}/decide` | POST | Approve/reject withdrawal (**requires AdminUser + TotpUser**) |
| `/ws/notifications` | WS | Real-time notifications |

## Security Testing

### Testing banned/frozen users (C-1)

```bash
# Ban a user, then verify 403
docker exec garant-pg psql -U garant -d garant -c "UPDATE users SET is_banned=true WHERE tg_user_id=111"
curl -s -H "Authorization: tma $BUYER_INIT" http://localhost:8080/api/me
# Expected: 403 {"detail":"Аккаунт заблокирован"}

# Freeze a user
docker exec garant-pg psql -U garant -d garant -c "UPDATE users SET is_banned=false, is_frozen=true WHERE tg_user_id=111"
curl -s -H "Authorization: tma $BUYER_INIT" http://localhost:8080/api/me
# Expected: 403 {"detail":"Аккаунт заморожен"}
```

### Testing PIN lock (C-2)

PIN endpoints use `/api/pin/setup` and `/api/pin/check` — NOT `/set` or `/verify`.
After `pin_max_attempts` (default 3) wrong attempts, the account locks for 60 min (HTTP 423).
Even the correct PIN returns 423 while locked.

### Testing path traversal (C-3)

The SPA fallback route only activates when `frontend/dist` directory exists.
For testing, create a minimal dist: `mkdir -p frontend/dist/assets && echo '<html>SPA</html>' > frontend/dist/index.html`
Then restart the backend so it registers the catch-all route.

```bash
curl -s http://localhost:8080/..%2F..%2Fetc%2Fpasswd
# Expected: index.html content, NOT /etc/passwd
```

### Testing admin endpoints (C-4)

Admin service moderation requires `AdminUser` dependency. Make a test user admin:
```bash
docker exec garant-pg psql -U garant -d garant -c "UPDATE users SET is_admin=true WHERE tg_user_id=111"
```
The `/moderate` and `/decide` endpoints additionally require `TotpUser` (2FA) — cannot test via simple curl without TOTP setup.

### Testing webhook status validation (H-5)

Sign webhook payloads with HMAC-SHA256 using SHA256(CRYPTOBOT_TOKEN) as key:
```python
import hashlib, hmac, json
secret = 'your-cryptobot-token'
key = hashlib.sha256(secret.encode()).digest()
body = json.dumps({'update_type': 'invoice_paid', 'payload': {'invoice_id': 'test-001', 'status': 'pending'}})
sig = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
# Send with header: crypto-pay-api-signature: <sig>
```
Webhook with `status != "paid"` returns `{"ok":false,"reason":"status is not paid"}`.

### Testing notification counters (H-11)

To verify the statement mutation fix, create notifications of different types with mixed read/unread states:
```sql
INSERT INTO notifications (recipient_id, type, title, body, is_read, created_at) VALUES
(1, 'deals', 'Deal Read', 'body', true, NOW()),
(1, 'deals', 'Deal Unread', 'body', false, NOW()),
(1, 'deposits', 'Dep Read', 'body', true, NOW()),
(1, 'system', 'Sys Read', 'body', true, NOW());
```
Then `GET /api/notifications/counters` should show `deals=2` (not 1). If the mutation bug exists, `deals` would only count unread deals because the `.where(is_read=False)` filter leaks from the unread counter.

### Testing hidden profile (H-12)

```bash
docker exec garant-pg psql -U garant -d garant -c "UPDATE users SET is_hidden_profile=true WHERE tg_user_id=333"
curl -s http://localhost:8080/api/users/hiddenuser  # Expected: 404
curl -s http://localhost:8080/api/users  # hiddenuser should NOT appear
```

### Testing online status (H-8)

```bash
# Recently active user → online=true
docker exec garant-pg psql -U garant -d garant -c "UPDATE users SET last_login_at=NOW() WHERE tg_user_id=222"
# Inactive user → online=false
docker exec garant-pg psql -U garant -d garant -c "UPDATE users SET last_login_at=NOW() - interval '1 hour' WHERE tg_user_id=111"
curl -s http://localhost:8080/api/users/testseller  # online=true
curl -s http://localhost:8080/api/users/testbuyer   # online=false
```

## Frontend Routes

| Route | Page |
|-------|------|
| `/search` | User search with filters |
| `/search/categories` | Categories grid |
| `/search/categories/:slug` | Services in category |
| `/services/:id` | Service detail (hero + owner card + stats + description + comments) |
| `/u/:username` | Public user profile |
| `/deals` | Deals list with role/status filter |
| `/deals/new` | Create deal form |
| `/deals/:id` | Deal detail with actions |
| `/help` | Help page |
| `/notifications` | Notifications with type tabs |
| `/profile` | User profile, balance, services |
| `/profile/services/new` | Add service |
| `/profile/deposit` | CryptoBot deposit page |
| `/profile/transfer` | Account transfer |
| `/wallet` | Wallet overview |
| `/wallet/:code` | Single-currency wallet detail |
| `*` | Catch-all — redirects to `/search` |

### Routing gotchas

- The catch-all (`*` → `/search`) means unknown paths silently land on the search hub. Be specific when testing bot URLs.
- `/wallet/:code` **shadows** any `/wallet/<anything>` URL. A buggy URL like `/wallet/deposit` does **not** fall through to the catch-all — it matches `/wallet/:code` with `code="deposit"` and renders `WalletCurrencyPage`'s "Валюта не поддерживается" error. Always check the real route table when wiring up new external links.
- There is **no** dedicated PIN settings page. `PinGate` handles PIN setup/unlock globally before any protected route renders, so links to PIN should just open any protected route (e.g. `/profile`) and let the gate trigger.
- A catalog `ServiceCard` click navigates to the **service detail** page (`/services/:id`), not the owner profile. To reach a seller's profile from a service tile, open the detail page first and click the owner card.

### Browser testing gotchas

- **Cyrillic input drops characters when typed via the keyboard layer.** Direct keystroke injection (xdotool-style `type` actions) often drops or rearranges Cyrillic characters in input/textarea fields. Workarounds: use English content for adversarial assertions where the body text is incidental, or paste from the clipboard if Russian text is actually required (e.g. `xdotool key ctrl+v` after `xclip -selection clipboard`).
- **Chrome address-bar autocomplete reuses previous paths.** Typing `localhost:5173/services/1` may autocomplete to `/services/123` (or any previously-visited path with the same prefix) and silently send you to the wrong URL. Always include the full origin, screenshot the address bar before pressing Enter, or click into the bar and press `Ctrl+A` + `Delete` before typing.

## Automated Frontend Tests (vitest + playwright)

Two complementary suites live under `frontend/`:

- **Vitest + React Testing Library** — `frontend/src/**/*.test.{ts,tsx}` with global setup in `frontend/src/test/setup.ts` and config in `frontend/vitest.config.ts`. jsdom env, shared `@/` alias with `vite.config.ts`. Run from `frontend/`:
  ```bash
  npm run test:run         # single pass
  npm run test             # watch mode
  npm run test:coverage    # v8 coverage report → frontend/coverage/
  ```
- **Playwright** — specs under `frontend/e2e/`, config in `frontend/playwright.config.ts`. Boots `vite dev` on `127.0.0.1:5174` with mobile viewport 390×844. Run from `frontend/`:
  ```bash
  npm run test:e2e:install   # once per machine, downloads Chromium
  npm run test:e2e           # full run
  npx playwright test --headed --debug   # interactive debugging
  ```

### Why `vite dev` (not `vite preview`)

`src/lib/tg.ts` reads `localStorage.dev_init_data` only when `import.meta.env.DEV` is true. `vite preview` serves a production bundle where that branch is dead-code-eliminated, so the seeded init data is never consulted and every API call returns 401. The playwright `webServer` config intentionally invokes `npm run dev` for that reason.

### E2E harness (`frontend/e2e/fixtures.ts`)

The harness deliberately bypasses the real auth + PIN flow so smoke tests run without backend/DB:

1. `seedSession(page)` writes three keys to `localStorage` via `page.addInitScript`:
   - `dev_init_data` — picked up by `src/lib/tg.ts` in DEV mode
   - `garant.pin_token` — the **PIN session token** that `PinGate` accepts directly
   - `garant.pin_token_expires` — far-future ISO timestamp
2. `mockApi(page)` registers Playwright routes for each endpoint with regex-anchored `^https?://[^/]+/api/<endpoint>(\?.*)?$` patterns. **Do NOT use `**/api/**`** — Vite serves real module URLs like `/src/api/client.ts` and that glob will intercept them, returning JSON where the browser expects JavaScript.
3. The catch-all route (`/.*/`) is registered **first**. Playwright matches the **last-registered** matching route, so explicit endpoint routes registered after the catch-all win.

### Adversarial verification rule

If you change the e2e harness or vitest specs, prove they are still sensitive by mutating **product code** they cover — not just fixture data:

- Example that does **not** work: flipping `pin/status` mock to `has_pin: false`. `seedSession()` writes a valid PIN token to `localStorage` and `PinGate` accepts it without ever calling `/api/pin/status`. The test still passes — that's correct, resilient harness behavior, not a test gap.
- Example that **does** work: change `<Route path="/" element={<Navigate to="/search" />}>` in `frontend/src/App.tsx` to a different target. The redirect spec fails with `toHaveURL` mismatch as expected.
- General rule: if you can't break a test by mutating a real source file, the test isn't actually constraining anything yet.

### Keeping fixtures in sync with backend

The playwright fixture mocks real DTOs. If you change a backend response shape (e.g. `me`, `services`, `deals`, `users`, `wallet/balances`), update the matching mock in `frontend/e2e/fixtures.ts` in the same PR — otherwise the e2e suite will pass against the old shape and silently mask real regressions.

### CI integration

`.github/workflows/ci.yml` runs vitest as a step inside the `frontend` job and playwright as a separate `frontend-e2e` job. The e2e job caches `~/.cache/ms-playwright` keyed by `@playwright/test` version, so Chromium is only re-downloaded on dep bumps (cold cache ≈ 3–4 min, warm ≈ 30s). On failure the job uploads `playwright-report/` as an artifact.

## Testing the Bot (aiogram menu)

The bot lives in `backend/app/bot/` (handlers, keyboards, sections, texts). It exposes a persistent reply keyboard with 4 sections and inline WebApp buttons that open the TMA at specific routes.

### Verifying bot → TMA URL mapping without a real Telegram client

A bot WebApp click only sends the `WebAppInfo.url` to Telegram, which opens it in the in-app browser. So verifying the URL→page mapping in a normal browser is equivalent proof for routing changes:

1. **In-process check** — import the keyboard module and render each section, then read the `web_app.url` of every button:

   ```python
   from backend.app.bot import keyboards as k
   for row in k.profile_keyboard().inline_keyboard:
       for btn in row:
           url = btn.web_app.url if btn.web_app else (btn.url or btn.callback_data)
           print(btn.text, '->', url)
   ```

2. **Browser check** — navigate Chrome to each emitted URL on `localhost:5173` and confirm the expected page renders (not the search-hub fallback).

This is much cheaper than driving an actual Telegram client and gives the same coverage for bot URL changes. The bot side (correct reply/inline keyboards, callback toggles) is already covered by the 15 unit tests in `tests/test_bot_menu.py` and doesn't need re-running per UI change.

### Required env vars for bot menu external links

Empty values hide the corresponding inline button — useful when testing without setting up real channels:

```
BOT_FORUMS_URL=
BOT_COMMUNITY_CHAT_URL=
BOT_ARBITRATION_URL=
BOT_DOCS_URL=
BOT_SUPPORT_USERNAME=  # without leading @
```

If you want to drive the bot end-to-end against real Telegram, set `RUN_BOT=1` and a real `BOT_TOKEN` (from @BotFather), then start the backend — aiogram will start polling. Don't store real tokens in plaintext in chat; request them via the Devin secrets panel.

## Pytest

Tests run against the same PostgreSQL instance, in a separate `garant_test`
database auto-created by `tests/conftest.py`. The fixture drops + recreates
that DB at session start, runs `alembic upgrade head`, then truncates all
tables between each test.

```bash
source .venv/bin/activate
pytest -v
```

Override DB connection via env vars: `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_ADMIN_DB`, `POSTGRES_TEST_DB`.

## Known Limitations

- CryptoBot deposit invoice creation returns 502 with fake token — this is expected behavior
- Telegram WebApp HapticFeedback/BackButton warnings appear in browser console — expected outside Telegram
- WebSocket connection auto-reconnects with exponential backoff — may see connection closed/reopened in logs
- The `arbitrate` endpoint uses a query parameter `reason`, not a request body
- Admin withdrawal `/decide` and service `/moderate` endpoints require TotpUser (2FA) — cannot test via simple curl without TOTP setup
- `wallet_deposits` table has a NOT NULL `provider` column — direct psql inserts need to include it
