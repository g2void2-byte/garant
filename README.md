# Garant — Telegram Mini App

Escrow-сервис для безопасных сделок между пользователями Telegram.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 (async + aiosqlite), Pydantic v2, aiogram 3
- **Frontend**: React 18, TypeScript, Vite, TailwindCSS, Framer Motion, TanStack Query
- **Payments**: AsyncPayments (CryptoBot SDK)

## Quick start

```bash
# 1. Clone
git clone https://github.com/g2void2-byte/garant.git && cd garant

# 2. Backend
cp .env.example .env          # fill in BOT_TOKEN, CRYPTOBOT_TOKEN, WEBAPP_URL
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # -> http://localhost:5173
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | Telegram Bot API token |
| `CRYPTOBOT_TOKEN` | — | CryptoBot API token |
| `WEBAPP_URL` | `http://localhost:5173` | Public URL of the frontend |
| `WEBAPP_PORT` | `8080` | Backend listen port |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS origins (comma-separated) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./database.db` | SQLAlchemy async DB URL |
| `RUN_BOT` | `1` | Start aiogram polling (set `0` to disable) |
| `ALLOW_UNSIGNED_INIT_DATA` | `0` | Accept unsigned initData (dev only!) |

## Project structure

```
garant/
├── backend/app/           # FastAPI + SQLAlchemy backend
│   ├── main.py            # App entrypoint + lifespan
│   ├── config.py          # pydantic-settings
│   ├── db.py              # async engine + session
│   ├── models.py          # SQLAlchemy 2 models
│   ├── schemas.py         # Pydantic DTOs
│   ├── security.py        # Telegram initData HMAC verification
│   ├── deps.py            # FastAPI dependencies
│   ├── services.py        # Escrow business logic
│   ├── notifier.py        # Push notifications + WS broadcast
│   ├── ws.py              # WebSocket connection manager
│   ├── seed.py            # Categories + settings seeder
│   ├── routers/           # HTTP route modules
│   └── bot/               # Aiogram bot (thin /start handler)
└── frontend/              # React + Vite + Tailwind
    └── src/
        ├── api/           # ky client, hooks, types
        ├── components/    # UI + domain components
        ├── pages/         # Route pages
        ├── lib/           # Utilities (tg, format, ws)
        └── App.tsx        # Router + providers
```
