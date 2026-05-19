# Audit-marker history

This document catalogues the inline audit identifiers used throughout
the codebase (`V5-A-X`, `V5-B-X`, `V5-C-X`, `V5-D-X`, `V5-E-X`, plus
the older `Comment NN` annotations from audit v9).  Per **L-10**
(audit v11) the inline `V5-X-Y — …` *prefixes* have been stripped from
production code — the explanatory comments stay, but the audit
identifier itself no longer leads the line.

Tests are deliberately **not** stripped because the audit bucket is the
test-file organisation: `tests/test_v5_a_security_auth.py`,
`tests/test_v5_b_wallet_withdrawals.py`, `tests/test_v5_c_bucket.py`,
`tests/test_v5_d_e_bucket.py`, `tests/test_notification_pagination.py`
(V5-D-1), `tests/test_alembic_advisory.py` (V5-D-9),
`tests/test_admin_2fa_replay.py` (V5-C-6),
`tests/test_pin_reset_no_code_in_logs.py` (V5-A-7),
`tests/test_search_fts.py` (V5-D-8) and
`tests/test_critical_race_conditions.py` (V5-B-1, follow-ups).
Renaming the test files would also break shell-level test discovery
patterns we rely on in CI logs, so the IDs survive there.

Marker residue that *is* allowed in production code:

- Cross-references inside a sentence (e.g.
  `# ``extra`` (see V5-A-7 contract above) — …`,
  `Security contract (V5-A-7): …`).
- Mixed audit-ID references where the V5 marker is joined to another
  series (e.g. `# V5-A-6 (M) / M-10 — …`).
- Semantic mentions where the identifier names a contract a test
  enforces (e.g. `(V5-E-1 destructive)`,
  `V5-E-1 marker because …`).

Everything else moved to the catalogue below.

---

## V5-A — Security & Auth

| ID | Summary | Closed in | Code anchors |
|---|---|---|---|
| **V5-A-1** | Replay window for Telegram WebApp `init_data` shortened to 15 min. | (pre-v3, see audits v3+) | `backend/app/config.py::SECURITY_INIT_DATA_REPLAY_S`; regression in `tests/test_medium_followups.py::test_init_data_replay_window`. |
| **V5-A-2** | Empty-hash invariant in `security.verify_init_data` — refuse to accept `init_data` where the `hash=` field is missing or empty. | (pre-v3) | `backend/app/security.py::verify_init_data`; regression `tests/test_v5_a_security_auth.py::test_verify_init_data_empty_hash_rejected`. |
| **V5-A-3** | Defence-in-depth: `_parse_unsigned` aborts in production/staging even if `ALLOW_UNSIGNED_INIT_DATA=1` somehow slips through env validation. | (pre-v3) | `backend/app/security.py::_parse_unsigned`; regression `tests/test_v5_a_security_auth.py::test_parse_unsigned_environment_gate`. |
| **V5-A-4** | Common-PIN blacklist (`COMMON_PINS`) enforced at every commit point: `/api/pin/setup`, `/api/pin/change`, `/api/pin/reset/confirm`. Blacklist check happens AFTER `verify_pin`/`verify_reset_code` so we don't leak info to attackers. | (pre-v3) | `backend/app/pin.py::COMMON_PINS`; `backend/app/routers/pin.py::setup_pin/change_pin/reset_confirm`; regression `tests/test_v5_a_security_auth.py::test_common_pin_blacklist_setup/change/reset_confirm`. |
| **V5-A-5** | `_ensure_format` runs *before* `_is_locked` in the PIN reset flow so a malformed PIN can't accidentally bump the lockout counter. | (pre-v3) | `backend/app/routers/pin.py::_ensure_format`; regression `tests/test_v5_a_security_auth.py::test_format_check_before_lock_check`. |
| **V5-A-6** | `change_pin` wraps the whole sequence in try/except so a transient DB error after `verify_pin` doesn't leave the user logged-out with no PIN. Joined with `M-10` in `routers/pin.py:210`. | (pre-v3) | `backend/app/routers/pin.py::change_pin`. |
| **V5-A-7** | PIN-reset code is plaintext; it is **never** logged. The plaintext token is excluded from every `extra={"…"}` payload sent to structured logging. | (pre-v3) | `backend/app/routers/pin.py::reset_confirm` and `bot/notify.py::send_text`; regression `tests/test_pin_reset_no_code_in_logs.py`. |
| **V5-A-9** | `ADMIN_TOTP_BYPASS` is re-read per-request rather than cached at import time, so toggling it for an e2e run does not require a process restart. | (pre-v3) | `backend/app/auth_2fa.py::_bypass_enabled`; regression `tests/test_v5_a_security_auth.py::test_admin_totp_bypass_per_request`. |
| **V5-A-10** | NTP/PTP requirement for TOTP — documented operationally, not a code change. | (pre-v3) | `backend/app/auth_2fa.py` module docstring (the operations team owns clock-skew monitoring). |

