# Аудит кода Garant от 2026-06-01

Репозиторий: `g2void2-byte/garant`
Ветка аудита/PR: `audit-fixes-2026-06-02-settings-system`, PR #255
База исходного аудита: `devin/1778660441-fresh-rewrite-sqlalchemy` @ `8b52761247b31697face725aba183d3b3ee6a1be`

## Область проверки

Проведен ручной аудит backend, frontend, миграций, платежных и wallet-потоков, админских сценариев, realtime/WebSocket, media, CSP/client-error endpoints, Telegram-уведомлений и основных тестов. Это инженерный аудит по коду и сценариям отказа, а не формальное доказательство отсутствия всех возможных дефектов.

## Автоматические проверки

- `npm run typecheck` - успешно.
- `npm run lint` - успешно.
- `npm run test:run` - успешно: 89 файлов, 933 теста. В выводе есть ожидаемые jsdom-трейсы ErrorBoundary/lazyWithRetry.
- `npm run build` - успешно.
- `npm audit --omit=dev --json` - 0 production-уязвимостей.
- `uv run --frozen ruff check .` - успешно.
- `uv run --frozen --extra dev pyright` - успешно.
- `node scripts/check-pinned-deps.cjs frontend\package.json` - успешно.
- Alembic: один head `zi9d0e1f2g3h`.
- `uv run --frozen --extra dev pytest -q` - не прошел из-за инфраструктуры БД: `asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in the middle of operation` в bootstrap из `tests/conftest.py`.
- `docker compose ps` - Docker недоступен в текущей среде.
- `uv run --frozen --extra dev python scripts/dump_openapi.py` - успешно; `frontend/openapi.json` перегенерирован под текущие backend schemas.

## Статус исправлений

Все findings из этого отчета, кроме намеренно снятого low-priority пункта по card/TRUST/manual fallback flows, закрыты в текущем дереве:

- H-01: admin force-release/split блокируют buyer/seller balances в детерминированном порядке.
- H-02: `delete_deal` удаляет физические media-файлы только после успешного commit БД.
- H-03: payment webhooks читают тело через ограниченный reader с cap 64 KiB до JSON parsing.
- H-04: TOTP gate больше не делает raw replay запроса в обход React Query callbacks.
- H-05: broadcast создает `Broadcast(status=sending)` и audit intent до отправки, затем фиксирует counters/final audit.
- H-06: frontend WebSocket не переподключается на terminal close codes `4001`, `4002`, `4003`.
- M-01/M-10: deposit/deal create paths отправляют суммы строкой/`Decimal`; старый withdraw tab на per-currency wallet page удален.
- M-02: комментарий вокруг `commission_paid` синхронизирован с фактическим invariant.
- M-03: withdrawal отказывается до lock-а, если нет auto/manual delivery path; auto-fail без админов возвращает locked funds.
- M-04/M-05: account-transfer length/TTL берутся из backend policy, а `code_hash` защищен DB unique constraint + retry.
- M-06: punctuation-only search для services возвращает пустой список.
- M-07: bot runner/notify/admin system используют общий validator configured bot token.
- M-08: nullable withdrawal address отражен во frontend types/admin UI.
- M-09: `TRUSTED_PROXIES` comment/startup guard приведены к фактической семантике.
- M-11: media upload удаляет уже записанный файл, если commit `Media`-строки в БД падает.
- M-12: GitHub Actions больше не используют Node.js 20-based `setup-python@v5` / `setup-uv@v3`.
- M-13: admin deposit mark-paid/refund инвалидируют все кэши, которые меняют backend side effects.
- M-14: admin financial mutations обновляют analytics/wallet кэши после deposit/withdrawal side effects.
- M-15: admin review create/edit/delete обновляют rating/review/public-user кэши после recompute side effects.
- M-16: admin service/comment edit/delete обновляют public catalog/service/comment/category/audit кэши после content side effects.
- M-17: admin taxonomy/currency mutations обновляют public category/service/wallet/admin projection кэши.
- M-18: backend `DELETE /api/admin/currencies/{id}` больше не является недоступной из UI операцией.
- M-19: admin broadcast delete обновляет audit cache после backend audit-log side effect.
- M-20: admin settings/system mutations обновляют maintenance/system/audit кэши после side effects.
- M-21: admin wallet adjust/rate mutations обновляют system/user-wallet/user-facing wallet кэши.
- M-22: admin user actions обновляют public user/profile/me кэши после public-profile side effects.
- M-23: admin in-app broadcast send обновляет notifications/counters cache после fan-out side effect.
- M-24: user review create обновляет public users list cache после rating recompute side effect.
- M-25: deal state transitions/WS events обновляют wallet/public-user/me кэши после participant side effects.
- M-26: user service update/delete обновляют category/detail/comment кэши после catalog side effects.
- M-27: profile hidden/public update обновляет service/category/review кэши, а category counters больше не считают hidden-owner services.
- M-28: create-deal frontend корректно обрабатывает `invoice: null`, когда сделка полностью оплачена с баланса.
- M-29: user deal list больше не игнорирует неизвестные `role`/`status` фильтры.
- M-30: admin deal list снова умеет фильтровать `pending_topup`, а deprecated `pending_payment` больше не показывается как UI-фильтр.
- M-31: admin deal/claim mutations сбрасывают audit log и точечный deal detail cache.
- M-32: admin deposit/withdrawal queues больше не запирают админа на первой странице.
- M-33: admin wallets inspector больше не запирает админа на первой странице пользователей.
- M-34: admin broadcasts history больше не запирает админа на первой странице рассылок.
- M-35: admin arbitration queue больше не запирает админа/арбитра на первой странице.
- M-36: admin user content sections больше не грузят неограниченные services/reviews/comments и не запирают админа на первой странице.
- M-37: admin deal detail больше не встраивает полный чат сделки; история грузится курсорными страницами.
- M-38: user-facing arbitration page больше не запирает пользователя/арбитра на первых 50 спорах.
- M-39: user search больше не обрезает выдачу первыми 100 пользователями без возможности догрузки.
- M-40: user deal list больше не отправляет invalid `role=all` и не грузит весь список сделок одним ответом.
- M-41: notifications page больше не запирает пользователя на первой странице уведомлений.
- M-42: per-currency wallet history больше не обрезается первыми 100 unfiltered deposit/withdrawal rows.
- M-43: service detail comments больше не запирают пользователя на первой странице комментариев.
- M-44: profile reviews больше не запирают пользователя на первой странице отзывов.
- M-45: profile/category service lists больше не запирают пользователя на первой странице услуг.
- M-46: deal detail review CTA больше не зависит от первой страницы отзывов профиля.
- M-47: users picker больше не обходит search gate пустым `picker=1` запросом.
- M-48: offset-пагинация admin/public списков больше не сортирует страницы только по `created_at` без `id` tie-breaker.
- M-49: admin deal approvals API больше не обрезает очередь первыми 200 заявками без total/offset.
- M-50-M-111: admin exact-user lookup, wallet preview, content rating validation, settings bounds/stats, zero-deal own-service listing, auto-withdraw races, paid PIN reset delivery rollback, account-transfer code race, Crystalpay webhook dedupe, refunded-deposit re-credit guards, event-loop-safe maintenance cache, strict deal attachment ids/admin review ids, strict review rating/deal_id, strict service-comment ratings, strict admin deal action ids, strict admin counter integers, strict boolean payload flags, strict admin manual rating numbers, admin currency schema hardening, service write schema hardening, broadcast audience strict ints, arbitration resolve enum, username refs, currency-code normalization, 2FA secret/code contract, query-filter contracts, public user search filters, notification/audit query contracts, admin numeric filter guards, strict route id parsing, notification deal-link parsing, admin finance form number parsing, user service/deal amount parsing, admin content form number parsing, admin user-detail form number parsing, admin deal action form number parsing, admin users page parsing, admin settings form parsing, admin deals page parsing follow-up, PIN reset price non-finite guard, display decimal parsing, topup invoice metadata, profile rating display, Retry-After/crop zoom parsing, service photo URL validation, broadcast deeplink validation, structured API error detail parsing, create-deal insufficient-funds parsing и live-notification runtime payload validation исправлены.
- M-112: frontend service DTO теперь отражает nullable `owner_username` и обязательный nullable `created_at`; карточки/детали услуг не строят `@null`, `/users/null` и `/create-deal/null`.
- M-113: per-currency wallet history больше не показывает refunded deposit raw-статусом, а OpenAPI contract test покрывает service/deposit DTO drift.
- M-114: frontend user/deal/review/support DTO теперь отражают nullable username-поля из OpenAPI; public search/profile/deal/review/support UI не строит `@null`, `/users/null`, `/deals/new?to=null` и `t.me/null`.
- M-115: deal media/message DTO вынесены в общий contract surface и приведены к OpenAPI; live-notification runtime guard больше не принимает attachment без обязательного `created_at`.
- M-116: admin audit/analytics UI больше не маскирует missing username как `@7`, `@system` или `@—`.
- M-117: frontend currency/admin finance DTOs now mirror OpenAPI default-backed fields and string money projections; contract tests cover admin currency/rate/deposit/withdrawal/wallet and notification payloads.
- M-118: admin deal/finance/user/content rows now share a username formatter and no longer render nullable usernames as `@--`/`@—` handles.
- M-119: Telegram contact links now go through a username URL builder, and `openTelegramLink` refuses non-`t.me` HTTP(S) URLs even in the desktop fallback.
- M-120: deal topup invoice and admin approval DTO money fields now match OpenAPI; contract tests bridge `AdminApprovalOut` and required numeric invoice totals.
- M-121: StatsBadge count-up no longer suppresses the React hooks dependency lint rule and restarts animations from the latest displayed value.
- M-122: admin deposit `pay_url` no longer renders a raw `href`; it is gated through the shared safe external-link predicate and payment opener.
- M-123: deal chat attachment URLs are validated before `href`/`img` use, and live-notification payloads reject malformed media URLs before cache insertion.
- M-124: admin currency create, wallet-adjust and USD-rate schemas now share the strict currency-code contract and OpenAPI pattern used by user money endpoints.
- M-125: profile banners no longer interpolate user-controlled URLs into CSS `background-image`; they render as a single inert `<img>` URL instead.
- M-126: shared Telegram/external/payment link openers now reject credential-bearing and whitespace/control-character URLs before reaching Telegram or `window.open`.
- M-127: backend profile/service media URL schemas now reject encoded/dot-segment media paths and malformed HTTPS ports before storage.
- M-128: service photo upload previews and public service galleries now gate every image URL through the shared `/media/...` runtime predicate before rendering/submitting.
- M-129: frontend public username route helpers now reject non-contract usernames before `/users/...`, `/create-deal/...`, `/deals/new?to=...`, and `/api/users/...` construction.
- M-130: profile/deal/service pages now gate route/query username refs before related services/reviews/create-deal queries, review targets, and counterparty submissions.
- M-131: admin broadcast fan-out now keyset-pages recipient ids instead of materializing the whole audience id list before chunking.
- M-132: admin broadcast create/preview and composer now require at least one delivery channel, so zero-channel broadcasts cannot be sent as successful records.
- M-133: admin broadcast language filters now enforce the same ASCII language-tag contract in backend schema and frontend composer validation.
- M-134: UI display preferences now tolerate blocked `localStorage` at import time and still update in-memory state.
- M-135: the dev `initData` fallback now treats blocked `localStorage` as a missing fallback instead of crashing auth bootstrap.
- M-136: lazy route chunk retry now preserves the original import error when `sessionStorage` is unavailable and reloads only with a stored guard.
- M-137: frontend `/media/...` runtime filtering now rejects encoded/double-slash/backslash/fragment paths instead of only checking origin and prefix.
- M-138: avatar/banner/admin user images now pass through the same safe image URL boundary before rendering.
- M-139: admin deals amount filters now drop/block reversed min/max ranges before querying.
- M-140: public user search registration-date filters now block reversed ranges in the sheet.
- M-141: public deal rows no longer nest profile links inside deal-detail links; row/profile navigation is separated.
- M-142: wallet history query params now mirror the backend currency/limit/offset contract before requests are enabled.
- M-143: wallet currency routes and balance rows now reject malformed API currency codes before path construction.
- M-144: profile fiat balance actions now normalize display currency refs before rendering wallet query links.
- M-145: cached PIN tokens with malformed stored expiry values are now treated as invalid and cleared before auth headers/UI gates can trust them.
- M-146: cached admin TOTP session tokens with malformed stored expiry values are now treated as invalid and cleared before admin auth headers can trust them.
- M-147: wallet deposit currency options now drop malformed API currency codes and normalize URL hints before creating invoices.
- M-148: wallet withdrawal options now require positive fiat balances with valid currency codes before selection/submission.
- M-149: trust-deposit currency options now normalize/drop malformed API currency rows before creating trust invoices.
- M-150: shared frontend date labels now reject malformed timestamps and avoid treating far-future timestamps as fresh activity.
- M-151: PIN lock countdown now ignores malformed `locked_until` values instead of rendering `NaN` and locking the keypad.
- M-152: account-transfer active-code countdown now renders malformed `expires_at` values as a neutral placeholder instead of `NaN мин.`.
- M-153: admin queue timestamps now share a safe formatter instead of rendering `Invalid Date` for malformed `created_at` values.
- M-154: operational/detail timestamp surfaces now render malformed dates as a neutral placeholder instead of raw invalid-date text.
- M-155: admin deal chat now uses the shared username formatter without adding a second `@` prefix.
- M-156: per-currency wallet history now pushes malformed timestamp rows behind valid dated rows instead of letting `NaN` freeze merge order.
- M-157: notifications load-more now refuses malformed keyset cursors before sending `before_created_at`/`before_id` to the API.
- M-158: shared frontend money badges now parse decimal-string payloads and reject exponent/hex notation instead of collapsing valid string amounts to `$0`.
- M-159: public user/service rating badges now parse string ratings and render malformed/out-of-range values as a neutral dash instead of calling `.toFixed()` on runtime payloads.
- M-160: admin user/service metric rows now share strict decimal/rating display helpers instead of calling `.toFixed()` on runtime payloads.
- M-161: admin finance/deal amount surfaces now share strict amount display helpers instead of rendering malformed Decimal payloads as `$0`/`0.00`.
- M-162: public profile review ratings now use the shared strict rating formatter instead of coercing malformed review payloads to `0.0`.
- M-163: admin system latency/uptime displays now reject malformed runtime numeric payloads instead of throwing or rendering `NaN`.
- M-164: public currency precision and create-deal commission previews now normalize runtime numeric DTOs before formatting.
- M-165: public wallet balance gates now parse string money mirrors strictly before showing withdraw/locked states.
- M-166: public user/profile/service/category counters now use strict integer parsing before display, gates, and pagination decisions.
- M-167: admin analytics KPI, sparkline and top-list metrics now reject malformed runtime numeric payloads before display/SVG plotting.
- M-168: public review star rows now parse runtime ratings strictly before filling stars instead of relying on JavaScript numeric coercion.
- M-169: notification unread counters now use strict integer parsing before badge/header display and local read-cache decrements.
- M-170: admin list pagination and queue badges now parse runtime totals/counters strictly before display and page math.
- M-171: account-transfer code length and TTL UI policy now rejects malformed/zero runtime values before regex, input limits, and labels.
- M-172: public stats badge now parses runtime counters/volume strictly before count-up animation and compact formatting.
- M-173: admin displayed totals and broadcast recipient counters now reject malformed runtime counts before subtitles, headers, toasts, and empty-page rewinds.
- M-174: admin dashboard KPI tiles now reject malformed runtime counters before display and accent-ring decisions.
- M-175: frontend positive money gates now reject malformed runtime amounts before wallet available-balance hints and deal commission rows.
- M-176: deal topup invoice amount rows now validate runtime money values before rendering create/detail invoice totals.
- M-177: admin audit/user identity labels now reject malformed runtime ids and counts before rendering operational identifiers.
- M-178: deal topup payment actions now require a strict positive invoice total before opening the provider link.
- M-179: deal and wallet payment modals now require strict positive invoice amounts before auto-opening or clicking provider payment links.
- M-180: public money summaries now render malformed/negative runtime amounts as neutral values instead of `$0`.
- M-181: deal list/detail amount displays now reject malformed/negative runtime totals instead of showing zero.
- M-182: wallet balance displays now reject malformed/negative runtime balance strings instead of showing zero.
- M-183: wallet locked hints and admin balance visibility now use strict positive-balance parsing instead of zero-coercing totals.
- M-184: create-deal balance defaults, hints, and Max previews now use canonical wallet amount strings instead of malformed runtime balance values.
- M-185: wallet deposit payment entry and history rows now require strict positive runtime amounts instead of opening pay links after zero-coercion.
- M-186: admin deposit/withdrawal money actions now require strict positive runtime amounts instead of acting on rows displayed as neutral.
- M-187: admin deal force-release/refund/split actions now require a strict positive runtime deal amount before opening money-moving sheets.
- M-188: admin deal pending approval rows now use strict runtime money formatting and block approval of malformed money requests.
- M-189: paid PIN-reset paywall now validates runtime price/balance/charged amounts before display or balance-payment entry.
- M-190: admin wallet adjustments and USD-rate upserts now send validated decimal strings instead of rounded JavaScript numbers.
- M-191: remaining admin Decimal submit paths now preserve validated decimal strings across settings, currency limits, user stats/trust deposits, per-user balance adjustments, and service edits.
- M-192: user service creation now preserves validated Decimal price strings instead of rounded JavaScript numbers.
- M-193: admin deal amount filters now preserve Decimal query strings instead of rounded JavaScript numbers.
- M-194: admin deal split ledger rows now preserve the exact Decimal percent string instead of normalizing it through float.
- M-195: admin service edit/delete audit payloads now preserve Decimal money fields as strings and keep delete-time deposit context.
- M-196: admin settings audit payloads now preserve Decimal settings as strings instead of JSON numbers.
- M-197: admin currency audit payloads now preserve Decimal limits as strings and keep full delete-time currency context.
- M-198: PIN unlock/reset attempts counters now reject malformed runtime values instead of rendering `NaN`/invalid counts.
- M-199: admin user wallet/content rows now format malformed runtime balances, counters, and ratings as neutral values instead of raw DTO strings.
- M-200: admin taxonomy currency-limit rows and system alert counters now render malformed runtime numbers as neutral values.
- M-201: create-deal insufficient-funds errors now validate runtime money fields and currency codes before showing balance hints.
- M-202: deal and payment invoice money surfaces now normalize runtime currency codes before rendering labels.
- M-203: paid PIN-reset paywall now normalizes runtime currency codes before rendering price/balance and paid toasts.
- M-204: admin deposit and withdrawal queues now normalize runtime currency labels before rendering money rows.
- M-205: remaining admin deal, wallet, and per-user balance money rows now normalize runtime currency labels before display.
- M-206: admin wallet adjustment forms now choose mutation currencies from normalized/catalog-backed codes instead of raw balance DTO labels.
- M-207: admin wallet currency selectors now normalize catalog row codes before adjustment and USD-rate mutations.
- M-208: create-deal fiat currency rows and funded-balance defaults now normalize runtime codes before display and submit.
- M-209: wallet currency detail pages now use route-normalized codes for balance display, history rows, and deposit submit.
- M-210: wallet deposit success toasts now normalize response currency labels before showing payment instructions.
- M-211: wallet history and deal surfaces now hide unknown runtime statuses behind neutral labels.

Пункт по card/TRUST/manual fallback flows снят из отчета: это ожидаемое поведение продукта, не defect.

## Findings, закрытые в текущем дереве

### H-01. Возможный deadlock в admin force-release/split

Ссылки: `backend/app/routers/admin/deals.py:809-856`, `backend/app/routers/admin/deals.py:893-943`, `backend/app/services_deals.py:253-286`.

В админских helper-функциях `_release_locked_to_seller` и `_split_locked` кошельки блокируются в порядке buyer, затем seller. Основной сервис сделок уже использует сортированный порядок lock-ов и прямо документирует deadlock-геометрию для двух встречных сделок между теми же пользователями. Админские force-сценарии эту защиту не повторяют.

Риск: при одновременном force-release или split по двум встречным сделкам транзакции могут зависнуть на взаимных row locks и упасть по deadlock/timeout. Это затрагивает ручное разрешение споров и операции с балансами.

Исправление: вынести общий helper блокировки wallet-строк с детерминированным порядком и использовать его в admin deal flows и основном сервисе.

### H-02. `delete_deal` удаляет файлы до commit БД

Ссылки: `backend/app/routers/admin/deals.py:1407-1483`.

В admin delete deal физические файлы удаляются через `asyncio.to_thread(delete_files)` до финального `session.commit()`. После удаления файлов код еще пишет audit, notifications и только затем коммитит транзакцию.

Риск: если audit/notification/commit упадет, строки сделки и attachments останутся в БД, но файлы уже будут удалены с диска. Получается несогласованность: UI и API видят attachment, а media storage его потерял.

Исправление: переносить физическое удаление после успешного commit, либо использовать outbox/job cleanup с повторяемой и идемпотентной задачей.

### H-03. Payment webhooks читают неограниченное тело до проверки подписи

Ссылки: `backend/app/routers/payments.py:80`, `backend/app/routers/payments.py:227`, контрпример `backend/app/routers/csp_report.py:149-159`.

CryptoBot и Crystalpay webhook handlers вызывают `await request.body()` до signature validation и без локального лимита на `Content-Length`/размер body. CSP/client-error endpoints уже имеют явный `_MAX_BODY=16KB`, но платежные webhooks такого ограничения не используют.

Риск: анонимный внешний endpoint можно нагружать большими payload-ами, заставляя приложение читать тело в память до дешевого отказа по подписи. Это DoS-поверхность на платежном контуре.

Исправление: добавить строгий лимит `Content-Length`, streaming read с cap и rate limit до полного чтения body. После cap возвращать 413 до signature parsing.

### H-04. TOTP replay обходит React Query и mutation callbacks

Ссылки: `frontend/src/components/TotpGate.tsx:37-64`, `frontend/src/components/TotpGate.tsx:122-124`, `frontend/src/api/client.ts:219-240`.

При ответе backend с `X-TOTP-Required` клиент открывает TOTP gate. После ввода кода компонент самостоятельно повторяет исходный запрос через raw `fetch`, а не через исходную mutation/query функцию. Ответ replay-запроса почти не обрабатывается.

Риск: админское действие может реально выполниться на backend, но исходная mutation уже завершилась ошибкой. UI не получит success/error callbacks, invalidation, toast, optimistic rollback и typed error handling. Пользователь видит устаревший экран или повторяет уже выполненную операцию.

Исправление: не делать автоматический raw replay. Лучше вернуть TOTP-код в исходный API layer и повторять ту же mutation, либо сделать централизованный interceptor, который сохраняет callbacks, ошибки и query invalidation.

### H-05. Broadcast отправляет уведомления до создания `Broadcast`/audit записи

Ссылки: `backend/app/routers/admin/broadcasts.py:185-238`, `backend/app/routers/admin/broadcasts.py:299-352`.

Admin broadcast сначала собирает адресатов, chunk-ами коммитит отправку, пушит WS/DM, а history/audit row создает только после рассылки.

Риск: если процесс упадет или финальный commit не пройдет после отправки части сообщений, пользователи уже получат уведомления, но в админской истории и audit trail не будет надежной записи о рассылке.

Исправление: сначала создавать `Broadcast(status=sending)` и audit intent в БД, затем отправлять chunk-и с обновлением counters/status. Финал переводить в `sent` или `failed`.

### H-06. Frontend WebSocket reconnect игнорирует terminal close codes

Ссылки: `frontend/src/lib/ws.ts:123-149`, `backend/app/routers/ws.py:274-295`, `backend/app/ws.py:57-71`.

Backend использует специальные close codes, включая lockout `4003`, а также auth-related коды `4001`/`4002`. Frontend reconnect loop планирует переподключение на любой close.

Риск: для banned/frozen/revoked/expired auth состояний клиент уходит в бесконечные переподключения. Это шумит в логах, ухудшает UX и может нагружать backend при массовых блокировках или истекших сессиях.

Исправление: считать backend close codes terminal для текущей auth-сессии. Для них закрывать socket manager, сбрасывать live state и давать UI перейти в auth/banned/frozen gate.

### M-01. Потеря decimal-точности в invoice/deposit/deal путях

Ссылки: `backend/app/routers/wallet.py:177-183`, `backend/app/services_wallet.py:311-321`, `backend/app/services_wallet.py:456-459`, `backend/app/services_wallet.py:554-558`, `backend/app/services_deals.py:621-626`, `backend/app/services_deals.py:676-680`, `frontend/src/pages/wallet/WalletDepositPage.tsx:112-124`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx:164-173`, `frontend/src/pages/wallet/WalletTrustDepositPage.tsx:68-80`, `frontend/src/pages/CreateDealPage.tsx:153-180`.

Frontend переводит суммы через `parseFloat`/`number`, backend местами делает `float(body.amount)` и передает float в invoice helpers, после чего значения попадают в `Numeric(28,8)`. Для денег это лишний риск округления и расхождения между invoice amount, балансом и audit.

Риск: редкие, но неприятные расхождения на граничных decimal-значениях, особенно при комиссиях, округлениях и последующих сверках.

Исправление: держать суммы строкой или `Decimal` от формы до gateway adapter. Нормализовать scale на backend и использовать typed decimal в generated frontend types. Withdrawal flow уже ближе к правильному варианту, так как отправляет amount строкой.

### M-02. Drift комментария/spec вокруг `commission_paid`

Ссылки: `backend/app/services_deals.py:872-889`.

Runtime выставляет `commission_paid=True`, когда `paid >= commission_due`. Ниже комментарий для underpayment говорит, что флаг остается false. Тесты и текущее поведение выглядят согласованными, но комментарий описывает другую модель.

Риск: следующий разработчик может исправить код под устаревший комментарий и сломать accounting-инвариант.

Исправление: обновить комментарий и, если нужно, явно описать invariant в тесте: full commission paid означает `commission_paid=True`, даже если seller amount частично уменьшен из-за underpayment.

### M-03. Withdrawal может заблокировать средства без доступного ручного обработчика

Ссылки: `backend/app/services_wallet.py:1086-1109`, `backend/app/services_wallet.py:1341-1393`, `backend/app/services_wallet.py:1404+`.

Если CryptoBot token настроен, но auto-withdraw выключен или transfer падает, а активных админов нет, Phase 1 уже блокирует средства и создает pending withdrawal. После этого код только логирует ситуацию. Sweep позже может вернуть средства, но пользователь получает зависшую операцию без очевидного обработчика.

Риск: деньги уходят из available balance в locked/pending, а операционная команда может не увидеть задачу вовремя.

Исправление: до блокировки средств проверять наличие хотя бы одного delivery path: auto-withdraw enabled либо доступные admin recipients. Если delivery path отсутствует, возвращать явную ошибку без lock-а.

### M-04. Account-transfer length/TTL настраиваются в service, но hardcoded в HTTP/UI

Ссылки: `backend/app/config.py:187-197`, `backend/app/routers/account.py:39-40`, `backend/app/routers/account.py:76-81`, `backend/app/services_account.py:396-402`, `frontend/src/pages/profile/AccountTransferPage.tsx:57`, `frontend/src/pages/profile/AccountTransferPage.tsx:141`, `frontend/src/pages/profile/AccountTransferPage.tsx:186`.

Config содержит настраиваемые length/TTL для transfer code, сервис валидирует динамическую длину. Но HTTP schema принимает только 6 символов, backend text говорит про 15 минут, а frontend тоже hardcode-ит 15 минут и пример `123456`.

Риск: изменение config silently ломает API/UI. Сервис готов к новой длине, но router и frontend отклонят валидный код или покажут неверный срок.

Исправление: отдавать policy endpoint или включать length/TTL в existing profile/config response. Router schema должна использовать config-aware validation вместо фиксированных `min_length=6,max_length=6`.

### M-05. Race при генерации account-transfer code

Ссылки: `backend/app/services_account.py:104-131`, `backend/app/models.py:1154-1159`, `alembic/versions/9d0e4d959e65_initial_schema.py:109-117`.

`_generate_unique_code` проверяет уникальность на уровне приложения, но в модели и миграции есть только обычный index, не unique constraint. Две параллельные операции могут сгенерировать одинаковый `code_hash`, обе пройти app-check и вставиться.

Риск: collision маловероятен, но при коротком numeric code и нагрузке это security/account takeover class defect. Один код может стать неоднозначным.

Исправление: добавить DB unique constraint на active code hash, либо advisory lock + retry на insert. App-level check оставить только как оптимизацию.

### M-06. Punctuation-only search возвращает весь catalog для services

Ссылки: `backend/app/routers/users.py:95-106`, `backend/app/routers/services.py:183-191`, `backend/app/routers/services.py:599-612`, `backend/app/search.py:47-70`.

Для users router корректно возвращает `[]`, если `build_prefix_tsquery(q)` не смог построить запрос. Для services и admin services такой же `q=!!!` превращается в отсутствие search-фильтра и возвращает полный список.

Риск: неожиданный UX, лишняя нагрузка и обход ожидаемой семантики поиска.

Исправление: унифицировать поведение search helpers: если пользователь явно передал непустой `q`, но query parser вернул `None`, возвращать пустой result set.

### M-07. `bot.notify.get_bot()` принимает placeholder token

Ссылки: `backend/app/bot/notify.py:25-56`, `backend/app/bot/runner.py:57-72`, `docker-compose.yml:136-142`.

Bot runner правильно отвергает placeholder token, начинающийся с `0000`, но notification helper проверяет только пустую строку. В docker-compose по умолчанию задан `BOT_TOKEN=0000000000:FAKE`.

Риск: прямые DM paths могут создать Bot с fake token и пытаться ходить в сеть, вместо того чтобы сразу отключиться. Это дает лишние ошибки, задержки и шум.

Исправление: вынести общий валидатор bot token и использовать его в runner и notify helper.

### M-08. Nullable withdrawal address не отражен во frontend types/admin UI

Ссылки: `backend/app/schemas.py:1054-1061`, `backend/app/schemas.py:1885-1896`, `frontend/src/api/types.ts:312-320`, `frontend/src/api/types.ts:721-732`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx:95-104`.

Backend schemas допускают `address: str | None`, что соответствует auto CryptoBot flow. Frontend types по-прежнему считают `address: string`, а admin withdrawals page рендерит и копирует `w.address` как обязательное значение.

Риск: null-address withdrawals отображаются некорректно, copy action может копировать пустоту/`null`, админский workflow становится хрупким.

Исправление: перегенерировать/исправить frontend types и явно отрисовывать разные withdrawal modes: address-based manual и provider/account-based auto.

### M-09. Комментарии и startup guard для `TRUSTED_PROXIES` устарели

Ссылки: `backend/app/config.py:241-244`, `backend/app/deps.py:77-112`, `backend/app/main.py:287-304`.

Комментарий в config говорит, что empty `TRUSTED_PROXIES` означает trust all. Реальный код в `deps.py` делает обратное: empty не доверяет X-Forwarded-For. Startup guard при этом повторяет старую модель угроз и может блокировать production/staging direct deploy с неверной диагностикой.

Риск: операторы получают неправильные инструкции по deploy, а startup failure может быть вызван неактуальной проверкой.

Исправление: синхронизировать комментарии, docs и startup guard с фактической семантикой. Если direct deploy без proxy разрешен, guard должен проверять это явно.

### M-10. Per-currency wallet page использует старый withdrawal contract

