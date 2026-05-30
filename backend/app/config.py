from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # V11-M-6 — ``extra="forbid"`` so a typo in an env var
    # (``POSTGRES_URI`` instead of ``DATABASE_URL``) fails loudly at
    # startup instead of silently falling back to the default. The
    # tradeoff: any env var name we don't model here also fails — see
    # also the explicit allowlist below for that reason.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="forbid")

    # Deployment mode. ``production`` enables fail-fast checks for
    # critical secrets (PIN JWT key, etc.) that would otherwise
    # silently fall back to derivable values in dev.
    environment: Literal["development", "test", "staging", "production"] = "development"

    # Allow custom variables in local .env to bypass extra="forbid" restriction
    postgres_password: str = ""
    vite_api_url: str = ""

    bot_token: str = ""
    cryptobot_token: str = ""
    cryptobot_testnet: bool = False

    # Crystalpay v3 API credentials (alternative deposit provider).
    # ``crystalpay_login`` is the cashbox login displayed in the
    # Crystalpay merchant cabinet; ``crystalpay_secret`` is the
    # cashbox secret used both as ``Authorization`` for v3 API calls
    # and as the salt for ``sha1(invoice_id:secret)`` webhook signature
    # verification (see ``backend.app.crystalpay``). Both empty
    # disables the provider — ``services_wallet.create_deposit_invoice``
    # raises 502 if a request specifies ``provider="crystalpay"`` and
    # either value is blank.
    crystalpay_login: str = ""
    crystalpay_secret: str = ""

    webapp_url: str = "http://localhost:5173"
    # Public backend/API origin used for provider webhooks and optional
    # split-origin CSP. Leave empty for same-origin monolith deploys.
    public_api_url: str = ""
    # More specific callback base for payment providers. Defaults to
    # ``public_api_url`` and then ``webapp_url`` for backwards compatibility.
    webhook_base_url: str = ""
    # Space-separated CSP sources for ``connect-src``. Empty means
    # ``'self'`` plus the origin from ``public_api_url`` when set.
    csp_connect_src: str = ""
    # ``None`` means production/staging only; set explicitly for a
    # custom staging/dev HTTPS domain.
    enable_hsts: bool | None = None
    webapp_port: int = 8080
    allowed_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://garant:garant@localhost:5432/garant"

    run_bot: bool = True
    allow_unsigned_init_data: bool = False

    # V12-H3 — gate the in-lifespan ``alembic upgrade head`` call. The
    # legacy default is ``true`` so single-process deploys (the manual
    # ``uvicorn`` setup documented in README) keep working: the FastAPI
    # lifespan migrates on startup just like before.
    #
    # ``docker compose`` and any horizontally-scaled deploy set this
    # to ``false`` and run alembic in a dedicated one-shot
    # ``migrate`` service instead. Each replica's lifespan then only
    # calls :func:`backend.app.db.verify_migrations_at_head` to assert
    # the DB schema matches the script-directory head before serving
    # traffic. This removes the dual-migration round-trip
    # (Dockerfile.dev CMD + lifespan both calling ``alembic upgrade
    # head`` on every container boot, contending on the alembic
    # advisory lock for no benefit) and the multi-replica race on
    # long-running migrations.
    run_migrations_on_startup: bool = True

    pin_jwt_secret: str = ""
    # Idle window for the PIN session. The JWT itself is long-lived
    # (``pin_session_jwt_ttl_seconds``) so it survives across re-opens
    # of the TMA — what enforces re-entry is the rolling
    # ``users.pin_last_activity_at`` column updated on every
    # authenticated request. If ``now - pin_last_activity_at`` exceeds
    # this value, the PIN session is rejected and the gate re-prompts.
    pin_session_ttl_seconds: int = 60 * 30
    # Absolute JWT lifetime — must be > ``pin_session_ttl_seconds`` to
    # leave headroom for idle enforcement. 30 days here so the same
    # PIN unlock can survive ~all reasonable absences while idle-gated.
    pin_session_jwt_ttl_seconds: int = 60 * 60 * 24 * 30
    pin_max_attempts: int = 3
    pin_lock_minutes: int = 60
    pin_reset_code_ttl_seconds: int = 10 * 60
    # Sliding idle write-debounce — within this window the activity
    # timestamp is NOT rewritten to avoid a write on every request.
    pin_activity_debounce_seconds: int = 30
    # TOTP session: after a single ``X-Totp-Code`` is accepted, the
    # server mints a 24h JWT (``X-Totp-Session``) the frontend caches
    # in localStorage and replays on subsequent admin actions. The
    # ``users.totp_session_epoch`` claim invalidates outstanding
    # sessions when 2FA is rotated or disabled.
    totp_session_ttl_seconds: int = 60 * 60 * 24

    # V11-M-1 — bcrypt rounds for PIN hashing. 12 rounds is the 2024
    # OWASP baseline (~200 ms / hash on a modern CPU). Bumped from
    # 10 (~50 ms / hash) to slow down offline brute-force on a leaked
    # PIN hash dump; combined with a 4-digit PIN keyspace of 10⁴,
    # rounds=12 stretches a full enumeration on commodity CPU from
    # ~8 min to ~30 min. Tunable so production can step it up further
    # without a code change.
    pin_bcrypt_rounds: int = 12
    # V11-M-1 — server-side pepper HMACed into the PIN *before* bcrypt
    # so a DB dump alone (without the env secret) is useless to an
    # attacker. Empty string disables the pepper for backwards-compat
    # with existing dev DBs (existing hashes remain valid; new hashes
    # use whatever value is set at hash time). MUST NOT be set in
    # production without a rollout plan — changing this AFTER hashes
    # exist breaks every existing PIN session.
    pin_pepper: str = ""

    # replay window for Telegram WebApp init data; Telegram
    # regenerates init-data on every TMA open so 15min is safe;
    # legacy default was 86400 (24h).
    init_data_max_age_seconds: int = 900

    # PR-3 — periodic sweep of stale deals (0 disables).
    inactivity_sweep_seconds: int = 600

    # M-6 — auto-expire pending wallet deposits the user never paid.
    # ``wallet_deposit_expiry_seconds`` is the grace window after which a
    # still-``pending`` deposit row gets flipped to ``expired`` so the
    # admin queue, user-facing list, and treasury aging report don't
    # accumulate forever. ``wallet_deposit_sweep_seconds`` is how often
    # the background loop runs; ``0`` disables the loop entirely (the
    # default in tests via the env var).
    #
    # The default is 30 minutes: invoices that sit longer than that
    # without payment are almost never going to be paid (the user
    # closed the TMA, the rate moved, etc.) and an active provider
    # invoice tying up a CryptoBot / Crystalpay slot has a real cost.
    # 30 min also matches the upstream lifetime we now pass to both
    # providers when creating the invoice so all three sides agree on
    # the terminal moment.
    wallet_deposit_expiry_seconds: int = 20 * 60  # 20 min
    wallet_deposit_sweep_seconds: int = 60

    # Audit (continuation) H-2 — auto-reconcile stale pending
    # withdrawal rows the ``create_withdrawal`` Phase 2 fail branch
    # left behind. ``wallet_withdrawal_stale_seconds`` is the
    # grace window after which a still-``pending`` withdrawal is
    # considered stuck and gets reconciled against CryptoBot's
    # ``getTransfers`` API by ``spend_id=wd:{id}``;
    # ``wallet_withdrawal_stale_sweep_seconds`` is how often the
    # background loop runs (``0`` disables the loop).
    #
    # The default cap is 24 hours: well past the longest realistic
    # admin response SLA, well short of "user contacts support".
    # The sweep interval is 5 min by default — same order of
    # magnitude as the deposit sweep, but slower because the
    # CryptoBot call is a roundtrip per row and we don't want a
    # tight loop hammering the upstream.
    wallet_withdrawal_stale_seconds: int = 24 * 60 * 60  # 24 h
    wallet_withdrawal_stale_sweep_seconds: int = 5 * 60  # 5 min

    # H-1 — the legacy ``Invoice`` ledger (``invoice_expiry_seconds`` /
    # ``invoice_sweep_seconds``) was retired together with the
    # ``users.balance`` USD column. The wallet ledger above is the
    # only sweep that survives.

    # PR-G (L-6) — if the maintenance-flag DB lookup fails the
    # middleware normally falls open (treats maintenance as off and
    # lets writes through) so a flaky DB doesn't lock the whole API.
    # Setting this to ``true`` flips the policy to fail-closed: write
    # endpoints are blocked with the maintenance message while the
    # lookup is broken. Useful in stricter prod deploys where it's
    # better to refuse writes than serve them without a maintenance
    # check.
    maintenance_fail_closed: bool = False

    # PR-CA — TTL for account-transfer one-time codes.
    account_transfer_code_ttl_seconds: int = 15 * 60
    # Operational tuning surface for account-transfer code generation.
    # ``account_transfer_max_code_generation_attempts`` bounds the
    # collision-avoidance loop in ``_generate_unique_code`` so a
    # pathologically full keyspace doesn't spin forever;
    # ``account_transfer_code_len`` is the digit-count of the OTP.
    # Brute-force protection for ``/api/account/confirm`` is delegated
    # entirely to ``RLPin`` (5/min/caller) — there is no longer a
    # per-code attempt counter.
    account_transfer_max_code_generation_attempts: int = 100
    account_transfer_code_len: int = 6
    # V11-M-12 — emit a ``logger.warning`` when ``_generate_unique_code``
    # had to retry more than this many times. With a 10⁶ keyspace and the
    # default 15-min TTL the live code set is tiny, so retrying more than
    # a handful of times is the early warning sign of pressure on the
    # keyspace. Default is 5: well above normal jitter, well below the
    # 100-iteration cap.
    account_transfer_code_generation_warn_threshold: int = 5

    # PR-E — uploaded media storage.
    media_root: str = "./media-uploads"
    media_base_url: str = "/media"  # served at this path on the backend host
    media_max_bytes: int = 5 * 1024 * 1024  # 5 MiB
    # V12-UI — added ``service`` so the "Новая услуга" gallery uploads
    # (``POST /api/media/upload`` with ``kind=service``) land in a
    # dedicated ``media-uploads/service/`` subtree and the resulting
    # ``/media/service/...`` URLs pass the ``ServiceCreate``/``ServiceUpdate``
    # whitelist validator.
    media_allowed_kinds: str = "avatar,banner,deal,service"

    # Audit v3 L-14 — comma-separated list of ``Media.kind`` buckets
    # whose URLs must be HMAC-signed and short-lived. Public buckets
    # (avatar, banner, service) keep the legacy unsigned
    # ``StaticFiles`` mount because they are already exposed on user
    # profiles / service cards; only deal-chat attachments — which
    # carry user-supplied screenshots inside a private 1:1 chat — get
    # the auth-gated, expiring-URL treatment by default.
    media_signed_kinds: str = "deal"
    # TTL for signed deal-media URLs. Long enough that a chat page
    # render still resolves attachments after a few minutes of idle,
    # short enough that a leaked link goes stale before it ends up
    # in a third-party log / referrer header. The ``Media.url``
    # values stored in the DB stay unsigned; signing happens at
    # serialisation time (``_signed_media_url`` in
    # ``media_signing.py``) per request.
    media_signed_url_ttl_seconds: int = 600
    # Empty (the default) derives the signing secret from
    # ``pin_secret()`` (which itself falls back to a deterministic
    # hash of ``BOT_TOKEN`` outside production / staging). Production
    # deployments should set this explicitly so rotating the
    # PIN-session secret does not invalidate every outstanding deal
    # attachment link in flight.
    media_url_signing_secret: str = ""

    # Comma-separated list of trusted proxy IPs/CIDRs. When set, X-Forwarded-For
    # is only honoured if the direct peer is in this list. Empty = trust all
    # (backwards-compatible, suitable for single-proxy setups).
    trusted_proxies: str = ""

    # P3.5 — Redis. Empty disables Redis and all features fall back to
    # in-process state (WS broadcasts stay local; rate-limit stays in-memory).
    redis_url: str = ""

    # Audit §4.5 — when set, the admin/2fa enrolment flow refuses to
    # fall back to the per-process ``_pending_secrets`` dict. The
    # fallback is fine for single-replica dev/test runs but breaks
    # transparently on scale-out: ``/setup`` lands on replica A,
    # ``/enable`` lands on replica B, and the secret isn't there.
    # Production deployments running >1 replica should flip this on
    # so the misconfiguration surfaces immediately (HTTP 503 on
    # ``/setup`` and ``/enable``) instead of users seeing "TOTP секрет
    # не найден" hours into the rollout. Default is ``False`` to
    # preserve the existing dev/test behaviour.
    require_redis_for_2fa: bool = False

    # Audit v3 L-11 — when ``True``, rate-limit checks return 503
    # instead of falling back to the in-memory deque when Redis is
    # unavailable. On a multi-replica deployment the in-memory
    # fallback gives each replica its own counter, effectively
    # multiplying the allowed rate by the replica count.
    #
    # The DEFAULT is ``False`` (dev/test friendly — Redis is
    # optional locally). :func:`effective_require_redis_for_rate_limit`
    # below upgrades this to ``True`` in production/staging so a
    # multi-replica prod that loses Redis fails closed instead of
    # silently weakening per-user PIN/withdrawal/admin throttles
    # by a factor of N.
    require_redis_for_rate_limit: bool = False

    # Comment 38 (audit v10) — WS DoS hardening tunables.
    ws_max_sockets_per_user: int = 5
    ws_recv_max_messages_per_second: float = 10.0
    ws_heartbeat_interval_seconds: int = 30
    # V11-L-1 — bounded send queue per socket. Pre-fix this was a
    # module-level constant in ``ws.py``; production can now resize
    # it without a code change. The default (100) matches the prior
    # hard-coded value: enough to absorb a normal notification burst
    # for a single user, small enough to bound memory at scale.
    ws_send_queue_size: int = 100
    # V11-L-1 — per-send timeout. Same rationale: lifted from a
    # module-level constant so production can tune the
    # back-pressure-vs-latency trade-off.
    ws_send_timeout_seconds: float = 10.0
    # V11-H-7 — how often the per-socket reaper sweeps to evict
    # connections whose ``auth_date`` has aged past
    # ``ws_max_age_seconds``. Previously hard-coded to 5 min which
    # left a stolen initData usable on an active WS for up to that
    # long past nominal expiry. 60 s is the new floor — load is
    # negligible (O(n_sockets) Python pass, no I/O).
    ws_age_check_interval_seconds: int = 60
    # V11-L-1 — auth_date age cap for an active WS socket. Once the
    # socket's initData is older than this, the per-socket reaper
    # closes it with code 4001.
    ws_max_age_seconds: int = 12 * 60 * 60

    # Comment 45 (audit v10) — GDPR: purge ``users.last_ip`` after
    # the retention window so we don't hold PII forever.
    last_ip_retention_seconds: int = 90 * 24 * 60 * 60  # 90 days
    last_ip_purge_sweep_seconds: int = 3600  # 1 h

    # V11-M-15 — optional override for the SPA dist directory. Empty
    # string (default) falls back to the legacy
    # ``Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"``,
    # which is right for a monorepo Docker build. Set this when the
    # frontend is deployed separately (CDN, S3, etc.) so the backend
    # doesn't try to serve a non-existent SPA shell — or to point a
    # specific deploy at a custom build path.
    frontend_dist_dir: str = ""

    # P3.2 — bot menu external links. Empty values hide the button.
    bot_forums_url: str = ""
    bot_community_chat_url: str = ""
    bot_arbitration_url: str = ""
    bot_docs_url: str = ""
    bot_support_username: str = ""  # Telegram username without leading @


