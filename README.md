# Garant — Telegram Escrow Bot + Mini App

Полнофункциональный гарант-сервис: классический Telegram-бот на **aiogram 3.4.1 +
peewee + SQLite** в качестве транспорта и интеграции с CryptoBot, плюс отдельный
**Telegram Mini App (TMA)** на **FastAPI + React 18 + Vite + Tailwind +
Framer Motion + TanStack Query**.

> Тёмная тема, жёлтый акцент (`#FFD60A`), нижняя 5-табная навигация, карточки
> услуг и пользователей по дизайну скриншотов.

## Архитектура

```
+----------------+    InlineKeyboard(web_app)    +-------------------+
|  aiogram Bot   |  ---------------------------> | Telegram Client   |
|  (polling)     |                               |  + Mini App       |
+----------------+                               +-------------------+
        |                                                  |
        | bot.send_message (push)                          | initData
        v                                                  v
+------------------------------------+        +-----------------------+
| utils/notifier.py (DB + WS + TG)   | <----  | FastAPI backend       |
+------------------------------------+        |  /api/* + /ws/...     |
        ^                                     +-----------------------+
        |                                              |
        |  peewee (sync, через asyncio.to_thread)      |
        +-------------------+    +---------------------+
                            v    v
                       +---------------+
                       |  SQLite (WAL) |
                       +---------------+
```

И бот, и API живут в **одном Python-процессе**, в **одном event loop**
(`asyncio.create_task` в `main.py`) — это даёт общий экземпляр `Bot`, общий пул
коннектов к SQLite и нулевую задержку между API-эвентом и TG push.

## Структура репозитория

```
free1 root
├── main.py                   # запускает Bot polling + uvicorn (FastAPI)
├── misc/config.py            # все секреты — через env vars
├── routers/                  # legacy aiogram routers (без изменений)
├── utils/
│   ├── database/
│   │   ├── models.py         # peewee модели (старые + новые TMA-таблицы)
│   │   ├── db.py             # legacy DB методы
│   │   └── extras.py         # WebDB: методы для FastAPI
│   ├── notifier.py           # единый push (DB row + WS + bot.send_message)
│   └── keyboards/            # +кнопка «🚀 Открыть приложение» в start_keyboard
└── webapp/
    ├── backend/              # FastAPI: app, deps, security, schemas, routers/*
    └── frontend/             # React 18 + Vite + TS SPA
```

## Запуск (dev)

### 1. Переменные окружения

Скопировать `.env.example` → `.env` и заполнить:

```env
BOT_TOKEN=123456:ABC-DEF
ADMIN_CHAT_ID=123456789
CRYPTOBOT_TOKEN=...

WEBAPP_URL=https://your-domain.example/app    # домен с TLS, который зашит в BotFather
WEBAPP_HOST=0.0.0.0
WEBAPP_PORT=8080
ALLOWED_ORIGINS=https://your-domain.example,http://localhost:5173
JWT_TTL_SECONDS=86400

# Dev only — позволяет принимать неподписанный initData (НЕ использовать в prod):
# ALLOW_UNSIGNED_INIT_DATA=1
```

### 2. Backend + бот

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r req.txt
python main.py
```

`main.py` поднимет одновременно:

- aiogram polling (если задан `BOT_TOKEN`)
- uvicorn на `WEBAPP_HOST:WEBAPP_PORT` (по умолчанию `0.0.0.0:8080`)

При первом запуске создаст таблицы (peewee `create_tables` — идемпотентно) и
заполнит 16 категорий по умолчанию.

### 3. Frontend

```bash
cd webapp/frontend
npm install
npm run dev          # vite dev на :5173 с прокси /api → :8080
```

Для прода:

```bash
npm run build        # → webapp/frontend/dist
```

FastAPI автоматически отдаёт собранный SPA из `webapp/frontend/dist/` —
если папки нет, отдаётся плейсхолдер.

### 4. Подключить как Telegram Mini App

В `@BotFather`:

1. `/mybots` → ваш бот → **Bot Settings → Menu Button → Edit menu button URL**
   → введите `WEBAPP_URL` (полный URL без `t.me`).
2. (Опционально) `/newapp` → создайте Mini App, привяжите к боту.

Кнопка `🚀 Открыть приложение` появится в `/start` автоматически, когда задан
`WEBAPP_URL` (см. `utils/keyboards/user_keyboards/start_keyboard.py`).

## API

Сокращённый список (полная схема — `GET /docs`):

| Метод   | Путь                                         | Описание                                  |
| ------- | -------------------------------------------- | ----------------------------------------- |
| GET     | `/api/me`                                    | профиль + агрегаты                        |
| PATCH   | `/api/me`                                    | описание / баннер / форумы                |
| GET     | `/api/categories`                            | плитки категорий + счётчик услуг          |
| GET     | `/api/services?category=&q=&owner=`          | список услуг                              |
| POST    | `/api/services`                              | создать услугу                            |
| DELETE  | `/api/services/{id}`                         | удалить свою услугу                       |
| GET     | `/api/users?q=&filter=`                      | поиск пользователей                       |
| GET     | `/api/users/{username}`                      | карточка пользователя                     |
| GET     | `/api/deals?role=&status=`                   | сделки текущего пользователя              |
| POST    | `/api/deals`                                 | создать сделку                            |
| POST    | `/api/deals/{id}/{confirm                    | complete                                  | cancel | arbitrate}`                          | управление сделкой |
| GET     | `/api/reviews?user=`                         | отзывы                                    |
| POST    | `/api/reviews`                               | оставить отзыв                            |
| POST    | `/api/payments/deposit/invoice`              | создать CryptoBot инвойс на депозит       |
| POST    | `/api/payments/withdraw`                     | заявка на вывод                           |
| GET     | `/api/notifications?type=`                   | уведомления                               |
| GET     | `/api/notifications/counters`                | счётчики непрочитанных                    |
| POST    | `/api/notifications/{id}/read`               | пометить прочитанным                      |
| GET     | `/api/support/{admins                        | arbiters}`                                | список администрации / арбитров        |
| WS      | `/ws/notifications`                          | live-пуш событий                          |

Все запросы требуют заголовок `Authorization: tma <initData>` (или
`X-Init-Data: <initData>`). HMAC-подпись валидируется по `BOT_TOKEN`,
TTL по умолчанию 24 часа.

## Безопасность

- `initData` валидируется по HMAC-SHA256(secret = HMAC("WebAppData", BOT_TOKEN)).
- CORS строго на `ALLOWED_ORIGINS` (по умолчанию dev-домен).
- Никаких секретов в коде — всё через `os.environ` / `.env`.
- Frontend код-сплит, бандлы ≤ 200KB gzip на роут (см. вывод `npm run build`).

## Команды разработки

```bash
# backend lint / typecheck (опционально, требует ruff / mypy)
ruff check .
python -m compileall -q webapp/

# frontend lint / typecheck
cd webapp/frontend
npm run typecheck
npm run lint
npm run build
```

## Лицензия

Внутренняя разработка.
