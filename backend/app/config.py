from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    cryptobot_token: str = ""

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


settings = Settings()


def pin_secret() -> str:
    """JWT secret for PIN session tokens. Falls back to bot_token-derived hash."""
    if settings.pin_jwt_secret:
        return settings.pin_jwt_secret
    import hashlib

    seed = (settings.bot_token or "garant-dev-pin-secret").encode()
    return hashlib.sha256(b"pin-jwt:" + seed).hexdigest()
