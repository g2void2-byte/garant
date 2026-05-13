# Test plan — PR #31: fix(bot): align inline-button URLs with real frontend routes

## What changed

The bot reply-keyboard sections (PR #30) sent users to routes that don't exist
on the TMA. The SPA's catch-all (`*` → `/search`) then silently dumped users
on the search hub instead of the intended page. PR #31 fixes the URLs.

| Section | Button | Before | After |
|---|---|---|---|
| Поиск | Поиск пользователя | `/search?tab=users` | `/search` |
| Поиск | Поиск услуг | `/search?tab=services` | `/search/categories` |
| Сделки | Покупок / Продаж / Ожидающие | `/deals?as=…`, `?filter=…` | `/deals` (×3) |
| Профиль | Мой профиль | `/profile/me` | `/profile` |
| Профиль | Депозит | `/wallet/deposit` | `/profile/deposit` |
| Настройки | PIN | `/settings/pin` | `/profile` |

Already confirmed via in-process call to the keyboard builders that the
`web_app.url` payloads now exactly match the new routes above (see
`backend/app/bot/keyboards.py:51-127`).

## Methodology

Telegram only forwards a click on a WebApp button by opening the
`web_app.url` in the in-app browser. Verifying the URL → frontend page
mapping in a regular browser is **equivalent proof** for the routing fix
(and is independent of having a phone). So:

For each fixed URL, navigate the local browser to it and verify the SPA
renders the matching page (not the catch-all `/search` fallback). For
the buggy "before" URLs, navigate and verify the SPA does fall through
to `/search` — proving the bug PR #31 fixes is real.

## Tests

Pre-state for every test: backend on `:8080`, frontend on `:5173`,
`localStorage.dev_init_data` set so `/api/me` returns 200.

### T1 — `/search` renders SearchPage (was `?tab=users`)
- Open `http://localhost:5173/search`
- **Pass:** URL bar stays `/search`; page header reads `Поиск` with subtitle
  `Найдите нужного пользователя или услугу за секунды`.
- **Fail signature if broken:** URL would change or page would show
  search hub but for a different route.

### T2 — `/search/categories` renders CategoriesPage (was `?tab=services`)
- Open `http://localhost:5173/search/categories`
- **Pass:** URL bar stays `/search/categories`; page header reads
  `Категории` with subtitle `Выберите раздел услуг`. There must be a
  visible "back" arrow (Page with `showBack`).
- **Fail signature if broken:** would redirect to `/search` and show the
  user-search subtitle instead.

### T3 — `/deals` renders DealsPage (was `?as=…` and `?filter=…`)
- Open `http://localhost:5173/deals`
- **Pass:** URL bar stays `/deals`; page header reads `Ваши сделки`.
  Role tabs (Все / Покупки / Продажи) are visible inside the page.
- **Fail signature if broken:** would redirect to `/search`.

### T4 — `/profile` renders ProfilePage (was `/profile/me`)
- Open `http://localhost:5173/profile`
- **Pass:** URL bar stays `/profile`; page renders `ProfileHeader` with
  the current user (no "Поиск" header). Profile actions (services / reviews
  tabs, action buttons) are visible.
- **Fail signature if broken:** would redirect to `/search`.

### T5 — `/profile/deposit` renders DepositPage (was `/wallet/deposit`)
- Open `http://localhost:5173/profile/deposit`
- **Pass:** URL bar stays `/profile/deposit`; page header reads
  `Пополнение баланса` with subtitle `USDT через CryptoBot`. The "back"
  arrow is visible.
- **Fail signature if broken:** would redirect to `/search`.

### T6 — Regression: confirm the BUG on the old URLs
This is the "before" check that distinguishes a real fix from a no-op.
- Open `http://localhost:5173/profile/me` →
  **Pass:** URL bar becomes `/search` (catch-all redirect), page shows
  the search hub with subtitle `Найдите нужного пользователя или услугу за секунды`.
- Open `http://localhost:5173/wallet/deposit` →
  **Pass:** redirects to `/search`.
- Open `http://localhost:5173/settings/pin` →
  **Pass:** redirects to `/search`.
- These all failing the same way confirm the bug PR #31 fixes was real.

## Why these tests would look different if the change were broken

If PR #31 didn't actually edit `keyboards.py`:
- T1–T5 would *redirect to `/search`* (catch-all). The header subtitle
  observed would be the search-hub one for every test.
- T6 would still pass (the bug is independent of the fix).

If PR #31 edited the URLs but used wrong replacements (e.g. `/profile/me` →
`/me` instead of `/profile`):
- The bot in-process URL probe would have caught it earlier; even so,
  T4 would land on `/search`.

## Out of scope

- Tapping the actual buttons inside Telegram on a phone client. The
  bot-side reply with the correct keyboards is already covered by the 15
  unit tests in PR #30, and the URL → page mapping is what fails when
  Telegram forwards the WebApp click.
- Toggling settings (anon/hidden) — covered by unit tests in PR #30 and
  unchanged by PR #31.
- PIN setup flow — `PinGate` is unchanged; PR #31 only re-points the
  bot's "PIN" button at `/profile` so the gate has a chance to show up.