Ссылки: `frontend/src/pages/wallet/WalletPage.tsx:144-146`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx:213-260`, `frontend/src/pages/wallet/WalletWithdrawPage.tsx:127-172`.

`WalletPage` ведет на `/wallet/:code`, где withdraw tab все еще требует address и не использует свежий PIN prompt. Каноническая страница `/wallet/withdraw` уже отправляет decimal string, не требует address и открывает `PinPromptModal`.

Риск: у пользователя есть два разных withdrawal UX с разными security/contract ожиданиями. Старый tab может ломаться на новом backend contract или обходить нужный PIN flow.

Исправление: удалить withdraw tab из per-currency page или переиспользовать канонический `WalletWithdrawPage`/hook.

### M-11. Media upload оставлял orphan-файл при падении commit БД

Ссылки: `backend/app/routers/media.py:347-375`, regression `tests/unit/test_media_upload_cleanup.py`.

После re-encode upload handler записывал файл на диск, создавал `Media` ORM-row и делал `session.commit()`. Если commit падал из-за БД/constraint/connection failure, HTTP-запрос завершался ошибкой, строки `media` не появлялось, но файл уже оставался в `MEDIA_ROOT` без владельца и без DB-ссылки.

Риск: накопление orphan-файлов после transient DB failures, расход диска и рассинхрон между storage и базой. Для приватных deal attachments это также усложняет последующую чистку, потому что файл не достижим из `Media`/deal graph.

Исправление: commit обернут в `try/except`; при ошибке handler best-effort удаляет только что записанный файл через `Path.unlink(missing_ok=True)`, логирует вторичную ошибку cleanup и пробрасывает исходную ошибку. Добавлен unit-regression на прямой вызов upload path с искусственным падением commit.

### M-12. CI использовал actions на deprecated Node.js 20 runtime

Ссылки: `.github/workflows/ci.yml`, `.github/workflows/security.yml`, GitHub Actions annotation в свежем run PR #253.

Свежие CI/Security runs после PR-fix проходили, но GitHub выдавал annotation: `actions/setup-python@v5` и `astral-sh/setup-uv@v3` работают на Node.js 20, который GitHub Actions начнет принудительно заменять на Node.js 24 с 2026-06-16 и удалит 2026-09-16. Это не красный тест сегодня, но это будущий CI breakage surface с конкретной датой.

Риск: после смены runner runtime старые actions могут начать падать или работать не так, а security/backend jobs завязаны на них в каждом PR.

Исправление: `actions/setup-python` обновлен до `v6`, `astral-sh/setup-uv` до `v8.1.0` (у action нет major-тега `v8`, поэтому закреплен существующий semver tag); остальные actions в workflow уже на актуальных major-версиях без этой annotation.

### M-13. Admin deposit actions оставляли stale wallet/user/audit/dashboard кэши

Ссылки: `backend/app/routers/admin/deposits.py:46-158`, `frontend/src/api/admin/hooks.ts:540-577`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend `mark_paid` и `refund_deposit` меняют не только строку депозита: они блокируют баланс пользователя, изменяют `UserBalance.amount`, пишут notification и audit log, а также влияют на dashboard/system состояние. Frontend hooks после success инвалидировали только `qk.admin.deposits.all()`.

Риск: админ мог видеть обновленный статус депозита рядом со старым admin wallet/user detail/audit/dashboard/system status. Текущий пользовательский wallet/me кэш тоже мог оставаться старым до ручного refresh или фонового refetch, что особенно плохо после ручной сверки платежа или refund.

Исправление: `useAdminDepositMarkPaid` и `useAdminDepositRefund` теперь инвалидируют deposit list, admin wallets, конкретный admin user wallet/detail, dashboard, system status, audit, общий wallet и `me`. Добавлен hook regression test на полный набор query keys для обеих mutations.

### M-14. Admin deposit/withdrawal decisions оставляли stale analytics и wallet кэши

Ссылки: `backend/app/routers/admin/analytics.py:101-273`, `backend/app/routers/admin/withdrawals.py:149-581`, `frontend/src/api/admin/hooks.ts:540-614`, regression `frontend/src/api/admin/hooks.test.tsx`.

Admin analytics читает `WalletDeposit.status/paid_at` для `deposits_30d`, `WalletWithdrawal.status/processed_at` для `withdrawals_30d` и `WalletWithdrawal.status == pending` для KPI `pending_withdrawals`. Но admin deposit mark-paid/refund не сбрасывали analytics series, а withdrawal approve/reject/mark_sent не сбрасывали analytics KPI/series и user-facing wallet caches. Отдельно опасен approve с CryptoBot: backend сначала commit-ит `approved`, а при ошибке transfer пишет audit/admin_note и возвращает 502, поэтому success-only invalidation вообще не срабатывала после уже измененной БД.

Риск: после ручной сверки депозита или решения по выводу `/admin/analytics` мог показывать старые финансовые графики/счетчики, а текущий пользовательский wallet cache мог оставаться старым до фонового refetch. Для `mark_sent` это особенно заметно: статус вывода уже `sent`, но график `withdrawals_30d` и wallet history могли не обновиться.

Исправление: deposit mutations теперь инвалидируют `qk.admin.analytics.series()`. Withdrawal decision mutation перешла на `onSettled`: при success использует `user_id` из ответа и инвалидирует конкретный admin user wallet/detail, а при error падает обратно на broad admin user/user-wallet prefixes. В обоих случаях сбрасываются withdrawal list, admin wallets, analytics KPI/series, system status, audit и user-facing wallet prefix. Добавлены regression tests на success и error-after-partial-commit paths.

### M-15. Admin review mutations оставляли stale rating/review/public-user кэши

Ссылки: `backend/app/routers/admin/content.py:391-609`, `frontend/src/api/admin/hooks.ts:388-445`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend admin review create/edit/delete не просто меняет строку `Review`: для create и rating edit он вызывает `lock_user_for_rating()` + `recompute_user_rating()`, а delete после `flush()` пересчитывает `target.good`/`target.bad`. Эти поля питают `AdminUserDetailOut.rating_*`, public `UserCardDto.rating/reviews_count`, `/api/reviews?user=...` и user search/list projections. Frontend hooks инвалидировали только текущий `qk.admin.userReviews.forUser(userId)`.

Риск: после ручной правки отзыва админ видел новый текст/оценку в секции отзывов, но карточка пользователя, список пользователей, публичный профиль и публичные reviews/search могли оставаться со старым рейтингом и счетчиком отзывов. При delete это особенно легко пропустить, потому что ответ `{deleted: true}` не несет `target_id`, а открытая вкладка может быть `written`, где текущий `userId` является автором, не получателем рейтинга.

Исправление: admin review mutations теперь сбрасывают admin review prefix, admin users/list/detail, audit, public reviews, public users list и public user detail. Create/update используют `author_id`/`target_id` из ответа для точечных admin user detail invalidations; delete падает обратно на broad `qk.admin.user.all()` из-за отсутствия `target_id` в response. Добавлены regression tests на create/update/delete invalidation наборы.

### M-16. Admin service/comment mutations оставляли stale public catalog/detail/comment кэши

Ссылки: `backend/app/routers/admin/content.py:190-359`, `backend/app/routers/admin/content.py:671-764`, `backend/app/routers/categories.py:27-49`, `frontend/src/api/admin/hooks.ts:336-503`, regression `frontend/src/api/admin/hooks.test.tsx`, `tests/integration/test_admin_content.py`.

Backend admin service edit/delete меняет те же строки `Service`, которые читают публичные `/api/services`, `/api/services/{id}` и category counters. При delete также удаляются `ServiceComment` строки. Admin comment edit/delete меняет `ServiceComment`, а публичный `ServiceDetailOut` пересчитывает comment rating average/count, плюс `/api/services/{id}/comments` показывает сам текст/рейтинг. Frontend hooks сбрасывали только admin user-scoped content lists, поэтому публичные catalog/detail/comments/categories и admin audit могли оставаться старыми до фонового refetch.

Риск: после модераторской правки услуги или комментария админ видел изменение в admin tab, но пользовательские страницы поиска, карточка услуги, счетчики категорий и комментарии к услуге могли показывать старые данные. При удалении комментария response не нес `service_id`, поэтому frontend не мог точечно сбросить `qk.service.comments(serviceId)` и `qk.service.detail(serviceId)`.

Исправление: service mutations теперь инвалидируют admin user services/detail, admin audit, public services, public service detail/comments и public categories. Comment mutations инвалидируют admin user comments, admin audit, public service comments и service detail; backend delete-comment response дополнен `service_id` и `author_id`, чтобы delete path тоже делал точечную invalidation. Добавлены hook regression tests и backend integration assertion на новый response contract.

### M-17. Admin taxonomy/currency mutations оставляли stale public/wallet/admin projection кэши

Ссылки: `backend/app/routers/admin/taxonomy.py:58-132`, `backend/app/routers/admin/taxonomy.py:177-340`, `backend/app/routers/categories.py:14-50`, `backend/app/routers/wallet.py:41-104`, `frontend/src/api/admin/hooks.ts:712-777`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend category upsert/delete меняет данные, которые читают public `/api/categories`, service list/detail category projection и admin audit. Backend currency upsert/delete меняет `CurrencyOut`, вложенный в wallet balances/deposits/withdrawals, admin wallet projections, admin deal/deposit/withdrawal amount formatting, analytics/system status и audit. Frontend hooks сбрасывали только `qk.admin.categories()` или `qk.admin.currencies()`, поэтому длинный `staleTime` у wallet currencies мог держать старые лимиты, active/kind и decimals до часа.

Риск: после изменения категории пользователи могли видеть старое имя/icon в каталоге и карточках услуг; после изменения валюты wallet/deposit/withdraw UI и admin finance pages могли показывать старые лимиты, активность, kind или precision. Для финансовых экранов это особенно рискованно из-за `decimals`, который влияет на форматирование сумм.

Исправление: category mutations теперь сбрасывают admin categories, admin audit, public categories, public services и service detail prefix. Currency mutations сбрасывают admin currencies, wallets/user-wallets, deals/deposits/withdrawals, analytics, system status, audit и весь user-facing wallet prefix. Добавлены hook regression tests на upsert/delete для обеих taxonomy веток.

### M-18. Currency delete route был backend-only и не был доступен в admin UI

Ссылки: `backend/app/routers/admin/taxonomy.py:282-340`, `frontend/src/pages/admin/AdminTaxonomyPage.tsx:209-370`, regression `frontend/src/pages/admin/AdminTaxonomyPage.test.tsx`.

Backend уже имел полноценный `DELETE /api/admin/currencies/{currency_id}` с FK-blocker checks и audit log, но admin taxonomy UI показывал для валют только edit. В результате unreferenced test/import currencies можно было удалить через API, но не через админскую панель, хотя страница позиционируется как редактор taxonomy CRUD.

Риск: операционная функция была фактически скрыта от админов; мусорные/тестовые валюты оставались в списке до ручного API вызова, а UI не соответствовал backend capability.

Исправление: добавлен `useAdminDeleteCurrency()` с тем же side-effect invalidation набором, что и currency upsert, и кнопка delete в currencies pane с confirm/toast flow. Добавлен UI regression test, который проверяет вызов delete mutation из `/admin/taxonomy?tab=currencies`.

### M-19. Broadcast delete оставлял stale admin audit cache

Ссылки: `backend/app/routers/admin/broadcasts.py:424-443`, `frontend/src/api/admin/hooks.ts:798-816`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend `DELETE /api/admin/broadcasts/{broadcast_id}` делает soft-delete `Broadcast`, затем пишет `broadcast.delete` в `admin_audit_log`. Frontend `useAdminDeleteBroadcast` после успешного DELETE инвалидировал только `qk.admin.broadcasts()`, хотя соседний `useAdminCreateBroadcast` уже сбрасывал и broadcasts, и audit. Поэтому админ мог удалить рассылку, увидеть обновленную history-таблицу, но открытый audit log оставался без строки `broadcast.delete` до фонового refetch/ручной навигации.

Риск: audit UI показывал неполную картину сразу после state-changing admin action; оператор мог решить, что удаление не было зафиксировано в audit trail, или пропустить важный след при проверке действий другого администратора.

Исправление: `useAdminDeleteBroadcast` теперь инвалидирует `qk.admin.audit.all()` вместе с `qk.admin.broadcasts()`. Добавлены hook regression tests, которые закрепляют audit invalidation для broadcast create и delete.

### M-20. Admin settings/system mutations оставляли stale maintenance/system/audit кэши

Ссылки: `backend/app/routers/admin/settings.py:123-210`, `backend/app/routers/admin/system.py:57-137`, `backend/app/routers/admin/system.py:310-350`, `frontend/src/components/MaintenanceBanner.tsx:8-16`, `frontend/src/api/admin/hooks.ts:698-861`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend `PATCH /api/admin/settings` меняет `AppSettings`, пишет `settings.update` в audit log, сбрасывает backend maintenance cache при изменении maintenance полей и влияет на `admin/system/status`: `_operational_alerts()` читает `pending_topup_expiry_hours` из той же singleton settings row. Frontend после settings update сбрасывал только admin settings, public settings и public stats. Отдельный `MaintenanceBanner` кэш `qk.maintenance()`, admin system status и audit log оставались старыми. `POST /api/admin/system/redis/flush` также пишет `system.redis_flush` в audit log, но frontend mutation вообще не инвалидировала кэши после успешного flush.

Риск: после включения/выключения maintenance админская сессия могла не увидеть публичный maintenance banner до следующего 30-секундного poll; system page мог показывать старый stale-topup alert threshold после изменения `pending_topup_expiry_hours`; audit UI не показывал `settings.update` или `system.redis_flush` сразу после действия.

Исправление: `useAdminUpdateSettings` теперь инвалидирует `qk.maintenance()`, `qk.admin.systemStatus()` и `qk.admin.audit.all()` дополнительно к прежним settings/public кэшам. `useAdminFlushRedis` инвалидирует system status и audit log. Добавлены hook regression tests для settings update и redis flush.

### M-21. Admin wallet adjust/rate mutations оставляли stale wallet/system projections

Ссылки: `backend/app/routers/admin/wallets.py:105-188`, `backend/app/routers/admin/wallets.py:206-248`, `backend/app/routers/admin/wallets.py:278-410`, `backend/app/routers/admin/system.py:118-170`, `frontend/src/api/admin/hooks.ts:551-585`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend `POST /api/admin/wallets/{user_id}/adjust` меняет `UserBalance.amount`, пишет ledger/audit row и может изменить `admin/system/status` alert `usd_rates_missing`, потому что status считает валюты с ненулевыми балансами без USD rate. Если админ корректирует собственный кошелек, тот же side effect виден и в user-facing `/api/wallet/balances`. Frontend сбрасывал только admin wallet list, конкретный admin user-wallet, admin user detail и audit. Backend `POST /api/admin/wallets/rates` меняет `CurrencyUsdRate`, который используется не только wallet list/rates endpoint, но и `GET /api/admin/wallets/{user_id}` для `usd_rate`/`usd_estimate`; frontend не сбрасывал `qk.admin.userWallet.all()`.

Риск: после ручной корректировки баланса system page мог продолжать скрывать или показывать устаревший missing-rate alert, а wallet page администратора мог держать старые balances. После изменения USD rate карточка конкретного admin user wallet могла показывать старый `usd_estimate`, хотя общий wallet list уже пересчитался.

Исправление: `useAdminAdjustBalance` теперь дополнительно инвалидирует admin system status и user-facing wallet prefix. `useAdminUpsertCurrencyRate` инвалидирует broad admin user-wallet prefix вместе с wallet/rates, system status и audit. Добавлены hook regression tests для balance adjust и rate upsert.

### M-22. Admin user actions оставляли stale public user/profile/me кэши

Ссылки: `backend/app/routers/admin/users.py:611-840`, `backend/app/serializers.py:17-164`, `backend/app/routers/users.py:58-194`, `frontend/src/api/admin/hooks.ts:111-132`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend admin user actions `role`, `rating`, `stats` и `trust-deposit` меняют поля `User`, которые напрямую читаются публичными `/api/users` и `/api/users/{username}` через общий serializer: `prefix`, role-флаги, `rating_manual`, `good`/`bad`, deal counters, `deals_sum_override` и `trust_deposit_balance` как public `deposit`. Те же поля попадают в `/api/me`, если админ редактирует собственную карточку через разрешенные action-пути. Frontend generic `useAdminUserAction` после success сбрасывал только admin users/detail/dashboard/related admin tabs/audit, поэтому публичный search/list/profile и current-user cache могли остаться со старой карточкой.

Риск: после ручного изменения рейтинга, статистики, роли или trust-deposit админ видел обновление в admin detail, но пользовательский каталог и публичный профиль могли показывать старый рейтинг, badge, сумму сделок или deposit до фонового refetch. При self-edit `/api/me` мог сохранять старую проекцию текущего пользователя.

Исправление: `useAdminUserAction` теперь дополнительно инвалидирует public users list, public user detail по username из ответа (или broad `qk.user.all()` без username) и `qk.me()`. Добавлены hook regression tests для username-specific и fallback invalidation paths.

### M-23. Admin in-app broadcast send оставлял stale notifications/counters cache

Ссылки: `backend/app/routers/admin/broadcasts.py:181-385`, `backend/app/routers/notifications.py:24-139`, `frontend/src/lib/useLiveNotifications.ts:73-113`, `frontend/src/api/admin/hooks.ts:809-819`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend `POST /api/admin/broadcasts` при `dispatch_inapp=true` не только создает строку `Broadcast` и audit entries, но и вставляет `Notification(type=system)` для каждого получателя, после commit публикуя WS event. Frontend admin mutation после success сбрасывала broadcast history и audit, но не `qk.notifications.all()`. Если текущий админ входил в аудиторию рассылки, а WS соединение было закрыто/пропустило frame, notification list и bell counters могли оставаться старыми до 30-секундного poll.

Риск: админ мог отправить in-app рассылку и сразу увидеть обновленную history/audit, но собственный notification center и счетчик непрочитанных не отражали новую system notification без ожидания polling или ручного refresh.

Исправление: `useAdminCreateBroadcast` теперь дополнительно инвалидирует `qk.notifications.all()`, что покрывает notification list и counters prefix. Broadcast create regression test закрепляет новый side-effect key.

### M-24. User review create оставлял stale public users list cache

Ссылки: `backend/app/routers/reviews.py:75-111`, `backend/app/services.py:47-109`, `backend/app/serializers.py:17-164`, `frontend/src/api/hooks.ts:507-516`, regression `frontend/src/api/hooks.test.tsx`.

Backend `POST /api/reviews` через `post_review()` блокирует target user и пересчитывает `good`/`bad` rating counters. Эти поля читаются не только `/api/reviews?user=...` и `/api/users/{username}`, но и public `/api/users`: карточка и сортировка/фильтры по рейтингу используют те же counters. Frontend `useCreateReview` после success сбрасывал review list и target profile, но не public users list.

Риск: после оставленного пользователем отзыва профиль target мог обновиться, а общий каталог/search продолжал показывать старый рейтинг или старую позицию в выдаче до следующего refetch.

Исправление: `useCreateReview` теперь дополнительно инвалидирует `qk.users.all()`. Добавлен hook regression test на review/profile/users invalidation set.

### M-25. Deal state transitions оставляли stale wallet/public-user/me кэши у участников

Ссылки: `backend/app/services_deals.py:1093-1484`, `backend/app/serializers.py:17-164`, `frontend/src/api/hooks.ts:432-448`, `frontend/src/lib/useLiveNotifications.ts:35-113`, regressions `frontend/src/api/hooks.test.tsx`, `frontend/src/lib/useLiveNotifications.test.tsx`.

Backend deal actions меняют не только строки `Deal`: `accept_deal` увеличивает `deals_total` у buyer/seller, `finish_deal` двигает locked/available balances и увеличивает `deals_success`, `start_arbitration` увеличивает `deals_arbitrage`, `resolve_arbitration` двигает баланс и увеличивает `deals_success`/`deals_failed`, а cancel/refund paths меняют wallet balances. Эти поля читаются public user list/detail, `/api/me` и wallet endpoints. Frontend `useDealAction` сбрасывал deals/deal/wallet только у инициатора, а `deal.updated`/deal notification WS handlers у второй стороны сбрасывали только deals/deal.

Риск: после принятия, завершения, отмены или арбитража сделки одна сторона могла видеть свежий статус сделки рядом со старым wallet balance, старым `deals_total`/`deals_success` в профиле и старым `/api/me` до ручного refresh или фонового refetch. Особенно заметно для seller после `finish`: деньги уже зачислены backend-ом, но wallet cache второй стороны не сбрасывался WS-событием.

Исправление: добавлен общий frontend helper `invalidateDealParticipantSideEffects()`, который сбрасывает wallet, public users list, public user-detail prefix и `me`. `useDealAction` вызывает его после state-changing HTTP actions, а `useLiveNotifications` вызывает его на `deal.updated` и deal-typed notification events. Добавлены regression tests для HTTP mutation и WS paths.

### M-26. User service update/delete оставляли stale category/detail/comment кэши

Ссылки: `backend/app/routers/services.py:242-545`, `backend/app/routers/categories.py:14-49`, `frontend/src/api/hooks.ts:169-221`, regression `frontend/src/api/hooks.test.tsx`.

Backend owner-side service update меняет `Service.title`, `description`, `price`, `status` и gallery, которые читаются public catalog и `GET /api/services/{id}`. При `status` active/paused дополнительно меняется `services_count` в `GET /api/categories`, потому что counter считает только active services. Owner-side delete удаляет саму service row и все `ServiceComment` rows, значит stale detail/comments/category caches тоже становятся неверными. Frontend `useUpdateService` сбрасывал только `qk.services.all()`, а `useDeleteService` тоже сбрасывал только catalog list.

Риск: после паузы/возврата услуги пользователь мог видеть старое число услуг в категориях и старую карточку detail; после удаления прямой detail/comments cache мог оставаться доступным в текущей сессии до фонового refetch, хотя backend уже вернул бы 404.

Исправление: `useUpdateService` теперь инвалидирует catalog, categories и точечный service detail. `useDeleteService` дополнительно инвалидирует categories, service detail и service comments. Добавлены hook regression tests для update/delete invalidation sets.

### M-27. Profile hide/update оставлял stale service/category/review projections

Ссылки: `backend/app/routers/me.py:14-132`, `backend/app/routers/categories.py:14-53`, `backend/app/routers/services.py:176-218`, `backend/app/routers/reviews.py:24-73`, `frontend/src/api/hooks.ts:65-116`, regressions `tests/integration/test_services_pagination_and_hidden.py`, `frontend/src/api/hooks.test.tsx`.

Backend `PATCH /api/me` меняет `is_hidden_profile` и публичные поля профиля. `GET /api/services`, service detail/comments и `GET /api/reviews?user=...` уже используют `is_hidden_profile` как public visibility gate, но `/api/categories` считал active services без join к owner и без `User.is_hidden_profile=false`. Поэтому category badge мог показывать hidden-owner active services, хотя сам каталог их не отдавал. Frontend `useUpdateMe` сбрасывал только `/api/me`, public user detail и users list, но не service catalog/detail/comment, categories и reviews cache.

Риск: пользователь включал скрытый профиль, backend переставал отдавать его услуги и reviews внешним пользователям, но category counters могли продолжать раскрывать наличие active services. В текущей frontend-сессии старые service/review/category кэши также могли показывать публичные проекции до ручного refresh или истечения stale window.

Исправление: `list_categories` теперь считает только active services владельцев с `is_hidden_profile=false`, чтобы counter совпадал с public catalog. `useUpdateMe` дополнительно инвалидирует own reviews, service catalog, broad service detail/comment prefix и categories. Добавлены backend regression test на category count hidden-owner exclusion и frontend hook test на invalidation set.

### M-28. Create-deal UI падал на balance-funded ответе `invoice: null`

Ссылки: `backend/app/schemas.py:712-728`, `backend/app/routers/deals.py:322-365`, `tests/e2e/test_deals_with_topup.py:529-584`, `frontend/src/pages/deals/CreateDealPage.tsx`, `frontend/src/api/types.ts`, regressions `frontend/src/pages/deals/CreateDealPage.test.tsx`, `frontend/src/api/openapi.contract.test.ts`.

Backend `POST /api/deals/with-topup` намеренно возвращает `invoice: null`, когда баланс покупателя покрывает сумму сделки и комиссию: сделка сразу переходит в `pending_confirmation`, без платежного invoice. Backend e2e уже закреплял этот контракт. Frontend DTO при этом объявлял `invoice` как non-null `DealTopupInvoiceDto`, а `CreateDealPage` после success сразу читал `deal.invoice.total` и в render ветке читал `created.invoice.*`.

Риск: пользователь с достаточным балансом создавал сделку, backend успешно списывал баланс/комиссию и возвращал 201, но frontend падал на `Cannot read properties of null`, вместо карточки "сделка создана, оплата с баланса". Это особенно опасно тем, что money mutation уже произошла, а UI выглядел как сломанная операция.

Исправление: `DealCreateWithTopupResponseDto.invoice` приведен к backend/OpenAPI контракту `DealTopupInvoiceDto | null`. `CreateDealPage` теперь отделяет invoices, требующие оплаты, от `invoice: null`/zero-total paths и показывает balance-funded confirmation без попытки открыть payment modal. Добавлены frontend regression test на `invoice=null` ответ и OpenAPI compile-time fixture для nullable invoice branch.

### M-29. Deal list silently ignored unknown `role`/`status` filters

Ссылки: `backend/app/routers/deals.py:196-207`, regression `tests/integration/test_deals_list_filters.py`, OpenAPI snapshot `frontend/openapi.json`, generated contract `frontend/src/api/openapi.generated.ts`.

Backend `GET /api/deals` принимал `role` и `status` как plain string. Неизвестный `role` просто не попадал ни в одну ветку, а неизвестный `status` ловился через `try/except ValueError` и тоже игнорировался. В результате запросы вроде `?role=all` или `?status=wat` возвращали весь список сделок пользователя вместо typed validation error.

Риск: опечатка или рассинхрон frontend фильтра выглядели как корректный широкий запрос. Пользователь мог получить смешанный buyer/seller список или все статусы, хотя UI/интеграция ожидали отфильтрованные данные; OpenAPI тоже не описывал допустимый enum, так что клиентская типизация не ловила drift.

Исправление: `role` переведен на `Literal["buyer", "seller"]`, `status` — на `DealStatus | None`, чтобы FastAPI/Pydantic возвращали `422` для неизвестных значений. OpenAPI snapshot и generated types обновлены; добавлен regression test на оба invalid filter paths.

### M-30. Admin deal status filters не покрывали `pending_topup` и показывали deprecated `pending_payment`

Ссылки: `backend/app/routers/admin/deals.py:604-655`, `frontend/src/pages/admin/AdminDealsPage.tsx:13-40`, regressions `tests/integration/test_admin_deals.py`, `frontend/src/pages/admin/AdminDealsPage.test.tsx`.

`DealStatus.pending_topup` — живой статус сделок, созданных через `/api/deals/with-topup`: buyer еще не оплатил linked deposit invoice, а sweep/admin system отдельно отслеживают stale `pending_topup`. Admin UI уже показывал chip "Ожидание инвойса" и отправлял `?status=pending_topup`, но backend `_STATUS_CHOICES` этот статус не включал и возвращал `400`. Одновременно UI строил chips из общего `STATUS_LABEL` и поэтому показывал `pending_payment`, хотя этот enum value прямо помечен как deprecated и backend intentionally dropped его из фильтров.

Риск: админ не мог отфильтровать зависшие top-up сделки из `/admin/deals` именно в сценарии, где нужна ручная проверка invoice/deal lifecycle. Deprecated `pending_payment` выглядел как рабочий фильтр, но приводил к ошибке запроса и путал диагностику.

Исправление: backend admin deals allow-list теперь принимает `pending_topup` и по-прежнему отвергает deprecated `pending_payment`. Frontend разделяет display labels и filterable statuses: строка `pending_payment` остается человекочитаемой для исторических rows, но chip фильтра больше не выводится. Добавлены backend regression на `?status=pending_topup`/`pending_payment` и frontend test на набор status chips.

### M-31. Admin deal actions и arbitration claim оставляли stale audit/detail кэши

Ссылки: `backend/app/routers/admin/deals.py:959-1351`, `backend/app/routers/admin/arbitration.py:116-194`, `frontend/src/api/admin/hooks.ts:229-336`, regression `frontend/src/api/admin/hooks.test.tsx`.

Backend admin deal actions (`force-release`, `force-refund`, `split`, `force-arbitration`, `assign-arbiter`, `delete`) пишут `AdminAuditLog` через `log_admin_action()`. `POST /api/admin/arbitration/{deal_id}/claim` тоже пишет audit row и меняет `Deal.arbitration_resolved_by`, который читается `GET /api/admin/deals/{id}` как `arbitration_resolved_by_id/username`. Frontend mutations сбрасывали deal lists/queues/dashboard, но не `qk.admin.audit.*`; claim также не сбрасывал точечный `qk.admin.deal.detail(deal_id)`.

Риск: админ мог выполнить force-action или claim и сразу открыть audit/detail, но увидеть старую audit history или старого назначенного арбитра до фонового refetch/manual refresh. Это особенно плохо для claim: очередь уже переносит дело в "В работе", а detail cache мог продолжать показывать `arbitration_resolved_by_id=null`.

Исправление: `useAdminDealAction` теперь инвалидирует `qk.admin.audit.all()` вместе с остальными projection caches. `useAdminClaimArbitration` использует `deal_id` из ответа и дополнительно инвалидирует `qk.admin.deal.detail(deal_id)` и `qk.admin.audit.all()`. Hook regression tests закрепляют audit/detail invalidation set.

### M-32. Admin deposits/withdrawals UI был заперт на первой странице

Ссылки: `backend/app/routers/admin/deposits.py:74-118`, `backend/app/routers/admin/withdrawals.py:79-145`, `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, regressions `frontend/src/pages/admin/AdminDepositsPage.test.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.test.tsx`.

Backend admin queues уже были paginated: `/api/admin/deposits` принимает `page/page_size` и возвращает `total/page/page_size`, `/api/admin/withdrawals` принимает `page/page_size` и возвращает status counters. Frontend при этом всегда вызывал deposits с `page: 1, page_size: 50`, а withdrawals — без `page`, то есть тоже page 1. Навигации по страницам в UI не было.

Риск: если в очереди больше 50 депозитов или выводов в одном статусе, админ не мог добраться до более старых строк через штатный интерфейс. Это ломало ручную сверку missed deposits, refunds, approved withdrawals и mark-sent recovery paths: backend данные существовали, но UI фактически скрывал их после первого page slice.

Исправление: `AdminDepositsPage` и `AdminWithdrawalsPage` получили page state, кнопки prev/next и reset page при смене status filter. Deposits считает pages по backend `total`; withdrawals использует status counters для текущей вкладки. Добавлены regression tests, которые проверяют переход на page 2 и сброс страницы при смене фильтра/таба.

### M-33. Admin wallets UI был заперт на первой странице

Ссылки: `backend/app/routers/admin/wallets.py:106-191`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, regression `frontend/src/pages/admin/AdminWalletsPage.test.tsx`.

Backend `/api/admin/wallets` уже принимает `page/page_size` и возвращает `total/page/page_size`. Frontend держал `page` state и сбрасывал его при поиске, но не рендерил никаких prev/next controls. В обычном UI page оставался равен 1, поэтому админ видел максимум первые 50 пользователей из wallet inspector.

Риск: ручные корректировки баланса, проверка locked balances и USD-rate gaps становились недоступны для пользователей за пределами первого page slice. Это особенно опасно для recovery/debug сценариев: данные и endpoint есть, но оператор не может выбрать нужного пользователя без точного search query.

Исправление: `AdminWalletsPage` теперь передает явный `page_size`, показывает pagination по backend `total/page_size` и сохраняет reset page на поиске. Regression test проверяет переход на page 2 и возврат на page 1 после search.

### M-34. Admin broadcasts history был заперт на первой странице

Ссылки: `backend/app/routers/admin/broadcasts.py:383-413`, `frontend/src/api/admin/hooks.ts`, `frontend/src/pages/admin/AdminBroadcastsPage.tsx`, regression `frontend/src/pages/admin/AdminBroadcastsPage.test.tsx`.

Backend `/api/admin/broadcasts` уже возвращает paginated history: `items/total/page/page_size`. Frontend hook всегда дергал endpoint без `page/page_size`, а page component не имел навигации. Поэтому история рассылок в админке показывала только первые 50 live rows, даже если backend корректно отдавал следующие pages.

Риск: старые broadcast records, delivery counts и soft-delete recovery context исчезали из штатного UI. Для аудита отправленных сообщений это плохой режим: запись существует и доступна API, но оператор не может дойти до нее без внешних инструментов.

Исправление: `useAdminBroadcasts` принимает pagination params и включает их в query key/search params. `AdminBroadcastsPage` получил page state и prev/next controls по backend `total/page_size`. Regression test проверяет переход на вторую страницу.

### M-35. Admin arbitration queue был заперт на первой странице

Ссылки: `backend/app/routers/admin/arbitration.py:76-117`, `frontend/src/api/admin/hooks.ts`, `frontend/src/pages/admin/AdminArbitrationPage.tsx`, regression `frontend/src/pages/admin/AdminArbitrationPage.test.tsx`.

Backend `/api/admin/arbitration` принимает `page/page_size`, а frontend hook уже умел передавать эти параметры. Но `AdminArbitrationPage` вызывал `useAdminArbitration(queue)` без page state и не показывал prev/next controls. При этом counters показывали полный размер очередей, то есть UI мог честно показывать `45` новых споров, но дать открыть только первые 20.

Риск: админ или арбитр не мог взять в работу/просмотреть споры за пределами первого page slice в любой из трех очередей (`new`, `in_progress`, `closed`). Это ломало triage при большом всплеске арбитражей: старые, но все еще активные disputes становились недоступны из штатного интерфейса.

Исправление: `AdminArbitrationPage` получил page state, явный `PAGE_SIZE`, pagination controls по counters текущей очереди и reset page при смене queue/claim. Regression test проверяет переход на page 2 и сброс page на 1 при смене вкладки.

### M-36. Admin user content sections грузили неограниченные списки и не имели пагинации

Ссылки: `backend/app/routers/admin/content.py:164-715`, `backend/app/schemas.py:1555-1705`, `frontend/src/api/admin/hooks.ts:344-540`, `frontend/src/pages/admin/UserContentSections.tsx`, regressions `tests/integration/test_admin_content.py`, `frontend/src/pages/admin/UserContentSections.test.tsx`, OpenAPI snapshot `frontend/openapi.json`.

Backend endpoints для админского редактирования контента пользователя (`/api/admin/users/{id}/services`, `/api/admin/users/{id}/reviews`, `/api/admin/users/{id}/comments`, `/api/admin/services/{id}/comments`) возвращали bare arrays без `limit/page_size/total`. Frontend `UserContentSections` вызывал эти endpoints без параметров и рендерил весь массив сразу. После исправлений пагинации в основных admin queues это оставалось отдельной дырой в контракте: user detail page мог сериализовать и отрисовать тысячи услуг/отзывов/комментариев одного пользователя.

Риск: админская карточка пользователя деградировала по памяти/latency на high-volume аккаунтах. Если backend просто ограничить лимитом без UI, старые services/reviews/comments стали бы недоступны из штатной админки, что ломает модерацию, миграционные правки и forensic review контента.

Исправление: list endpoints теперь принимают `page/page_size`, возвращают `items/total/page/page_size` и сортируют стабильно по `created_at desc, id desc`. Admin hooks включают pagination params в query key/search params, а `ServicesSection`, `ReviewsSection` и `CommentsSection` показывают total и prev/next controls; page сбрасывается при смене пользователя/направления отзывов и корректируется после удаления последнего элемента страницы. OpenAPI snapshot/generated types обновлены, добавлены regression-проверки backend envelope и frontend page reset.

### M-37. Admin deal detail встраивал полный чат сделки

