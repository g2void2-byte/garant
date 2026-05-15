# Garant TMA — Аудит-статус v6 (после PR #84 + PR #85)

> **Дата**: 2026-05-15
> **Репозиторий**: `g2void2-byte/garant`
> **Базовая ветка**: `devin/1778660441-fresh-rewrite-sqlalchemy`
> **Обновление к**: v3 + v5 (всё не сделанное оттуда переехало сюда; сделанное удалено)

---

## Что замержено с v5

### PR #84 (frontend coverage)
- **PR O.3** — 17 admin-страниц, 173 теста
- **PR O.4 финал** — PinPage / PinResetPage / NotificationsPage / NotificationDetailPage (45 тестов)
- **N-2 расширение** — 51 admin-схема в `openapi.contract.test.ts` + 3 runtime-проверки `required` + 2 compile-time bridges

### PR #85 (V5 backend money-safety, CI зелёный)
- **V5-A-1** — init-data replay window 24h → 15min (через `init_data_max_age_seconds`)
- **V5-A-7** — PIN reset code log-leak preventive contract + регрессионный тест
- **V5-B-1** — `SELECT FOR UPDATE` на `WalletDeposit` + balance-row → дабл-кредит закрыт
- **V5-B-2** — то же на legacy `Invoice` + `User.balance`
- **V5-B-7** — `sweep_expired_invoices` для `manual_deposit` (mirror `wallet_deposit_sweep`)
- **V5-F-5** — invalidate `["admin", "user", buyer/seller_id]` после force-release/refund/claim

---

## Сводка осталось

| Категория | Осталось |
|-----------|---------:|
| Backend audit comments 28–51 | 24 |
| V5-A (security/auth) | 8 |
| V5-B (money/payments) | 7 |
| V5-C (admin guards / maintenance / audit) | 7 |
| V5-D (notifications / reviews / arbitration / search / db) | 11 |
| V5-E (alembic / CSP / docker) | 8 |
| V5-F (frontend admin / pin / ws) | 15 |
| Frontend coverage / e2e | 3 (O.6 + N-2 v2 + N-2 v3) |
| Ops follow-up | 1 |
| **Итого** | **84** |

---

## 1. Backend audit comments 28–51 (24 шт.)

Все открыты, ни один не закрыт PR #84 / #85.

### Critical / High
- **Comment 28** (H) — Race на создании нового юзера: 4 параллельных запроса `/api/me`, `/api/wallet/balances`, `/api/notifications`, `/api/categories` ловят `IntegrityError`. Нужен `INSERT … ON CONFLICT DO NOTHING` + повторный SELECT в `deps.get_current_user`. Тест: 5 параллельных `get_current_user` с одним initData нового юзера.
- **Comment 31** (H/griefing) — `deals_total` инкрементируется на **создании** сделки → атакующий накручивает счётчик жертве 10 000 копеечных pending-сделок. Перенести инкремент в `accept_deal` / `finish_deal`.
- **Comment 37** (H/harassment) — `POST /api/deals/{id}/messages` принимает сообщения в `completed/cancelled/refunded/resolved_*` сделке. Добавить `409` на этих статусах. Staff может только в `arbitration` / `resolved_*`.
- **Comment 47** (H) — `_hit_redis` делает `INCR` + `EXPIRE` двумя round-trip'ами. Если `EXPIRE` упал, ключ остался без TTL и блокирует scope:key вечно. Обернуть в pipeline / Lua.
- **Comment 51** (H) — Fixed-window rate-limit позволяет 2× лимит на стыке окон. Особенно опасно для `RLPin` (5/60s → де-факто 10 за 100мс). Перейти на sliding-window или token-bucket.

