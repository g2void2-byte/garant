"""Application configuration.

All sensitive values are read from environment variables; safe defaults are
provided for local development. Copy ``.env.example`` to ``.env`` and edit.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


BASE_DIR = Path(__file__).resolve().parent.parent

# --- Bot ----------------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "0000000000:TEST_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "garant_bot")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "0")

# --- Crypto bot ---------------------------------------------------------
cryptobot_token = os.getenv("CRYPTOBOT_TOKEN", "")

# --- Web app -----------------------------------------------------------
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:5173")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8080"))

# Comma separated list of allowed origins for CORS.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:8080",
    ).split(",")
    if origin.strip()
]

# initData TTL (in seconds)
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", str(60 * 60 * 24)))

# Toggle to run the bot in the same process as the API.
RUN_BOT = os.getenv("RUN_BOT", "1") == "1"
RUN_API = os.getenv("RUN_API", "1") == "1"
