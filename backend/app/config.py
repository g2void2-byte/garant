from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    cryptobot_token: str = ""
    cryptobot_testnet: bool = False

    webapp_url: str = "http://localhost:5173"
    webapp_port: int = 8080
    allowed_origins: str = "http://localhost:5173"

    database_url: str = "sqlite+aiosqlite:///./database.db"

    run_bot: bool = True
    allow_unsigned_init_data: bool = False

    pin_jwt_secret: str = ""
    pin_session_ttl_seconds: int = 60 * 60 * 12
    pin_max_attempts: int = 3
    pin_lock_minutes: int = 60
    pin_reset_code_ttl_seconds: int = 10 * 60

    # PR-3 — periodic sweep of stale deals (0 disables).
    inactivity_sweep_seconds: int = 600

    # PR-CA — TTL for account-transfer one-time codes.
    account_transfer_code_ttl_seconds: int = 15 * 60

    # PR-E — uploaded media storage.
    media_root: str = "./media-uploads"
    media_base_url: str = "/media"  # served at this path on the backend host
    media_max_bytes: int = 5 * 1024 * 1024  # 5 MiB
    media_allowed_kinds: str = "avatar,banner,deal"

    # P3.2 — bot menu external links. Empty values hide the button.
    bot_forums_url: str = ""
    bot_community_chat_url: str = ""
    bot_arbitration_url: str = ""
    bot_docs_url: str = ""
    bot_support_username: str = ""  # Telegram username without leading @


settings = Settings()


def pin_secret() -> str:
    """JWT secret for PIN session tokens. Falls back to bot_token-derived hash."""
    if settings.pin_jwt_secret:
        return settings.pin_jwt_secret
    import hashlib

    seed = (settings.bot_token or "garant-dev-pin-secret").encode()
    return hashlib.sha256(b"pin-jwt:" + seed).hexdigest()