### Medium
- **Comment 29** (M/privacy) — `/api/users` и `/api/users/{username}` отдают `tg_user_id` любому. Сделать публичный `UserPublicOut` без `user_id`.
- **Comment 30** (M/privacy) — `UserOut` светит `dm_*`, `is_banned`, `is_frozen` другим. Те же поля только в `/api/me` / `AdminUserOut`.
- **Comment 32** (M/correctness) — `sweep_inactivity` шлёт WS + DM **до** `session.commit()`. Нужен `after_commit`-механизм для WS publish (как для DM в Comment 19).
- **Comment 33** (M/UX) — `DELETE /api/services/{id}` падает 500 на FK violation если есть комменты/отзывы. Либо `ondelete="CASCADE"` + миграция, либо явное удаление зависимых строк перед `session.delete(service)`.
- **Comment 34** (M/integrity) — `admin/broadcasts.create_broadcast` не делает `html.escape` → Telegram отбивает 400 на любом `<` в title/body.
- **Comment 35** (M/privacy) — `UserUpdate.photo_url` / `banner_url` принимает `http://`. Whitelist: `https://` + относительный `/media/...`.
- **Comment 36** (M/phishing) — `Forum.url` принимает `tg://` deep-link. Whitelist схем `https://` + опционально `https://t.me/`.
- **Comment 38** (M/DoS) — WS не лимитирует число одновременных сокетов на user.id. Capped per-user (5), вытеснение со close-code; rate-limit на `WebSocket.receive_text`; heartbeat-ping.
- **Comment 39** (M) — `Notification.payload` без cap размера. Лимит 4 KB в `notifier.push`, для audit-payload — отдельная таблица.
- **Comment 42** (M/auth) — `setPinToken` принимает кривой `expiresAt` → `getTime()` = `NaN` → токен «вечный». Валидация `Number.isFinite(...)` при set.
- **Comment 43** (M) — `_purge_expired` чистит коды только старше 24h, накапливаются истёкшие. `_generate_code` без проверки коллизии активных. Удалять истёкшие сразу + `while`-проверка уникальности.
- **Comment 44** (M/UX) — `update_me` после full-replace форумов делает `session.refresh(user)` без `attribute_names=["forums"]` → клиент видит старый список. Передать `attribute_names`.
- **Comment 45** (M/GDPR) — `User.last_ip` хранится бессрочно. Либо не хранить (`last_login_at` достаточно), либо хешировать, либо background job на zeroing старше N дней.
- **Comment 48** (M/finance) — `admin/treasury.treasury_withdraw` помечает row `status="sent"` даже без CryptoBot токена → бухгалтерия расходится. Возвращать 503 при missing токене.
- **Comment 49** (M/UX) — `admin/twofa.setup` генерит свежий secret каждый GET → две вкладки = два рассинхронных QR. Хранить `pending_totp_secret` + TTL.
- **Comment 50** (M) — `get_current_user` обновляет `last_login_at` для забаненного юзера до проверки `is_banned`. Вынести проверку до `commit`.

### Low
- **Comment 40** (L) — `devtoolsGuard` не блокирует `Cmd+Opt+I/J/U/C` на macOS Telegram Desktop.
- **Comment 41** (L/защита от XSS-эскалации) — `getInitData()` читает `localStorage["dev_init_data"]` под `import.meta.env.DEV`. Убрать `localStorage` fallback, перейти на `?dev_init_data=…` + `hostname === "localhost"` runtime guard.
- **Comment 46** (L/disk) — Старые `Media` записи и файлы не удаляются при замене `photo_url` / `banner_url` / attachments. Периодический `cleanup_orphan_media` + FK с `ondelete="SET NULL"`.

---

## 2. V5-A — Security / Auth (8 шт.)