settings = Settings()


def effective_require_redis_for_rate_limit() -> bool:
    """Return whether the rate-limiter must fail closed on Redis loss.

    In production/staging this is always ``True`` — a multi-replica
    deploy that loses Redis would otherwise silently weaken per-user
    PIN/withdrawal/admin throttles by a factor of N (each replica
    keeps its own in-memory counter). Dev/test still respects the
    explicit setting so local runs without Redis stay usable.
    """
    if settings.environment in ("production", "staging"):
        return True
    return bool(settings.require_redis_for_rate_limit)


def pin_secret() -> str:
    """JWT secret for PIN session tokens.

    In production / staging this must be set explicitly via
    ``PIN_JWT_SECRET``. Anything else (dev, test) falls back to a
    deterministic hash derived from ``BOT_TOKEN`` so local runs
    don't need a separate secret. The fallback is deliberately
    blocked in production because compromising ``BOT_TOKEN`` would
    otherwise compromise every PIN session ever issued.
    """
    if settings.pin_jwt_secret:
        return settings.pin_jwt_secret
    if settings.environment in ("production", "staging"):
        raise RuntimeError(
            "PIN_JWT_SECRET must be set explicitly when ENVIRONMENT is "
            f"'{settings.environment}'; refusing to derive it from BOT_TOKEN."
        )
    import hashlib

    seed = (settings.bot_token or "garant-dev-pin-secret").encode()
    return hashlib.sha256(b"pin-jwt:" + seed).hexdigest()
