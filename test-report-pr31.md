# Test report — PR #31

**PR:** https://github.com/g2void2-byte/garant/pull/31 — *fix(bot): align inline-button URLs with real frontend routes*
**Session:** https://app.devin.ai/sessions/41c999cb1248410f91f7101c48247798

## Summary

Ran the local backend + Vite frontend on `:8080/:5173`, set `dev_init_data` for unsigned auth, created a PIN, then drove the browser to each of the 5 fixed bot URLs and to the 3 old buggy URLs. The bot keyboard builders (`backend/app/bot/keyboards.py`) were also invoked in-process to confirm the exact `WebAppInfo.url` strings produced.

**Result:** 6/6 tests passed. All buttons that were broken now land on the correct page. Old buggy URLs either fall through to `/search` or — for `/wallet/deposit` — match an unrelated currency-detail route and show "Валюта не поддерживается" (more on this below).

## Tests

| # | Test | Result |
|---|---|---|
| T1 | `/search` opens SearchPage (was `?tab=users`) | **passed** |
| T2 | `/search/categories` opens CategoriesPage (was `?tab=services`) | **passed** |
| T3 | `/deals` opens DealsPage (was `?as=`/`?filter=`) | **passed** |
| T4 | `/profile` opens ProfilePage (was `/profile/me`) | **passed** |
| T5 | `/profile/deposit` opens DepositPage (was `/wallet/deposit`) | **passed** |
| T6 | Old buggy URLs all break (proves the bug was real) | **passed** |

## In-process check on the bot keyboards

Imported `backend.app.bot.keyboards` and rendered each section's `InlineKeyboardMarkup` — confirmed every `web_app.url` now matches the new routes:

```
search:    /search, /search/categories
deals:     /deals (×3)
profile:   /profile, /profile/deposit
settings:  /profile (PIN button → PinGate)
```

No `/profile/me`, no `/wallet/deposit`, no `/settings/pin`, no query strings.

## Evidence — fixed URLs (each lands on the right page)

| Test | URL | Screenshot |
|---|---|---|
| T1 | `/search` | ![T1](https://app.devin.ai/attachments/7bd9a513-6bb9-4193-955b-1d2b1171c1f8/screenshot_807a4020fbc14507905c8eaa39abe98a.png) |
| T2 | `/search/categories` | ![T2](https://app.devin.ai/attachments/640b66c3-e0a1-4746-ae48-f027f82e384b/screenshot_d830ade520d84915824b3041c275016b.png) |
| T3 | `/deals` | ![T3](https://app.devin.ai/attachments/e32914ff-75f7-4e6a-b1e8-4bb46926ae2f/screenshot_8adea191a12241ef8abf7ac72275a78e.png) |
| T4 | `/profile` | ![T4](https://app.devin.ai/attachments/74a4b047-5c4f-4dfe-a5e5-0d9c651a927c/screenshot_30aa437f8e924d12a318b0c8d1b2b88b.png) |
| T5 | `/profile/deposit` | ![T5](https://app.devin.ai/attachments/41c0dba3-4f0e-47a6-8914-399fd600d9bf/screenshot_8e5f1c8935d04af9b4dc7c8f5369822c.png) |

## Evidence — old buggy URLs (T6)

The "before" check that distinguishes a real fix from a no-op: visiting the URLs the bot used to send shows users land on the wrong/broken page.

| Buggy URL | Outcome | Screenshot |
|---|---|---|
| `/profile/me` | Catch-all redirects to `/search` (search hub) | ![profile/me](https://app.devin.ai/attachments/cca7b234-1f78-4608-b185-07e2bbb50d7c/screenshot_d30a66e2e0b343cd9cce73680d806322.png) |
| `/wallet/deposit` | Matches `/wallet/:code` with code="deposit" → "DEPOSIT — Валюта не поддерживается" | ![wallet/deposit](https://app.devin.ai/attachments/e6ffbc1c-b805-409b-aff5-653c45c14035/screenshot_f1872bb250514e6d8ec16cff4167ad48.png) |
| `/settings/pin` | Catch-all redirects to `/search` | ![settings/pin](https://app.devin.ai/attachments/bfd3b466-6299-40b5-b5b8-767773cf30a3/screenshot_8b6b7359884a44b89a3894ebe86f5f0f.png) |

Note: `/wallet/deposit` was a bit worse than I initially expected — instead of falling through to `/search` it hits the dynamic `WalletCurrencyPage` route (`/wallet/:code`) and renders an unhelpful "Валюта не поддерживается" error page. That's the actual broken UX the fix replaces with the real CryptoBot deposit form.

## Out of scope (not tested)

- Tapping the bot's reply keyboard inside Telegram on a phone — would require physical/emulated Telegram client. The bot's reply with the right inline keyboard is already covered by 15 unit tests in PR #30. Telegram simply opens `WebAppInfo.url` in its in-app browser; verifying the URL→page mapping in a regular browser is equivalent proof for the routing change in PR #31.
- Toggling Анонимность/Скрытый профиль in the Настройки submenu — unchanged by PR #31 (also covered by unit tests).
- PIN setup flow itself — `PinGate` is unchanged; PR #31 only re-points the "🔒 PIN" button at `/profile` so the gate has a chance to trigger.