| ID | Sev | Файл | Минимум фикс |
|----|-----|------|--------------|
| V5-A-2 | L | `security.py` | Прокомментировать инвариант пустого hash |
| V5-A-3 | M | `security.py` | Доп. чек по hostname для `_parse_unsigned` в dev |
| V5-A-4 | M | `routers/pin.py` | Blacklist популярных PIN'ов (`0000`, `1234`, `1111`, `2580`, …) |
| V5-A-5 | L | `routers/pin.py` | Поднять `_ensure_format` до `_is_locked` |
| V5-A-6 | M | `routers/pin.py` | Уточнить комментарий M-10 про rollback |
| V5-A-8 | M | `routers/pin.py` | Отдельный счётчик `pin_reset_attempts` |
| V5-A-9 | L | `auth_2fa.py` | `ADMIN_TOTP_BYPASS` читать в каждом запросе + лог при старте |
| V5-A-10 | M | `auth_2fa.py` | Документировать NTP/PTP требования |

---

## 3. V5-B — Money / Payments (7 шт.)

| ID | Sev | Файл | Минимум фикс |
|----|-----|------|--------------|
| V5-B-3 | M | `services_wallet.py` | Гарантировать non-empty `pay_url` (валидация в `cryptopay.create_invoice`) |
| V5-B-4 | M | `services_wallet.py` | Per-currency regex-валидатор адреса в `create_withdrawal` |
| V5-B-5 | M | `services_wallet.py` + `admin/withdrawals.py` | Зафиксировать комментом, что `spend_id` идемпотентен на стороне CryptoBot |
| V5-B-6 | M | `admin/withdrawals.py` | На `reject` ставить `w.locked_until = None` |
| V5-B-8 | M | `routers/payments.py` | Убрать legacy fallback `body.get("type")` |
| V5-B-9 | L | `admin/withdrawals.py` | `SELECT status, COUNT(*) GROUP BY status` единым запросом |
| V5-B-10 | M | `routers/wallet.py` | Throttle `poll_deposit_status` (1/30s через Redis) или `rate_limit("wallet-poll")` |

---

## 4. V5-C — Admin guards / Maintenance / Audit (7 шт.)

| ID | Sev | Файл | Минимум фикс |
|----|-----|------|--------------|
| V5-C-1 | M | `maintenance.py` | Throttled logger при DB-down (first + every Nth) |
| V5-C-2 | L | `maintenance.py` | Redis pubsub invalidate либо TTL → 5s |
| V5-C-3 | M | `maintenance.py` | Ограничить `/api/auth/*` префикс только read-эндпоинтами |
| V5-C-4 | M | `admin_audit.py` | 4 KB cap на `payload` через `json.dumps + truncate` |
| V5-C-5 | L | `admin_audit.py` | Документировать trusted-proxy конфигурацию для X-Forwarded-For |
| V5-C-6 | M | `admin_guard.py` + `auth_2fa.py` | Redis idempotency на TOTP counter (in-process check независимо от commit) |
| V5-C-7 | L | `admin_guard.py` | Regression test: `/api/admin/dashboard` без auth → 401 |

---

## 5. V5-D — Notifications / Reviews / Arbitration / Search / DB (11 шт.)

| ID | Sev | Файл | Минимум фикс |
|----|-----|------|--------------|
| V5-D-1 | M | `notifications.py` | Cursor-pagination по `(created_at, id)` |
| V5-D-2 | M | `notifications.py` | RLPin-style лимит на `mark_all_read` |
| V5-D-3 | L | `notifications.py` | OK как есть (404 на чужое/не-существующее — privacy) |
| V5-D-4 | M | `reviews.py` | Hard cap `offset <= 10000` |
| V5-D-5 | M | `arbitration.py` | `selectinload(buyer/seller)` в `_deal_out` для list-эндпоинта |
| V5-D-6 | L | `support.py` | OK на текущий объём, future-pagination |
| V5-D-7 | L | `csp_report.py` | Категорное гашение после N репортов одной error-категории/час |
| V5-D-8 | M | `search.py` | `tokens[:10]` в `build_prefix_tsquery` |
| V5-D-9 | M | `db.py` + `alembic/env.py` | Проверить advisory lock в alembic env (rolling deploy 8 воркеров) |
| V5-D-10 | L | `services.py` | `SUM(CASE…)` вместо двух COUNT |
| V5-D-11 | M | `services.py` ↔ `services_wallet.py` | Тест-инвариант: `INVOICE.paid` меняет только `User.balance`, `WalletDeposit.paid` — только `UserBalance` |

