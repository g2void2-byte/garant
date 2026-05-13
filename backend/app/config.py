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


settings = Settings()