Ссылки: `backend/app/routers/admin/deals.py:219-271`, `frontend/src/pages/admin/AdminDealDetailPage.tsx`, `frontend/src/api/hooks.ts:392-455`, regressions `tests/integration/test_admin_deals.py`, `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`.

`GET /api/admin/deals/{id}` строил detail DTO вместе со всем transcript из `deal_messages`, хотя пользовательский chat endpoint уже имеет `limit/before_id` пагинацию. В длинной арбитражной сделке админское открытие карточки могло тянуть тысячи сообщений и attachments одним JSON-ответом; frontend при этом отрисовывал только встроенный `deal.messages` и не давал подгрузить более ранние сообщения отдельными страницами.

Риск: одна тяжелая сделка превращала обычный admin detail view в большой DB/JSON/render spike. Это особенно плохо для споров, где администратор открывает карточку именно в момент нагрузки, а история может содержать месяцы переписки и вложений.

Исправление: admin detail теперь встраивает только newest page размера `_DEFAULT_MESSAGE_PAGE` с тем же batched media load. `AdminDealDetailPage` перешел на общие chat hooks `useDealMessages`, `useLoadOlderDealMessages` и `useSendDealMessage`, показывает control "Показать более ранние" и отправляет сообщения через typed mutation. Добавлены backend regression на лимит/порядок latest 50 и frontend regression на cursor load + send hook.

### M-38. User-facing arbitration page не подгружал следующие страницы

Ссылки: `backend/app/routers/arbitration.py:29-57`, `frontend/src/pages/arbitration/ArbitrationPage.tsx`, regression `frontend/src/pages/arbitration/ArbitrationPage.test.tsx`.

`GET /api/arbitration/deals` уже принимает `limit/offset` и по умолчанию возвращает только первые 50 строк. Но `ArbitrationPage` вызывал endpoint без параметров и отрисовывал только этот первый ответ без кнопки next/load-more. Для обычного пользователя это обрезало длинную историю споров; для арбитра или админа в основной вкладке arbitration список системных споров тоже заканчивался на первой странице.

Риск: старые или более поздние споры были фактически недоступны из user-facing arbitration tab, хотя backend их отдавал через offset. Пользователь видел неполную историю, а арбитр мог пропустить часть очереди при работе из основной вкладки.

Исправление: `ArbitrationPage` теперь явно запрашивает `limit=50&offset=0`, хранит локально загруженные страницы и показывает кнопку "Показать еще", пока backend возвращает полные страницы. Следующая загрузка идет с `offset=items.length`, короткая страница скрывает кнопку. Добавлен frontend regression на offset 50 и append второй страницы.

### M-39. User search был hard-capped без pagination affordance

Ссылки: `backend/app/routers/users.py:58-179`, `frontend/src/api/hooks.ts:284-333`, `frontend/src/pages/search/SearchPage.tsx`, regressions `tests/integration/test_users_filters.py`, `frontend/src/pages/search/SearchPage.test.tsx`.

`GET /api/users` всегда делал `LIMIT 100` без `offset`, а `SearchPage` отрисовывал только этот массив. При широком поиске, фильтре "все" или популярных rating/deals buckets пользователь видел первые 100 профилей и не имел способа открыть следующие результаты. Это расходилось с уже paginated `/api/services` и admin-list surfaces.

Риск: пользователи за пределами top-100 по текущему sort order были практически скрыты из search UI. Для маркетплейса это не только UX-проблема, но и skew ранжирования: новые или менее активные профили могли быть недоступны даже при валидном фильтре.

Исправление: public users endpoint теперь принимает `limit/offset`, выставляет `X-Total-Count` и сортирует стабильно с `User.id.desc()` tie-breaker. `useUsers` прокидывает pagination params, а `SearchPage` запрашивает первую страницу по 50 пользователей и догружает следующую кнопкой "Показать еще" через offset `users.length`. Добавлены backend regression на `limit/offset` и frontend regression на append следующей страницы.

### M-40. User deal list отправлял invalid `role=all` и грузил список без page cap

Ссылки: `backend/app/routers/deals.py:193-253`, `frontend/src/api/hooks.ts:335-357`, `frontend/src/pages/deals/DealsPage.tsx`, regressions `tests/integration/test_deals_list_filters.py`, `frontend/src/pages/deals/DealsPage.test.tsx`.

После M-29 backend `GET /api/deals` стал строго валидировать `role` как `buyer|seller`, но `DealsPage` продолжал передавать default tab `role=all`. В результате первый запрос страницы сделок мог получать `422` вместо общего списка. Отдельно endpoint не имел `limit/offset` и возвращал все сделки пользователя одним массивом, а frontend рендерил его без возможности догрузки страниц.

Риск: основной экран сделок мог ломаться на дефолтной вкладке после ужесточения backend validation. У активных пользователей с длинной историей сделок API/UI также сохраняли unbounded payload/render path, в отличие от уже исправленных admin и arbitration списков.

Исправление: frontend теперь нормализует вкладку "Все" в отсутствие `role`, а shared `buildDealsSearchParams` дополнительно защищает raw callers от `role=all`. Public deals endpoint принимает `limit/offset`, выставляет `X-Total-Count`, сортирует стабильно по `created_at desc, id desc` и гидратит top-up invoice data только для текущей страницы. `DealsPage` запрашивает первые 50 сделок и догружает следующие через offset `deals.length`. Добавлены backend regression на `limit/offset` и frontend regressions на omission `role=all` и load-more offset.

### M-41. Notifications page не подгружал следующие cursor pages

Ссылки: `backend/app/routers/notifications.py:18-110`, `frontend/src/api/hooks.ts:565-587`, `frontend/src/pages/notifications/NotificationsPage.tsx`, regression `frontend/src/pages/notifications/NotificationsPage.test.tsx`.

Backend `GET /api/notifications` уже имел keyset pagination по `(created_at, id)` и по умолчанию возвращал ограниченную страницу. Но `NotificationsPage` вызывал endpoint только один раз на выбранный tab и не передавал cursor последнего элемента. Пользователь с длинной историей видел только первую страницу уведомлений, несмотря на то что backend уже отдавал следующие страницы через `before_created_at/before_id`.

Риск: старые уведомления становились недоступны из основного экрана, а фильтрованные вкладки `deals/deposits/system` выглядели неполными. Это особенно заметно после broadcast fan-out и у активных пользователей, где первые 50-200 событий быстро вытесняют более старые.

Исправление: `useNotifications` теперь принимает structured pagination params и строит search params через shared helper. `NotificationsPage` запрашивает первую страницу по 50 уведомлений, хранит загруженные rows локально и догружает следующую страницу кнопкой "Показать еще" с keyset cursor последнего row. Regression test проверяет передачу `before_created_at` и `before_id`.

### M-42. Per-currency wallet history был обрезан первыми 100 unfiltered rows

Ссылки: `backend/app/routers/wallet.py:191-282`, `frontend/src/api/hooks.ts:904-970`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regressions `tests/integration/test_wallet_history_pagination.py`, `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`, OpenAPI snapshot `frontend/openapi.json`.

`GET /api/wallet/deposits` и `GET /api/wallet/withdrawals` всегда возвращали только последние 100 операций пользователя по всем валютам, а `WalletCurrencyPage` затем фильтровал массив на клиенте по текущей валюте. Если у пользователя больше 100 операций или более свежие операции другой валюты вытесняли нужную валюту из первого ответа, per-currency history становился неполным. UI также не имел кнопки догрузки.

Риск: пользователь видел неполную историю пополнений/выводов по валюте, не мог штатно добраться до старых операций и pending invoice link мог исчезнуть из истории при большом количестве более свежих строк другой валюты.

Исправление: wallet deposit/withdrawal list endpoints принимают `currency`, `limit`, `offset`, выставляют `X-Total-Count` и сортируют стабильно по `created_at desc, id desc`. Frontend hooks прокидывают structured history params, а `WalletCurrencyPage` запрашивает первые 50 операций текущей валюты и догружает следующие страницы кнопкой "Показать еще" через offset. Добавлены backend regression на currency-scoped `limit/offset` и frontend regression на first-page params + load-more offsets.

### M-43. Service detail comments не подгружали следующие страницы

Ссылки: `backend/app/routers/services.py:343-377`, `frontend/src/api/hooks.ts:248-272`, `frontend/src/pages/search/ServiceDetailPage.tsx`, regressions `tests/integration/test_service_comments.py`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`, OpenAPI snapshot `frontend/openapi.json`.

`GET /api/services/{id}/comments` принимал только `limit` и по умолчанию возвращал первые 50 комментариев. `ServiceDetailPage` вызывал hook без pagination params и рендерил только этот первый ответ, хотя detail DTO рядом показывал полный `comments_count`. Пользователь видел счетчик, например `120`, но открыть комментарии после первой страницы не мог.

Риск: старые комментарии и оценки услуги становились недоступны из публичного service detail UI. Для услуг с большим числом отзывов это ломало пользовательскую проверку репутации и модераторскую/владельческую работу с более старыми комментариями.

Исправление: comments endpoint принимает `limit/offset`, выставляет `X-Total-Count` и сортирует стабильно по `created_at desc, id desc`. `useServiceComments` принимает structured params, а `ServiceDetailPage` запрашивает первую страницу по 50 комментариев и показывает "Показать еще", пока локально загружено меньше `comments_count`. Добавлены backend regression на `limit/offset` и frontend regressions на first-page params + load-more offset.

### M-44. Profile reviews не подгружали следующие страницы

Ссылки: `backend/app/routers/reviews.py:29-78`, `frontend/src/api/hooks.ts:559-591`, `frontend/src/pages/profile/ProfilePage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, regressions `tests/integration/test_reviews_hidden_target.py`, `frontend/src/pages/profile/ProfilePage.test.tsx`, `frontend/src/pages/search/UserProfilePage.test.tsx`.

`GET /api/reviews` уже принимал `limit/offset`, но frontend `useReviews` не прокидывал pagination params. `ProfilePage` и `UserProfilePage` рендерили только первые 50 отзывов, хотя рядом в user DTO был полный `reviews_count`. На профиле с большим числом отзывов пользователь видел общий счетчик, но не мог открыть отзывы после первой страницы.

Риск: старые отзывы становились недоступны из собственного и публичного профиля. Это ухудшало проверку репутации пользователя и могло скрывать контекст по давним сделкам, хотя backend эти данные уже хранил.

Исправление: reviews endpoint выставляет `X-Total-Count` и сортирует стабильно по `created_at desc, id desc`. `useReviews` принимает structured params, а оба profile UI запрашивают первую страницу по 50 отзывов, показывают общий `reviews_count` в табе и догружают следующие страницы кнопкой "Показать еще" через offset. Добавлены backend regression на `limit/offset` + total header и frontend regressions на first-page params + load-more offsets для собственного и публичного профиля.

### M-45. Profile/category service lists не подгружали следующие страницы

Ссылки: `frontend/src/api/hooks.ts:160-190`, `frontend/src/pages/profile/ProfilePage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, `frontend/src/pages/search/CategoriesPage.tsx`, regressions `frontend/src/pages/profile/ProfilePage.test.tsx`, `frontend/src/pages/search/UserProfilePage.test.tsx`, `frontend/src/pages/search/CategoriesPage.test.tsx`.

Backend `GET /api/services` уже принимал `limit/offset` и выставлял `X-Total-Count`, но frontend `useServices` не прокидывал pagination params. Own profile, public user profile и category detail рендерили только дефолтный первый ответ `/api/services` и не давали открыть следующие услуги.

Риск: профили и категории с большим числом услуг выглядели неполными. Пользователь не мог штатно добраться до старых активных услуг в категории или до старых услуг конкретного продавца, хотя backend список поддерживал постраничную выдачу.

Исправление: `useServices` принимает structured `limit/offset`, а profile/category pages запрашивают первые 50 услуг и догружают следующие страницы кнопкой "Показать еще" через offset. Category page использует `services_count` категории для отображения полного счетчика и скрытия лишней догрузки, profile pages догружают пока backend не вернет неполную страницу. Добавлены frontend regressions на first-page params + load-more offsets для own profile, public profile и category detail.

### M-46. Deal detail мог показывать повторный CTA отзыва после пагинации profile reviews

Ссылки: `backend/app/routers/reviews.py:31-80`, `frontend/src/api/hooks.ts:578-604`, `frontend/src/pages/deals/DealDetailPage.tsx`, regressions `tests/integration/test_reviews_hidden_target.py`, `frontend/src/pages/deals/DealDetailPage.test.tsx`, OpenAPI snapshot `frontend/openapi.json`.

После M-44 `useReviews` стал корректно работать с первой страницей профиля, но `DealDetailPage` продолжал вызывать `useReviews(otherUser)` без фильтра по сделке и проверял `existingReviews.some(r => r.deal_id === deal.id)`. Если у контрагента было больше 50 более свежих отзывов, уже оставленный отзыв по текущей закрытой сделке мог не попасть в первую страницу. UI снова показывал кнопку "Оставить отзыв", хотя backend затем отклонял POST как duplicate review.

Риск: пользователь в terminal deal видел доступное действие, которое гарантированно падало на сервере. Это ухудшало закрытие сделки, плодило лишние POST-запросы и шум в `reviews.create.rejected` логах, особенно у активных продавцов с длинной историей отзывов.

Исправление: `GET /api/reviews` принимает optional `deal_id`, применяет его и к выборке, и к `X-Total-Count`. `useReviews`/query key прокидывают этот параметр, а `DealDetailPage` проверяет состояние отзыва точечным запросом `deal_id + limit=1`, не завися от страницы профиля. Добавлены backend regression на filtered total/body и frontend regressions на параметры запроса и скрытие CTA, когда точечный запрос вернул уже существующий отзыв.

### M-47. Пустой users picker обходил search gate и грузил global top users

Ссылки: `backend/app/routers/users.py:58-194`, `frontend/src/components/domain/UserPicker.tsx`, regressions `tests/integration/test_users_filters.py`, `frontend/src/components/domain/UserPicker.test.tsx`.

`UserPicker` на `/deals/new` и в admin content sheet вызывал `useUsers({ picker: true })` сразу при пустом поле. Backend трактовал `picker=1` как bypass для правила "минимум 1 сделка для поиска" и при отсутствии `q` отдавал обычную top-by-deals выдачу. Dropdown при пустом поле не показывался, но сетевой запрос всё равно уходил и raw `/api/users?picker=1` позволял zero-deal пользователю получить первую страницу каталога.

Риск: `picker=1` был задуман как точечный поиск известного контрагента для первой сделки, а не как browse-режим. Пустой запрос создавал лишнюю нагрузку на каждом mount picker-компонента и ослаблял search gate для пользователей без сделок.

Исправление: backend для `picker=true` без непустого `q` возвращает `200 []` и `X-Total-Count: 0`, сохраняя поиск по `q` для zero-deal пользователей. Frontend `UserPicker` теперь держит query disabled до ввода, всегда передает `limit=8&offset=0` и больше не режет более крупный ответ на клиенте. Добавлены backend regression на пустой/непустой picker и frontend regressions на disabled empty query + capped live-search params.

### M-48. Offset-пагинация нескольких списков была нестабильной при одинаковом `created_at`

Ссылки: `backend/app/routers/admin/deals.py`, `backend/app/routers/admin/arbitration.py`, `backend/app/routers/arbitration.py`, `backend/app/routers/admin/users.py`, `backend/app/routers/admin/deposits.py`, `backend/app/routers/admin/withdrawals.py`, `backend/app/routers/admin/broadcasts.py`, `backend/app/routers/admin/audit.py`, regression `tests/integration/test_audit_stable_pagination_order.py`.

Несколько paginated list endpoints сортировали страницы только по `created_at desc` или по бизнес-метрике без уникального вторичного ключа. Это оставалось после фиксов на page/load-more: если несколько строк создавались в одной транзакции или получали одинаковый timestamp, база могла отдавать ties в разном порядке между запросами `page=1` и `page=2` / `offset=N`. Затронуты admin deals, admin/public arbitration, audit log, broadcasts, deposits, withdrawals и sort modes в admin users.

Риск: админ мог видеть дубликаты между соседними страницами или не видеть часть строк вообще. Для очередей выплат/депозитов/арбитража это особенно плохо: элемент мог исчезнуть из штатного triage не из-за фильтра, а из-за недетерминированной границы страницы.

Исправление: все найденные `created_at`-based router lists теперь добавляют уникальный tie-breaker `id` (`desc` для newest-first, `asc` для `created_asc`). Sort modes admin users также получили `User.id` tie-breaker для `created_desc`, `created_asc`, `rating` и `deals`. Добавлен regression, который запрещает одинокий `order_by(Model.created_at.desc())` в routers и пинует id tie-breakers в admin users sort map.

### M-49. Admin deal approvals API был hard-capped первыми 200 заявками

Ссылки: `backend/app/routers/admin/deals.py:703-735`, regression `tests/integration/test_admin_deals.py`, OpenAPI snapshot `frontend/openapi.json`, generated types `frontend/src/api/openapi.generated.ts`.

`GET /api/admin/deals/approvals` возвращал bare array с `.limit(200)` и не принимал ни `offset`, ни `page`, ни `X-Total-Count`. Даже после исправления основных admin queues этот endpoint оставался скрытым hard cap: при большом числе pending/approved maker-checker заявок оператор или будущая UI-страница могли увидеть только первые 200 строк по `created_at desc, id desc`.

Риск: high-risk money movement approvals после первых 200 становились недоступны через штатный API списка. Для maker-checker flow это опасно: часть заявок могла не попасть в triage/forensic review, а total backlog был неизвестен клиенту.

Исправление: endpoint принимает `limit` (1..200, default 200) и `offset`, считает полный total по тем же `status/target_id` фильтрам и выставляет `X-Total-Count`. Сортировка осталась стабильной по `created_at desc, id desc`. Добавлен backend regression на 205 заявок, `offset=200` и total header; OpenAPI snapshot/generated types обновлены под новые query params.

### M-50. Назначение арбитра могло не найти точный username из-за первой страницы поиска

Ссылки: `backend/app/routers/admin/users.py:265-336`, `frontend/src/pages/admin/AdminDealDetailPage.tsx:317-345`, regressions `tests/integration/test_admin_users.py`, `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`.

Admin deal detail назначал арбитра через `GET /api/admin/users?q=<username>`, а затем искал точное совпадение username только внутри первой страницы ответа. Backend search при этом использовал substring matching по username/display_name/tg_id и сортировал результат по дефолтному `created_at desc, id desc`. Если у старого арбитра был username `arbiter_target`, а после него появились десятки более новых пользователей с username/display_name, содержащими тот же фрагмент, точный арбитр уходил за первую страницу и UI показывал "Юзер не найден".

Риск: админ не мог штатно назначить существующего арбитра в спорную сделку через UI, хотя backend `assign-arbiter` принимал его id. Это блокировало triage арбитража и создавало ложное впечатление, что роль/аккаунт арбитра отсутствует.

Исправление: `/api/admin/users` теперь при непустом `q` добавляет exact-match priority для `username`, `display_name` и numeric `tg_user_id`, поэтому точные совпадения всегда попадают в начало первой страницы перед более новыми substring matches. Frontend lookup для назначения арбитра запрашивает только `page=1&page_size=1`, опираясь на этот exact-first contract. Добавлены backend regressions на старый exact username/tg_id за 25 новыми partial matches и frontend regression на параметры lookup + отправку найденного `arbiter_id`.

### M-51. Admin wallets скрывал часть ненулевых балансов в карточке пользователя

Ссылки: `frontend/src/pages/admin/AdminWalletsPage.tsx`, regression `frontend/src/pages/admin/AdminWalletsPage.test.tsx`.

`/admin/wallets` получал от backend полный `balances` массив по активным валютам, но в строке пользователя показывал только `nonZero.slice(0, 4)`. При пяти и более ненулевых валютах остальные суммы не отображались нигде в UI: клик по строке открывал только форму корректировки, без полного breakdown текущих балансов.

Риск: админ мог принять решение о ручной корректировке или расследовании кошелька по неполной картине, особенно у пользователей с балансами в нескольких валютах. Backend данные уже были в ответе, проблема была именно в представлении.

Исправление: sheet корректировки теперь перед формой показывает полный список всех ненулевых балансов выбранного пользователя, включая locked-часть. Список в строке остается компактным preview, но полный breakdown доступен штатным кликом по пользователю. Добавлен frontend regression: пятая валюта не видна в row preview, но появляется в adjust sheet с точной decimal-точностью.

### M-52. Admin content UI принимал rating `0` для отзывов и комментариев, хотя backend требует `1..5`

Ссылки: `frontend/src/pages/admin/UserContentSections.tsx`, `backend/app/schemas.py:1667-1690`, `backend/app/schemas.py:1713-1734`, regression `frontend/src/pages/admin/UserContentSections.test.tsx`.

В `ReviewCreateSheet`, `ReviewEditSheet` и `CommentEditSheet` frontend проверял `rating < 0 || rating > 5` и подписывал поля как `Рейтинг 0..5`. Backend-схемы `AdminReviewUpsertIn` и `AdminCommentUpdateIn` при этом валидировали `1..5`, а основная review service logic также отвергает `0`. В результате админ мог ввести `0`, UI отправлял mutation, а сервер отвечал 422 вместо локального понятного отказа.

Риск: админские формы редактирования контента выглядели валидными, но гарантированно падали на сервере для `0`. Это создавало лишние failed requests, шум в error flow и путало различие между service manual rating override (`0..5`, intended) и реальными review/comment ratings (`1..5`).

Исправление: review create/edit и comment edit теперь валидируют `1..5`, показывают локальную ошибку `Рейтинг 1..5` и подписывают поля тем же диапазоном. Service `rating_manual` оставлен `0..5`, потому что это отдельный manual override contract. Добавлены frontend regressions на create review, update review и update comment с rating `0`: mutation не вызывается, ошибка показывается локально.

### M-53. Admin settings принимал `-1` для обычной комиссии, хотя БД разрешает только `0..100`

Ссылки: `backend/app/schemas.py:1982-2020`, `backend/app/models.py:698-722`, regression `tests/unit/test_admin_settings_schema.py`.

`AdminSettingsUpdateIn` валидировал `deal_commission_percent` и `vip_commission_percent` одним общим правилом `-1..100`. Но `-1` является sentinel только для `vip_commission_percent` (`-1 = наследовать обычную комиссию`). Обычная `deal_commission_percent` защищена DB constraint `ck_app_settings_deal_commission_pct_range` и должна быть в диапазоне `0..100`. Поэтому PATCH `/api/admin/settings` с `{"deal_commission_percent": -1}` проходил Pydantic-валидацию и падал уже на commit по constraint вместо нормального 422 на границе API.

Риск: админский endpoint мог возвращать внутреннюю ошибку/rollback на некорректном, но легко вводимом значении. Это также размывало контракт настроек: один и тот же `-1` выглядел допустимым для обеих комиссий, хотя бизнес-смысл у него есть только в VIP override.

Исправление: валидаторы разделены. `deal_commission_percent` теперь принимает только конечные числа `0..100`, а `vip_commission_percent` сохраняет прежний диапазон `-1..100`. Добавлен unit regression: обычная комиссия отвергает `-1` до DB constraint, `0` остаётся валидной границей, VIP-комиссия сохраняет sentinel `-1`, а `-1.01` отклоняется.

### M-54. Admin FAQ stats принимали отрицательные публичные счётчики

Ссылки: `backend/app/schemas.py:1982-2059`, `backend/app/routers/public_stats.py:24-33`, `frontend/src/components/domain/StatsBadge.tsx`, regression `tests/unit/test_admin_settings_schema.py`.

`AdminSettingsUpdateIn` документировал, что numeric settings не могут быть отрицательными, но валидатор `_int_ok` покрывал только inactivity/max-active/pending-topup поля. `faq_stats_users`, `faq_stats_deals` и `faq_stats_total_usd` не проверялись вообще. Поэтому PATCH `/api/admin/settings` мог сохранить `-5` пользователей, `-7` сделок или отрицательный USD volume, а `/api/stats/public` затем отдавал эти значения на публичный `/faq` badge.

Риск: публичная витрина статистики могла показывать отрицательные счётчики и объём, хотя эти поля являются showcase/marketing numbers. Это не ломало деньги напрямую, но создавало user-visible неконсистентность и нарушало собственный контракт схемы "numeric values must be non-negative".

Исправление: `faq_stats_users` и `faq_stats_deals` добавлены в общий non-negative int validator, `faq_stats_total_usd` получил отдельный finite money validator с запретом отрицательных значений. Заодно VIP commission теперь тоже проходит через общий finite-money guard. Добавлены unit regressions на отрицательные FAQ counts/total и на нулевую границу.

### M-55. Zero-deal пользователь не мог открыть собственный список услуг

Ссылки: `backend/app/routers/services.py:173-205`, `frontend/src/pages/profile/ProfilePage.tsx:43-123`, regression `tests/integration/test_search_gating.py`.

`GET /api/services` блокировал любого не-админа с `deals_total == 0` до разбора `owner`. Это правильно для публичного каталога/поиска, но ломало owner-scoped запросы: новый пользователь мог создать услугу через `POST /api/services`, а затем собственный профиль запрашивал `GET /api/services?owner=<me>` и получал 403 "Минимум 1 сделка для поиска" вместо своих услуг.

Риск: onboarding продавца с нулём сделок был сам себе противоречивым. Backend разрешал завести первую услугу, но штатная страница профиля не могла отобразить и управлять этой услугой до появления сделки. Для скрытого профиля это особенно заметно: owner/admin bypass был реализован ниже по коду, но до него запрос не доходил.

Исправление: `target_owner_self` вычисляется до search gate, и gate применяется только к public browse/search запросам, не к `owner=<current username>`. Admin bypass сохранён. Добавлен regression: zero-deal пользователь всё ещё получает 403 на общий `/api/services`, но получает 200, `X-Total-Count: 1` и свою услугу на `/api/services?owner=<me>`.

### M-56. Auto-withdraw Phase 2 мог гоняться с admin reject и возвращать уже отправленные средства

Ссылки: `backend/app/services_wallet.py:49-92`, `backend/app/services_wallet.py:1174-1438`, `backend/app/services_wallet.py:1613-1675`, `backend/app/routers/admin/withdrawals.py:175-404`, regression `tests/integration/test_admin_finance.py`.

`services_wallet.create_withdrawal` и admin `approve` отправляют CryptoBot Transfer во второй фазе без DB lock, чтобы не держать `wallet_withdrawals`/`user_balances` во время HTTP roundtrip. Но до исправления строка оставалась видимой как обычная `pending` или `approved`: параллельный admin `reject` мог вернуть `locked -> amount`, пока CryptoBot Transfer уже выполнялся или уже успел уйти. После успешного ответа Phase 3 видел, что статус изменился, логировал race и выходил, оставляя пользователю и внешний payout, и внутренний refund.

Риск: прямой double-spend на выводах. Один и тот же `WalletWithdrawal` мог закончиться внешней выплатой через CryptoBot при одновременном возврате зарезервированных средств в баланс пользователя, особенно если оператор вручную разгребал очередь во время медленного/повторяющегося upstream-запроса.

Исправление: строки с автоматической отправкой помечаются marker-строкой `[auto-send in progress]` в `admin_note` на время Phase 2. Admin `approve`/`reject` теперь отвечают 409, если marker активен; успешные и failed пути снимают marker или заменяют его `[auto-send failed]`. Stale sweep дополнительно пропускает свежие in-progress marker-строки, чтобы низкий `wallet_withdrawal_stale_seconds` не мог refund-нуть вывод, пока HTTP-запрос ещё выполняется, но старые зависшие строки всё ещё остаются recoverable через прежний CryptoBot reconciliation. Добавлены regressions: approve/reject не меняют статус и баланс при активном marker, а stale sweep не вызывает CryptoBot и не возвращает средства для свежей in-flight строки.

### M-57. Paid PIN reset списывал USD, даже если Telegram DM с кодом не доставлен

Ссылки: `backend/app/routers/pin.py:539-604`, regression `tests/integration/test_pin_reset_no_code_in_logs.py:183`.

`POST /api/pin/reset/paid` списывал `pin_reset_price_usd` с USD-баланса, вызывал `_mint_and_send_reset_code`, а затем коммитил транзакцию независимо от `delivered`. Если `send_dm` возвращал `False` из-за отсутствующего bot token, ошибки Telegram API или пользователя, который не запускал бота, backend всё равно сохранял `pin_reset_code_hash` и уменьшал баланс. Пользователь видел paid reset как успешную операцию с `delivered=false`, но фактически не получал одноразовый код.

Риск: платный recovery flow мог забирать деньги без предоставления recovery-секрета. Повторная попытка могла снова списать USD, а сохранённый недоставленный code hash не помогал пользователю, потому что plaintext code известен только DM-каналу.

Исправление: paid reset теперь делает `rollback` и возвращает 502, если DM не доставлен; это покрывает и нулевую цену, и обычное списание. Баланс не меняется, `pin_reset_code_hash`/`pin_reset_expires` не сохраняются. Добавлен regression: при `send_dm=False` ответ 502, USD-баланс остаётся прежним, reset-code поля остаются пустыми.

### M-58. Account-transfer code можно было употребить дважды в параллельном confirm

Ссылки: `backend/app/services_account.py:392-529`, regression `tests/integration/test_audit_simple_flags.py:144`.

`confirm_transfer` выбирал live `AccountTransferCode` по `code_hash`, `consumed_at IS NULL` и `expires_at > now`, но не брал `FOR UPDATE` на саму строку кода. Дальше функция блокировала только source/target `users` rows. Если два target-аккаунта параллельно отправляли один и тот же код, второй запрос мог прочитать `consumed_at=NULL` до коммита первого, затем ждать lock на source user, а после коммита первого продолжить со stale ORM-строкой кода и повторно перевесить source account уже на второго target.

Риск: одноразовый account-transfer code не был строго одноразовым под гонкой. При утечке кода или double-submit атакующий target мог выиграть второй confirm и перезаписать `tg_user_id` источника после легитимного target, фактически угнав перенос аккаунта.

Исправление: выбор `AccountTransferCode` в `confirm_transfer` теперь выполняется с `SELECT ... FOR UPDATE` и `populate_existing=True`. Второй confirm ждёт освобождения code-row lock и после первого коммита заново применяет `consumed_at IS NULL`, получая обычный отказ "код недействителен или истёк" вместо stale-row продолжения. Добавлен concurrency regression: первый target специально останавливается перед commit, второй target стартует с тем же кодом; в итоге успешен ровно один confirm, source остаётся на первом target, второй target не удаляется, а code row помечен consumed один раз.

### M-59. Admin `mark_sent` мог закрыть вывод во время in-flight CryptoBot Transfer

Ссылки: `backend/app/routers/admin/withdrawals.py:175-588`, regression `tests/integration/test_admin_finance.py:273`.

После M-56 admin `approve`/`reject` блокировались, если в `admin_note` стоял marker `[auto-send in progress]`, но `mark_sent` не входил в этот guard. Поэтому во время второй фазы auto-send, когда строка уже `approved`, а CryptoBot HTTP-запрос ещё выполняется без DB lock, другой админ мог нажать `mark_sent`. Эта ветка снимала locked-средства и переводила строку в `sent`, пока автоматический Transfer ещё мог как успешно завершиться, так и упасть.

Риск: при ошибке CryptoBot после такого `mark_sent` заявка оставалась `sent`, хотя автоматическая выплата могла не состояться; при успехе Phase 3 auto-send работал поверх уже изменённой строки и мог писать повторные ledger/audit/notification события. Это ломало операционный контракт вывода: строка выглядела закрытой вручную, пока внешний payout ещё не получил достоверный outcome.

Исправление: in-progress marker теперь блокирует все admin-решения, которые меняют состояние вывода: `approve`, `reject` и `mark_sent`. Phase 3 auto-send дополнительно перечитывает locked withdrawal/balance rows с `populate_existing=True`, чтобы locking SELECT не вернул stale ORM-объект из identity map. Regression расширен на `approved + mark_sent`: ответ 409, статус и locked-баланс не меняются.

### M-60. Crystalpay webhook dedupe подавлял исправленную `payed` доставку

Ссылки: `backend/app/routers/payments.py:273-309`, regression `tests/integration/test_crystalpay_webhook.py:243`.

Crystalpay не присылает отдельный `update_id`, и router строил `event_id` как `invoice_id:state`. Это слишком грубый ключ: первая валидно подписанная доставка `state=payed` с отсутствующей или заниженной `amount` проходила signature-check, попадала в inbox и возвращала `amount mismatch`. Событие помечалось `processed`, а следующая доставка с тем же invoice/state, но уже корректной `amount`, считалась duplicate и получала закэшированный mismatch, не доходя до `handle_crystalpay_invoice`.

Риск: оплаченный Crystalpay invoice мог навсегда остаться `pending`, если первый webhook был неполным, stale или отличался по amount. Пользователь платил, но баланс не пополнялся, потому что исправленная доставка подавлялась dedupe-слоем до бизнес-логики; ручная сверка требовалась даже при последующем корректном webhook.

Исправление: для Crystalpay dedupe-key теперь строится по `raw_event_id(raw)`, то есть по sha256 всего тела доставки. Точный повтор того же payload по-прежнему dedupe-ится, но payload с исправленной `amount` получает отдельную inbox-row и проходит в idempotent deposit handler, где `WalletDeposit.status` защищает от double-credit. Regression сначала отправляет `payed` с `amount=1` для invoice на `10`, затем корректный `payed` с `amount=10`; после исправления второй webhook кредитует баланс и переводит deposit в `paid`.

### M-61. Refunded CryptoBot deposit можно было заново зачислить свежим paid event или mark-paid

Ссылки: `backend/app/services_payments.py:157-243`, `backend/app/routers/admin/deposits.py:122-198`, regressions `tests/integration/test_cryptobot_webhook.py`, `tests/integration/test_admin_deposits_refund.py`.

`handle_invoice_paid` считал idempotent только `status=paid`. Если депозит уже был админом возвращен (`status=refunded`), а CryptoBot позже присылал новый `invoice_paid` event по тому же invoice id (например, с новым `update_id`, поэтому inbox-dedupe не считал его точным дублем), код проходил обычный amount-check и вызывал `credit_deposit`. Аналогично admin `mark-paid` не отличал `refunded` от обычного missed-webhook состояния и мог вручную снова зачислить уже возвращенный депозит.

Риск: admin refund переставал быть терминальным состоянием. Пользователь мог получить баланс обратно после возврата депозита, а audit trail показывал бы отдельное повторное зачисление вместо отказа на терминальной строке. Это особенно опасно для спорных/мошеннических пополнений, где refund уже был явным операторским решением.

Исправление: CryptoBot paid handler теперь отдельно отсекает `WalletDepositStatus.refunded`, логирует `cryptobot.webhook.paid_on_refunded` и возвращает `deposit not pending` без изменения баланса. Admin `mark-paid` на `refunded` отвечает 409 `Депозит уже возвращен`. Добавлены regressions: свежий signed `invoice_paid` для refunded deposit не меняет статус/баланс, а ручной `mark-paid` не может заново открыть возвращенный депозит.

### M-62. Maintenance cache lock падал в full-suite CI при смене event loop

Ссылки: `backend/app/maintenance.py:119-222`, regression `tests/integration/test_v5_c_bucket.py`.

Maintenance middleware держал module-level `_cache_lock = asyncio.Lock()`. В Python 3.12 lock лениво привязывается к event loop, когда на нём появляется waiter. Full-suite pytest/ASGI прогон переиспользует импортированный FastAPI app между тестами с разными event loops; после contention в одном loop следующий contended write-request в другом loop падал с `RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop`. Именно это сломало CI backend job на `test_concurrent_service_create_respects_active_limit`, хотя бизнес-логика теста была не связана с maintenance.

Риск: backend test suite становился nondeterministic/flaky, а в любых runtime-сценариях с несколькими event loops в одном процессе maintenance middleware мог выбросить 500 до route handler. Проблема особенно заметна на write endpoints, потому что read-only requests bypass-ят cache lookup.

Исправление: cache-refresh lock теперь создается через `_get_cache_lock()` как event-loop-local primitive. В обычном worker loop сериализация refresh сохраняется, а при смене loop создается новый `asyncio.Lock` вместо переиспользования несовместимого. Regression дважды запускает contended `_get_maintenance()` через два свежих `asyncio.run()` loop-а; старый module-level lock падал на втором запуске, новый проходит.

### M-63. Deal chat attachments принимали coerced ids вроде `true` и `"1"`

Ссылки: `backend/app/schemas.py:832-856`, regression `tests/unit/test_deal_message_schema.py`.

`DealMessageCreate.attachments` был объявлен как `list[int]` и проверял только длину списка. Pydantic до валидатора приводил JSON `true` к `1`, `false` к `0`, строку `"1"` к `1`, а также пропускал `0`/отрицательные числа до router-level lookup. В результате `POST /api/deals/{id}/messages` принимал неявные media ids: `attachments: [true]` мог превратиться в ссылку на media id `1`, если такая строка принадлежала отправителю.

Риск: attachment contract становился stringly/boolean tolerant там, где API должен принимать только явные положительные integer primary keys. Это не обходило owner/kind checks, но создавало неожиданные привязки файлов, лишние DB lookups для заведомо невалидных id и расхождение между create-path и `_parse_attachment_ids`, который уже отвергал bool при сериализации старых rows.

Исправление: `attachments` теперь проходит `mode="before"` validator: значение должно быть списком, каждый элемент должен быть именно `int` (не `bool`, не строка/float), а после этого ids должны быть положительными. Добавлен unit regression на accepted `[1, 42]` и rejected `[true]`, `[false]`, `["1"]`, `[1.0]`, `[0]`, `[-1]`.

### M-64. Admin review create/edit принимал coerced primary keys

Ссылки: `backend/app/schemas.py:1684-1715`, regression `tests/unit/test_admin_review_schema.py`.

`AdminReviewUpsertIn` объявлял `author_id`, `target_id` и `deal_id` как обычные `int | None`. До endpoint-логики Pydantic приводил JSON `true` к `1`, строку `"1"` к `1`, float `1.0` к `1`, а также пропускал `0` и отрицательные ids. На create это могло создать отзыв от имени/в адрес неявного пользователя id `1` или привязать отзыв к неявной сделке id `1`; `0`/отрицательные значения уходили дальше в DB lookup/FK-path вместо раннего contract rejection.

Риск: TOTP-защищенный admin endpoint оставался tolerant к boolean/stringly ids там, где операция пишет чужой пользовательский контент и должна принимать только явные положительные integer primary keys. Ошибка оператора или stale frontend payload могла превратиться в валидную запись не для того пользователя/сделки, а не в 422.

Исправление: `AdminReviewUpsertIn` теперь валидирует `author_id`, `target_id` и `deal_id` в `mode="before"`: допускается `None` для edit-пути, иначе значение должно быть именно `int` (без `bool`, строк и float) и `> 0`. Добавлены unit regressions на accepted positive ids, omitted ids for edit и rejected `[true]`, `[false]`, `"1"`, `1.0`, `0`, `-1` для каждого поля.

### M-65. Review create/admin rating принимали coerced числа вместо явных integer payloads

Ссылки: `backend/app/schemas.py:881-906`, `backend/app/schemas.py:1717-1733`, regressions `tests/unit/test_review_schema.py`, `tests/unit/test_admin_review_schema.py`.

После M-64 оставалась соседняя contract-hole: `ReviewCreate.rating`, `ReviewCreate.deal_id` и `AdminReviewUpsertIn.rating` были обычными `int`. Pydantic приводил `rating: true` к `1`, `rating: "5"` к `5`, `rating: 1.0` к `1`, а `deal_id: true` / `deal_id: "42"` к integer primary key. `ReviewCreate.deal_id=0` тоже проходил schema-слой и отсеивался только поздним `session.get(Deal, 0)`.

Риск: user-facing `POST /api/reviews` мог принять malformed JSON как реальный отзыв: boolean `true` становился 1-star rating, string/float значения проходили как числа, а coerced `deal_id` мог привязать отзыв к сделке id `1`/`42`. Admin review edit/create имел такой же rating coercion. Это ломало API contract и маскировало frontend/input bugs вместо раннего 422.

Исправление: `ReviewCreate` теперь до coercion требует `rating` как настоящий `int` в диапазоне 1..5, а `deal_id` как настоящий положительный `int`. `AdminReviewUpsertIn.rating` получил такой же strict integer gate перед range-check. Добавлены unit regressions на rejected `true`, `false`, строки, float и out-of-range значения; прямой schema smoke подтверждает, что malformed review payloads больше не принимаются.

### M-66. Service comment ratings принимали `true`, `"5"` и `1.0` как валидные оценки

Ссылки: `backend/app/schemas.py:608-631`, `backend/app/schemas.py:1764-1796`, regression `tests/unit/test_service_comment_schema.py`.

`ServiceCommentCreate.rating` и `AdminCommentUpdateIn.rating` оставались `int | None` с обычным range-check. Pydantic сначала приводил JSON `true` к `1`, строку `"5"` к `5` и float `1.0` к `1`, а уже затем валидатор проверял диапазон. Поэтому `POST /api/services/{id}/comments` и admin edit-comment могли записать malformed rating payload как настоящую оценку.

Риск: комментарии к услугам имели более слабый contract, чем свежезакрытые review endpoints: boolean `true` становился 1-star оценкой, string/float payloads проходили как числа, а frontend/input bugs маскировались вместо 422. Это влияло на `rating_avg` / `rating_count` услуги и admin audit payload для comment edit.

Исправление: оба schema-класса теперь валидируют `rating` в `mode="before"`: `None` разрешен как отсутствие/очистка оценки, иначе принимается только настоящий `int` (не `bool`, строка или float) с прежним диапазоном 1..5. Добавлен unit regression на user create и admin update paths.

### M-67. Admin deal actions принимали coerced `approval_id` / `arbiter_id`

Ссылки: `backend/app/schemas.py:1526-1599`, `backend/app/routers/admin/deals.py:981-1354`, regression `tests/unit/test_admin_deal_schema.py`.

Тела `force-release` / `force-refund` (`AdminDealForceOut`) и `assign-arbiter` (`AdminDealAssignArbiterIn`) объявляли ids как обычные `int | None`. Pydantic приводил `approval_id: true` к `1`, `approval_id: "1"` к `1`, `arbiter_id: true` к `1`, а также пропускал `0`/отрицательные ids до route/service lookup. `split` имел тот же `approval_id` contract gap при валидном `buyer_percent`.

Риск: TOTP-защищенные admin deal actions могли выполнять ручную операцию с неявно выбранной approval-заявкой id `1` или назначать арбитра id `1` из boolean/string payload. Даже когда такие значения дальше падали в 404, API contract оставался tolerant к malformed primary keys в денежных deal actions вместо раннего 422.

Исправление: добавлен общий helper strict optional positive int id. `AdminDealForceOut.approval_id`, `AdminDealSplitIn.approval_id`, `AdminDealAssignArbiterIn.arbiter_id` и ранее исправленный `AdminReviewUpsertIn` теперь требуют настоящий положительный `int` или `None`. Unit regression покрывает accepted positive/None и rejected `true`, `false`, `"1"`, `1.0`, `0`, `-1` для всех трех admin deal action ids.

### M-68. Admin counter/stat/settings integers принимали bool/string/float как числа

Ссылки: `backend/app/schemas.py:1298-1334`, `backend/app/schemas.py:1621-1688`, `backend/app/schemas.py:2051-2118`, regression `tests/unit/test_admin_counter_schema.py`.

Admin stats (`deals_total`, `good`, `bad` и соседние счетчики), admin service counters (`views`, `deals_count`) и integer settings (`max_active_services_per_user`, FAQ counters, inactivity/topup windows) были `int | None` с after-validator на неотрицательность. Pydantic до валидатора приводил `true` к `1`, `false` к `0`, строку `"5"` к `5` и float `1.0` к `1`.

Риск: операторская корректировка статистики/счетчиков и production settings принимали malformed JSON как реальные числовые значения. Особенно опасны `false -> 0` для лимитов/окон и `true -> 1` для публичных stats/FAQ counters: фронтендовая ошибка или ручной API-call мог тихо поменять бизнес-лимит вместо явного 422.

Исправление: добавлен общий helper strict optional non-negative int. `AdminSetStatsIn`, `AdminServiceUpdateIn` и integer-поля `AdminSettingsUpdateIn` теперь валидируются в `mode="before"`: разрешены только настоящий `int >= 0` или `None`; bool, строки и float отвергаются до coercion. Unit regression покрывает accepted explicit ints и rejected `true`, `false`, `"5"`, `1.0`, `-1` для всех затронутых полей.

### M-69. Boolean write-boundary fields принимали строки/числа как флаги

Ссылки: `backend/app/schemas.py:308-377`, `backend/app/schemas.py:516-526`, `backend/app/schemas.py:1307-1322`, `backend/app/schemas.py:1684-1755`, `backend/app/schemas.py:1833-1875`, `backend/app/schemas.py:2116-2215`, `backend/app/schemas.py:2289-2406`, `backend/app/schemas.py:2442-2557`, regression `tests/unit/test_strict_bool_schema.py`.

Несколько write-схем объявляли флаги как обычный `bool` / `bool | None`. Pydantic до валидаторов приводил JSON-строки и числа к boolean: `"true"` становился `True`, `"false"` становился `False`, `1` становился `True`, а `0` становился `False`. Затронуты user privacy/DM flags, admin role flags, `clear_rating`, production settings, active currency flag и broadcast dispatch flags.

Риск: malformed JSON или stale frontend payload мог тихо включить/выключить роль, режим обслуживания, auto-withdraw, FAQ badge, активность валюты, очистку рейтинга, способ доставки рассылки или приватность/DM-настройки пользователя вместо раннего 422. Для admin endpoints это особенно плохо: операторское действие выглядит успешным, хотя тело запроса не соответствует API contract.

Исправление: добавлены общие strict bool validators и `mode="before"` проверки на всех найденных boolean write-boundaries. Optional-флаги принимают только настоящий `bool` или `None`; non-optional флаги принимают только настоящий `bool`, а строки, числа и явный `null` отвергают до coercion. Unit regression покрывает accepted `true`/`false` как реальные bool и rejected `"true"`, `"false"`, `1`, `0`, плюс `None` для non-optional flags.

### M-70. Admin manual user rating принимал `true`, строки и `NaN` как рейтинг

Ссылки: `backend/app/schemas.py:528-536`, `backend/app/schemas.py:1335-1357`, regression `tests/unit/test_admin_rating_schema.py`.

`AdminSetRatingIn.rating` был объявлен как обычный `float | None` и проверял только диапазон `0..5` после Pydantic coercion. Поэтому `rating: true` превращался в `1.0`, строка `"4.2"` превращалась в число, а `NaN` проходил range-check, потому что сравнения `NaN < 0` и `NaN > 5` возвращают `False`.

Риск: TOTP-защищенный admin endpoint ручного рейтинга мог сохранить malformed payload как валидный override или попытаться записать non-finite значение в `User.rating_manual`. Это маскировало frontend/API ошибки и могло довести запрос до DB/serialization path с `NaN` вместо нормального 422 на границе схемы.

Исправление: добавлен strict finite-number helper. `AdminSetRatingIn.rating` теперь в `mode="before"` принимает только настоящий `int`/`float`/`Decimal` или `None`, отвергает `bool`, строки и non-finite значения, а затем применяет прежний диапазон `0..5` и округление до одного знака. Unit regression покрывает accepted `0`, `4.8`, `None` и rejected `true`, `false`, `"4.2"`, `"NaN"`, `NaN`, `Infinity`, `-1`, `6`.

### M-71. Admin currency `decimals` / `sort_order` принимали coerced integers

Ссылки: `backend/app/schemas.py:508-514`, `backend/app/schemas.py:2315-2403`, regression `tests/unit/test_admin_currency_schema.py`.

`AdminCurrencyUpsertIn.decimals` и `sort_order` были обычными `int | None`. Pydantic до validators приводил `true` к `1`, `false` к `0`, строки вроде `"8"` к `8`, а float `8.0` к `8`.

Риск: admin currency editor мог принять malformed payload как реальную настройку precision/sorting. Особенно опасны `false -> 0` для `decimals` и `true -> 1` для `sort_order`: ошибка формы или ручной API-call меняли денежное отображение/порядок валют вместо раннего 422.

Исправление: добавлен strict optional int helper. `decimals` и `sort_order` теперь валидируются в `mode="before"`: разрешены только настоящий `int` или `None`; bool, строки и float отвергаются до coercion. Regression покрывает accepted explicit ints/None и rejected coerced values.

### M-72. Admin currency `decimals` разрешал precision выше фактического `Numeric(28, 8)` scale

Ссылки: `backend/app/money.py:54-61`, `backend/app/schemas.py:13`, `backend/app/schemas.py:2398-2404`, regression `tests/unit/test_admin_currency_schema.py`.

Схема разрешала `decimals` до `18`, хотя все money columns проекта закреплены как `Numeric(28, 8)` и `MONEY_SCALE == 8`. При currency `decimals=9..18` UI/quantize layer обещал больше дробных знаков, чем БД может хранить без округления до 8 знаков.

Риск: админ мог создать валюту с заявленной precision выше storage contract, после чего deposits/deals/balances выглядели как поддерживающие 9-18 знаков, но persistence layer всё равно ограничивался 8. Это ломало денежный invariant и создавало silent precision loss для новых валют.

Исправление: `AdminCurrencyUpsertIn.decimals` теперь ограничен `0..MONEY_SCALE`, где `MONEY_SCALE` импортируется из `backend.app.money` как единый источник правды для `Numeric(28, 8)`. Regression отвергает `9`, прежнюю верхнюю границу `18` и `19`, сохраняя `8` валидным.

### M-73. Admin currency text fields не совпадали с DB/string contract

Ссылки: `backend/app/models.py:844-866`, `backend/app/schemas.py:2359-2387`, regression `tests/unit/test_admin_currency_schema.py`.

`AdminCurrencyUpsertIn.name`, `network` и `icon_url` почти не валидировались: пустой/whitespace `name` проходил, `name` длиннее `Currency.name String(64)` и `network` длиннее `String(32)` проходили до DB commit, а `icon_url` принимал non-https/empty-host формы.

Риск: admin upsert мог падать поздно на DB constraint/rollback вместо нормального 422, либо сохранять пустое название валюты и некорректную ссылку на иконку в публичный wallet/admin DTO. Это тот же класс schema-vs-model drift, который уже закрыт для category fields.

Исправление: `name` теперь trim + non-empty + `≤64`, `network` trim + `≤32` с возможностью очистки пустой строкой, `icon_url` принимает только пустое значение, `/media/...` или валидный `https://` URL через общий URL validator. Regression покрывает trim happy path и rejected empty/too-long/bad-url cases.

