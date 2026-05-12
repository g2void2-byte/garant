"""Application configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from `.env`."""

    bot_token: str = ""
    bot_username: str = "AutoGarantBot"
    webapp_url: str = "https://example.com"
    admin_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///./autogarant.db"
    commission_percent: float = 5.0
    insurance_deposit: float = 100.0
    disable_bot: int = 0

    welcome_message: str = (
        "👋 Добро пожаловать в <b>AutoGarant</b> — безопасный сервис эскроу-сделок!\n\n"
        "🔒 Средства покупателя замораживаются до выполнения условий — "
        "продавец получает их только после подтверждения.\n\n"
        "📋 <b>Основные возможности:</b>\n"
        "• Сделки с эскроу-депозитом\n"
        "• Страховой депозит\n"
        "• Рейтинг участников\n"
        "• Разрешение споров\n\n"
        "💵 Комиссия сервиса: <b>{commission}%</b>"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def admin_id_list(self) -> list[int]:
        """Return admin Telegram IDs as integers."""
        return [
            int(piece.strip())
            for piece in self.admin_ids.split(",")
            if piece.strip().isdigit()
        ]


settings = Settings()