## V5-B — Wallet & deposits

| ID | Summary | Closed in | Code anchors |
|---|---|---|---|
| **V5-B-1** | `FOR UPDATE` lock on `users.balance` before crediting a deposit so concurrent webhook deliveries can't double-credit. Includes a follow-up that aligns the polling fallback (`poll_deposit_status`) with the webhook lock-order. | (pre-v3) | `backend/app/services_wallet.py::credit_deposit/poll_deposit_status`; `backend/app/services_payments.py::handle_invoice_paid`; regression `tests/test_critical_race_conditions.py::*invoice_paid*`. |
| **V5-B-2** | Same race shape as B-1 but on the legacy USD-only ledger; retired entirely when H-1 dropped `User.balance` / `Invoice`. | #139 | (no code; row removed from `users` table). |
| **V5-B-3** | `create_deposit_invoice` rejects upstream invoices whose pay-URL fields are all empty. | (pre-v3) | `backend/app/services_wallet.py::create_deposit_invoice`; regression `tests/test_v5_b_wallet_withdrawals.py::test_create_deposit_invoice_pay_url`. |
| **V5-B-4** | Per-currency anchored regex on user-supplied payout addresses. Empty regex = skip (back-compat for new currencies seeded before their regex is known). | (pre-v3) | `backend/app/models.py::Currency.address_regex`; `backend/app/services_wallet.py::create_withdrawal`; `backend/app/seed.py::CURRENCY_ADDRESS_REGEX`; regression `tests/test_v5_b_wallet_withdrawals.py::test_create_withdrawal_address_regex_*`; alembic `d9f1c3a8e205_currencies_address_regex.py`. |
| **V5-B-5** | `spend_id=f"wd:{w.id}"` is the idempotency key CryptoBot uses to deduplicate Transfer calls. Used in both `services_wallet.create_withdrawal` and admin `routers/admin/withdrawals.decide`. | (pre-v3) | as above. |
| **V5-B-6** | Admin `reject` on a withdrawal clears `WalletWithdrawal.locked_until` so the user can resubmit without waiting the dispute cool-down. | (pre-v3) | `backend/app/routers/admin/withdrawals.py::decide`; regression `tests/test_v5_b_wallet_withdrawals.py::test_reject_clears_locked_until`. |
| **V5-B-7** | Disable deposit/legacy-invoice expiry sweep in tests by default (matches `pytest.ini`). | (pre-v3) | `pyproject.toml::filterwarnings`. |
| **V5-B-8** | Crypto Pay webhook ignores payloads that carry only the legacy `type` field (no `update_type`), closing a downgrade-attack vector. | (pre-v3) | `backend/app/routers/payments.py::cryptobot_webhook`; regression `tests/test_v5_b_wallet_withdrawals.py::test_cryptobot_webhook_legacy_type_field_rejected`. |
| **V5-B-9** | Admin withdrawals counters use one `GROUP BY` query (not N+1 separate counts). | (pre-v3) | `backend/app/routers/admin/withdrawals.py::list_withdrawals`; regression `tests/test_v5_b_wallet_withdrawals.py::test_admin_withdrawals_counters_single_query`. |
| **V5-B-10** | `GET /api/wallet/deposits/{id}` throttled to 2/30s to protect CryptoBot's rate limit. | (pre-v3) | `backend/app/rate_limit.py::WALLET_POLL_BUCKET`; `backend/app/routers/wallet.py::get_deposit`; regression `tests/test_v5_b_wallet_withdrawals.py::test_wallet_poll_throttle`. |
| **V5-B-11** (≙ audit residual 4.2 HIGH) | Admin `decide_withdrawal` no longer holds the `wallet_withdrawals` row lock through the CryptoBot `transfer` HTTP roundtrip. The auto-send branch now uses a three-phase commit: (1) mark `approved` + commit (releases the lock), (2) call CryptoBot with `spend_id=wd:{id}` for idempotency outside any lock, (3) re-acquire the lock briefly, mark `sent`, decrement `balance.locked`, stage notification + audit, commit. Crash-recovery: a worker dying between phase 1 and phase 3 leaves the row at `approved` with no audit row; the operator can retry via the existing `mark_sent` action and CryptoBot's `spend_id` dedupe makes the retry safe. | (this PR) | `backend/app/routers/admin/withdrawals.py::decide_withdrawal`; regression `tests/test_admin_finance.py::test_withdrawals_decide_reject_returns_funds` covers the non-auto branch unchanged; `tests/test_admin_2fa_gates.py::test_withdrawals_decide_requires_2fa` covers the TOTP gate. |