---

## 6. V5-E — Alembic migrations / CSP / Docker (8 шт.)

| ID | Sev | Файл | Минимум фикс |
|----|-----|------|--------------|
| V5-E-1 | L | `alembic/versions/*` | Документировать irreversible data loss на downgrade |
| V5-E-2 | M | `c8f4a2e91d35_*.py` | `postgresql_concurrently=True` + autocommit-block |
| V5-E-3 | M | `b8adfad43818_*.py` | То же для FTS-индексов на `services` / `users` |
| V5-E-4 | L | `main.py` CSP | Перевести 7 inline-style файлов в Tailwind / CSS-modules |
| V5-E-5 | M | `main.py` CSP | Sentry-grade алерт на CSP-violations в production |
| V5-E-6 | M | `docker-compose.yml` | `127.0.0.1:5432:5432` или `expose` вместо `ports` + warning в README |
| V5-E-7 | L | `backend/Dockerfile.dev` | `pip install -e . --no-deps` или кэш на CMD-time install |
| V5-E-8 | L | `frontend/Dockerfile.dev` | Закрепить `--port` явно (минор, OK как есть) |

**Бонус из v4** (тоже в этом блоке):
- `models.User.last_ip` — `String`, не `INET` (Postgres-тип дал бы валидацию + индексацию).
- `Deal.sum` (legacy `Numeric(14,2)`) и `Deal.amount` — двойная бухгалтерия, миграция к удалению `Deal.sum`.
- `manager.publish` логирует `logger.exception(...)` на каждое падение `send_json` → `logger.debug` для известных «socket closed».

---

## 7. V5-F — Frontend (admin / pin / ui / ws) (15 шт.)

