# Аудит кода Garant от 2026-06-01

Репозиторий: `g2void2-byte/garant`
Ветка аудита/PR: `audit-fixes-2026-06-02-settings-system`, PR #255
База исходного аудита: `devin/1778660441-fresh-rewrite-sqlalchemy` @ `8b52761247b31697face725aba183d3b3ee6a1be`

## Область проверки

Проведен ручной аудит backend, frontend, миграций, платежных и wallet-потоков, админских сценариев, realtime/WebSocket, media, CSP/client-error endpoints, Telegram-уведомлений и основных тестов. Это инженерный аудит по коду и сценариям отказа, а не формальное доказательство отсутствия всех возможных дефектов.

## Автоматические проверки

- `npm run typecheck` - успешно.
- `npm run lint` - успешно.
- `npm run test:run` - успешно: 61 файл, 532 теста. В выводе есть ожидаемые jsdom-трейсы ErrorBoundary.
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