### M-74. `ServiceCreate` принимал пустые/слишком длинные title и пустой category slug

Ссылки: `backend/app/schemas.py:616-654`, `backend/app/routers/services.py:244-262`, `backend/app/models.py:358-382`, regression `tests/unit/test_service_schema.py`.

`ServiceCreate.category_slug` и `title` были обычными `str`: пустой title, whitespace-only title, title длиннее `Service.title String(256)` и пустой category slug проходили schema layer. Router потом вручную отклонял часть title cases через 400, а пустой/пробельный slug доходил до lookup категории и превращался в 404.

Риск: публичный create-service contract расходился с OpenAPI/schema boundary и модельным contract. Клиент видел, что payload валиден на уровне body schema, но фактически получал поздний 400/404, а слишком длинный title оставался защищен только ручной router-проверкой вместо единого 422 на входе.

Исправление: добавлены общие service validators. `category_slug` теперь trim + lower + non-empty + `<=64`, `title` trim + non-empty + `<=256`; `ServiceCreate` возвращает уже нормализованные значения, а regression покрывает happy path и rejected empty/too-long inputs.

### M-75. `ServiceUpdate.status` принимал admin-only/unknown statuses, а title валидировался только в router

Ссылки: `backend/app/schemas.py:657-683`, `backend/app/routers/services.py:460-526`, regression `tests/unit/test_service_schema.py`.

`ServiceUpdate.title` имел тот же schema gap, что create: пустая/слишком длинная строка проходила Pydantic и отклонялась только внутри route handler. `ServiceUpdate.status` был `str | None`, поэтому schema принимала `banned` и произвольные строки, хотя user-facing PATCH может менять только `draft`, `active`, `paused`; бан должен проходить через admin content endpoint с `ban_reason` и audit log.

Риск: user/admin PATCH endpoint имел OpenAPI contract шире фактического state machine. Особенно плохо для `banned`: payload проходил body parsing и только потом получал 400, хотя route сам документирует, что бан через этот endpoint запрещен из-за отсутствия `ban_reason`.

Исправление: `ServiceUpdate.title` использует общий title validator, а `status` теперь `Literal["draft", "active", "paused"] | None`. Admin-only `banned`, unknown statuses и padded variants получают ранний schema rejection; разрешенные public statuses и `None` сохранены.

### M-76. `ServiceModerationDecision.action` принимал любые строки

Ссылки: `backend/app/schemas.py:686-693`, `backend/app/routers/services.py:638-667`, regression `tests/unit/test_service_schema.py`.

Admin moderation body объявлял `action: str`, хотя router поддерживает только `ban` и `unban`. Любая другая строка проходила schema/OpenAPI и падала поздно в route handler через ручной `else`.

Риск: TOTP-protected moderation endpoint принимал malformed action payload на уровне API body contract. Это не давало выполнить неизвестное действие, но оставляло слабый contract для админского клиента и маскировало frontend/API ошибки до route branch вместо раннего 422.

Исправление: `action` переведен на `Literal["ban", "unban"]`, а `reason` получил тот же `MAX_DESCRIPTION_LEN` guard, что service/deal descriptions. Regression покрывает accepted `ban`/`unban`, rejected unknown actions и лимит причины.

### M-77. Admin broadcast audience-фильтры принимали bool/string/float как integers

Ссылки: `backend/app/schemas.py:2592-2666`, `backend/app/routers/admin/broadcasts.py:65-96`, regression `tests/unit/test_admin_broadcast_schema.py`.

`AdminBroadcastCreateIn.audience_active_days` и `audience_min_deals` были `int | None` с after-validator на неотрицательность. Pydantic до validator приводил `true` к `1`, строку `"5"` к `5` и `5.0` к `5`.

Риск: TOTP-protected broadcast preview/send мог тихо поменять аудиторию рассылки из malformed payload. `true -> 1` для active-days сужал аудиторию до пользователей за 1 день, а строковые/float значения маскировали frontend/API баги вместо раннего 422.

Исправление: audience integer fields теперь валидируются в `mode="before"` через strict optional non-negative int helper. Разрешены только настоящий `int >= 0` или `None`; bool, строки, float и отрицательные значения отвергаются. Regression покрывает оба поля.

### M-78. Arbitration resolve `winner` был свободной строкой в OpenAPI/schema

Ссылки: `backend/app/schemas.py:904-910`, `backend/app/routers/deals.py:474-485`, regression `tests/unit/test_audit_v3_m5_deal_amount.py`.

`DealResolveRequest.winner` был объявлен как `str` и отсеивал неизвестные значения только ручным validator. Роутер и service реально поддерживают только `buyer` и `seller`, но OpenAPI говорил клиентам, что допустима любая строка.

Риск: arbitration UI/API contract был шире фактической state-machine: malformed `winner` проходил body schema и падал поздно, а сгенерированные frontend-типы не фиксировали закрытый набор решений.

Исправление: `winner` переведен на `Literal["buyer", "seller"]`. OpenAPI/types теперь показывают закрытый enum, а regression покрывает accepted `buyer`/`seller` и rejected unknown/padded values.

### M-79. Deal/review username refs принимали пустые, пробельные и невалидные строки

Ссылки: `backend/app/schemas.py:454-538`, `backend/app/schemas.py:786-824`, `backend/app/schemas.py:1022-1061`, `backend/app/routers/deals.py:300-348`, `backend/app/routers/reviews.py:84-100`, regression `tests/unit/test_audit_v3_m5_deal_amount.py`, `tests/unit/test_review_schema.py`.

`DealCreate.counterparty` и `ReviewCreate.target_username` были обычными строками. Пустые/whitespace значения, `@`, пробелы внутри, unicode/invalid символы и строки длиннее `User.username String(64)` доходили до DB lookup и превращались в поздний 404. При этом frontend picker уже нормализует leading `@`, а direct API callers не получали такого же schema contract.

Риск: публичные money/review write endpoints принимали невалидные ссылки на пользователя на уровне body schema. Это не давало найти другого пользователя, но делало API contract слабым и превращало input bugs в 404 вместо раннего 422; слишком длинные значения также расходились с модельной длиной username.

Исправление: добавлен общий username-ref validator: trim, снятие leading `@`, non-empty, ASCII `[A-Za-z0-9_-]`, `<=64`. `DealCreate` и `ReviewCreate` теперь получают нормализованный bare username до router lookup. Regression покрывает happy normalization и rejected invalid refs.

### M-80. Deal/wallet currency codes не нормализовались на schema boundary

Ссылки: `backend/app/schemas.py:454-538`, `backend/app/schemas.py:786-824`, `backend/app/schemas.py:1160-1233`, `backend/app/services_wallet.py:212-218`, regression `tests/unit/test_audit_v3_m5_deal_amount.py`, `tests/unit/test_wallet_schema.py`.

`DealCreate.currency_code`, `WalletDepositCreateReq.currency_code` и `WalletWithdrawCreateReq.currency_code` были обычными строками. `get_currency_by_code()` делал `upper()`, но не `strip()`, поэтому `" usdt "` доходил до 404; пустые, whitespace, unicode, пробелы/дефисы и строки длиннее `Currency.code String(16)` тоже проходили schema layer.

Риск: money-moving user endpoints имели слабый code contract и зависели от позднего lookup/service behavior. Stale UI или manual API-call мог получить 404 на фактически валидную валюту с пробелами либо протащить явно malformed code до service layer вместо 422.

Исправление: добавлен общий currency-code validator: trim + uppercase + non-empty + ASCII alnum + `<=16`. Deal create, wallet deposit и wallet withdrawal теперь передают в сервисы нормализованный код. Regression покрывает normalization и rejected invalid values.

### M-81. Admin 2FA secret принимал не-base32 значения и мог падать в verifier

Ссылки: `backend/app/schemas.py:533-573`, `backend/app/schemas.py:2797-2848`, `backend/app/auth_2fa.py:138-160`, regression `tests/unit/test_admin_twofa_schema.py`.

`Admin2faConfirmIn.secret` проверял только trim и длину `16..64`. Строки из не-base32 символов проходили body schema; на rotation path такой secret доходил до `verify_totp_and_counter()`, где `base64.b32decode()` выбрасывал исключение вместо нормального invalid-code результата. Такой же late-crash был возможен при поврежденном `users.totp_secret` в БД.

Риск: TOTP-protected 2FA rotation/session path мог превращать malformed secret в 500 вместо раннего 422/401. Это слабый admin API contract и потенциальный operational foot-gun: одна поврежденная persisted secret строка ломала все проверки для аккаунта через exception path.

Исправление: добавлен общий TOTP-secret validator: trim, uppercase, удаление пробелов, alphabet `[A-Z2-7]`, длина `16..64` и пробный padded base32 decode. `verify_totp_and_counter()` теперь fail-closed возвращает `None` для invalid stored secret вместо исключения. Regression покрывает schema rejection, normalization и verifier fallback.

### M-82. Admin 2FA UI/schema принимали 8-значные коды, хотя backend TOTP использует 6 цифр

Ссылки: `backend/app/auth_2fa.py:81-114`, `backend/app/schemas.py:2797-2848`, `frontend/src/components/TotpGate.tsx`, `frontend/src/pages/admin/AdminTwoFactorPage.tsx`, regressions `tests/unit/test_admin_twofa_schema.py`, `frontend/src/components/TotpGate.test.tsx`, `frontend/src/pages/admin/AdminTwoFactorPage.test.tsx`.

`Admin2faConfirmIn.code/current_code` и `Admin2faVerifyIn.code` разрешали длину 6 или 8, а `TotpGate` тоже принимал pattern `[0-9]{6,8}`. Но `auth_2fa` генерирует `otpauth://...&digits=6`, `_DIGITS = 6`, а `verify_totp_and_counter()` отвергает любую длину кроме 6. В `/admin/2fa` инпуты дополнительно не чистили пробелы, хотя placeholder показывал `123 456`.

Риск: OpenAPI/frontend contract обещал пользователю/API caller 8-значные коды, которые фактически всегда падали как invalid TOTP. Это маскировало клиентские ошибки и ухудшало UX при ручном вводе кода с пробелом из placeholder.

Исправление: TOTP code schema теперь `^\d{6}$` с before-validator trim и strict string check; 8-значные, пробельные внутри, alpha и numeric JSON payloads получают schema rejection. Frontend gate и admin 2FA page ограничены 6 цифрами, а setup/disable inputs чистят нецифровой ввод и режут значение до 6 цифр.

### M-83. Admin deal filters принимали malformed query params до SQL слоя

Ссылки: `backend/app/routers/admin/deals.py:588-668`, `backend/app/schemas.py:463-568`, generated OpenAPI/types, regression `tests/unit/test_query_filter_contracts.py`.

`GET /api/admin/deals` объявлял `status` как свободную строку, `currency` как обычный `str`, суммы как `float`, а `buyer_id`/`seller_id` без `ge=1`. В результате OpenAPI обещал слишком широкий contract: `status=bogus` документировался как валидная строка, `currency=" USDT "` доходила до lookup как другой код, malformed currency codes проходили query parsing, а `min_amount=NaN|Infinity` и `buyer_id=0` могли попасть в фильтры и возвращать пустые/непредсказуемые результаты вместо раннего 422.

Риск: admin UI/deep-link/API caller мог получать late 400/404 или silent-empty pages на технически malformed фильтрах. Для money/admin history это плохо: оператор видит пустой список и может принять его за реальное отсутствие сделок, а generated clients не видят закрытые enums/bounds.

Исправление: deal status filter переведён на закрытый `Literal` без deprecated `pending_payment`, currency query использует общий `CurrencyCodeStr` (trim + uppercase + ASCII alnum + `<=16`, pattern в OpenAPI), суммы стали `Decimal` query params с `ge=0` и finite-number rejection, `buyer_id`/`seller_id`/approval `target_id` получили `ge=1`, а `min_amount > max_amount` возвращает 422. OpenAPI и frontend generated types перегенерированы.

### M-84. Wallet/admin deposit/withdrawal history filters расходились с enum/currency contract

Ссылки: `backend/app/routers/admin/deposits.py:77-100`, `backend/app/routers/admin/withdrawals.py:91-107`, `backend/app/routers/wallet.py:194-287`, `backend/app/schemas.py:463-568`, generated OpenAPI/types, regression `tests/unit/test_query_filter_contracts.py`.

Admin deposit/withdrawal list endpoints принимали `status` как `str | None` и валидировали enum вручную внутри handler. User wallet history и admin deposits принимали `currency` как обычную строку и делали только `.upper()`. Поэтому OpenAPI не показывал допустимые статусные значения для админских очередей, а currency query params не имели того же trim/ASCII/length contract, который уже был добавлен для money-moving body schemas.

Риск: stale frontend/deep-link мог отправить `status=paid `, неизвестный статус или пробельную валюту и получить late error/silent-empty result вместо одинакового query-level 422. Generated API types оставались с `string`, то есть не помогали frontend поймать неверный статус очереди до запроса.

Исправление: admin deposit status теперь `WalletDepositStatus | None`, withdrawal status - `WalletWithdrawStatus | None`, а wallet/admin currency history filters используют `CurrencyCodeStr`. OpenAPI теперь содержит enum schemas для очередей и currency pattern/bounds для history filters.

### M-85. Public user search top filters were UI-only

Ссылки: `frontend/src/pages/search/SearchPage.tsx:32-41`, `backend/app/routers/users.py:136-154`, regression `tests/integration/test_users_filters.py`.

SearchPage отправляла верхние фильтры `with_deposit` и `top_rating`, но backend обрабатывал только `arbiters` и `admins`. В итоге deep-link или обычный клик по вкладкам выглядел успешным, но `with_deposit` возвращал общий каталог, а `top_rating` оставлял сортировку по `deals_total`/relevance.

Риск: пользователь видел silently-wrong выдачу и мог принимать обычных пользователей за участников с trust deposit или считать список отсортированным по рейтингу. Это особенно плохо для поиска контрагента: UI обещал важный trust/rating критерий, а API его игнорировал.

Исправление: `/api/users?filter=with_deposit` теперь фильтрует `User.trust_deposit_balance > 0`, а `filter=top_rating` сортирует по вычисленному рейтингу `5 * good / (good + bad)` с deterministic tie-breakers. Добавлены integration tests на оба режима.

### M-86. `/api/users` filter query contract был слишком широким

Ссылки: `backend/app/routers/users.py:44-88`, `frontend/src/api/hooks.ts:316-326`, `frontend/src/components/domain/SearchFilterSheet.tsx:21-57`, generated OpenAPI/types, regression `tests/integration/test_users_filters.py`, `frontend/src/pages/search/SearchPage.test.tsx`.

Public users endpoint принимал `filter`/`rating`/`deals`/`status`/registration dates как свободные строки и валидировал часть значений поздно внутри handler. OpenAPI поэтому документировал слишком широкий contract, frontend types тоже были `string`, а retired moderator tier `status=4` всё ещё предлагался в filter sheet, хотя backend уже не поддерживал роль.

Риск: stale UI/deep-link/API caller мог получить inconsistent 400 или silent-empty result вместо query-level 422, а generated clients не ловили неверные buckets до запроса. Retired moderator option в UI провоцировал гарантированно невалидный фильтр.

Исправление: query params переведены на закрытые `Literal` unions и `date` parsing на FastAPI boundary; reversed registration range возвращает 422. Frontend `UsersQueryParams`/filter controls используют те же unions, moderator option удалён, OpenAPI/types регенерируются, а invalid bucket/status/date сценарии покрыты regression tests.

### M-87. Notification list query contract был слишком мягким

Ссылки: `backend/app/routers/notifications.py:23-68`, `backend/app/schemas.py:1131-1151`, `frontend/src/api/hooks.ts:624-638`, generated OpenAPI/types, regression `tests/integration/test_notification_pagination.py`.

`GET /api/notifications` принимал `type` как свободную строку и неизвестный тип молча превращал в отсутствие фильтра. Cursor timestamp тоже парсился вручную как строка и возвращал late 400, а OpenAPI не показывал закрытый notification type enum и `date-time` формат cursor-а. `NotificationOut.type` был `string`, поэтому generated/manual frontend types не защищали consumers от несуществующих buckets.

Риск: stale client или deep-link с `type=security` мог показать весь inbox вместо ожидаемого пустого/ошибочного результата; malformed cursor мог скрывать баг пагинации за inconsistent 400. Для уведомлений это особенно неприятно: пользователь думает, что смотрит только сделки/депозиты, но видит системные события тоже.

Исправление: `type` переведён на `NotificationType` enum query, `before_created_at` - на FastAPI `datetime`, half-cursor и malformed values теперь 422 на boundary. Aware cursor timestamps нормализуются к naive UTC для DB column, `NotificationOut.type` стал закрытым enum, OpenAPI/types регенерированы, frontend query/manual DTO types используют тот же union.

### M-88. Admin audit filters принимали невозможные ids/ranges