| ID | Sev | Файл | Минимум фикс |
|----|-----|------|--------------|
| V5-F-1 | M | `api/admin/hooks.ts` | Расширить `useAdminUserAction.onSuccess` на `user-services`/`user-reviews`/`user-wallet` |
| V5-F-2 | M | `useAdminDecideWithdrawal` | + `["admin","user-wallet", userId]` + `["admin","treasury"]` |
| V5-F-3 | M | `useAdminAdjustBalance` | + `["admin", "user", userId]` |
| V5-F-4 | M | `useAdminCreateBroadcast` | минор (user-side кеш) |
| V5-F-6 | M | `useAdminDecideWithdrawal` | + `["admin", "audit", …]` |
| V5-F-7 | M | `pages/pin/PinPage.tsx` | Сброс `memo` на mount (KeepAlive-safe) |
| V5-F-8 | M | `pages/pin/PinResetPage.tsx` | Показать оставшиеся попытки на reset-странице |
| V5-F-9 | L | `pages/pin/PinResetPage.tsx` | `autoComplete="one-time-code"` + `maxLength={6}` |
| V5-F-10 | M | `lib/ws.ts` | Try-catch + fallback на `new URL()` для относительного |
| V5-F-11 | M | `lib/ws.ts` | Обязательный `VITE_API_URL` в production-build |
| V5-F-12 | L | `NotificationDetailPage.tsx` | Phrase-anchor `сделка #(\\d+)` вместо `#(\\d+)` |
| V5-F-13 | L | `components/ui/Toast.tsx` | OK (NoOp в unmount'е) |
| V5-F-14 | M | `pages/deals/DealChatPanel.tsx` | Документировать инвариант: `m.url` всегда trusted (через `routers/media.py`) |
| V5-F-15 | L | `pages/profile/AddForumPage.tsx` | Validator `https?://` |
| V5-F-16 | M | `pages/profile/SettingsPage.tsx` | `useIsMutating` для общего `isAnyMutationPending` |

---

## 8. Frontend coverage / e2e (3 шт.)

### PR O.6 — e2e расширение (1–2 дня)

Сейчас 4 smoke'а с замоканным API. Не покрыто:
- Полный PIN setup-flow без `seedSession` bypass: «Создайте PIN» → «Подтвердите PIN» → unlock.
- Создание сделки end-to-end (`/deals/new` → fill → submit → redirect на detail).
- Подтверждение/завершение от двух ролей (Playwright два browser context'а).
- Фильтрация каталога по категории + сортировка.
- Withdrawal flow с PIN session check.
- Notifications WebSocket — open соединение, payload, проверка UI.

### N-2 variant 2 — live backend в e2e (1 день)
Поднимать Postgres + backend в CI job'е, не мокать API в Playwright. +3-5 минут CI, ловит runtime-несоответствия (rate-limits, JWT, бизнес-логика).

### N-2 variant 3 — Pact-стайл (2 дня)
Consumer-contracts фронта в Pact-broker, бэк валидирует свои PRs. Делать только если появится второй consumer (mobile / web).

---

## 9. Ops follow-up — BotFather + прод-домен

**Без изменений с v3**, на стороне пользователя:
- Вставить URL в BotFather: `/mybots` → `@EWGarant_bot` → **Bot Settings** → **Configure Mini App** → **Edit Mini App URL**.
- Визуальная проверка fullscreen на ПК / минимизации на телефоне.
- **Прод**: trycloudflare-тоннель временный. Свой домен + nginx/Caddy → backend и frontend (или Fly / Vercel + Railway).

---

## 10. Топ-приоритеты v6

По реальному ущербу:

1. **Comment 28** (H) — race на старте новых юзеров. Простой фикс, высокая частота.
2. **Comment 31** (H/griefing) — счётчик `deals_total` накручивается жертве. Активно эксплуатируется в подобных сервисах.
3. **Comment 37** (H/harassment) — чат живёт в completed/refunded сделке. Прямой attack vector.
4. **Comment 47** (H) — Redis `INCR` + `EXPIRE` без atomic. Может выключить rate-limit полностью на flap'е.
5. **Comment 51** (H) — 2× rate-limit на стыке окон. Тривиально обходимый bypass.
6. **V5-D-9** (M) — alembic upgrade race на rolling deploy.
7. **V5-E-2 / V5-E-3** (M) — миграции без CONCURRENTLY на больших таблицах.
8. **V5-C-6** (M) — TOTP-replay в read-эндпоинтах.

Остальные M — UX-correctness / lifecycle, не блокеры релиза.

---

## 11. Что не пройдено детально (мост в v7)

- `routers/admin/treasury.py`, `routers/admin/broadcasts.py`, `routers/admin/2fa.py`, `routers/admin/users.py` (детально, кроме ban/unban) — не пройдено.
- `services_account.py`, `services_deals.py` (полностью, кроме legacy mediator-комитов из v4).
- `bot/handlers.py` (полностью), `notifier._format_dm`, шаблоны DM (XSS / TG-Markdown HTML escape).
- Frontend i18n / locale handling — не подтверждено наличие.
- nginx / Caddy конфиги (production).

---

## 12. Метрики

| Метрика | Текущее |
|---------|--------:|
| Backend тесты | **393** (после PR #85, +12 от V5) |
| Frontend unit/component | **~470+** (после PR #84) |
| Frontend e2e smoke | 4 |
| Frontend coverage (statements) | **~52–55%** (прогноз после PR #84) |
| Backend audit closed (1–27 + 28–51) | **27 / 51** |
| V5 closed | **6 / 57** (V5-A-1, V5-A-7, V5-B-1, V5-B-2, V5-B-7, V5-F-5) |
| Backlog total | **84 items** |
