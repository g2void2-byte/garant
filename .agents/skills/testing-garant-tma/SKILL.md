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

### 1. Start PostgreSQL (the only supported DB)

```bash
docker run -d --name garant-pg \
  -e POSTGRES_USER=garant -e POSTGRES_PASSWORD=garant -e POSTGRES_DB=garant \
  -p 5432:5432 postgres:16-alpine
```

### 2. Create `.env` file

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

### 3. Start backend

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

On startup the backend runs `alembic upgrade head` (creates 17 tables) and
seeds 16 categories + 10 currencies + default app settings.

### 4. Start frontend

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

Set `localStorage.dev_init_data` in browser console before refreshing:

```javascript
localStorage.setItem('dev_init_data', 'user=%7B%22id%22%3A111%2C%22first_name%22%3A%22TestBuyer%22%2C%22username%22%3A%22testbuyer%22%7D&auth_date=1700000000&hash=dev');
```

Then refresh the page. Without this, API calls from the frontend might return 422 (missing Authorization header).

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
| `/api/deals` | GET/POST | List/create deals |
| `/api/deals/{id}/confirm` | POST | Confirm deal |
| `/api/deals/{id}/complete` | POST | Complete deal (buyer only) |
| `/api/deals/{id}/cancel` | POST | Cancel deal |
| `/api/deals/{id}/arbitrate` | POST | Arbitrate (query param: reason) |
| `/api/notifications` | GET | List notifications |
| `/api/notifications/counters` | GET | Notification counts |
| `/api/payments/deposit/invoice` | POST | CryptoBot invoice (needs real token) |
| `/ws/notifications` | WS | Real-time notifications |

## Frontend Routes

| Route | Page |
|-------|------|
| `/search` | User search with filters |
| `/search/categories` | Categories grid |
| `/deals` | Deals list with status filter |
| `/deals/new` | Create deal form |
| `/deals/:id` | Deal detail with actions |
| `/notifications` | Notifications with type tabs |
| `/profile` | User profile, balance, services |
| `/profile/deposit` | CryptoBot deposit page |
| `/u/:username` | Public user profile |

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