Ссылки: `backend/app/routers/admin/audit.py:23-72`, `frontend/src/pages/admin/AdminAuditPage.tsx:12-27`, `frontend/src/api/admin/hooks.ts:951-972`, generated OpenAPI/types, regression `tests/integration/test_admin_misc.py`, `frontend/src/pages/admin/AdminAuditPage.test.tsx`.

`GET /api/admin/audit` принимал `actor_id=0`, `target_id=0`, arbitrary whitespace-bearing action/target filters и reversed `since`/`until` ranges. Frontend actor filter также отправлял `NaN`/`0`, если оператор вводил нечисловое или нулевое значение, потому что `Number(actorId)` вызывался без positive-int guard.

Риск: audit viewer мог отдавать silent-empty страницы для невозможных фильтров, а generated clients не видели bounds/patterns. Для админского расследования empty result должен означать отсутствие событий, а не технически malformed query.

Исправление: audit query params получили `ge=1` для ids, bounded ASCII patterns для `action`/`target_type`, 422 для `since > until`; frontend actor filter теперь отправляет только safe positive integers. Hook/query-key types расширены под `since`/`until`, OpenAPI/types регенерированы, backend/frontend regression tests добавлены.

### M-89. Admin broadcast composer мог silently drop numeric audience filters

Ссылки: `frontend/src/pages/admin/AdminBroadcastsPage.tsx:165-225`, `backend/app/schemas.py:2655-2721`, generated OpenAPI/types, regression `frontend/src/pages/admin/AdminBroadcastsPage.test.tsx`.

Composer брал `audience_active_days` и `audience_min_deals` через `Number(raw)`. Если оператор вводил `1.5`, `abc` или слишком большое значение, frontend строил `NaN`; `JSON.stringify` превращает `NaN` в `null`, и backend видел фильтр как отсутствующий. То есть предпросмотр/отправка могли уйти на более широкую аудиторию, чем оператор ожидал.

Риск: рассылка с malformed numeric cohort могла быть отправлена всем matching по остальным фильтрам пользователям вместо нужного среза. Для broadcast это не просто cosmetic bug: ошибка в фильтре меняет реальную аудиторию уведомления.

Исправление: frontend валидирует optional non-negative integer strings до preview/send, показывает inline error и блокирует обе primary actions при invalid input. Валидные значения уходят как safe integers. Backend schema теперь также отражает `ge=0` в OpenAPI для этих полей.

### M-90. Admin deals URL filters могли отправлять NaN/retired status в API

Ссылки: `frontend/src/pages/admin/AdminDealsPage.tsx:46-124`, `frontend/src/api/types.ts:545-556`, regression `frontend/src/pages/admin/AdminDealsPage.test.tsx`.

Admin deals page напрямую парсил `status`, `currency`, `min_amount`, `max_amount` и `page` из URL. Deep-link вроде `?status=pending_payment&min_amount=NaN&page=-5` доходил до `useAdminDeals` как deprecated status, `NaN` amount и отрицательная page; hook затем сериализовал это в query string и backend возвращал 422/пустое состояние вместо стабильной страницы.

Риск: dashboard/deep-link с устаревшим или повреждённым URL ломал админский список сделок. Оператор видел не нормальную первую страницу с очищенными фильтрами, а ошибочный запрос; active chips тоже могли показывать технический `NaN` как будто это реальный фильтр.

Исправление: URL params теперь проходят allow-list для filterable statuses, currency pattern, non-negative decimal parsing и positive page parsing; malformed numbers удаляются при update/apply. `AdminListDealsQuery.status` сужен до filterable statuses без deprecated `pending_payment`.

### M-91. Detail routes принимали ambiguous numeric ids через `Number(id)`

Ссылки: `frontend/src/pages/deals/DealDetailPage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/api/hooks.ts`, `frontend/src/api/admin/hooks.ts`, regression `frontend/src/lib/routeParams.test.ts`, `frontend/src/pages/deals/DealDetailPage.test.tsx`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.test.tsx`.

Route params detail-экранов парсились через `Number(id)`. JavaScript принимает `1e2`, `0x5`, decimal fractions, `Infinity` и пробельные формы не так, как path-инт backend. Часть хуков дополнительно считала `0`/unsafe integers допустимыми, а публичные detail pages при invalid/not-found состоянии могли бесконечно показывать skeleton.

Риск: поврежденная или злонамеренная deep-link ссылка могла открыть другой объект (`/admin/users/0x5` -> user 5, `/deals/1e2` -> deal 100) либо отправить запрос с невозможным id. Для admin detail/action pages это особенно опасно: оператор мог работать не с тем объектом, который указан в URL.

Исправление: добавлен общий parser canonical positive decimal safe-int route params. Public/admin deal, service, notification и user detail pages используют его вместо `Number(id)`, а data hooks включаются только для positive safe integers. Invalid/not-found public detail states теперь показывают явный empty state вместо вечного skeleton. Regression покрывает `1e2`, `0x*`, `0`, non-numeric и happy canonical ids.

### M-92. Notification detail строил deal CTA из ambiguous `deal_id`

Ссылки: `frontend/src/pages/notifications/NotificationDetailPage.tsx`, `frontend/src/lib/routeParams.ts`, regression `frontend/src/pages/notifications/NotificationDetailPage.test.tsx`.

Notification detail вычислял `dealRef` через `Number(payload.deal_id)` и `Number(match[1])`. Payload вроде `{deal_id: "0x2"}` превращался в deal 2, а body-reference `#0` считался валидной ссылкой-кандидатом.

Риск: испорченное уведомление или stale producer мог показать CTA на неправильную сделку. Пользователь кликает trusted notification UI, но переходит не на тот объект.

Исправление: notification payload/body refs используют тот же positive safe-int parser; ambiguous string ids, ноль и unsafe integers отбрасываются. Regression проверяет отсутствие CTA для `deal_id="0x2"` и `#0`, а unread notification still marks read on successful load.

### M-93. Admin wallet forms принимали hex/exponent finance values через `Number()`

Ссылки: `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/admin/AdminWalletsPage.test.tsx`, `frontend/src/lib/formNumbers.test.ts`.

Admin wallet USD-rate и manual adjustment формы использовали `Number(value)`. Поэтому `0x10` превращался в 16, `1e2` превращался в 100, а `Infinity`/слишком большие значения могли стать non-finite number, который `JSON.stringify` сериализует как `null`.

Риск: админ мог сохранить курс или корректировку баланса не тем числом, которое буквально ввёл, либо получить поздний 422/null-body вместо понятной UI-валидации. На финансовой форме это опасно: `0x10` визуально не выглядит как `16`, но старый код отправлял именно 16.

Исправление: добавлен общий parser plain decimal form inputs без hex/exponent/non-finite/unsafe значений. Wallet rate принимает только positive decimal, wallet adjustment - signed non-zero decimal. Invalid values подсвечиваются inline, submit блокируется, а mutation получает уже распарсенное canonical number. Regression покрывает `0x10`, `1e2` и happy decimal save.

### M-94. Admin currency numeric fields могли silently drop/default malformed values

Ссылки: `frontend/src/pages/admin/AdminTaxonomyPage.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/admin/AdminTaxonomyPage.test.tsx`, `frontend/src/lib/formNumbers.test.ts`.

Currency editor отправлял `decimals`, `min_deposit` и `min_withdraw` через `Number(...)`. `Number("")` превращал очищенное поле в 0, `Number("1e2")` принимал exponent notation, а `Number("abc")` становился `NaN` и уходил в JSON как `null`. Backend для nullable upsert fields трактует `null` как default/no-op, поэтому часть ошибок формы silently меняла смысл операции.

Риск: админ мог случайно сохранить decimals/min limits в другое значение или не изменить поле вообще, не понимая почему. Для справочника валют это влияет на округление и минимальные суммы депозитов/выводов.

Исправление: currency editor теперь использует plain decimal/int parsers: `decimals` строго integer `0..8`, min deposit/withdraw - non-negative decimal без exponent/hex. Пустой/invalid input блокирует submit и показывает inline error; valid save отправляет trimmed code/name/network и parsed numeric values.

### M-95. User service/deal amount forms могли принимать exponent или строить inconsistent money UI

Ссылки: `frontend/src/pages/profile/AddServicePage.tsx`, `frontend/src/pages/deals/CreateDealPage.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/profile/AddServicePage.test.tsx`, `frontend/src/pages/deals/CreateDealPage.test.tsx`, `frontend/src/lib/formNumbers.test.ts`.

Add service отправлял цену через `parseFloat(price) || 0`. Поэтому `1e2` принимался как 100, а malformed non-empty ввод в некоторых браузерных/программных состояниях мог превращаться в 0 вместо явной ошибки. Create deal уже имел regex на submit, но preview суммы и проверка invoice total использовали `parseFloat`, из-за чего UI мог считать exponent/prefix-like значение положительной суммой не тем же правилом, которым форма разрешала отправку.

Риск: пользователь или оператор видел/отправлял сумму не в той форме, которую буквально ввёл; для сервисной цены это могло создать услугу с unexpected price, а для сделки - рассинхронизировать commission/invoice preview и submit validation. В денежных сценариях разное правило parsing-а между preview, submit и invoice UI быстро становится источником ошибок поддержки.

Исправление: add-service price, create-deal amount preview/validation и invoice-positive check теперь используют общий plain decimal parser без exponent/hex/non-finite/unsafe значений. Invalid price подсвечивается inline и блокирует create-service mutation; invalid deal amount не открывает PIN prompt. Regression покрывает exponent inputs и happy decimal save.

### M-96. Admin content forms принимали exponent/fraction ratings через `Number()`

Ссылки: `frontend/src/pages/admin/UserContentSections.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/admin/UserContentSections.test.tsx`, `frontend/src/lib/formNumbers.test.ts`.

Admin user content sheets парсили service price/deposit/views/deals_count/rating_manual, review rating и comment rating через `Number(...)`. Это принимало `1e2`/`0x10`, а для review/comment rating также пропускало дробные значения вроде `1.5`, хотя backend contract для этих рейтингов - integer `1..5`. `NaN` в JSON дополнительно превращался в `null`, что давало поздний 422 или неочевидное изменение payload.

Риск: админ мог сохранить неканоническое или wrong-scale значение в контентной форме, особенно для strict-int рейтингов и счетчиков. Для moderation/admin tooling это опасно тем, что UI выглядел как обычное числовое поле, но отправлял значение с JavaScript-specific parsing semantics.

Исправление: content editor теперь использует shared plain decimal/int parsers. Service numeric fields блокируют invalid submit и показывают inline errors; review/comment ratings требуют strict integer `1..5`; manual service rating остаётся decimal `0..5`, но без exponent/hex. Regression покрывает exponent service fields, fractional/exponent review/comment ratings и прежний zero-rating guard.

### M-97. Admin user detail forms принимали exponent/hex и дробили strict-int stats

Ссылки: `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/admin/AdminUserDetailPage.numbers.test.tsx`.

Admin user detail парсил manual rating, profile stats, trust deposit и per-user balance adjustment через `Number(...)` или `Number(raw.replace(",", "."))`. Поэтому `1e2` принимался как 100, `0x10` в части полей мог стать 16, а strict-int stats вроде `deals_total` пропускали `1.9` через `Math.trunc` и silently сохраняли 1.

Риск: оператор мог изменить рейтинг, счетчики, trust deposit или ручную корректировку баланса не тем числом, которое буквально ввёл. Для stats это особенно неприятно: дробная ошибка ввода превращалась в валидный integer без подтверждения, а для balance/trust flows exponent notation меняла денежное значение.

Исправление: admin user detail теперь использует shared plain decimal/int parsers. Rating override допускает только plain decimal `0..5`, stats counters требуют non-negative integer без truncation, trust deposit - non-negative decimal, per-user balance adjustment - positive decimal; invalid adjustment также отключает кнопки. Regression покрывает exponent rating/stats/trust/balance, fractional stats и happy `.5` balance adjustment.

### M-98. Admin deal action sheet принимал ambiguous approval/split numbers

Ссылки: `frontend/src/pages/admin/AdminDealDetailPage.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`.

Deal action sheet парсил `approval_id` и `buyer_percent` через `Number(...)`. Typed `approval_id="0x10"` превращался в 16, а `buyer_percent="1e2"` проходил как 100. Backend schema уже стала строже, но frontend всё ещё мог отправлять surprising values и получать late 422/approval mismatch вместо локальной ошибки.

Риск: force-release/refund/split мог ссылаться на не тот approval id, а split percent мог сохранить exponent-form значение без явной UI-валидации. Это админские money-moving actions, поэтому frontend должен блокировать ambiguous numeric syntax до mutation.

Исправление: approval id теперь strict positive integer, split buyer percent - plain decimal `0..100`; invalid значения подсвечиваются inline и блокируют mutation с явным toast. Regression покрывает `0x10` approval id и `1e2` split percent.

### M-99. Admin users list принимал invalid `page` из URL

Ссылки: `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/lib/routeParams.ts`, regression `frontend/src/pages/admin/AdminUsersPage.test.tsx`.

Admin users list строил `page` через `Number(searchParams.get("page") ?? "1") || 1`. В отличие от уже hardened detail routes, deep-link `?page=-5`, `?page=1e2` или `?page=0x10` доходил до `useAdminUsers` как отрицательная/ambiguous страница.

Риск: повреждённая ссылка могла отправить админский список на неверную страницу или в backend 422/пустое состояние вместо стабильной первой страницы. Для URL-driven dashboard filters это тот же класс дефекта, что ранее закрывался в admin deals filters.

Исправление: `page` теперь проходит canonical positive safe-int parser; malformed/ambiguous values fallback-ятся к page 1. Regression покрывает negative, exponent и hex page params.

### M-100. Admin settings form принимал ambiguous/bounds-breaking numeric values

Ссылки: `frontend/src/pages/admin/AdminSettingsPage.tsx`, `frontend/src/lib/formNumbers.ts`, regression `frontend/src/pages/admin/AdminSettingsPage.test.tsx`, `frontend/src/lib/formNumbers.test.ts`.

Admin settings использовал общий `Number(e.target.value)` для всех числовых полей. Из-за этого `1e2` и `0x10` становились обычными числами, пустая строка могла стать `0`, дробные значения проходили в integer-настройки, а комиссии и цены уходили в API без frontend range/type guard. Эти поля управляют комиссиями, таймингами, лимитами, FAQ-статистикой и ценой PIN reset, поэтому поздний 422 или неожиданная конвертация в admin tool здесь не просто косметика.

Риск: оператор мог сохранить не то значение, которое буквально ввел, либо получить позднюю backend-ошибку уже после нажатия save. Для integer-настроек это также ломало контракт backend schema: UI выглядел как обычное numeric поле, но мог отправить `1.5`.

Исправление: settings page теперь использует shared plain-decimal/int parsers: counters/timings/limits требуют non-negative integer, обычная комиссия - decimal `0..100`, VIP комиссия - decimal `-1..100`, money/stat price fields - non-negative decimal. Ambiguous syntax и wrong-type input не dirty-ят форму и не уходят в mutation. Добавлен signed decimal parser для форм, где ноль и отрицательный sentinel допустимы.

### M-101. Admin deals page все еще принимал exponent/hex `page` после URL-filter hardening

Ссылки: `frontend/src/pages/admin/AdminDealsPage.tsx`, `frontend/src/lib/routeParams.ts`, regression `frontend/src/pages/admin/AdminDealsPage.test.tsx`.

M-90 закрыл большую часть malformed URL filters на deals list, но `page` оставался на `Number(value)`. Поэтому `?page=1e2` превращался в page 100, а `?page=0x10` - в page 16. Для остальных route ids уже был canonical positive safe-int parser, но эта страница еще не использовала его.

Риск: dashboard/deep-link мог отправить админский список сделок на неожиданную страницу без явной ошибки. Это создавало тот же класс проблем, что и предыдущие route-id fixes: URL выглядит неканонично, а UI/API работают с другим числом.

Исправление: `page` в admin deals list теперь парсится через `parsePositiveIntRouteParam`; exponent/hex/negative/zero values fallback-ятся к page 1. Regression заменяет старый negative-only сценарий на exponent case, который раньше проходил.

### M-102. `pin_reset_price_usd` backend schema пропускала non-finite Decimal

Ссылки: `backend/app/schemas.py`, regression `tests/unit/test_admin_settings_schema.py`.

Большинство money settings уже использовали `_reject_non_finite_money`, но `pin_reset_price_usd` вручную делал `Decimal(str(v))` и проверял только `< 0`. `Decimal("Infinity")` проходил как валидная цена, а `Decimal("NaN")` мог провалиться через decimal comparison path вместо нормальной Pydantic validation error.

Риск: non-finite price мог дойти до ORM/DB или audit payload и сломать сохранение настроек неочевидной ошибкой. Для публичной цены PIN reset это особенно неприятно: значение читается пользователями до payment flow.

Исправление: `pin_reset_price_usd` теперь использует общий finite money guard и затем прежнюю non-negative check. Unit regression покрывает `Infinity` и `NaN`.

### M-103. Frontend display decimal helper принимал exponent/hex строки как деньги

Ссылки: `frontend/src/lib/format.ts`, regression `frontend/src/lib/format.test.ts`.

Общий `parseDecimal()` использовался в wallet/admin/deal display paths и non-zero decisions, но строковые значения парсил через `Number(value)`. Поэтому corrupt wire/display value вроде `1e2` или `0x10` превращался в 100/16 вместо malformed fallback. Для display-only helper это не money-moving mutation, но он влияет на wallet balances, admin wallets, deal rows и invoice snippets, где оператор принимает решения по видимым числам.

Риск: поврежденный backend/mock/provider payload мог выглядеть как валидная сумма другого масштаба. Особенно неприятно в местах, где `parseDecimal(...) > 0` решает, показывать ли баланс/оплаченную часть.

Исправление: string branch теперь принимает только plain signed decimal без exponent/hex/non-finite tokens. JSON numbers остаются валидными, если они finite; malformed strings fallback-ятся в `0` как и раньше. Regression покрывает signed decimal и `1e2`/`0x10`/`Infinity`.

### M-104. Deal topup invoice показывал currency на metadata rows и ambiguous paid total

Ссылки: `frontend/src/pages/deals/DealDetailPage.tsx`, regression `frontend/src/pages/deals/DealDetailPage.test.tsx`.

`TopupInvoiceRow` всегда дописывал `currency`, поэтому provider row выглядел как `CryptoBot USD`, а expiry row как дата с валютой. В той же секции `paid_total` проверялся через `Number(paid_total) > 0`, так что `paid_total="0x10"` открывал строку `Уже оплачено: 0x10 USD`.

Риск: invoice card смешивал metadata и money rows, а malformed partial payment мог отображаться как валидная оплаченная часть. Это сбивает покупателя/оператора в pending-topup сценарии.

Исправление: currency у `TopupInvoiceRow` теперь optional; provider/expiry rows не получают валюту, money rows получают. `paid_total` gate использует hardened `parseDecimal()`, поэтому ambiguous strings не показываются.

### M-105. Profile rating display мог коэрсить malformed runtime value

Ссылки: `frontend/src/components/domain/ProfileStatsGrid.tsx`, regression `frontend/src/components/domain/ProfileStatsGrid.test.tsx`.

Profile stats grid делал `Number(user.rating) || 0`. Если runtime payload приходил строкой `0x5`/`1e1` или non-finite number, UI мог показать валидно выглядящий рейтинг либо замаскировать corruption как `0.0` при наличии reviews.

Риск: рейтинг - доверительный сигнал профиля. Даже если backend обычно держит контракт, frontend не должен превращать неканоничный payload в убедительный score.

Исправление: rating display теперь принимает только finite number или plain decimal string в диапазоне `0..5`; malformed/out-of-range values показывают empty rating state. Regression закрепляет `"0x5"`.

### M-106. Retry-After и banner zoom оставались на prefix/exponent parsing

Ссылки: `frontend/src/api/client.ts`, `frontend/src/components/BannerCropModal.tsx`, regressions `frontend/src/api/client.test.ts`, `frontend/src/components/BannerCropModal.test.tsx`.

Rate-limit toast парсил `Retry-After` через `parseFloat`, поэтому header `1abc` превращался в 1 second вместо malformed fallback. Crop zoom slider тоже использовал `parseFloat`, из-за чего synthetic/programmatic `1e2` мог поставить zoom вне ожидаемого диапазона до следующей нормализации cropper-а.

Риск: это не core business mutation, но оба места являются user-facing recovery controls. Rate-limit UI мог обещать неверное время повтора, а crop modal мог получить invalid/oversized zoom state при нестандартном event payload.

Исправление: `Retry-After` теперь принимает strict integer seconds или HTTP-date, иначе fallback toast остается 5 seconds. Banner zoom принимает only plain decimals, clamps to `1..3`, and keeps current zoom for malformed values.

### M-107. Service photo URL schema все еще полагалась на prefix-only URL check

Ссылки: `backend/app/schemas.py`, regression `tests/unit/test_service_schema.py`.

`ServiceCreate.photo_urls` и `ServiceUpdate.photo_urls` имели собственный validator, который проверял только `https://` или `/media/` prefix. При этом profile/forum/banner URL уже проходили общий parser с host/userinfo/control-character checks. Из-за расхождения service photo list принимал `https:///photo.png`, `https://cdn.example@evil.example/photo.png` и raw newline/control-character формы.

Риск: service gallery могла сохранить визуально обманчивую или malformed ссылку, которую frontend затем отдавал в `<img src>`. Для admin/user-generated service content это тот же URL-boundary, что уже был закрыт для avatar/banner/forum links, но оставался более слабым в service photos.

Исправление: service photo validator теперь использует общий `_validate_https_or_media_url`, сохраняя прежние `/media/...` ссылки, trim/empty-drop/dedupe поведение и cap на 6 фото. Unit regression покрывает valid https/media, dedupe, empty host, userinfo, http и control-character inputs.

### M-108. Broadcast deeplink backend/frontend принимали malformed URL по одному prefix

Ссылки: `backend/app/schemas.py`, `frontend/src/pages/admin/AdminBroadcastsPage.tsx`, regressions `tests/unit/test_admin_broadcast_schema.py`, `frontend/src/pages/admin/AdminBroadcastsPage.test.tsx`.

Admin broadcast deeplink валидировался через lowercase `startsWith("https://") || startsWith("tg://")` на backend и frontend. Поэтому `https:///garant`, `https://t.me@evil.example/garant`, raw newline/control-character URL и пустой `tg://` проходили frontend inline gate или доходили до backend schema как допустимые ссылки.

Риск: broadcast DM path заворачивает deeplink в HTML `<a href="...">`; prefix-only validation оставляла место для обманчивых Telegram/HTTPS ссылок или malformed href, которые могут выглядеть как доверенный домен либо ломать Telegram parsing уже после отправки рассылки.

Исправление: добавлен parser для admin deeplinks: `https` требует host без userinfo, `tg` требует target, raw whitespace/control chars запрещены, length cap сохранен. Frontend composer зеркалит тот же contract и блокирует preview/send до запроса.

### M-109. Ky structured error detail принимал malformed runtime shape

Ссылки: `frontend/src/api/client.ts`, regression `frontend/src/api/client.test.ts`.

Общий `api` client обрабатывал backend ошибки вида `{"detail":{"code":"...","detail":"..."}}` через прямой cast. Если runtime payload приходил с нестроковым `code` или `detail`, hook мог присвоить `err.message` объект/`undefined`, а сравнение code для PIN/TOTP side effects оставалось неявным.

Риск: поврежденный/error-proxy payload мог ломать user-facing текст ошибки и случайно взаимодействовать с security flow вокруг `pin_session_invalid` / `totp_required`. Это не давало privilege escalation само по себе, но делало общий error boundary менее предсказуемым именно на sensitive 401 paths.

Исправление: structured branch теперь принимает только string `code` и string `detail`; malformed detail сериализуется как JSON, а non-string code не запускает PIN/TOTP side effects. Regression покрывает 401 с non-string code и object detail.

### M-110. Create-deal insufficient-funds parser доверял partial JSON

Ссылки: `frontend/src/pages/deals/CreateDealPage.tsx`, regression `frontend/src/pages/deals/CreateDealPage.test.tsx`.

Create-deal error path считал любой JSON с `code:"insufficient_funds"` полным `InsufficientFundsDetail`. Payload без `required`/`balance`/`deficit` попадал в inline alert и toast, где UI мог показывать `undefined` вместо сумм.

Риск: stale/mock/corrupt API response превращался в убедительный money-facing alert с неполными данными. Пользователь мог принять решение по сделке или пополнению на основе сломанной строки, вместо обычной generic API error ветки.

Исправление: parser теперь валидирует весь shape: `message`, `required`, `balance`, `deficit` как строки и `currency_code` как string/null. Partial JSON уходит в generic error toast, полный payload продолжает показывать low-funds alert.

### M-111. Live notification WS handler доверял runtime payload casts

Ссылки: `frontend/src/lib/useLiveNotifications.ts`, `frontend/src/api/types.ts`, `backend/app/notifier.py`, regression `frontend/src/lib/useLiveNotifications.test.tsx`.

WS hook кастовал `deal_message`, `notification`, `notification.read` и `deal.updated` data напрямую. Malformed frame мог записать сообщение в cache key `qk.deal.messages(undefined)`, показать forged toast/notification row без полного `NotificationDto`, применить read-delta с некорректными ids или инвалидировать detail cache по ambiguous `deal_id`.

Риск: WebSocket канал уже проходит auth, но frontend все равно является runtime boundary: Redis/pubsub bug, backend drift или replayed malformed frame не должны отравлять React Query caches и user-facing toast lane. Для notifications был дополнительный drift: backend WS event не отправлял `created_at`, а frontend ручной `NotificationDto` не отражал допустимый `payload: null` из OpenAPI/backend.

Исправление: WS hook теперь валидирует deal messages, media attachments, notification rows, read payloads и deal ids до side effects. Notification type приведен к `payload: Record<string, unknown> | null`, backend WS notification включает `created_at`, а malformed frames игнорируются без haptic/toast/cache mutations. Regression покрывает валидные payloads и malformed `deal_message`, `notification`, `notification.read`, `deal.updated` cases.

### M-112. Service DTO drift позволял строить ссылки на `null` owner

Ссылки: `frontend/src/api/types.ts`, `frontend/src/components/domain/ServiceCard.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, regression `frontend/src/components/domain/ServiceCard.test.tsx`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`, contract `frontend/src/api/openapi.contract.test.ts`.

Ручной `ServiceDto` расходился с OpenAPI: `ServiceOut.owner_username` и `ServiceDetailOut.owner.username` nullable, а `created_at` обязателен, но может быть `null`. Frontend тип держал `owner_username: string` и optional `created_at`, из-за чего UI-код без guard-а строил `@${owner_username}`, `/users/${owner.username}` и `/create-deal/${owner.username}`.

Риск: при удаленном/недоступном владельце или backend drift карточка услуги могла показывать `@null`, а detail page - ссылку `/users/null` и CTA `/create-deal/null`. Это не давало корректного профиля/сделки и маскировало контрактную проблему за валидно выглядящим UI.

Исправление: frontend DTO приведен к OpenAPI nullability, ServiceCard показывает fallback владельца, а ServiceDetailPage не рендерит профильную ссылку и action-кнопки без username. Contract test теперь фиксирует nullable service owner и required nullable `created_at`.

### M-113. Refunded wallet deposit отображался raw-статусом в истории

Ссылки: `frontend/src/api/types.ts`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regression `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`, contract `frontend/src/api/openapi.contract.test.ts`.

Backend wallet enum уже содержит `refunded`, и модалки invoice/deposit обрабатывали этот статус, но per-currency history не имела label/tone для refunded deposit. Одновременно ручной `WalletDepositDto.status` перечислял только `pending`/`paid`/`expired` перед fallback `string`, что скрывало drift от OpenAPI enum.

Риск: пользователь видел техническое `refunded` в истории кошелька вместо локализованного состояния возврата, хотя соседние wallet surfaces показывали нормальный label. Для финансовой истории это выглядит как несогласованное состояние платежа.

Исправление: refunded deposit получил локализованный label/tone в wallet history, `WalletDepositDto.status` документирует `refunded`, а contract fixture закрепляет refunded deposit payload alongside service DTO drift checks.

### M-114. Nullable username-поля расходились с OpenAPI на user/deal/review surfaces

Ссылки: `frontend/src/api/types.ts`, `frontend/src/components/domain/UserCard.tsx`, `frontend/src/components/domain/UserPicker.tsx`, `frontend/src/components/domain/DealRow.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, `frontend/src/pages/search/SearchPage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, regressions `frontend/src/components/domain/UserCard.test.tsx`, `frontend/src/components/domain/UserPicker.test.tsx`, `frontend/src/components/domain/DealRow.test.tsx`, `frontend/src/pages/deals/DealDetailPage.test.tsx`, contract `frontend/src/api/openapi.contract.test.ts`.

OpenAPI уже объявлял nullable username-поля у `UserOut`/`UserPublicOut`, `SupportPersonOut`, `DealOut.buyer/seller` и `ReviewOut.author_username/target_username`. Ручные frontend DTO держали эти поля строками, поэтому несколько UI surfaces напрямую строили `@${username}`, `/users/${username}`, `/deals/new?to=${username}` и `https://t.me/${username}` без null guard.

Риск: пользователь без Telegram username, удаленная сторона сделки или orphaned review/support row могли превращаться в `@null`, `/users/null`, `/deals/new?to=null` или `t.me/null`. Это особенно неприятно в сделках и подборе контрагента: UI выглядел кликабельным, но вел в несуществующий профиль/чат или создавал форму сделки с невалидным контрагентом.

Исправление: DTO nullability приведена к OpenAPI, public cards/search/picker/profile/deal/review/support components показывают явные fallback-состояния и отключают действия, которым нужен username. Contract fixtures закрепляют nullable `UserOut.username`, `DealOut.buyer/seller`, `ReviewOut.author_username/target_username` и `SupportPersonOut.username`.

### M-115. Deal message/media DTO жили вне общего contract surface и расходились с OpenAPI

Ссылки: `frontend/src/api/types.ts`, `frontend/src/api/hooks.ts`, `frontend/src/lib/useLiveNotifications.ts`, `frontend/src/lib/useLiveNotifications.test.tsx`, contract `frontend/src/api/openapi.contract.test.ts`.

`MediaDto` и `DealMessageDto` были объявлены прямо в `api/hooks.ts`, поэтому OpenAPI contract test их не проверял. Ручной `AdminDealMessageDto` дополнительно ожидал несуществующий `sender_display_name` и упрощал `attachments` до `{id,url,mime}`, хотя backend отдает `DealMessageOut.attachments: MediaOut[]` с `kind`, `name`, `size`, `content_type` и обязательным nullable `created_at`.

Риск: frontend мог принять или закешировать message attachment, который не соответствует backend-схеме, а будущий код admin deal detail мог опереться на фантомный `sender_display_name` или неполный media object. Live WS guard тоже пропускал attachment без `created_at`, хотя REST/OpenAPI контракт это поле требует.

Исправление: `MediaDto`/`DealMessageDto` перенесены в общий `api/types.ts`, `AdminDealDetailDto.messages` теперь использует тот же `DealMessageDto`, stale `sender_display_name` удален через alias, а `isMediaDto()` требует `created_at: string | null`. Contract fixtures закрепляют `MediaOut`, `DealMessageOut`, `AdminDealDetailOut` и `AdminUserDetailOut.sessions_count`.

### M-116. Admin audit/analytics показывали fallback actor/username как Telegram handle

Ссылки: `frontend/src/pages/admin/AdminAuditPage.tsx`, `frontend/src/pages/admin/AdminAnalyticsPage.tsx`, regressions `frontend/src/pages/admin/AdminAuditPage.test.tsx`, `frontend/src/pages/admin/AdminAnalyticsPage.test.tsx`.

Admin audit row строил `by @{row.actor_username ?? row.actor_id ?? "system"}`, поэтому системное событие отображалось как `by @system`, а запись с отсутствующим username, но известным actor_id, как `by @7`. Аналитика top-users аналогично показывала пользователя без username как `@—`.

Риск: оператор мог принять числовой actor_id или системный источник за Telegram username, особенно при разборе audit trail. `@—` в top-листах выглядело как сломанный handle, а не как нормальное отсутствие username.

Исправление: audit row теперь явно различает `by @username`, `by user #id` и `by system`; analytics top-users показывает fallback `username не задан` без `@`.

### M-117. Currency/admin finance DTO drift hid OpenAPI-backed defaults and string money fields

Links: `frontend/src/api/types.ts`, `frontend/src/api/openapi.contract.test.ts`, `frontend/src/pages/deals/CreateDealPage.tsx`, `frontend/src/pages/wallet/WalletDepositPage.tsx`, regressions `frontend/src/pages/admin/AdminTaxonomyPage.test.tsx`, `frontend/src/pages/admin/AdminWalletsPage.test.tsx`, `frontend/src/pages/wallet/WalletWithdrawPage.test.tsx`.

Manual frontend DTOs treated `CurrencyDto.kind`, `AdminCurrencyDto.kind`, and `AdminCurrencyDto.address_regex` as optional even though the backend response schema always projects them with defaults. The same DTO surface allowed numeric admin USD-rate/estimate response fields (`usd_rate`, `usd_estimate`, `total_usd_estimate`) while OpenAPI exposes those money projections as strings. The contract bridge also listed `AdminCurrencyOut`, admin deposit/withdrawal/wallet, notification, and wallet-withdrawal schemas only by name, without representative DTO assignments.

Risk: wallet/deal pages could silently classify a malformed currency without `kind` as crypto through `kind ?? "crypto"`, hiding fiat choices instead of surfacing a contract drift. Admin finance UI/tests could keep accepting numeric money projections that the backend no longer emits, making future parsing and display assumptions harder to audit.

