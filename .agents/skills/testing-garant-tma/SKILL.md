---
name: testing-garant-tma
description: E2E test the Garant Telegram Mini App (FastAPI + React + aiogram). Use when verifying UI flows, API endpoints, or DB-side effects of `webapp/`.
---

# Testing the Garant TMA end-to-end

This app is a Telegram Mini App on top of a legacy aiogram escrow bot.
`main.py` runs both bot polling and uvicorn in a single asyncio loop.
The frontend is a React+Vite SPA served from `webapp/frontend/`.

## Quick start

```bash
# 1. Fresh DB (optional but recommended for deterministic seed)
rm -f database.db database.db-shm database.db-wal

# 2. Backend on :8080 (no bot polling, signature check bypassed)
BOT_TOKEN=0000000000:TEST_TOKEN \
  ALLOW_UNSIGNED_INIT_DATA=1 \
  RUN_BOT=0 RUN_API=1 \
  WEBAPP_HOST=127.0.0.1 WEBAPP_PORT=8080 \
  ALLOWED_ORIGINS=http://localhost:5173 \
  .venv/bin/python main.py &

# 3. Frontend Vite dev on :5173
(cd webapp/frontend && npm run dev) &
```

## Auth in dev mode

The SPA reads Telegram initData from `window.Telegram.WebApp` when running inside Telegram. Outside of TG it falls back to `localStorage.getItem('dev_init_data')` (`webapp/frontend/src/lib/tg.ts`).

The backend checks the HMAC signature, but `ALLOW_UNSIGNED_INIT_DATA=1` bypasses the check (`webapp/backend/security.py`). So in dev you can use a placeholder hash; **only** `auth_date`, `query_id`, `user` are required.

## Injecting dev_init_data — preferred method (CDP + Playwright)

The GUI `console` tool sometimes refuses to run because Chrome appears "not in foreground" even when it is. The reliable workaround is Playwright connecting to Chrome's CDP endpoint (already exposed on this VM at `http://localhost:29229`):

```python
# scripts/dev_login.py (one-shot)
import asyncio, json, time
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://localhost:29229')
        ctx = browser.contexts[0]
        page = next(pg for pg in ctx.pages if 'localhost:5173' in pg.url)
        init = (
            'auth_date=' + str(int(time.time()))
            + '&query_id=dev'
            + '&user=' + json.dumps(
                {'id': 7777, 'username': 'tester', 'first_name': 'tester', 'language_code': 'ru'},
                separators=(',', ':'))
            + '&hash=placeholder'
        )
        await page.evaluate("(v) => localStorage.setItem('dev_init_data', v)", init)
        await page.reload()

asyncio.run(main())
```

Direct `ws://localhost:29229/...` connections **fail** with `403 Forbidden` due to CDP origin filtering — that's why we use Playwright instead of a raw websocket client.

## Minimal seed for meaningful tests

`Category` rows (16 of them) are auto-seeded by `WebDB().seed_default_categories()` in the FastAPI lifespan. For users/admins/arbiters:

```python
from utils.database.models import db, Users
db.connect(reuse_if_open=True)
Users.get_or_create(user_id=7777, defaults={'username':'tester','balance':0,'admin':0,'ban':False,'good':0,'bad':0})
Users.get_or_create(user_id=1001, defaults={'username':'arbiter_alice','admin':1,'ban':False,'good':0,'bad':0,'balance':0})
Users.get_or_create(user_id=2001, defaults={'username':'admin_root','admin':2,'ban':False,'good':0,'bad':0,'balance':0})
```

- `admin=2` → Help → Администрация tab.
- `admin=1` → Help → Арбитры tab.

## Known issues to avoid during testing

- **`webapp/backend/routers/deals.py:99`** (as of PR #2): reads `info["seller"]` but `DB.update_deal_confirm` returns `{"position", "user_id"}`. Clicking «Подтвердить» on a deal will `KeyError`. Test path: create-deal works fine, confirm-deal will crash until fixed.
- The dev `localStorage` fallback only works if BOT_TOKEN env matches what the backend used to build the test signature. With `ALLOW_UNSIGNED_INIT_DATA=1`, any hash is accepted, so we don't need real BOT_TOKEN parity.

## What to assert (strongest signals)

1. Search → Пользователи lists seeded `Users` rows with role-prefix badges.
2. Categories: exactly 16 tiles, default sort by `sort_order` then `name`, each shows `Всего: N` from the LEFT JOIN aggregate in `WebDB.list_categories`.
3. **End-to-end write path:** AddService form → service appears in Profile/Услуги AND in `/search/categories/{slug}` AND the category tile's `Всего:` increments. This single chain proves SPA↔ky↔FastAPI↔peewee↔SQLite.
4. Deal create → counterparty receives a `Notification` row (verify by querying DB or by switching to the counterparty's session).

## Recording

Always record E2E flows. Use `annotate_recording` with `setup` for pre-recording state (login, seed), then `test_start` + `assertion` per scenario. Maximize the Chrome window first: `wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`.

## Devin Secrets Needed

For this dev/test flow: none — `BOT_TOKEN=0000000000:TEST_TOKEN` and `ALLOW_UNSIGNED_INIT_DATA=1` are enough.

For a real Telegram WebApp test against BotFather you would need:
- `BOT_TOKEN` (real, from @BotFather)
- `CRYPTOBOT_TOKEN` (for invoice/withdraw paths)
- A TLS-served public URL pointing at `WEBAPP_URL`