## V5-C — Admin / 2FA / observability

| ID | Summary | Closed in | Code anchors |
|---|---|---|---|
| **V5-C-1** | Throttle the "DB lookup failed" log line so a flapping DB doesn't fan the log out to 10k lines/minute. | (pre-v3) | `backend/app/maintenance.py::_throttled_db_log`; regression `tests/test_v5_c_bucket.py::*throttled_db_log*`. |
| **V5-C-2** | Maintenance-flag cache TTL shortened (30 s → 5 s) so a multi-instance deploy converges quickly on flag flips. | (pre-v3) | `backend/app/maintenance.py::MAINTENANCE_CACHE_TTL_S`. |
| **V5-C-3** | `/api/auth/` is *intentionally not* in the maintenance allow-list — admins must still be able to log in during a maintenance window. | (pre-v3) | `backend/app/maintenance.py::MAINTENANCE_ALLOWLIST`; regression `tests/test_v5_c_bucket.py::test_maintenance_blocks_auth_only_during_outage`. |
| **V5-C-4** | `admin_audit_log.payload` capped at 4 KB to mirror the `text` column limit and prevent runaway audit rows. | (pre-v3) | `backend/app/admin_audit.py::_PAYLOAD_BYTES_CAP`; regression `tests/test_v5_c_bucket.py::test_admin_audit_payload_4kb_cap`. |
| **V5-C-5** | Audit-log IP column comes from `X-Forwarded-For` only when `TRUSTED_PROXY_COUNT > 0`; otherwise it uses the direct socket peer. | (pre-v3) | `backend/app/admin_audit.py::client_ip`; regression `tests/test_v5_c_bucket.py::test_trusted_proxy_gate`. |
| **V5-C-6** | TOTP replay protection: claim the counter in Redis BEFORE we trust the DB row's `last_used_at` to avoid the two-process race where both verify the same OTP. | (pre-v3) | `backend/app/auth_2fa.py::_claim_counter`; regression `tests/test_admin_2fa_replay.py`. |
| **V5-C-7** | Regression for `/admin/dashboard` returning 401 (not 500) when the caller isn't authenticated. | (pre-v3) | `backend/app/routers/admin/dashboard.py`; regression `tests/test_v5_c_bucket.py::test_dashboard_unauth_returns_401`. |

## V5-D — Performance / pagination / dampening