Fix: public/admin currency DTOs now require the default-backed `kind`/`address_regex` response fields, admin finance response money projections are typed as strings, and create-deal/deposit filters use the explicit `kind` value. OpenAPI contract tests now bridge admin currency, rate, deposit, withdrawal, wallet list/balance, wallet withdrawal, notification, and notification-counter fixtures into the manual DTOs.

### M-118. Admin user rows still rendered missing usernames as Telegram handles

Links: `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminDealsPage.tsx`, `frontend/src/pages/admin/AdminArbitrationPage.tsx`, `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.tsx`, `frontend/src/pages/admin/UserContentSections.tsx`.

After M-116 fixed audit/analytics labels, the same `@${username ?? "--"}` pattern still existed across admin deal queues, finance queues, wallet/user lists, user detail, deal detail balance snapshots/chat, and user content review rows. OpenAPI correctly marks these username fields nullable, but the UI rendered the fallback with an `@` prefix, so a missing Telegram username looked like a broken handle.

Risk: admin operators could read `@--` as an actual Telegram identity or a clickable-style handle while resolving deals, withdrawals, deposits, balances, or user content. In audit-heavy admin workflows that makes identity review noisier and can hide the real nullable-user contract.

Fix: admin pages now share `formatAdminUsername()`, which emits `@username` only for a real trimmed username and otherwise renders the explicit `username не задан` label. Regression coverage was added for the formatter and representative admin deal/arbitration/finance/wallet/user/detail/content surfaces.

### M-119. Telegram contact links accepted raw usernames and non-Telegram fallback URLs

Links: `frontend/src/lib/tg.ts`, `frontend/src/lib/telegramLinks.ts`, `frontend/src/components/BannedGate.tsx`, `frontend/src/components/PinResetPaywallModal.tsx`, `frontend/src/components/domain/SupportPersonRow.tsx`, `frontend/src/pages/wallet/WalletWithdrawPage.tsx`, `frontend/src/pages/wallet/WalletTrustDepositPage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, regressions `frontend/src/lib/tg.test.ts`, `frontend/src/lib/telegramLinks.test.ts`, `frontend/src/components/domain/SupportPersonRow.test.tsx`.

Several UI surfaces interpolated server/user usernames directly into `https://t.me/${username}`. `openTelegramLink` also accepted any safe `http(s)` URL in the no-Telegram desktop fallback, even though the Telegram API path is supposed to receive only `t.me` links.

Risk: a malformed username containing path/query characters could produce a misleading Telegram URL, and a future caller could accidentally route a non-Telegram URL through `openTelegramLink` where Telegram clients reject it but desktop preview opens it. That makes the frontend URL boundary inconsistent between production Telegram and local/fallback execution.

Fix: added `buildTelegramUserUrl()` with trim, optional `@` normalization, username character validation, and safe query construction for prefilled messages. All Telegram username contact CTAs now use that helper and disable themselves when the username is malformed. `openTelegramLink` now accepts only `t.me` HTTP(S) URLs before delegating to Telegram or `window.open`.

### M-120. Topup invoice/admin approval DTO money fields drifted from OpenAPI

Links: `frontend/src/api/types.ts`, `frontend/src/api/openapi.contract.test.ts`, regressions `frontend/src/pages/deals/CreateDealPage.test.tsx`, `frontend/src/pages/deals/DealDetailPage.test.tsx`.

Manual frontend DTOs still allowed `DealTopupInvoiceDto.total`, `topup_principal`, `commission`, and `paid_total` as strings, while OpenAPI exposes the invoice values as required numbers. `AdminApprovalDto.amount` and `amount_usd_estimate` likewise allowed numbers even though `AdminApprovalOut` serializes them as strings/null.

Risk: frontend fixtures and future UI code could keep accepting shapes the backend contract does not emit, weakening the OpenAPI bridge and hiding schema drift in money-facing deal/admin flows.

Fix: the DTOs now mirror OpenAPI for these fields: topup invoice totals are required numbers, and admin approval money projections are strings/null. Contract tests now include an `AdminApprovalOut` fixture and bridge it into `AdminApprovalDto`, while deal topup fixtures use numeric invoice totals.

### M-121. StatsBadge count-up hid a stale-state dependency with eslint-disable

Links: `frontend/src/components/domain/StatsBadge.tsx`.

`useCountUp()` intentionally suppressed `react-hooks/exhaustive-deps` because the animation wanted to start from the current displayed value without re-running on every animation frame. That made the hook harder to audit and left future changes one stale-closure edit away from starting a refreshed counter from the wrong value.

Risk: public stats and admin-settings preview counters are display-only, but misleading animated totals can make a refreshed settings preview look broken or jumpy. The lint suppression also created a local exception that could hide real dependency mistakes.

Fix: the hook now mirrors the latest displayed value into a ref and starts each target change from that ref. The eslint-disable is gone, so the hook is checked by the normal lint rule while preserving the intended animation behavior.

### M-122. Admin deposit pay_url rendered raw external links

Links: `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/lib/tg.ts`, regressions `frontend/src/pages/admin/AdminDepositsPage.test.tsx`, `frontend/src/lib/tg.test.ts`.

The admin deposits queue rendered `deposit.pay_url` directly as `<a href={d.pay_url} target="_blank">`. Payment providers should emit HTTPS URLs, but this was still a raw external-link sink fed by API data and it bypassed the same Telegram/payment opener boundary used by user-facing payment flows.

Risk: malformed or compromised API data could create a `javascript:`/non-HTTP link in the admin UI. Even when React blocks some dangerous URL forms, keeping a direct external `href` made the admin finance queue inconsistent with the rest of the payment-link hardening.

Fix: `isSafeExternalLink()` now exposes the existing HTTP(S)-only predicate from `tg.ts`. Admin deposits render `pay_url` as an opener button only when that predicate passes, and click handling delegates to `openPaymentLink()`, which repeats the URL safety check before opening. Regression coverage verifies safe openers and rejects `javascript:` values without rendering a link/button.

### M-123. Deal chat media URLs were trusted at the render/cache boundary

Links: `frontend/src/pages/deals/DealChatPanel.tsx`, `frontend/src/lib/mediaLinks.ts`, `frontend/src/lib/useLiveNotifications.ts`, regressions `frontend/src/pages/deals/DealChatPanel.test.tsx`, `frontend/src/lib/mediaLinks.test.ts`, `frontend/src/lib/useLiveNotifications.test.tsx`.

Deal chat attachments used server-provided `m.url` directly as both anchor `href` and image `src`. Backend media serving signs `/media/deal/...` URLs, but the frontend runtime boundary still accepted arbitrary attachment URLs from REST/WS payloads, including malformed frames injected before React Query cache insertion.

Risk: a malformed live frame or API drift could place a non-media URL into the deal-message cache and render it as a clickable attachment or image source. That is a smaller surface than public free-form links, but it sits in a deal/chat workflow where users expect file previews to be trusted artifacts.

Fix: added `safeMediaUrl()`, which accepts only same-origin relative `/media/...` paths and gates fragments/ambiguous paths before preserving signed query params. Deal chat now validates every attachment URL before rendering `href`/`img`; unsafe entries render only the existing broken-preview placeholder. The live-notification guard also requires a safe media URL before appending incoming deal messages to cache.

### M-124. Admin currency write paths accepted malformed currency codes

Links: `backend/app/schemas.py`, `frontend/openapi.json`, regression `tests/unit/test_admin_currency_schema.py`.

Public wallet/deal currency inputs already used the shared `CurrencyCodeStr` contract: trim, uppercase, ASCII alphanumeric, `<=16`. Admin currency creation, manual wallet adjustment, and USD-rate upsert still had local validators that only trimmed/uppercased and checked length, so values like `USD T`, `USD-T`, or unicode lookalikes passed schema parsing.

Risk: the taxonomy endpoint could create malformed `Currency.code` rows from an admin payload, while wallet adjust/rate endpoints turned the same malformed shape into late 404s. That left the admin money contract wider than the user money contract and kept OpenAPI from documenting the actual code pattern for generated clients.

Fix: `AdminCurrencyUpsertIn.code`, `AdminWalletAdjustIn.currency_code`, and `AdminCurrencyRateUpsertIn.currency_code` now use `CurrencyCodeStr` plus the shared validator. The committed OpenAPI snapshot now exposes `minLength`, `maxLength`, and `^[A-Z0-9]+$` for those admin payload fields, and schema regression coverage checks normalization and rejects spaces, punctuation, unicode, empty strings, and overlong codes.

### M-125. Profile banner URLs were interpolated into CSS

Links: `frontend/src/components/domain/ProfileHeader.tsx`, regression `frontend/src/components/domain/ProfileHeader.test.tsx`.

`ProfileHeader` rendered `user.banner_url` by building `backgroundImage: url(${user.banner_url})`. Backend URL validation rejects dangerous schemes, but the value is still user-controlled text placed into a CSS `url(...)` context. A path containing CSS delimiters such as `),url(...)` can change how many image URLs the browser parses, even though the same string is inert when used as an ordinary `img src` attribute.

Risk: a malformed or legacy banner URL could trigger extra same-page image fetches from a profile view, bypassing the intended single-banner rendering contract and making future URL-validation drift harder to reason about.

Fix: profile banners now render as an absolutely positioned `<img>` inside the existing banner frame, with lazy decoding and `referrerPolicy="no-referrer"`. The inline style keeps only transform/opacity animation state. Regression coverage uses a delimiter-bearing URL and asserts it is assigned to a single image `src`, not to a CSS `background-image` string.

### M-126. Shared external-link validation still allowed credentials and raw whitespace

Links: `frontend/src/lib/tg.ts`, regression `frontend/src/lib/tg.test.ts`.

`openExternalLink`, `openTelegramLink`, and `openPaymentLink` all went through an `http(s)` scheme check, but the predicate still accepted URLs with embedded credentials (`https://example.com@evil.example/...`, `https://user:pass@example.com/...`) and raw whitespace/control characters before handing them to Telegram or the browser fallback.

Risk: these URLs are not script-execution vectors, but they are phishing and parser-confusion inputs on payment, forum, support, and admin deposit opener surfaces. `openPaymentLink` also used a raw `startsWith("https://t.me/")` branch instead of the parsed Telegram-link predicate, so edge-case Telegram invoice URLs were routed inconsistently.

Fix: link parsing is now centralized in `parseSafeLink()`: only `http`/`https` URLs with a hostname, no username/password, and no raw spaces/control bytes pass. `openTelegramLink` and `openPaymentLink` share the parsed `t.me` predicate. Tests cover safe encoded paths, credential-bearing URLs, raw-newline URLs, no-Telegram fallbacks, and Telegram invoice routing with an explicit default port.

### M-127. Backend media URL schemas accepted parser-drift paths

Links: `backend/app/schemas.py`, regression `tests/unit/test_service_schema.py`.

`_validate_https_or_media_url()` accepted any string starting with `/media/` without canonicalizing the path. That left profile avatars/banners, service photo lists, and currency icons accepting shapes the upload pipeline never emits: dot-segments, URL-encoded dot-segments, double slashes, fragments, and malformed HTTPS hosts/ports.

Risk: these inputs are usually not script-execution vectors, but they create parser drift between Pydantic, browser URL parsing, and Starlette static media serving. A future UI could treat a stored `/media/...` string as backend-generated even when it was a hand-written ambiguous path.

Fix: `/media/...` values now go through `_validate_media_path_url()`, which requires a relative canonical path with no fragments, encoded path segments, backslashes, double slashes, or dot-segment normalization. The HTTPS branch now requires `parsed.hostname`, rejects userinfo through parsed username/password, and touches `parsed.port` so malformed ports fail schema validation. Schema regressions cover service photo URLs plus profile avatar/banner URL fields.

### M-128. Service image rendering bypassed the shared media URL predicate

Links: `frontend/src/pages/profile/AddServicePage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, regressions `frontend/src/pages/profile/AddServicePage.test.tsx`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`.

`DealChatPanel` and live notifications already used `safeMediaUrl()`, but service image surfaces still trusted API/upload-returned strings directly: `AddServicePage` stored `uploadMedia`'s `m.url` into `photo_urls`, and `ServiceDetailPage` rendered each `service.photo_urls` entry as raw `<img src>`.

Risk: backend schema validation is the primary guard, but the frontend runtime boundary was weaker than the deal media boundary. A compromised payload, legacy row, or future API drift could render a non-media image URL in the service create preview or public gallery.

Fix: service uploads now validate the returned media URL before preview/storage and skip unsafe values. Public service galleries filter through `safeMediaUrl()` before rendering images. Regression tests cover mixed safe/unsafe upload responses and mixed safe/unsafe gallery data.

### M-129. Public username links interpolated raw API/user strings

Links: `frontend/src/lib/usernames.ts`, `frontend/src/App.tsx`, `frontend/src/api/hooks.ts`, `frontend/src/components/domain/UserCard.tsx`, `frontend/src/components/domain/ProfileHeader.tsx`, `frontend/src/components/domain/ServiceCard.tsx`, `frontend/src/components/domain/SupportPersonRow.tsx`, `frontend/src/components/domain/ReviewRow.tsx`, `frontend/src/components/domain/DealRow.tsx`, `frontend/src/components/domain/UserPicker.tsx`, `frontend/src/pages/search/SearchPage.tsx`.

Several public frontend surfaces built `/users/${username}` or `api/users/${username}` directly from route params, API payloads, or picker input. Null usernames had already been handled, but malformed non-null strings such as `../admin`, `alice/bob`, or encoded slash shapes could still become router paths, query keys, or visible `@...` handles.

Risk: React Router generally treats these as client-side paths rather than backend requests, but the UI boundary was weaker than the backend username contract. A malformed legacy/API payload could create confusing profile links, stale cache keys, or redirect targets that do not represent an actual username reference.

Fix: added shared username helpers mirroring the backend `@? [A-Za-z0-9_-]{1,64}` contract. Public card/review/deal/search/picker surfaces now normalize username refs before labels and links, and omit profile actions for unsafe values. `useUser()` now builds `api/users/{username}` only after the same normalization. Regression tests cover unsafe username rows and legacy `/u/:username` redirects.

### M-130. Username route/query refs could still drive profile/deal side effects

Links: `frontend/src/pages/profile/ProfilePage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, `frontend/src/pages/deals/CreateDealPage.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, regressions in adjacent page tests.

The profile, deal detail, service detail, and create-deal pages reused route/query usernames in secondary flows: profile services/reviews queries, load-more calls, `?to=` seeds, review target usernames, Telegram/create-deal buttons, and owner/comment links. These paths needed the same username contract as the simple profile links, otherwise an unsafe ref could still reach API search params or mutation bodies even after link rendering was hardened.

Risk: malformed username refs could create wrong list queries, invalid create-deal counterparty submissions, or review mutations against a non-contract target. The backend rejects the worst cases, but frontend state could still open PIN prompts or show actions for a value that was never a valid public username.

Fix: these pages now normalize route/query/API usernames before use. Invalid public profile routes render a not-found state and keep services/reviews hooks disabled; create-deal drops unsafe `?to=` and legacy route seeds before validation/submission; deal detail hides review/profile/contact actions for unsafe counterparties; service owner/comment actions use sanitized profile/deal paths only. Regression tests cover unsafe seeds, owners, comments, counterparties, and profile routes.

### M-131. Admin broadcast fan-out still materialized the full audience id set

Links: `backend/app/routers/admin/broadcasts.py`, regression `tests/integration/test_admin_misc.py`.

The send path had been converted to commit notification inserts per chunk, but it still ran one `SELECT users.id ...` and converted the entire matching audience into `all_user_ids` before slicing it in Python. The comment claimed streaming/chunking, but a 50K+ recipient broadcast still paid the full id-list memory cost up front.

Risk: large all-user or broad-cohort broadcasts could put avoidable pressure on worker memory before the first chunk was even sent. The later per-chunk commits did not protect this earlier materialization step.

Fix: recipient ids are now fetched with keyset pages (`User.id > last_user_id AND User.id <= max_user_id ORDER BY User.id LIMIT _CHUNK_SIZE`) and each page is loaded/sent independently. Regression coverage lowers `_CHUNK_SIZE`, sends to several users, and asserts the broadcast uses multiple limited, upper-bounded recipient-id selects.

### M-132. Admin broadcast could be sent with no delivery channel

Links: `backend/app/schemas.py`, `backend/app/routers/admin/broadcasts.py`, `frontend/src/pages/admin/AdminBroadcastsPage.tsx`, regressions `tests/unit/test_admin_broadcast_schema.py`, `frontend/src/pages/admin/AdminBroadcastsPage.test.tsx`.

`dispatch_inapp=false` and `dispatch_dm=false` was a valid payload. The backend created a `Broadcast(status=sent)` and the old accounting path could count recipients as delivered even though no notification row and no DM were produced. The composer also allowed both switches to be turned off.

Risk: admin history/audit could show a successful broadcast that reached nobody. This is a bad operational record because the UI presents delivery counters as evidence of a real send.

Fix: `AdminBroadcastCreateIn` now rejects payloads without any dispatch channel, and the composer blocks preview/send with the same rule. The delivery loop also only counts the in-app fallback when in-app dispatch is actually enabled.

### M-133. Broadcast language filter validation drifted between backend and UI

Links: `backend/app/schemas.py`, `frontend/src/pages/admin/AdminBroadcastsPage.tsx`, regressions `tests/unit/test_admin_broadcast_schema.py`, `frontend/src/pages/admin/AdminBroadcastsPage.test.tsx`.

The composer only capped the language input length. It did not reject characters that the backend validator claimed to reject, and the backend used Python `str.isalnum()`, which accepts non-ASCII letters despite the stored Telegram language tags being ASCII/IETF-style values.

Risk: malformed language filters could be caught only after submit, or accepted by backend while not matching the intended language-code contract. That makes a broadcast audience harder to reason about and weakens the schema/UI mirror promised in the composer comment.

Fix: backend language validation now requires ASCII alphanumeric characters plus `-`, while still lowercasing and trimming. The composer applies the same max length and character rule before preview/send and normalizes valid tags such as `PT-BR` to `pt-br` in the request body.

### M-134. UI preference store could crash at module import when localStorage was blocked

Links: `frontend/src/stores/ui.ts`, `frontend/src/lib/storage.ts`, regression `frontend/src/stores/ui.test.ts`.

`useUI` read `window.localStorage.getItem("hideDesignations")` while the module was evaluated, then wrote/removed the same key directly from the setter. Browsers can throw `SecurityError` when storage is disabled, origin policy blocks it, or the app is embedded in a constrained WebView. Because the read happened during import, this could fail before React mounted any recovery UI.

Risk: a user with blocked storage could white-screen on startup from a display preference that should be best-effort only. Later writes could likewise throw instead of updating in-memory UI state.

Fix: added safe browser-storage helpers that guard storage object access and method calls. The UI store now initializes the preference through that helper and always updates the in-memory zustand state even when persistence is unavailable. Regression coverage forces `localStorage` reads/writes to throw and verifies import/setter behavior remains stable.

### M-135. Dev initData fallback could throw during auth bootstrap

Links: `frontend/src/lib/tg.ts`, `frontend/src/lib/storage.ts`, regression `frontend/src/lib/tg.test.ts`.

`getInitData()` had a production-gated local-development fallback for `localStorage.dev_init_data`, but the fallback still called `window.localStorage.getItem()` directly. In dev, preview, or tests with blocked storage this could throw while the API client or WebSocket auth path was bootstrapping.

Risk: local/preview environments outside Telegram could crash before returning the intended empty initData string. That makes auth diagnostics noisier and keeps a dev-only convenience path wider than other best-effort storage helpers in the frontend.

Fix: the dev fallback now uses the shared safe localStorage getter. Blocked storage simply behaves like a missing fallback value and `getInitData()` returns `""`; Telegram-provided `initData` still takes priority.

### M-136. Lazy chunk retry could mask import failures with sessionStorage errors

Links: `frontend/src/lib/lazyWithRetry.ts`, `frontend/src/lib/storage.ts`, regression `frontend/src/lib/lazyWithRetry.test.tsx`.

`lazyWithRetry()` used `sessionStorage` as a one-shot reload guard after a failed dynamic import. If `sessionStorage.getItem()`/`setItem()`/`removeItem()` threw, the storage exception replaced the original chunk import error and the reload-loop guard could not be trusted.

Risk: a stale or missing route chunk in a storage-blocked WebView could surface as a misleading storage failure, or attempt a hard reload without a persisted guard. That weakens the top-level error boundary path for the exact startup/navigation failure this helper is meant to contain.

Fix: the retry path now uses safe sessionStorage helpers. It reloads only when the guard can be stored, preserves the original chunk error when storage is unavailable, and treats guard cleanup as best-effort. Regression coverage verifies the one-shot reload path and the blocked-storage path.

### M-137. Frontend media URL predicate still accepted parser-drift paths

Links: `frontend/src/lib/mediaLinks.ts`, regressions `frontend/src/lib/mediaLinks.test.ts`.

The backend media schema now rejects ambiguous `/media/...` shapes: encoded path segments, dot-segments, double slashes, backslashes, semicolon params, and fragments. The frontend runtime predicate still only checked that `new URL(raw, origin)` stayed same-origin and that the parsed pathname started with `/media/`. That left values like `/media/deal//proof.png`, `/media/deal/%2F/proof.png`, or `/media/deal/proof.png#fragment` accepted at the render/cache boundary.

Risk: deal-chat attachments, service upload previews, public service galleries, and live-notification cache insertion could still treat parser-drift URLs as backend media artifacts even though the backend write schema would reject them. This weakens the runtime boundary that is supposed to protect the UI from malformed legacy rows or compromised live frames.

Fix: `safeMediaUrl()` now mirrors the stricter media-path contract before rendering: relative `/media/` only, no fragments, no encoded path segments, no double slashes/backslashes/semicolon params, and no dot-segment normalization. Signed query params are still preserved.

### M-138. User image rendering did not share the hardened image URL boundary

Links: `frontend/src/components/ui/Avatar.tsx`, `frontend/src/components/domain/ProfileHeader.tsx`, `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, regressions `frontend/src/components/ui/Avatar.test.tsx`, `frontend/src/components/domain/ProfileHeader.test.tsx`, `frontend/src/lib/mediaLinks.test.ts`.

Most public user cards already rendered through `<Avatar />`, but that component passed any non-empty `src` straight to `<img>`. Profile banners had the same direct image render, and a few admin identity surfaces used raw `<img src={user.photo_url}>` instead of the shared avatar component. Backend validation rejects unsafe avatar/banner values on writes, but the frontend runtime boundary did not protect against API drift, legacy rows, or a compromised Telegram `photo_url` global.

Risk: user-controlled image fields could become tracking or parser-confusion sinks in admin/public views if the backend contract drifted or old data bypassed current validators. This was especially inconsistent because profile banners and avatars already deliberately use `referrerPolicy="no-referrer"` once rendered, but unsafe schemes and malformed media paths could still reach the render decision.

Fix: added `safeUserImageUrl()` for the HTTPS-or-strict-media image contract. `Avatar` and `ProfileHeader` sanitize before rendering, unsafe values fall back to initials/logo, and admin users/detail/wallets now use `Avatar` instead of raw image tags. Regression coverage checks malicious schemes, credential-bearing HTTPS URLs, malformed media paths, and unsafe banners.

### M-139. Admin deal amount filters accepted reversed ranges

Links: `frontend/src/pages/admin/AdminDealsPage.tsx`, regression `frontend/src/pages/admin/AdminDealsPage.test.tsx`.

The admin deals page parsed `min_amount` and `max_amount` independently from the URL and from the filter sheet. A damaged deep link such as `?min_amount=500&max_amount=10`, or the same values entered by an operator, could reach `useAdminDeals()` as a reversed range.

Risk: backend validation rejects the inconsistent range, which turns a simple malformed filter into a broken admin list instead of a recoverable local validation state.

Fix: URL ranges are parsed as a pair and dropped when `min_amount > max_amount`. The filter sheet now shows an inline range error and disables Apply while the draft range is reversed. Regression coverage checks both URL parsing and sheet submission.

### M-140. Public user search could submit reversed registration-date ranges

Links: `frontend/src/components/domain/SearchFilterSheet.tsx`, regression `frontend/src/components/domain/SearchFilterSheet.test.tsx`.

The public search filter sheet allowed `reg_from` later than `reg_to` and passed the draft filters to the caller unchanged.

Risk: a reversed date range could be sent to the backend and fail as a validation error, leaving the user-facing search results in an avoidably broken state.

Fix: the sheet now validates the local registration-date pair before applying filters, surfaces an inline date-range error, and disables Apply until the range is coherent. Regression coverage checks that reversed ranges are blocked and valid ranges still apply.

### M-141. Deal rows nested profile links inside deal-detail links

Links: `frontend/src/components/domain/DealRow.tsx`, regression `frontend/src/components/domain/DealRow.test.tsx`.

Public deal rows rendered the entire row as a React Router link to `/deals/:id`, then rendered the counterparty profile action as another link inside that anchor.

Risk: nested anchors are invalid HTML and profile clicks could bubble into row navigation in some browser/router paths, making the profile action unreliable and weakening keyboard behavior around the row.

Fix: the row wrapper is now a keyboard-accessible `role=link` surface that navigates programmatically, while the profile action remains a normal profile link and stops event propagation. Regression coverage checks row navigation and profile-link isolation.

### M-142. Wallet history filters could send malformed currency/pagination params

Links: `frontend/src/api/hooks.ts`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regressions `frontend/src/api/hooks.test.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`.

The wallet history helpers serialized `currency`, `limit`, and `offset` directly. The per-currency wallet route also mounted deposit/withdrawal history queries before proving the route `:code` was a valid backend currency code and an active fiat row.

Risk: malformed routes such as `/wallet/USD!x`, stale links, or future hook misuse could hit `/api/wallet/deposits` and `/api/wallet/withdrawals` with values the backend rejects, turning an unsupported wallet page into a noisy validation failure instead of a local unsupported-currency state.

Fix: wallet history query params now normalize currency codes through the backend `^[A-Z0-9]{1,16}$` contract, drop invalid `limit`/`offset` values, and use normalized params in query keys. The per-currency page disables both history queries until the route code is valid and resolves to an active fiat currency. Regression coverage checks helper normalization and disabled malformed/unknown route queries.

### M-143. Wallet balance rows interpolated API currency codes into routes

Links: `frontend/src/lib/currencyCodes.ts`, `frontend/src/pages/wallet/WalletPage.tsx`, regressions `frontend/src/lib/currencyCodes.test.ts`, `frontend/src/pages/wallet/WalletPage.test.tsx`.

The wallet landing page filtered balances by `currency.kind === "fiat"`, but still used `currency.code` directly in `/wallet/${code}` links and display formatting. A malformed legacy/API row could therefore build a route path that does not represent a valid wallet currency.

Risk: the backend normally controls currency rows, but a stale cache, legacy row, or admin catalogue drift could produce broken client-side links and route/query behavior from a value outside the currency-code contract.

Fix: added shared frontend currency-code helpers and made the wallet list omit fiat balance rows whose code does not normalize to the backend contract. Valid codes are normalized before path construction and formatting. Regression coverage checks path/query-breaking currency code rejection.

### M-144. Profile fiat balance actions trusted display_currency_code

Links: `frontend/src/components/domain/ProfileFiatBalanceCard.tsx`, regression `frontend/src/components/domain/ProfileFiatBalanceCard.test.tsx`.

The profile fiat balance card used `user.display_currency_code` directly in the visible balance label and in `?currency=${code}` links for deposit/withdrawal actions.

Risk: current profile writes validate the preferred currency, but legacy/profile API drift could inject query separators or non-contract codes into wallet action links, causing the wallet forms to open with malformed URL state.

Fix: the card now normalizes the preferred display currency through the shared helper, falls back to `USD` for invalid values, and builds wallet action links with `URLSearchParams`. Regression coverage checks malformed fallback and lowercase/space normalization.

### M-145. PIN token reads accepted malformed stored expiry values

Links: `frontend/src/lib/pin.ts`, regression `frontend/src/lib/pin.test.ts`.

`setPinToken()` rejected malformed `expiresAt` values, but `getPinToken()` did not revalidate the expiry already stored in `localStorage`. If a corrupted storage entry, legacy build, test fixture, or WebView storage glitch left `garant.pin_token_expires = "not-a-date"`, `new Date(expires).getTime()` returned `NaN`; the old `NaN <= Date.now()` check was false, so the helper returned the token as valid.

Risk: the frontend could attach a stale/corrupted `X-Pin-Token` header and keep `PinGate` unlocked until the backend rejected the request. That turns a malformed local cache entry into avoidable authenticated UI state and extra 401 recovery churn.

Fix: PIN expiry parsing is now centralized and requires a finite timestamp on both write and read. Invalid stored expiries are treated the same as expired tokens: the helper clears both storage keys, emits the existing token-change event, and returns `null`.

### M-146. TOTP session token reads accepted malformed stored expiry values

Links: `frontend/src/lib/totp.ts`, regression `frontend/src/lib/totp.test.ts`.

The admin TOTP session helper mirrored the PIN bug: malformed `garant.totp_session_token_expires` values already in `localStorage` bypassed the expiry comparison because `NaN <= Date.now()` is false. A corrupted cached admin session token could therefore be forwarded as `X-Totp-Session` until the backend forced the gate again.

Risk: admin actions could start from stale local 2FA state, producing unnecessary 401/TOTP prompts and weakening the frontend's own session boundary. The backend still validates the JWT, but the client should not trust a cache entry with an invalid expiry contract.

Fix: TOTP expiry parsing now requires a finite timestamp on write and read, matching the PIN helper. Invalid stored expiries clear the token and expiry keys and return `null`. A new dedicated TOTP storage regression file covers empty, valid, expired, malformed-expiry, clear, and event semantics.

### M-147. Wallet deposit form trusted API currency codes after filtering only by kind

Links: `frontend/src/pages/wallet/WalletDepositPage.tsx`, `frontend/src/lib/currencyCodes.ts`, regressions `frontend/src/pages/wallet/WalletDepositPage.test.tsx`, `frontend/src/lib/currencyCodes.test.ts`.

The standalone wallet deposit page requested `kind=fiat` and filtered stale responses by `c.kind === "fiat"`, but it still used `c.code` directly as the select value and `currency_code` mutation body. It also normalized `?currency=` by uppercasing only, so a malformed deep link was not passed through the same currency-code contract used by wallet routes and action links.

Risk: a malformed legacy/API fiat row such as `USD/../admin` could be displayed as a deposit option and submitted to `POST /api/wallet/deposits`, relying on backend validation to reject a form state the client could have omitted locally.

Fix: added a shared row normalizer that trims/uppercases valid codes, drops invalid and duplicate rows, and reuses the backend `^[A-Z0-9]{1,16}$` contract. The deposit page now normalizes URL hints, omits malformed fiat rows, and submits only normalized `currency_code` values.

### M-148. Wallet withdrawal form could offer malformed or stale non-fiat balance rows

Links: `frontend/src/pages/wallet/WalletWithdrawPage.tsx`, regression `frontend/src/pages/wallet/WalletWithdrawPage.test.tsx`.

The withdrawal page asked the API for fiat balances, but its local eligibility filter only checked `amount > 0`. If a stale cache or API drift returned a positive crypto row or a fiat row with a malformed code, the dropdown could offer it and submit the raw `currency_code` after the PIN prompt.

Risk: users could enter a sensitive PIN flow for a withdrawal that the backend would reject as an invalid or unsupported currency. This is especially poor on money-moving screens because the UI should not present an action that cannot satisfy the backend contract.

Fix: withdrawal eligibility now requires `currency.kind === "fiat"`, a valid normalized currency code, positive balance, and one row per normalized code. Query-string hints are normalized through the same helper before matching. Regression coverage verifies positive crypto/malformed rows are hidden and a lowercase/space-padded fiat row submits as the normalized code.

### M-149. Trust-deposit form submitted raw currency catalogue codes

Links: `frontend/src/pages/wallet/WalletTrustDepositPage.tsx`, regression `frontend/src/pages/wallet/WalletTrustDepositPage.test.tsx`.

The trust-deposit page used the full currency catalogue directly for its select values. A malformed catalogue row could therefore become the selected `currency_code` for a `purpose: "trust"` deposit invoice.

Risk: malformed currency catalogue drift could turn the trust-deposit screen into a backend validation failure instead of a local omission. The trust balance is user-visible reputation capital, so its funding UI should share the same currency-code boundary as wallet deposit/withdrawal screens.

Fix: trust-deposit options now pass through the shared currency-row normalizer before selection and invoice creation. Invalid rows are omitted, valid codes are normalized, and regression coverage verifies a malformed row is hidden while a space/lowercase code submits as `UAH` with `purpose: "trust"`.

### M-150. Shared date labels trusted malformed and future timestamps

Links: `frontend/src/lib/format.ts`, regression `frontend/src/lib/format.test.ts`.

`relativeTime()` and `dayKey()` called `new Date(iso)` and then used comparisons or locale formatting without checking that the parsed timestamp was finite. Malformed values could fall through to invalid date display, while far-future values produced a negative diff and were shown as `только что`.

Risk: notifications, deal rows/chat, reviews, wallet history, and other shared date surfaces could make stale or malformed API data look like fresh user activity, or render a broken date label instead of a neutral state.

Fix: shared date parsing now requires a finite timestamp before formatting. Malformed timestamps render a neutral dash, and future timestamps beyond small clock skew are formatted as a calendar date instead of a fresh relative label.

### M-151. PIN lock banner rendered NaN for malformed lock expiry

Links: `frontend/src/pages/pin/PinPage.tsx`, regression `frontend/src/pages/pin/PinPage.test.tsx`.

`formatLock(status.locked_until)` subtracted `Date.now()` from `new Date(locked_until).getTime()` without validating the parse result. For malformed `locked_until`, `ms` became `NaN`; the expired check did not catch it and the page could render `NaN мин` or `NaN ч` while treating the keypad as locked.

Risk: a malformed lock timestamp from API drift or stale cache could block the PIN pad and show a nonsensical countdown instead of letting the user continue through the normal unlocked state.

Fix: PIN lock parsing now rejects non-finite timestamps before computing the countdown. Malformed lock data is treated as no active frontend lock, and regression coverage verifies no `NaN` banner or keypad disablement.

### M-152. Account-transfer active-code countdown rendered NaN for malformed expiry

Links: `frontend/src/pages/profile/AccountTransferPage.tsx`, regression `frontend/src/pages/profile/AccountTransferPage.test.tsx`.

The account-transfer page used the same unchecked date arithmetic for `expires_at` in the active-code banner. A malformed active transfer expiry rendered `NaN мин.` even though the value could not be trusted as a valid countdown.

Risk: the account migration screen could present an active transfer code with a broken lifetime label, making it unclear whether the code was usable, expired, or corrupted.

Fix: `relativeMinutes()` now requires a finite expiry timestamp and falls back to a neutral placeholder for malformed data. Valid expired and future values keep the existing labels.

### M-153. Admin queues rendered raw invalid-date labels for malformed timestamps

Links: `frontend/src/lib/format.ts`, `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, `frontend/src/pages/admin/AdminAuditPage.tsx`, regressions in the adjacent tests.

