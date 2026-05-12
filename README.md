# AutoGarant — Telegram Escrow Bot & Mini App

AutoGarant is a Telegram bot with a Mini App for safe escrow deals. Buyers' funds are frozen until the conditions are met, and sellers receive payment only after confirmation. The service charges a 5% commission.

## Features

- Telegram bot with inline menu and Mini App launcher
- Mini App UI: Home, Deals, Balance, Profile, Search
- Escrow deals with insurance deposit, rating, and dispute resolution
- Flexible admin panel (users, deals, disputes, commission, bot settings)
- Dark theme with orange accent + smooth animations (Framer Motion)
- Telegram WebApp `initData` HMAC validation
- SQLite for local dev, PostgreSQL-ready via `DATABASE_URL`

## Tech stack

**Backend** — Python 3.11+ · FastAPI · aiogram 3 · SQLAlchemy 2 · Pydantic v2
**Frontend** — React 18 · TypeScript · Vite · TailwindCSS · Framer Motion · Zustand
**Database** — SQLite by default, PostgreSQL-ready

## Project layout

```
garant/
├── backend/                 # FastAPI + aiogram bot
│   ├── app/
│   │   ├── main.py          # FastAPI entrypoint
│   │   ├── bot.py           # aiogram bot
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── auth.py          # initData validation
│   │   ├── deps.py
│   │   └── routers/
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                # React + Vite Mini App + Admin
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── api.ts
│   │   ├── telegram.ts
│   │   └── store.ts
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
└── README.md
```

## Local development

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # then edit BOT_TOKEN, ADMIN_IDS, etc.
uvicorn app.main:app --reload
```

The bot starts in long-polling mode together with FastAPI on `http://localhost:8000`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL in Telegram via `t.me/<your_bot>/<app>` (BotFather → Configure Mini App → Web App URL).

### Environment variables

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `BOT_USERNAME` | Bot username (without `@`) — used in deep links |
| `WEBAPP_URL` | Public URL of the Mini App (e.g. ngrok / Vercel) |
| `ADMIN_IDS` | Comma-separated Telegram user IDs with admin access |
| `DATABASE_URL` | Optional, defaults to `sqlite+aiosqlite:///./autogarant.db` |
| `COMMISSION_PERCENT` | Service commission, defaults to `5` |
| `INSURANCE_DEPOSIT` | Required insurance deposit for sellers, defaults to `100` |

## Admin panel

Available inside the Mini App at `/admin` for Telegram users whose IDs are listed in `ADMIN_IDS`. The panel lets you:

- Inspect / top up / freeze any user's balance
- Browse and force-resolve any deal or dispute
- Change the commission percent and insurance deposit on the fly
- Edit the bot welcome message
- View aggregated stats (deals, volume, revenue, active users)

## License

MIT