| ID | Summary | Closed in | Code anchors |
|---|---|---|---|
| **V5-D-1** | Cursor-paginated `GET /api/notifications` (page size = 200) keyed on `(created_at, id)` for stable ordering when timestamps tie. | (pre-v3) | `backend/app/routers/notifications.py::list_notifications`; `tests/test_notification_pagination.py`. |
| **V5-D-2** | `POST /api/notifications/read-all` is a fan-out UPDATE and gets its own rate-limit bucket. | (pre-v3) | `backend/app/rate_limit.py::READ_ALL_BUCKET`. |
| **V5-D-4** | `GET /api/reviews?offset=…` capped at 10 000 — without an upper bound a paginator can wedge Postgres into a sequential scan. | (pre-v3) | `backend/app/routers/reviews.py::list_reviews`; regression `tests/test_reviews_hidden_target.py::test_reviews_offset_cap`. |
| **V5-D-5** | `selectinload(buyer/seller/currency)` on the deal-list endpoint so the serializer doesn't trigger 3N+1. | (pre-v3) | `backend/app/routers/arbitration.py::list_arbitrations`; regression `tests/test_v5_d_e_bucket.py::test_arbitration_list_selectinload`. |
| **V5-D-7** | Categorical CSP-report dampening — known-noise sources (browser extensions, broken add-ons) get logged at WARN with a category, not ERROR with a full payload. | (pre-v3) | `backend/app/routers/csp_report.py::DAMPED_PREFIXES`; regression `tests/test_v5_d_e_bucket.py::test_csp_report_known_noise/real_violation/etc`. |
| **V5-D-8** | `search.build_tsquery` caps complexity to the first 10 tokens so a 50-word paste doesn't lock the index. | (pre-v3) | `backend/app/search.py::build_tsquery`; regression `tests/test_search_fts.py::test_pathological_search_input_bounded`. |
| **V5-D-9** | Alembic advisory-lock literal = `hashtext('garant_alembic_migrations')` so concurrent `upgrade head` invocations serialise without colliding with other apps. | #102 | `alembic/env.py`; regression `tests/test_alembic_advisory.py`. |
| **V5-D-10** | `_recompute_user_rating` collapsed two queries into one round-trip `SUM(CASE …)`. | (pre-v3) | `backend/app/services.py::_recompute_user_rating`; regression `tests/test_v5_d_e_bucket.py::test_recompute_user_rating_*`. |
| **V5-D-11** | Wallet credit-path invariant (post-H-1) — total credited == sum of `WalletDeposit.amount` for paid deposits. | (pre-v3) | regression `tests/test_wallet_invariant.py`. |

## V5-E — Migrations / housekeeping

| ID | Summary | Closed in | Code anchors |
|---|---|---|---|
| **V5-E-1** | Every migration whose `downgrade()` either drops a Numeric width or removes a column **must** carry the literal marker `V5-E-1 — irreversible data loss on downgrade` in its top-of-file docstring. The marker is asserted by `tests/test_v5_d_e_bucket.py::test_v5_e_1_contract`; the assertion is AST-driven (auto-detects new narrowing in `downgrade()` per Mig-1 / #153). This is the **only** V5-X-Y identifier that remains operationally load-bearing — do not rename it. |
| **V5-E-2** | Auto-generated banner removed from `initial_schema.py`. | (pre-v3) | regression `tests/test_v5_d_e_bucket.py::test_initial_schema_no_banner`. |
| **V5-E-3** | `initial_schema.py` uses PEP 604 `str \| None` syntax (not `Optional[str]`). | (pre-v3) | regression `tests/test_v5_d_e_bucket.py::test_initial_schema_pep604`. |
| **V5-E-4..6** | Alembic housekeeping — banners gone, PEP 604, `pr4_user_moderator_flag` references the drop revision. | (pre-v3) | regression `tests/test_v10_final_audit.py::test_v5_e_4*`. |

---

## Comment NN — older audit-v9 batch

These survive **only** in `schemas.py` as `# Comment NN (audit v9)`
markers tagging specific decisions (e.g. dropping `http://` from
photo/banner URL whitelists, omitting `tg_user_id` and DM-prefs from
`UserPublicOut`).  They are kept because the schemas file is the
canonical contract — a casual reader hitting one of these validators
benefits from the cross-reference.

| Comment | Decision | Anchor |
|---|---|---|
| 29 | `UserPublicOut` omits `user_id` (= `tg_user_id`) to stop enumeration of TG IDs from search/detail. | `schemas.py::UserPublicOut` |
| 30 | `UserPublicOut` also omits DM-prefs (`dm_*`) and moderation flags (`is_banned` / `is_frozen`). | `schemas.py::UserPublicOut` |
| 35 | Drop `http://` from `photo_url` / `banner_url` whitelists; allow `/media/...`. | `schemas.py::UserUpdate._photo_url_ok/_banner_url_ok` |
| 36 | Forum links whitelist `https://` only (drop `http://` and `tg://`). | `schemas.py::ForumOut._url_ok` |

---

## Future markers

When a future audit assigns a new identifier (`A9-X-Y`, `V12-L-N`,
`v11 Mig-N`, etc.), the bucket should be added to this document
*before* the corresponding inline comment is committed, so the
catalogue stays the single source of truth.  Inline `# Vxx-Y-Z — …`
prefixes are acceptable while a fix is in-flight (i.e. while the PR
is open) but should be stripped when the fix lands, leaving only the
explanatory body behind.