Deposit, withdrawal, and audit-log queues formatted `created_at` with direct `new Date(...).toLocaleString()` calls. If API drift, legacy rows, or test fixtures produced a malformed timestamp, these admin queues rendered browser invalid-date text instead of a controlled UI value.

Risk: operators could see broken timestamps on money-moving and audit-log screens, making queue ordering/history harder to trust and obscuring whether the row data was simply malformed or the UI had failed.

Fix: added a shared `formatDateTime()` helper that requires finite timestamps and returns a neutral dash for malformed values. Admin deposit, withdrawal, and audit queues now use it, with regression coverage for malformed `created_at` rows.

### M-154. Operational/detail pages exposed unchecked timestamp formatting

Links: `frontend/src/pages/deals/DealDetailPage.tsx`, `frontend/src/pages/admin/AdminSystemPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.tsx`, regressions in the adjacent tests.

Several non-queue detail surfaces had the same unchecked date formatting: pending-topup invoice expiry, system `started_at`, USD-rate `observed_at`, admin user identity dates, and admin deal event/chat timestamps. Some used direct locale formatting, while admin deal detail returned the raw malformed value from its local `shortDate()` helper.

Risk: malformed timestamps could leak as `Invalid Date` or raw contract-breaking strings across admin/detail screens. These surfaces are used for operational diagnosis and payment/deal inspection, so a neutral timestamp boundary is preferable to browser-dependent invalid-date text.

Fix: those surfaces now use the shared safe formatter. Valid date formatting remains localized, while malformed values render as a neutral dash. Regression tests cover topup expiry, system uptime, USD rates, identity timestamps, and admin deal event/message timestamps.

### M-155. Admin deal chat double-prefixed formatted usernames

Links: `frontend/src/pages/admin/AdminDealDetailPage.tsx`, regression `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`.

The admin deal chat header prepended a literal `@` before calling `formatAdminUsername()`, even though that helper already returns `@username` for present usernames and a non-handle label for missing usernames. A normal chat row could therefore display `@@buyer`, while a missing username was rendered with an extra handle prefix before the non-handle label.

Risk: admin chat metadata looked inconsistent with other admin identity surfaces and could mislead operators when copying or comparing usernames in dispute review.

Fix: removed the extra literal prefix and kept the shared formatter as the single username boundary. Regression coverage verifies chat rows no longer render `@@username`.

### M-156. Wallet history merge sorted malformed timestamps as equal rows

Links: `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regression `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`.

The per-currency wallet history merged deposits first and withdrawals second, then sorted with `+new Date(created_at)`. For malformed `created_at`, the comparator returned `NaN`; JavaScript treats that as an equal comparison, so an invalid deposit row could remain above a valid newer withdrawal row.

Risk: corrupted or legacy timestamp data could make wallet history look out of chronological order on a money-facing screen. The row still rendered a neutral date label, but ordering remained misleading.

Fix: wallet history now sorts through the shared finite timestamp parser. Valid dated rows always sort ahead of malformed rows, equal timestamps remain stable, and regression coverage pins the malformed-deposit/newer-withdrawal merge order.

### M-157. Notification load-more sent malformed keyset cursors

Links: `frontend/src/pages/notifications/NotificationsPage.tsx`, regression `frontend/src/pages/notifications/NotificationsPage.test.tsx`.

The notifications page used the last rendered row as a keyset cursor without validating `created_at` or `id`. A malformed runtime row could send `before_created_at=not-a-date` or `before_id=0` to `GET /api/notifications`, producing a repeated late backend failure instead of a local pagination stop.

Risk: stale cache/API drift in the last visible notification could leave the load-more button issuing doomed requests and showing a generic backend error every time the user retried.

Fix: load-more now requires a finite timestamp and positive safe integer id before building the cursor. Invalid cursors stop pagination locally with the existing load-more error, and regression coverage verifies no API call is made.

### M-158. Money badges collapsed valid decimal-string payloads

Links: `frontend/src/lib/format.ts`, `frontend/src/components/domain/ServiceCard.tsx`, `frontend/src/components/domain/UserCard.tsx`, `frontend/src/pages/search/SearchPage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, regressions `frontend/src/lib/format.test.ts`, `frontend/src/components/domain/ServiceCard.test.tsx`, `frontend/src/components/domain/UserCard.test.tsx`, `frontend/src/pages/search/SearchPage.test.tsx`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`.

Several public money badges used `formatMoney()` on values that are typed as numbers locally but may cross the JSON/runtime boundary as decimal strings when serializers or generated DTOs drift. The helper only accepted finite numbers, so a valid payload like `"1500"` rendered as `$0`. At the same time, accepting arbitrary `Number()` coercion would make exponent or hex-like strings look valid.

Risk: service cards, service detail, user cards and search rows could understate a price/deposit after harmless serializer drift. On money-facing surfaces, a silent `$0` is worse than a neutral fallback because it looks like a real value.

Fix: `formatMoney()` now parses through the shared strict decimal parser. Canonical decimal strings render normally, non-finite/malformed values still fall back to `$0`, and regression coverage pins both valid string amounts and rejected `1e3`/`0x10` shapes.

### M-159. Public rating badges called `.toFixed()` on runtime payloads

Links: `frontend/src/lib/format.ts`, `frontend/src/components/domain/UserCard.tsx`, `frontend/src/components/domain/UserPicker.tsx`, `frontend/src/pages/search/SearchPage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, regressions `frontend/src/lib/format.test.ts`, `frontend/src/components/domain/UserCard.test.tsx`, `frontend/src/components/domain/UserPicker.test.tsx`, `frontend/src/pages/search/SearchPage.test.tsx`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`.

User cards, user picker rows, search rows and service detail stats called `.toFixed(1)` directly on rating fields. The backend normally emits numbers, but a string decimal from API drift or cache injection would throw during render. Malformed or out-of-range values also had no shared display boundary.

Risk: one malformed rating in a public card/list/detail payload could crash the affected React subtree and hide otherwise usable search/profile/service content.

Fix: added shared `parseRatingValue()`/`formatRatingValue()` helpers. Public rating displays now accept canonical decimal strings, reject exponent/hex and out-of-range values, and render a neutral dash for invalid ratings instead of throwing. Regression coverage exercises user cards, picker suggestions, search rows and service detail.

### M-160. Admin user/service metrics called `.toFixed()` on runtime payloads

Links: `frontend/src/lib/format.ts`, `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/pages/admin/UserContentSections.tsx`, regressions `frontend/src/pages/admin/format.test.ts`, `frontend/src/pages/admin/AdminUsersPage.test.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.test.tsx`, `frontend/src/pages/admin/UserContentSections.test.tsx`.

Admin user rows, user detail identity/rating blocks and service content rows still called `.toFixed()` directly on rating, trust-deposit and service price fields. These admin DTOs are typed as numbers, but the surrounding admin finance surfaces already had to tolerate string money projections; a string decimal here would crash the admin panel while inspecting users/content.

Risk: one malformed or stringified metric in an admin response could hide moderation controls, user identity data, or user service rows from operators.

Fix: added shared admin display helpers backed by the strict decimal/rating parsers. Canonical decimal strings render normally, malformed/exponent/hex values render as a neutral dash, and regression coverage pins list/detail/content rows.

### M-161. Admin finance/deal amount displays coerced malformed decimals to zero

Links: `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminDealsPage.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.tsx`, `frontend/src/pages/admin/AdminArbitrationPage.tsx`, `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, regressions `frontend/src/pages/admin/format.test.ts`, `frontend/src/pages/admin/AdminDealsPage.test.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`, `frontend/src/pages/admin/AdminArbitrationPage.test.tsx`, `frontend/src/pages/admin/AdminDepositsPage.test.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.test.tsx`, `frontend/src/pages/admin/AdminWalletsPage.test.tsx`.

Admin deal list/detail, arbitration, deposit, withdrawal and wallet rows still formatted runtime decimal payloads with `parseDecimal(...).toFixed(...)`. The strict parser returned zero for malformed strings, so exponent/hex/bad money payloads could render as `0.00`, `$0.00`, or a zeroed locked amount instead of an invalid value.

Risk: a malformed admin finance row could mislead operators into treating a deal, deposit, withdrawal or user balance as zero-valued while the backend value was actually invalid.

Fix: added `formatAdminAmount()` and routed the affected admin finance rows through strict amount/USD display helpers. Canonical decimal strings render normally; malformed/exponent/hex values render as a neutral dash. Regression coverage pins list/detail/arbitration/deposit/withdrawal/wallet displays.

### M-162. Public profile review ratings coerced malformed payloads to zero

Links: `frontend/src/lib/format.ts`, `frontend/src/components/domain/ProfileStatsGrid.tsx`, `frontend/src/pages/profile/ProfilePage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, regressions `frontend/src/components/domain/ProfileStatsGrid.test.tsx`, `frontend/src/pages/profile/ProfilePage.test.tsx`, `frontend/src/pages/search/UserProfilePage.test.tsx`.

Own-profile and public-profile review rows still displayed `parseDecimal(r.rating).toFixed(1)`. The strict decimal parser returns zero for malformed strings, so exponent/hex/bad rating payloads could render as a real-looking `0.0` review score. The profile stats grid also carried a local rating parser, which made public rating behavior diverge from the shared helper added for the other rating surfaces.

Risk: one malformed review rating could lower visible profile reputation to `0.0` instead of showing an invalid/neutral value, misleading users and operators while the rest of the profile remained valid.

Fix: profile stats now use the shared `parseRatingValue()`, and own/public review rows render via `formatRatingValue()`. Canonical decimal strings still render normally; malformed/exponent/hex/out-of-range ratings render as a neutral dash. Regression coverage pins the stats grid plus both review tabs.

### M-163. Admin system latency and uptime displays trusted runtime numbers

Links: `frontend/src/pages/admin/AdminSystemPage.tsx`, `frontend/src/pages/admin/format.ts`, regression `frontend/src/pages/admin/AdminSystemPage.test.tsx`.

The admin system page called `.toFixed(1)` directly on `db_latency_ms` and `redis_latency_ms`, and `formatUptime()` trusted `uptime_seconds` as a finite number. Backend schemas emit numbers, but a stringified, malformed, or compromised runtime payload could crash the system page or render `NaN` in the uptime line.

Risk: a single bad health payload could hide the operational dashboard from admins exactly when they are checking service status, or display invalid uptime/latency as real diagnostic data.

Fix: latency now goes through the strict admin decimal formatter, preserving normal decimal-string values and rendering malformed values as a neutral dash. Uptime parses through the strict decimal parser and rejects malformed/negative values. Regression coverage pins string latency, malformed latency, and malformed uptime behavior.

### M-164. Public currency precision and deal commission preview trusted runtime numbers

Links: `frontend/src/lib/format.ts`, `frontend/src/pages/deals/CreateDealPage.tsx`, regressions `frontend/src/lib/format.test.ts`, `frontend/src/pages/deals/CreateDealPage.test.tsx`.

Public wallet/deal surfaces passed API-provided currency `decimals` directly into `Intl.NumberFormat`, and the create-deal page returned `deal_commission_percent`/`vip_commission_percent` straight from the public settings DTO before calling `.toFixed()` in the preview label. Backend contracts normally emit bounded numbers, but a stringified or malformed runtime payload could still throw during render, while exponent-style balances could be coerced in the max-amount path.

Risk: one malformed public settings or currency payload could crash deal creation or wallet amount displays, hiding the form while the rest of the page data was still usable.

Fix: added a shared display-decimal resolver that accepts only integer precision in the browser-safe display range and falls back to per-currency defaults. Create-deal now parses commission settings and active balances through the strict decimal parser before preview/max calculations, falls back to the default 5% commission when settings are invalid, and keeps canonical decimal strings working. Regression coverage pins malformed precision overrides and string/malformed commission settings.

### M-165. Public wallet gates coerced malformed balance payloads

Links: `frontend/src/lib/walletAmounts.ts`, `frontend/src/pages/wallet/WalletWithdrawPage.tsx`, `frontend/src/pages/wallet/WalletPage.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regressions `frontend/src/pages/wallet/WalletWithdrawPage.test.tsx`, `frontend/src/pages/wallet/WalletPage.test.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`.

Wallet withdrawal eligibility and locked-balance hints compared runtime DTO money fields with plain JavaScript relational operators (`b.amount <= 0`, `locked > 0`). Backend contracts normally provide numbers plus canonical `*_str` mirrors, but a stringified exponent/hex payload would be coerced by JavaScript for the gate while the display formatter rejected it as malformed.

Risk: a malformed balance could appear as withdrawable or locked even though the rendered amount looked like zero/invalid, confusing users and letting them enter a withdrawal path that later fails validation.

Fix: added shared wallet balance parsing helpers that prefer canonical string money mirrors and reject malformed/exponent/hex values before gating UI state. Withdrawal options now require a strictly parsed positive balance and keep the canonical amount string for the “all” button. Wallet landing and per-currency pages now use the same strict locked-balance gate and display the string mirror. Regression coverage pins malformed withdraw balances and malformed locked hints.

### M-166. Public count displays and gates coerced malformed runtime counters

Links: `frontend/src/lib/format.ts`, `frontend/src/components/ui/ToggleTabs.tsx`, `frontend/src/components/domain/CategoryTile.tsx`, `frontend/src/components/domain/ProfileStatsGrid.tsx`, `frontend/src/components/domain/UserCard.tsx`, `frontend/src/components/domain/UserPicker.tsx`, `frontend/src/pages/search/SearchPage.tsx`, `frontend/src/pages/search/CategoriesPage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, `frontend/src/pages/profile/ProfilePage.tsx`, `frontend/src/pages/search/UserProfilePage.tsx`, regressions `frontend/src/lib/format.test.ts`, `frontend/src/pages/search/CategoriesPage.test.tsx`, `frontend/src/pages/search/SearchPage.test.tsx`, `frontend/src/pages/search/ServiceDetailPage.test.tsx`, `frontend/src/components/domain/UserCard.test.tsx`, `frontend/src/components/domain/ProfileStatsGrid.test.tsx`, `frontend/src/pages/profile/ProfilePage.test.tsx`, `frontend/src/pages/search/UserProfilePage.test.tsx`.

Public user, profile, category, and service pages trusted runtime integer counters directly. Search/category gates compared `deals_count === 0`, count labels passed values into modulo/string rendering, rating badges used raw `reviews_count` truthiness, and load-more buttons compared page lengths against `services_count` / `comments_count` / `reviews_count` with JavaScript coercion. A runtime string like `"0"` could bypass the catalog gate, while `"1e2"` or `"0x10"` could render as a real stat or drive pagination decisions.

Risk: malformed public DTO counters could make restricted search/catalog pages visible to a user with zero completed deals, show bogus trust/activity stats, or expose misleading load-more controls. These fields are not money-moving by themselves, but they are trust and access signals on user-facing discovery/profile surfaces.

Fix: added a shared non-negative safe-integer parser and count formatter. Public gates now treat missing/malformed/zero `deals_count` as restricted for non-admins; count labels and tab badges render a neutral placeholder for malformed counters; rating badges require a valid positive review count; service/category/profile comment/review pagination only trusts strict counters. Regression coverage pins string-zero gates, malformed display counters, and malformed pagination counts.

### M-167. Admin analytics trusted runtime metric numbers

Links: `frontend/src/pages/admin/AdminAnalyticsPage.tsx`, regression `frontend/src/pages/admin/AdminAnalyticsPage.test.tsx`.

Admin analytics KPI cards, sparklines and top-user lists rendered API metric fields directly. KPI cards interpolated counters as strings, volume called `toLocaleString` on the runtime value, sparklines used `Math.max`, division and `.toFixed()` on `d.value`, and top-list rows rendered `e.value` directly. A malformed payload like `"1e2"` or `"0x10"` could therefore appear as a legitimate metric or produce `NaN`/`Infinity` coordinates in the SVG polyline.

Risk: the operational analytics dashboard could show inflated/ambiguous business metrics or malformed chart geometry instead of surfacing that a metric payload was invalid. This is admin-only, but it is still a decision surface for volume, user growth, withdrawals and arbitration workload.

Fix: analytics now uses strict non-negative integer parsing for count metrics and strict plain-decimal parsing for volume/amount metrics. Malformed KPI/top-list values render a neutral dash, malformed sparkline points are dropped before plotting, and SVG points are generated only from validated finite numbers. Regression coverage pins malformed KPI values, malformed sparkline points and malformed top-list metrics.

### M-168. Public review stars coerced malformed runtime ratings

Links: `frontend/src/components/domain/ReviewRow.tsx`, regression `frontend/src/components/domain/ReviewRow.rating.test.tsx`.

Public profile review rows already rendered text rating values through a strict formatter, but the star strip still rounded `review.rating` directly. JavaScript coerces strings such as `"1e1"` and `"0x5"` to numbers before `Math.round`, so malformed runtime payloads could show five filled stars even when the textual rating path treated the same payload as invalid.

Risk: a corrupted or drifted review DTO could make an invalid review look like a perfect rating in own-profile and public-profile review lists. This is a trust-signal mismatch rather than a write-path vulnerability, but it affects the same public reputation surface as the hardened rating text.

Fix: `ReviewRow` now uses the shared strict rating parser before deriving filled stars. Malformed, exponent/hex-like and out-of-range values render zero filled stars; canonical decimal-string ratings still render normally. Regression coverage pins valid decimal strings and malformed runtime rating strings.

### M-169. Notification counters coerced malformed runtime unread counts

Links: `frontend/src/api/hooks.ts`, `frontend/src/components/layout/BottomNav.tsx`, `frontend/src/pages/notifications/NotificationsPage.tsx`, regressions `frontend/src/components/layout/BottomNav.test.tsx`, `frontend/src/pages/notifications/NotificationsPage.test.tsx`, `frontend/src/lib/useLiveNotifications.test.tsx`.

The bottom nav badge and notifications header compared `counters.unread` directly, while the optimistic/read-event cache updater decremented cached counters with `(prev[key] ?? 0) - delta`. Runtime strings such as `"1e2"` and `"0x10"` therefore became valid-looking unread counts or were rewritten into numeric cache values during local mark-read mirroring.

Risk: a malformed notification counter payload could show a bogus unread badge/header action or make a cross-tab `notification.read` event normalize corrupted counters into believable numbers. This is user-facing state rather than authorization, but it is still a notification reliability and trust signal.

Fix: unread badge/header decisions now parse counters with the shared non-negative safe-integer parser. Local read-cache decrement also parses each cached counter before arithmetic and leaves malformed values uncoerced so display boundaries can treat them as invalid. Regression coverage pins malformed bottom-nav/header unread counters and malformed cached counters during WS read mirroring.

### M-170. Admin list pagination coerced malformed runtime totals and counters

Links: `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminDealsPage.tsx`, `frontend/src/pages/admin/AdminAuditPage.tsx`, `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminBroadcastsPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/pages/admin/UserContentSections.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, `frontend/src/pages/admin/AdminArbitrationPage.tsx`, regressions `frontend/src/pages/admin/format.test.ts`, `frontend/src/pages/admin/AdminDealsPage.test.tsx`, `frontend/src/pages/admin/AdminAuditPage.test.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.test.tsx`.

Several admin list pages computed pagination or queue badges directly from `data.total`, `data.page_size`, or `counters[...]`. Runtime strings like `"1e2"` and `"0x10"` were coerced by comparisons, `Math.ceil`, and direct rendering into valid-looking counts/pages.

Risk: malformed admin DTO counters could show bogus queue badges, enable unexpected pagination, or make operational lists look larger than the server's validated contract. This affects admin decision surfaces across deals, audit, wallets, deposits, broadcasts, user content, withdrawals and arbitration queues.

Fix: added shared strict admin count helpers for count display and pagination math. Admin list totals/page sizes/status counters now require non-negative safe integers before display, badge rendering, or total-page calculations. Malformed totals fall back to a neutral dash/no pagination, and malformed queue counters are not shown as badges. Regression coverage pins malformed totals/counters.

### M-171. Account-transfer UI trusted malformed runtime policy values

Links: `frontend/src/pages/profile/AccountTransferPage.tsx`, regression `frontend/src/pages/profile/AccountTransferPage.test.tsx`.

The account-transfer page used `status.data.code_length` directly in the confirmation regex, input `slice()` limit, placeholder generation, disabled-state comparison, and error copy. It also rounded `ttl_seconds` directly for the visible TTL label. Runtime values like `"1e2"` and `"0x10"` were therefore coerced by JavaScript into large or misleading values, and `code_length=0` could enable the confirm button for an empty local code before the backend rejected it.

Risk: a malformed account-transfer policy payload could make the receive-code UI impossible to use, show a misleading TTL, or let a zero-length policy activate an empty-code confirm path. The backend still enforces the real code policy, but the frontend was presenting a broken security-sensitive workflow instead of failing back to a bounded local policy.

Fix: account-transfer code length and TTL now pass through strict positive safe-integer parsing. Code length falls back to the default 6 digits unless it is a positive integer within the backend request cap of 32; TTL falls back to the default 15 minutes unless it is a positive integer. Regression coverage pins malformed exponent/hex-like values and zero-length policy values.

### M-172. Public stats badge coerced malformed runtime counters during animation

Links: `frontend/src/components/domain/StatsBadge.tsx`, regression `frontend/src/components/domain/StatsBadge.test.tsx`.

`StatsBadge` animated `/api/stats/public` and admin-settings preview values directly. The component's TypeScript interface said `users`, `deals`, and `total_usd` were numbers, but at runtime a malformed payload like `"1e2"`, `"0x10"`, or `"bad"` still reached the count-up arithmetic and compact formatters. JavaScript then coerced exponent/hex-like strings into legitimate-looking public counters or propagated `NaN` into the rendered USD badge.

Risk: the FAQ/public trust badge and admin settings preview could display bogus platform statistics instead of treating the DTO as corrupt. Because this badge is a public credibility surface, malformed counter coercion can mislead users even though it does not move money.

Fix: public stats counters now use the shared strict non-negative safe-integer parser, and USD volume accepts only finite non-negative canonical decimal values. Malformed counters/volume fall back to zero before animation and formatting, while canonical decimal-string runtime values still render correctly. Regression coverage pins both accepted canonical strings and rejected exponent/hex/malformed values.

### M-173. Admin displayed totals still trusted malformed runtime counters

Links: `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminBroadcastsPage.tsx`, `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/pages/admin/UserContentSections.tsx`, regressions `frontend/src/pages/admin/AdminBroadcastsPage.test.tsx`, `frontend/src/pages/admin/AdminDepositsPage.test.tsx`, `frontend/src/pages/admin/AdminWalletsPage.test.tsx`, `frontend/src/pages/admin/AdminUsersPage.test.tsx`, `frontend/src/pages/admin/UserContentSections.test.tsx`.

M-170 hardened admin pagination math and several queue badges, but some admin display surfaces still interpolated raw `data.total` values. Broadcast history also rendered `total_recipients`/`delivered_count` directly, and preview/create success paths trusted `total_recipients` in visible counters/toasts. User-content sections still used `data.total > 0` for empty-page rewind, so runtime strings like `"1e2"` could be coerced by JavaScript even after pagination stopped trusting them.

Risk: malformed DTO counters could still mislead operators in broadcasts, deposits, users, wallets, and user content sections, or silently move an admin off a page through a coerced empty-page rewind.

Fix: these surfaces now route displayed totals and broadcast recipient counts through `formatAdminCount`, and user-content rewind checks use `parseAdminCount` before comparing. Malformed totals/counters render as a neutral dash, do not appear raw in subtitles/headers/toasts, and no longer trigger empty-page rewind logic. Regression coverage pins malformed admin totals, broadcast list/preview/create counts, and user-content total rewinds.

### M-174. Admin dashboard KPI tiles coerced malformed runtime counters

Links: `frontend/src/pages/admin/AdminDashboardPage.tsx`, shared formatter `frontend/src/pages/admin/format.ts`, regression `frontend/src/pages/admin/AdminDashboardPage.test.tsx`.

The admin dashboard rendered `/api/admin/dashboard` counters directly in KPI tiles and used raw comparisons like `data.open_arbitration > 0` / `data.banned_users > 0` to add urgent accent rings. Runtime strings such as `"1e2"` or `"0x10"` could therefore appear as credible admin counts, and JavaScript coercion could mark arbitration or banned-user tiles as urgent even though the payload was malformed.

Risk: the dashboard is the admin landing page, so malformed counters could mislead operators before they enter the stricter list pages fixed by M-170/M-173.

Fix: KPI tile values now use `formatAdminCount`, and accent rings use `parseAdminCount` before comparing to zero. Malformed counters render as a neutral dash and do not trigger urgent styling. Regression coverage pins malformed display values and positive-looking malformed accent inputs.

### M-175. Positive money gates trusted malformed runtime amounts

Links: `frontend/src/pages/wallet/WalletDepositPage.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, shared helpers `frontend/src/lib/walletAmounts.ts`, `frontend/src/lib/format.ts`, regressions `frontend/src/pages/wallet/WalletDepositPage.test.tsx`, `frontend/src/pages/deals/DealDetailPage.test.tsx`.

Several frontend money surfaces already formatted malformed amounts as neutral values, but their visibility gates still compared raw runtime payloads. The wallet deposit page used `(balance?.amount ?? 0) > 0` before showing the available-balance hint, and deal detail used `deal.commission_amount > 0` before rendering the commission row. Runtime strings like `"1e2"` could pass those gates through JavaScript coercion even though the display formatter would reject the amount.

Risk: users could see balance/commission rows that should have been treated as corrupt input, including misleading zero/neutral displays opened by a positive-looking malformed payload.

Fix: wallet deposit now uses the shared wallet decimal parser and displays the canonical `amount_str` mirror when present. Deal detail parses `commission_amount` with the strict decimal parser before both visibility and formatting. Malformed exponent-like values no longer open either row, while canonical decimal strings still render.

### M-176. Deal topup invoice rows displayed runtime amount fields directly

Links: `frontend/src/pages/deals/CreateDealPage.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, shared parser `frontend/src/lib/format.ts`, regressions `frontend/src/pages/deals/CreateDealPage.test.tsx`, `frontend/src/pages/deals/DealDetailPage.test.tsx`.

The create-deal invoice preview and deal-detail topup invoice card rendered invoice money DTO fields by interpolation: `topup_principal`, `commission`, `total`, and the already-paid value once its gate opened. Earlier fixes hardened the paid-total visibility gate, but malformed runtime values such as `"1e2"` or `"0x10"` could still appear as credible invoice money in rows that were already visible.

Risk: a buyer could see a corrupt or ambiguous invoice amount in the same UI that opens the payment flow, making support/debugging harder and potentially encouraging payment against a value the frontend should have treated as invalid input.

Fix: invoice amount rows now parse runtime values with the strict decimal parser and render a neutral `—` amount when the value is malformed or negative. Metadata rows keep their previous raw labels, valid canonical decimal strings still render, and regressions cover create-response invoice rows plus deal-detail pending-topup totals.

### M-177. Admin identity labels displayed malformed runtime ids and counts directly

Links: `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminAuditPage.tsx`, `frontend/src/pages/admin/AdminUsersPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, regressions in the adjacent tests.

Most admin counters were already strict, but several operational identity labels still interpolated DTO fields directly: audit `actor_id`/`target_id`, admin-user-list `tg_user_id`/`deals_total`, and admin-user-detail `tg_user_id`/`login_count`. Runtime payloads like `"1e2"` or `"0x10"` could therefore appear as credible user IDs or counts in admin audit and identity surfaces.

Risk: these are operator-facing investigation screens. A malformed identifier rendered raw can send an admin to the wrong mental model while tracing audit events, users, bans, freezes, or trust-deposit changes.

Fix: added shared `formatAdminId()` on top of the strict integer parser and routed audit/user identity labels through strict id/count formatters. Malformed or zero identifiers render as a neutral dash, valid numeric strings remain supported, and regressions cover audit actor/target IDs plus admin user list/detail identity counters.

### M-178. Deal topup payment action stayed enabled after malformed invoice totals

Links: `frontend/src/pages/deals/DealDetailPage.tsx`, shared parser `frontend/src/lib/format.ts`, regression `frontend/src/pages/deals/DealDetailPage.test.tsx`.

M-176 hardened how pending-topup invoice totals are displayed, but the buyer action still rendered `Открыть оплату` whenever a `topup_invoice` object existed. A malformed runtime `total` could therefore show a neutral dash in the invoice row while the same card still opened the upstream provider link.

Risk: the UI could invite payment even after it had already classified the payable amount as invalid. That weakens the money-flow invariant that display, action gating, and modal/payment entry all agree on the same strict invoice total.

Fix: deal detail now parses `topup_invoice.total` with the strict decimal parser before enabling payment actions. The provider link is only shown for buyer-side pending topups with a valid positive total; the cancel action remains available so the user is not trapped behind a corrupt invoice payload.

### M-179. Payment modals auto-opened provider links from malformed invoice amounts

Links: `frontend/src/components/wallet/DealInvoiceModal.tsx`, `frontend/src/components/wallet/DepositStatusModal.tsx`, shared parser `frontend/src/lib/format.ts`, regression `frontend/src/components/wallet/PaymentModals.amounts.test.tsx`.

M-178 hardened the deal-detail card, but the reusable deal-invoice modal and wallet-deposit modal still trusted their `amount` props for payment entry. Runtime values such as `"1e2"` or `"0x10"` were formatted through the legacy zero-coercing money formatter while the modal could still auto-open the upstream provider after its delay or keep a clickable payment CTA.

Risk: a corrupt invoice amount could reach the last payment-entry surface. Even if the backend/provider ultimately enforces the real invoice, the frontend would present a provider link after showing an amount it should have treated as invalid.

Fix: both payment modals now parse invoice amounts with the strict decimal parser, render a neutral dash for malformed/negative values, and require a valid positive amount before auto-opening or clicking the provider payment link. Regressions pin malformed deal topup and wallet deposit modal amounts.

### M-180. Public money summaries masked malformed runtime amounts as `$0`

Links: `frontend/src/lib/format.ts`, public surfaces `frontend/src/components/domain/UserCard.tsx`, `frontend/src/components/domain/ProfileStatsGrid.tsx`, `frontend/src/components/domain/ServiceCard.tsx`, `frontend/src/pages/search/SearchPage.tsx`, `frontend/src/pages/search/ServiceDetailPage.tsx`, `frontend/src/pages/wallet/WalletPage.tsx`, regressions in the adjacent tests.

The shared `formatMoney()` helper still used the legacy zero-coercing decimal parser. Runtime values like `"1e3"`, `"0x10"`, `NaN`, or negative numbers therefore rendered as credible `$0` or signed public money values in user cards, profile stats, service cards/details, search rows, and the wallet trust-deposit summary.

Risk: public trust and price surfaces could silently understate corrupt values instead of flagging them as invalid. That is especially misleading for service price, trust deposit, and total-deals money summaries because `$0` looks like a valid business value.

Fix: `formatMoney()` now uses the strict decimal parser and returns a neutral fallback for malformed or negative values while preserving canonical decimal-string amounts. Regressions cover the shared helper and the affected user/profile/service/search/wallet surfaces.

### M-181. Deal amount displays coerced malformed runtime totals to zero

Links: `frontend/src/lib/format.ts`, `frontend/src/components/domain/DealRow.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, regressions `frontend/src/lib/format.test.ts`, `frontend/src/components/domain/DealRow.test.tsx`, `frontend/src/pages/deals/DealDetailPage.test.tsx`.

After M-180, the deal-specific `formatAmount()` helper still used the legacy zero-coercing parser. Runtime deal totals such as `"1e2"`, `"0x10"`, `NaN`, or negative values could therefore render as `0 USDT`/`0 USD` in the deal list and detail header.

Risk: a corrupted escrow amount could look like a legitimate zero-value deal rather than invalid data. This is misleading in the primary money view for deal participants and can hide the same kind of DTO drift already hardened in invoice and public-money surfaces.

Fix: `formatAmount()` now uses the strict decimal parser and returns a neutral fallback for malformed or negative values while preserving canonical decimal-string amounts and currency precision. Regressions pin malformed deal list and deal detail totals.

### M-182. Wallet balance displays coerced malformed runtime balances to zero

