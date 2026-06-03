# Аудит кода Garant от 2026-06-01

Репозиторий: `g2void2-byte/garant`
Ветка аудита/PR: `audit-fixes-2026-06-02-settings-system`, PR #255
База исходного аудита: `devin/1778660441-fresh-rewrite-sqlalchemy` @ `8b52761247b31697face725aba183d3b3ee6a1be`

## Область проверки

Проведен ручной аудит backend, frontend, миграций, платежных и wallet-потоков, админских сценариев, realtime/WebSocket, media, CSP/client-error endpoints, Telegram-уведомлений и основных тестов. Это инженерный аудит по коду и сценариям отказа, а не формальное доказательство отсутствия всех возможных дефектов.

## Автоматические проверки

- `npm run typecheck` - успешно.
- `npm run lint` - успешно.
- `npm run test:run` - успешно: 63 файла, 568 тестов. В выводе есть ожидаемые jsdom-трейсы ErrorBoundary.
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
- M-50-M-90: admin exact-user lookup, wallet preview, content rating validation, settings bounds/stats, zero-deal own-service listing, auto-withdraw races, paid PIN reset delivery rollback, account-transfer code race, Crystalpay webhook dedupe, refunded-deposit re-credit guards, event-loop-safe maintenance cache, strict deal attachment ids/admin review ids, strict review rating/deal_id, strict service-comment ratings, strict admin deal action ids, strict admin counter integers, strict boolean payload flags, strict admin manual rating numbers, admin currency schema hardening, service write schema hardening, broadcast audience strict ints, arbitration resolve enum, username refs, currency-code normalization, 2FA secret/code contract, query-filter contracts, public user search filters, notification/audit query contracts и admin numeric filter guards исправлены.

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
