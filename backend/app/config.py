from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Deployment mode. ``production`` enables fail-fast checks for
    # critical secrets (PIN JWT key, etc.) that would otherwise
    # silently fall back to derivable values in dev.
    environment: Literal["development", "test", "staging", "production"] = "development"

    bot_token: str = ""
    cryptobot_token: str = ""
    cryptobot_testnet: bool = False

    webapp_url: str = "http://localhost:5173"
    webapp_port: int = 8080
    allowed_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://garant:garant@localhost:5432/garant"

    run_bot: bool = True
    allow_unsigned_init_data: bool = False

    pin_jwt_secret: str = ""
    pin_session_ttl_seconds: int = 60 * 60 * 12
    pin_max_attempts: int = 3
    pin_lock_minutes: int = 60
    pin_reset_code_ttl_seconds: int = 10 * 60

    # PR-3 — periodic sweep of stale deals (0 disables).
    inactivity_sweep_seconds: int = 600

    # M-6 — auto-expire pending wallet deposits the user never paid.
    # ``wallet_deposit_expiry_seconds`` is the grace window after which a
    # still-``pending`` deposit row gets flipped to ``expired`` so the
    # admin queue, user-facing list, and treasury aging report don't
    # accumulate forever. ``wallet_deposit_sweep_seconds`` is how often
    # the background loop runs; ``0`` disables the loop entirely (the
    # default in tests via the env var).
    wallet_deposit_expiry_seconds: int = 24 * 60 * 60  # 24h
    wallet_deposit_sweep_seconds: int = 600

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

    # PR-E — uploaded media storage.
    media_root: str = "./media-uploads"
    media_base_url: str = "/media"  # served at this path on the backend host
    media_max_bytes: int = 5 * 1024 * 1024  # 5 MiB
    media_allowed_kinds: str = "avatar,banner,deal"

    # Comma-separated list of trusted proxy IPs/CIDRs. When set, X-Forwarded-For
    # is only honoured if the direct peer is in this list. Empty = trust all
    # (backwards-compatible, suitable for single-proxy setups).
    trusted_proxies: str = ""

    # P3.5 — Redis. Empty disables Redis and all features fall back to
    # in-process state (WS broadcasts stay local; rate-limit stays in-memory).
    redis_url: str = ""

    # P3.2 — bot menu external links. Empty values hide the button.
    bot_forums_url: str = ""
    bot_community_chat_url: str = ""
    bot_arbitration_url: str = ""
    bot_docs_url: str = ""
    bot_support_username: str = ""  # Telegram username without leading @


settings = Settings()


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