Links: `frontend/src/lib/walletAmounts.ts`, `frontend/src/pages/wallet/WalletPage.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, `frontend/src/components/domain/ProfileFiatBalanceCard.tsx`, regressions `frontend/src/lib/walletAmounts.test.ts`, `frontend/src/pages/wallet/WalletPage.test.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`, `frontend/src/components/domain/ProfileFiatBalanceCard.test.tsx`.

The wallet DTO already exposes canonical `amount_str`/`locked_str` mirrors, but the user-facing balance displays still passed those runtime strings through the legacy zero-coercing `formatCurrency()` helper. Values such as `"1e2"`, `"0x10"`, `NaN`, or negative strings could therefore render as credible `0 USD`/`0 USDT` balances on the wallet list, per-currency balance header, and profile fiat-balance card.

Risk: a corrupted available balance looked like a legitimate empty wallet instead of invalid data. That is especially misleading on withdrawal/top-up entry points because the user can interpret `0 CODE` as a real account state rather than a DTO/runtime validation failure.

Fix: wallet balance display now uses a strict formatter built on the existing `walletAmounts` parser. Missing balance rows still render as `0 CODE`, while malformed or negative runtime balance fields render as a neutral dash with the currency code. Regressions cover the shared helper and the three affected user-facing balance surfaces.

### M-183. Wallet/admin balance gates still mixed strict display with zero-coercing visibility

Links: `frontend/src/lib/walletAmounts.ts`, `frontend/src/pages/wallet/WalletPage.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, `frontend/src/pages/admin/format.ts`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, regressions in the adjacent wallet/admin tests.

After M-182, the primary wallet balances were strict, but locked-hint rendering still formatted `locked_str` directly. A positive numeric `locked` fallback with a blank string mirror could pass the visibility gate and then render as `+0 CODE`. Admin wallet grids had the inverse issue: they used strict display formatting, but filtered/defaulted balances through legacy `parseDecimal(total)`, so malformed totals such as `"1e2"` could hide a valid `amount`/`locked` balance or choose the wrong default currency in an adjustment sheet.

Risk: users could see a misleading zero locked amount, while admins could miss a real balance row or apply a manual adjustment against the wrong default currency after DTO drift in `total`.

Fix: wallet locked hints now reuse the same strict wallet-balance formatter as available balances. Admin balance visibility/default selection now uses strict decimal parsing and falls back to valid positive `amount`/`locked` fields when `total` is malformed instead of collapsing the row to zero. Regressions cover blank locked string mirrors, malformed admin totals, and adjustment default currency selection.

### M-184. Create-deal balance previews still trusted malformed runtime wallet amounts

Links: `frontend/src/pages/deals/CreateDealPage.tsx`, shared wallet parser `frontend/src/lib/walletAmounts.ts`, regression `frontend/src/pages/deals/CreateDealPage.test.tsx`.

After M-182/M-183, wallet screens and admin balance gates were strict, but the create-deal form still read `WalletBalanceDto.amount` directly for the funded-currency default, the "На балансе" hint, the balance-funded preview, and the `Макс` button. If the runtime `amount` was malformed such as `"1e2"` while canonical `amount_str` was valid, the deal form could miss a funded fiat row, show `0 USD`, hide `Макс`, or compute the balance-funded preview from the wrong value.

Risk: the primary escrow creation surface could disagree with wallet displays about the same balance. A buyer with a valid canonical balance could be pushed into an unnecessary top-up flow, while the amount preview and `Макс` affordance no longer matched the backend wallet projection.

Fix: create-deal now uses the shared wallet amount parser/formatter for default currency selection, balance hints, full-balance gating, and `Макс` calculation. Regressions cover malformed runtime `amount` with valid `amount_str` for default currency selection, displayed hint text, and balance-funded preview math.

### M-185. Wallet deposit payment entry still opened links after malformed runtime amounts

Links: `frontend/src/lib/format.ts`, `frontend/src/pages/wallet/WalletDepositPage.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, `frontend/src/pages/wallet/WalletTrustDepositPage.tsx`, regressions in the adjacent tests.

The deposit status modals were already hardened, but the wallet deposit pages still opened `dep.pay_url` directly after `createDeposit` succeeded and formatted `dep.amount` with the legacy zero-coercing currency formatter. Per-currency wallet history had the same display issue: malformed deposit/withdrawal amounts such as `"1e2"` or `"0x10"` rendered as signed `0 CODE`, and pending deposit rows could still expose the payment link.

Risk: a corrupted invoice or history payload could reach the payment-entry surface after the UI had enough information to classify the amount as invalid. Users could be sent to an upstream provider or see a credible zero-value operation instead of a neutral invalid-data state.

Fix: added a strict currency formatter for runtime money values that preserves canonical decimal strings but renders malformed/negative values as a neutral dash. Wallet deposit, per-currency deposit, and trust-deposit submit paths now require a strict positive created amount before opening `pay_url`; wallet history renders malformed operation amounts neutrally and hides pay links unless the amount is valid and positive. Regressions cover malformed create responses and malformed history rows.

### M-186. Admin finance actions stayed enabled on rows with invalid amounts

Links: `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, shared admin parser `frontend/src/pages/admin/format.ts`, regressions in the adjacent tests.

Admin deposit and withdrawal queues already rendered malformed amounts such as `"1e3"`/`"1e1"` as a neutral dash, but the action gates still depended only on row status. A pending deposit with an invalid amount could still expose `pay_url` and "mark paid"; a paid deposit could still expose refund; a pending withdrawal could still be approved; and an approved withdrawal could still be marked sent.

Risk: admin operators could trigger money-moving mutations on the same rows the UI had already classified as invalid money data. That weakens the invariant that display and action gating agree before payment, credit, refund, or payout decisions.

Fix: admin deposit `pay_url`, mark-paid, refund, withdrawal approve, and withdrawal mark-sent actions now require a strict positive runtime amount via the shared admin decimal parser. Withdrawal reject remains available so an operator can safely close a malformed pending request. Regressions cover malformed deposit mark/refund/pay-url gates and malformed withdrawal approve/mark-sent gates.

### M-187. Admin deal force actions stayed enabled after malformed deal amounts

Links: `frontend/src/pages/admin/AdminDealDetailPage.tsx`, shared admin parser `frontend/src/pages/admin/format.ts`, regression in `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`.

Admin deal detail already rendered malformed deal amounts as a neutral dash via the strict admin formatter, but the force-release, force-refund, and split buttons were gated only by terminal status. A corrupted runtime `deal.amount` such as `"1e3"` could therefore leave money-moving admin sheets available on the same screen that no longer displayed a valid amount.

Risk: an operator could start a release/refund/split flow without a trustworthy displayed principal. Even though the backend owns final accounting, the admin UI should not present irreversible money actions when its own runtime boundary has classified the principal as invalid.

Fix: force-release, force-refund, and split now require `hasPositiveAdminDecimal(deal.amount)` before the buttons open their sheets or the confirm handler sends a mutation. Arbitration, assign, and delete remain available so admins can still investigate or close a malformed deal. The regression covers malformed deal amount display plus the enabled/disabled split between money-moving and non-money actions.

### M-188. Admin deal approval rows rendered raw malformed money

Links: `frontend/src/pages/admin/AdminDealDetailPage.tsx`, shared admin parser/formatters `frontend/src/pages/admin/format.ts`, regression in `frontend/src/pages/admin/AdminDealDetailPage.test.tsx`.

The pending approval panel on admin deal detail rendered `amount` and `amount_usd_estimate` directly from the runtime DTO. A corrupted approval payload could therefore show values such as `"1e3"` or `"0x10"` as if they were trustworthy approval amounts, while the adjacent `OK` button remained available.

Risk: a second admin could approve a money-moving request without a strictly parsed principal on the screen. That weakens the two-admin approval UX: the reviewer is meant to approve an exact amount, not a raw malformed DTO string.

Fix: approval rows now render native amounts with the strict admin amount formatter and USD estimates with the strict USD formatter. Pending approval `OK` is disabled unless the native approval amount is a strict positive decimal; `Reject` remains available so malformed approval requests can be closed. The regression covers neutral rendering plus the OK/Reject enabled split.

### M-189. Paid PIN reset paywall trusted raw runtime money

Links: `frontend/src/components/PinResetPaywallModal.tsx`, shared formatter `frontend/src/lib/format.ts`, regression in `frontend/src/components/PinResetPaywallModal.test.tsx`, OpenAPI contract `frontend/src/api/openapi.generated.ts`.

OpenAPI exposes PIN reset `price`, `user_balance`, and paid `charged` as decimal strings, but the paywall component typed the values as numbers and rendered them directly. It also enabled "pay from balance" from the server `can_afford` flag alone. A malformed runtime payload such as `"1e2"` / `"0x10"` could therefore appear in the paywall or success toast as a credible amount, and a bad `can_afford: true` could leave the balance-payment entry active.

Risk: the paid PIN reset flow can debit a wallet balance, so the user must see validated price and balance data before clicking. Raw malformed DTO strings or an unchecked affordability flag make the payment surface look trustworthy when the frontend has not actually parsed the money fields.

Fix: the paywall now accepts string/number runtime money, formats price, balance, and charged values through the strict currency formatter, and enables balance payment only when price and balance parse as non-negative decimals and the parsed balance covers the parsed price. Malformed price data renders a neutral state and leaves the admin-contact path available. Regressions cover malformed price/balance display, disabled payment entry, and malformed charged amounts in the success toast.

### M-190. Admin wallet money forms rounded Decimal inputs before submit

Links: `frontend/src/pages/admin/AdminWalletsPage.tsx`, DTO type `frontend/src/api/types.ts`, OpenAPI contract `frontend/src/api/openapi.generated.ts`, backend Decimal schemas `backend/app/schemas.py`, regression in `frontend/src/pages/admin/AdminWalletsPage.test.tsx`.

The admin wallet adjustment form and USD-rate form validated plain decimal input strings, but then sent the parsed JavaScript `number` to the API. The backend schemas accept `Decimal`, and OpenAPI already allows `number | string` for these payloads, so the frontend was needlessly round-tripping precise admin-entered money/rate values through IEEE-754 before the backend could parse them.

Risk: manual balance adjustments are direct money-moving operations, and USD rates affect displayed estimates. A value such as `0.123456789123456789` is a valid decimal string but cannot be represented exactly as a JavaScript number, so the request body could differ from what the admin typed.

Fix: both forms still use the strict decimal parser for UI validation and disabled-state gating, but the mutation payload now sends the trimmed decimal string. The local admin wallet DTO was widened to match OpenAPI, and regressions assert exact string payloads for high-precision adjustment and USD-rate inputs.

### M-191. Remaining admin Decimal submit paths still rounded precise inputs

Links: `frontend/src/pages/admin/AdminSettingsPage.tsx`, `frontend/src/pages/admin/AdminTaxonomyPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/pages/admin/UserContentSections.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, DTO type `frontend/src/api/types.ts`, OpenAPI contract `frontend/src/api/openapi.generated.ts`, backend Decimal schemas `backend/app/schemas.py`, regressions in the adjacent admin page tests.

After M-190, the main admin wallet page preserved decimal strings, but several neighboring admin forms still validated plain decimal input and then submitted JavaScript numbers: settings commission/FAQ/PIN reset amounts, currency `min_deposit`/`min_withdraw`, user `deals_sum_override`, trust-deposit totals, the per-user balance adjustment form, and service `price`/`deposit`/`rating_manual`. One wallet shortcut also changed signs through `Math.abs(parsed)`, which could round a precise string before submit.

Risk: these admin controls write money, rates, public profile totals, or fee configuration. A value such as `0.123456789123456789` is accepted by the backend Decimal schemas and OpenAPI already allows string payloads for these fields, but the frontend could silently alter it before the backend parsed it.

Fix: the affected forms still use the strict decimal parsers for validation and disabled-state gating, but submit trimmed or normalized decimal strings for Decimal fields while leaving integer fields numeric. The wallet sign shortcut now preserves the original decimal string while flipping only the sign. Local DTOs were widened to match OpenAPI, and regressions assert exact high-precision string payloads across settings, taxonomy, user detail stats/trust/balance, services, and the wallet shortcut.

### M-192. User service price submit still rounded precise Decimal inputs

Links: `frontend/src/pages/profile/AddServicePage.tsx`, `frontend/src/api/hooks.ts`, OpenAPI contract `frontend/src/api/openapi.generated.ts`, backend Decimal schemas `backend/app/schemas.py`, regression `frontend/src/pages/profile/AddServicePage.test.tsx`.

The admin service editor was covered in M-191, but the owner-facing "add service" form still validated a plain decimal price and submitted the parsed JavaScript `number`. The backend `ServiceCreate.price` and `ServiceUpdate.price` schemas accept `Decimal`, and OpenAPI already allows `number | string` for those request bodies, so the local hook types were also narrower than the generated contract.

Risk: a seller entering a precise service price such as `0.123456789123456789` could have the value rounded by IEEE-754 before the backend parsed it. That makes the stored listing price differ from the user-visible input and from the backend Decimal contract.

Fix: service creation now keeps using the strict decimal parser for validation, but submits the trimmed decimal string (or `"0"` for an empty price). The public service create/update hooks now accept string prices in line with OpenAPI. A regression asserts that high-precision service prices reach `useCreateService` unchanged.

### M-193. Admin deal amount filters still rounded Decimal query params

Links: `frontend/src/pages/admin/AdminDealsPage.tsx`, DTO type `frontend/src/api/types.ts`, OpenAPI contract `frontend/src/api/openapi.generated.ts`, backend Decimal query params `backend/app/routers/admin/deals.py`, regression `frontend/src/pages/admin/AdminDealsPage.test.tsx`.

The admin deal list accepted `min_amount`/`max_amount` URL and sheet filters as plain decimal strings, but parsed them through JavaScript `Number` before passing them to `useAdminDeals`. The backend query parameters are `Decimal | None`, and the generated OpenAPI contract allows `number | string`, so precise filters such as `0.123456789123456789` were rounded before the backend could compare them.

Risk: an admin searching for exact high-precision deal amounts could receive a broader or narrower result set than requested. Reversed-range validation also depended on rounded numbers, so two adjacent decimal strings could be misclassified after coercion.

Fix: admin deal filters now keep validated decimal filters as trimmed strings, and range validation compares normalized decimal strings directly instead of using `Number`. The local DTO was widened to match OpenAPI, and regressions assert exact high-precision URL filters plus exact reversed-range rejection.

### M-194. Admin split ledger normalized Decimal percent through float

Links: `backend/app/routers/admin/deals.py`, Decimal request schema `backend/app/schemas.py`, regression `tests/integration/test_admin_deals.py`.

The admin deal split endpoint validated `buyer_percent` as `Decimal`, but then converted it to `float` before calculating the split and writing wallet ledger metadata. The calculation used `Decimal(str(...))`, so common two-decimal shares usually avoided binary artifacts, but canonical operator input such as `"33.30"` was still stored in ledger meta as `"33.3"` while the approval payload and admin audit payload kept `"33.30"`.

Risk: the wallet ledger is the forensic trail for money movement. Losing the canonical decimal text makes ledger rows disagree with the approval/audit trail for the same operation, which weakens reconciliation and makes exact operator intent harder to prove after the fact.

Fix: `_split_locked` now accepts the validated `Decimal` directly and uses it for both share calculation and ledger metadata. A regression posts a `"33.30"` split and asserts exact buyer/seller ledger deltas, ledger meta, and audit payload values.

### M-195. Admin service audit payloads rounded Decimal money fields

Links: `backend/app/routers/admin/content.py`, Decimal request schema `backend/app/schemas.py`, regressions `tests/integration/test_admin_content.py`.

The admin service editor compared `price`, `deposit`, and `rating_manual` as `Decimal`, but wrote the audit `before`/`after` payload through `float(...)`. The service delete audit snapshot also cast `price` to float and omitted `deposit`, even though the deleted row is no longer available for later reconciliation.

Risk: admin service edits and deletes are part of the permanent audit trail. JSON numbers can round precise money fields, and deleting a service without a deposit snapshot removes useful monetary context from the only remaining forensic record.

Fix: admin content audit payloads now store Decimal fields as canonical strings. Service delete snapshots also include `deposit` and `rating_manual`. Regressions cover precise edit payloads plus delete snapshots after the service row is gone.

### M-196. Admin settings audit payloads rounded Decimal settings

Links: `backend/app/routers/admin/settings.py`, Decimal request schema `backend/app/schemas.py`, regression `tests/integration/test_admin_misc.py`.

The settings editor already compared Decimal fields without using `float`, but its `settings.update` audit payload converted changed Decimal values through `float(...)`. This affected money-like settings such as `pin_reset_price_usd` and `faq_stats_total_usd`, where the database column is `Numeric(28, 8)` and the request schema accepts Decimal input.

Risk: settings changes are operationally important and the audit trail is the durable record of who changed fee/price/stat values. JSON numbers can round the exact Decimal value that was stored, making later reconciliation compare against a lossy audit value.

Fix: Decimal settings now write canonical strings to the audit `before`/`after` payload while preserving Decimal comparison and the existing API response shape. The regression updates precise PIN-reset and FAQ total values and asserts exact audit strings.

### M-197. Admin currency audit payloads rounded limits and omitted delete context

Links: `backend/app/routers/admin/taxonomy.py`, Decimal request schema `backend/app/schemas.py`, regressions `tests/integration/test_admin_taxonomy_currencies.py`.

The currency upsert endpoint wrote `min_deposit` and `min_withdraw` audit values through two lossy paths: the update `before` snapshot used `float(...)`, and the update `after` snapshot came from `AdminCurrencyOut.model_dump()`, whose `MoneyDecimal` serializer also emits floats. The delete snapshot omitted limit, icon, regex, and kind fields entirely.

Risk: currency limits control deposit/withdrawal validation and are reference data that may be deleted after operational cleanup. Rounding the update audit payload or deleting a row without the full snapshot weakens the only durable record of the exact limits and validation policy that existed at the time.

Fix: currency audit snapshots now use a dedicated helper that stores Decimal limits as strings and includes the full relevant currency context. Regressions cover precise create/update audit payloads plus a delete snapshot after the currency row is gone.

### M-198. PIN attempts counters trusted malformed runtime values

Links: `frontend/src/pages/pin/PinPage.tsx`, `frontend/src/pages/pin/PinResetPage.tsx`, shared formatter `frontend/src/lib/format.ts`, regressions in the adjacent PIN page tests.

The PIN unlock screen rendered `status.attempts_left` directly, and the standalone PIN reset page rendered any value whose runtime type was `number`. If a stale API/client boundary, corrupted test fixture, or malformed runtime payload supplied `NaN`, `Infinity`, a negative value, or another unsafe number, the lock/recovery UI could show misleading text such as `NaN` attempts left.

Risk: the PIN screens are security UX. Users should not receive impossible or malformed lockout/retry counters while deciding whether to retry, wait, or start account recovery.

Fix: the unlock screen now formats attempts through the shared strict non-negative count formatter, and the reset page only renders the counter after strict safe-integer validation. Regressions cover malformed attempts counters on both PIN surfaces.

### M-199. Admin user wallet/content rows trusted malformed runtime numbers

Links: `frontend/src/pages/admin/AdminUserDetailPage.tsx`, `frontend/src/pages/admin/UserContentSections.tsx`, shared admin formatters `frontend/src/pages/admin/format.ts`, regressions in the adjacent admin page tests.

The admin user detail balance section rendered `AdminUserBalanceDto.total` directly, and the user content rows rendered service `deals_count`, service `rating_manual`, review `rating`, and comment `rating` directly. Other admin list totals and money cells already used strict formatters, so malformed runtime payloads such as `"1e2"` or `"0x10"` could still appear as credible balances, counters, or ratings inside these nested user-detail sections.

Risk: these rows are operator-facing evidence while reviewing a user account. Raw malformed balances/counters/ratings can make a corrupted DTO look intentional and can disagree with adjacent strict admin surfaces.

Fix: per-user wallet totals now use the strict admin amount formatter with currency decimals. User content rows use the shared admin count and rating formatters, preserving canonical values while rendering malformed runtime numbers as a neutral dash. Regressions cover malformed wallet totals, invalid currency decimals, service row counters/ratings, review ratings, and comment ratings.

### M-200. Admin taxonomy/system rows still trusted malformed runtime numbers

Links: `frontend/src/pages/admin/AdminTaxonomyPage.tsx`, `frontend/src/pages/admin/AdminSystemPage.tsx`, shared admin formatters `frontend/src/pages/admin/format.ts`, regressions in the adjacent admin page tests.

After the broader admin numeric-display hardening, two operator-facing rows still printed DTO numbers directly: taxonomy currency rows rendered `min_deposit` / `min_withdraw` as raw runtime values, and system operational alerts rendered `alert.count` directly. A malformed payload such as `"1e2"` or `"0x10"` could therefore appear as a credible currency limit or alert count while neighboring admin surfaces already showed neutral values for the same malformed shapes.

Risk: currency limits and operational alerts are decision surfaces for admins. Raw malformed numbers can make a corrupted DTO look like intentional configuration or a real system count, which weakens triage and auditability.

Fix: taxonomy currency limits now use the strict admin amount formatter with each currency's decimals, and operational alert counts use the strict admin count formatter. Regressions cover malformed currency limits and malformed alert counts rendering as neutral dashes without leaking the raw DTO strings.

### M-201. Create-deal insufficient-funds errors trusted malformed runtime money

Links: `frontend/src/pages/deals/CreateDealPage.tsx`, shared currency-code normalizer `frontend/src/lib/currencyCodes.ts`, regression `frontend/src/pages/deals/CreateDealPage.test.tsx`.

The create-deal page parsed the structured `insufficient_funds` error by checking only that `required`, `balance`, `deficit`, and `currency_code` were strings. It then rendered those values directly in the toast and inline alert. A malformed runtime payload such as `"1e2"` / `"0x10"` or a non-contract currency code could therefore appear as a credible balance hint while the rest of the create-deal money path used strict decimal parsing.

Risk: the insufficient-funds alert is shown exactly when the user is deciding whether to reduce the deal amount or fund the wallet. Invalid money fields or currency labels in that alert can mislead the user about how much is missing or which wallet is involved.

Fix: the structured error parser now accepts only strict non-negative decimal strings and a normalized contract currency code. Malformed `insufficient_funds` payloads fall back to a safe generic balance-check error instead of rendering raw JSON or raw money strings. Regressions cover valid normalized currency codes, malformed money fields, malformed currency codes, and partial structured payloads.

### M-202. Deal and invoice money surfaces trusted runtime currency labels

Links: `frontend/src/components/domain/DealRow.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, `frontend/src/pages/deals/CreateDealPage.tsx`, `frontend/src/components/wallet/DealInvoiceModal.tsx`, `frontend/src/components/wallet/DepositStatusModal.tsx`, shared normalizer `frontend/src/lib/currencyCodes.ts`, regressions in the adjacent component/page tests.

Several user-facing money surfaces already rejected malformed runtime amounts, but still appended the raw DTO currency code next to those amounts. A malformed label such as `"../USD"` or `" usd "` could therefore show up in deal rows, pending topup invoice details, create-deal invoice previews, and realtime payment modals even while the numeric value itself was sanitized.

Risk: these screens are payment decision surfaces. Rendering a raw runtime currency label next to a valid or neutralized amount can make a corrupted DTO look like a different wallet/currency and weakens the user's ability to verify what they are paying.

Fix: deal rows, deal detail invoice rows, create-deal invoice previews, and both deal/deposit payment modals now pass currency codes through the shared contract normalizer before rendering. Invalid codes fall back to a neutral known display code instead of leaking raw DTO strings, and lowercase/trimmed contract codes normalize to uppercase. Regressions cover malformed and normalized currency labels across the affected surfaces.

### M-203. PIN-reset paywall trusted runtime currency labels

Links: `frontend/src/components/PinResetPaywallModal.tsx`, shared normalizer `frontend/src/lib/currencyCodes.ts`, regression `frontend/src/components/PinResetPaywallModal.test.tsx`.

The paid PIN-reset paywall already rendered malformed runtime price, balance, and charged amounts neutrally, but it only trimmed `currency_code` before appending it to those values. A malformed price payload or paid response could therefore render a raw label such as `"../USD"` next to the reset price, user balance, or "charged" success toast.

Risk: the PIN-reset modal is a money-moving confirmation path. Even when the amount is valid, a raw runtime currency label can misstate which balance is being debited and make a corrupted DTO look like a legitimate charge.

Fix: the price payload currency and paid-result currency now pass through the shared currency-code normalizer before display, falling back to `USD` for malformed values. Regressions cover normalized lowercase/trimmed price currency codes, malformed price currency codes, and malformed paid-result currency codes in the success toast.

### M-204. Admin deposit/withdrawal queues trusted runtime currency labels

Links: `frontend/src/pages/admin/AdminDepositsPage.tsx`, `frontend/src/pages/admin/AdminWithdrawalsPage.tsx`, shared admin formatter `frontend/src/pages/admin/format.ts`, regressions in the adjacent admin page tests.

The admin deposit and withdrawal queues used strict admin amount formatting, but appended the raw `currency_code` from the DTO. A malformed label such as `"../USD"` or `" usdt "` could therefore appear beside an otherwise sanitized money amount in operator payment queues.

Risk: these queues drive manual payment decisions: marking deposits paid/refunded and approving withdrawals. Raw currency labels can make corrupted payment DTOs look like legitimate currency rows and weaken operator review.

Fix: both queues now use a shared admin currency-code formatter backed by the contract normalizer. Lowercase/trimmed codes normalize to uppercase; malformed or missing labels render as a neutral dash instead of leaking the raw DTO value. Regressions cover the helper plus deposit and withdrawal queue rows.

### M-205. Admin deal/wallet money rows trusted runtime currency labels

Links: `frontend/src/pages/admin/AdminDealsPage.tsx`, `frontend/src/pages/admin/AdminArbitrationPage.tsx`, `frontend/src/pages/admin/AdminDealDetailPage.tsx`, `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, shared admin formatter `frontend/src/pages/admin/format.ts`, regressions in the adjacent admin page tests.

After M-204, several adjacent operator-facing money rows still formatted amounts strictly but appended raw currency labels: admin deal list rows, arbitration queue rows, deal-detail balance snapshots and pending approvals, wallet balance previews/sheets, and per-user balance rows. Malformed DTO labels such as `"../USDT"` or `" usdt "` could therefore appear beside trusted admin money values.

Risk: these are admin review and money-operation surfaces. Raw labels next to sanitized amounts can make corrupted deal or wallet DTOs look like valid currency rows, weakening manual triage and approval decisions.

Fix: the remaining admin deal/wallet/user balance money rows now use the shared admin currency-code formatter. Canonicalizable labels are normalized to uppercase, while malformed labels render as a neutral dash. Regressions cover the deal list, arbitration queue, deal-detail snapshots and approvals, wallet balance rows/sheet, and per-user wallet rows.

### M-206. Admin wallet adjustments trusted runtime currency labels for mutations

Links: `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, shared admin formatter `frontend/src/pages/admin/format.ts`, regressions in `frontend/src/pages/admin/format.test.ts`, `frontend/src/pages/admin/AdminWalletsPage.test.tsx`, and `frontend/src/pages/admin/AdminUserDetailPage.numbers.test.tsx`.

The wallet adjustment sheets selected their initial mutation currency from the first visible balance row. After M-205 the UI label was normalized for display, but the mutation state could still retain the raw DTO value. A balance code like `" ton "` could therefore show as a normal-looking `TON` row while submitting `currency_code: " ton "` to the admin adjust endpoint.

Risk: these forms perform manual credit/debit operations. Sending a currency value that differs from the visible catalog-backed chip can fail the operation or make operator intent ambiguous during money correction workflows.

Fix: admin adjustment forms now initialize and reconcile the selected mutation currency through a shared helper that normalizes the preferred balance code and validates it against loaded admin currency rows. If the current selection is malformed or absent from the catalog, the form falls back to a valid known code. Regressions cover the helper, the admin wallets sheet, and the per-user balance form.

### M-207. Admin wallet currency selectors trusted raw catalog codes

Links: `frontend/src/pages/admin/AdminWalletsPage.tsx`, `frontend/src/pages/admin/AdminUserDetailPage.tsx`, regressions in `frontend/src/pages/admin/AdminWalletsPage.test.tsx` and `frontend/src/pages/admin/AdminUserDetailPage.numbers.test.tsx`.

M-206 normalized the selected adjustment currency, but the selector buttons still rendered and stored `c.code` directly from admin currency DTO rows. The admin wallets USD-rate form had the same path: a catalog row like `" usdt "` could render as a selector and submit `currency_code: " usdt "` to the rate upsert mutation.

Risk: manual wallet adjustments and exchange-rate edits are money-operation controls. If the displayed selector and submitted currency diverge because a catalog DTO is non-canonical, the operator can perform an action that does not match the visible normalized currency intent.

Fix: the affected admin wallet/user selectors now use `normalizeCurrencyCodeRows` before rendering options, storing selection state, matching current rates, or submitting mutations. Malformed catalog rows are dropped and canonicalizable rows submit uppercase codes. Regressions cover adjustment chip clicks and USD-rate upserts with non-canonical catalog DTO codes.

### M-208. Create-deal currency picker trusted raw fiat codes

Links: `frontend/src/pages/deals/CreateDealPage.tsx`, regressions in `frontend/src/pages/deals/CreateDealPage.test.tsx`.

The create-deal page filtered the currency catalog to fiat rows but did not normalize row codes before building picker options. It also defaulted `currencyCode` from the first funded balance by assigning `funded.currency.code` directly and matched active balances by raw `b.currency.code === currencyCode`. A runtime row like `" usd "` could therefore break the selected label, hide the balance preview, or submit `currency_code: " usd "` when the funded balance default path ran.

Risk: create-deal is a money-locking workflow. A non-canonical fiat code in the picker or balance DTO can desynchronize the visible currency, balance hint, commission preview, and the create-deal payload.

Fix: create-deal fiat rows now go through `normalizeCurrencyCodeRows`, funded-balance defaults normalize the balance code, active balance lookup compares normalized codes, and balance/commission previews receive the normalized display code. Regressions cover malformed catalog rows and a funded balance default that submits canonical `USD`.

### M-209. Wallet currency detail reused raw matched DTO codes

Links: `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regressions in `frontend/src/pages/wallet/WalletCurrencyPage.test.tsx`.

`WalletCurrencyPage` looked up the route currency with `normalizeCurrencyCode`, but after finding the matching currency DTO it passed `currency.code` directly into balance display, the deposit form, and history row rendering. A route like `/wallet/USDT` could therefore match a runtime DTO code `" usdt "` and then display or submit that non-canonical value.

Risk: the per-currency wallet page is a direct deposit entry point. Reusing a raw matched DTO code can make the page appear to support a canonical route while sending a different `currency_code` in the deposit mutation.

Fix: after route normalization, the page now uses the canonical route code for balance display, deposit form props, and history formatting. Regressions cover a route-matched currency DTO with `" usdt "` and assert both display and deposit submit use `USDT`.

### M-210. Wallet deposit success toasts trusted response currency labels

Links: `frontend/src/pages/wallet/WalletDepositPage.tsx`, `frontend/src/pages/wallet/WalletTrustDepositPage.tsx`, `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, regressions in the adjacent wallet page tests.

The wallet deposit, trust-deposit, and per-currency deposit forms submitted normalized currency codes, but their success toast bodies formatted `dep.amount` with `dep.currency.code` from the create-deposit response. A response code like `" usd "` or `" uah "` could therefore leak into payment instructions immediately after a successful invoice creation.

Risk: these toasts are user-facing payment instructions. Showing a non-canonical response label next to an invoice amount can confuse payment review and contradict the normalized currency that was submitted.

Fix: each deposit success path now normalizes the response currency code and falls back to the already selected canonical code if the response label is malformed. Regressions cover wallet deposit, trust deposit, and per-currency deposit toasts with non-canonical response codes.

### M-211. Wallet/deal status labels trusted unknown runtime statuses

Links: `frontend/src/pages/wallet/WalletCurrencyPage.tsx`, `frontend/src/components/domain/DealRow.tsx`, `frontend/src/pages/deals/DealDetailPage.tsx`, regressions in the adjacent wallet/deal tests.

Wallet history rows, deal list cards, and deal detail headers mapped known contract statuses to localized labels, but fell back to rendering the raw runtime status string when the DTO contained an unknown value. A corrupted or drifted status like `provider_reconciled` could therefore appear as a credible user-facing state on money/deal review screens.

Risk: these are decision surfaces. Unknown raw status labels can confuse users about whether a payment, withdrawal, or deal state is actionable, and they weaken the invariant that unsupported runtime contract drift is displayed neutrally.

Fix: unknown wallet-history and deal statuses now render the neutral `Статус неизвестен` label with muted styling instead of leaking the raw DTO value. Deposit pay links remain gated on the explicit `pending` contract status. Regressions cover unknown deposit, withdrawal, deal-row, and deal-detail statuses.

## Наблюдения без отдельного finding


- Media upload/serve выглядит сильной зоной: есть streaming cap, magic bytes, Pillow reencode, reject animation, signed deal URLs и path validation.
- CSP report и client-error endpoints имеют body cap/rate limit; именно на их фоне webhook gap из H-03 выглядит явным расхождением.
- Admin wallet adjust использует `Decimal` и row locks.
- Защита от демоушена последнего админа реализована с блокировками.
- Backend WebSocket часть имеет bounded send queue, auth-first message и inbound cap. Основная проблема находится на frontend reconnect policy.

## Итог исправлений

Приоритетные H/M findings закрыты в коде и покрыты доступными lint/type/test/build проверками. Low-priority пункт по card/TRUST/manual fallback flows снят как intended product behavior.

## Ограничения аудита

Backend pytest suite не удалось прогнать из-за недоступной/падающей тестовой БД в текущей среде. Docker также недоступен, поэтому сценарии с реальным Postgres/Redis/Bot/Gateway не поднимались. Выводы выше основаны на статическом чтении кода, frontend test/build проверках, backend type/lint проверках и локальной трассировке control flow.
