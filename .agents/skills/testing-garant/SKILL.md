---
name: testing-garant
description: End-to-end testing procedures for the garant Telegram Mini App. Use when verifying backend API, WebSocket, admin, or frontend changes.
---

# Testing Garant App

## Infrastructure Setup

```bash
# Postgres (usually already running)
docker start garant-pg || docker run -d --name garant-pg -p 5432:5432 \
  -e POSTGRES_USER=garant -e POSTGRES_PASSWORD=garant -e POSTGRES_DB=garant \
  postgres:16-alpine

# Redis
docker start garant-redis || docker run -d --name garant-redis -p 6379:6379 redis:7-alpine

# Apply migrations
cd /home/ubuntu/repos/garant
source .venv/bin/activate
alembic upgrade head

# Backend (port 8080)
REDIS_URL=redis://localhost:6379 ALLOW_UNSIGNED_INIT_DATA=1 \
  uvicorn backend.app.main:app --host 0.0.0.0 --port 8080

# Frontend (port 5173, separate shell)
cd frontend && VITE_API_URL=http://localhost:8080 npm run dev
```

## Auth in Dev Mode

With `ALLOW_UNSIGNED_INIT_DATA=1`, use raw JSON as init data:

```bash
# API call
curl -H 'Authorization: tma {"id":123,"username":"test","first_name":"test"}' \
  http://localhost:8080/api/me

# WebSocket auth frame
{"type": "auth", "init_data": "{\"id\":123,\"username\":\"test\",\"first_name\":\"test\"}"}
```

## Key Test Scenarios

### WebSocket DoS Hardening
- **Socket cap**: Max 5 connections per user. 6th is closed with code **4008** "Too many connections"
- **Rate limit**: Max 10 messages/second. Exceeding triggers close code **4008** "Rate limit exceeded"
- **Heartbeat**: Server sends `{"type":"ping"}` every 30 seconds
- Use `pip install websockets` and async Python scripts for WS testing

### GDPR IP Purge
- `sweep_user_last_ip()` in `backend/app/services.py` nulls `last_ip` for users whose `last_login_at` exceeds retention period
- Default retention: 90 days (`last_ip_retention_seconds` in settings)
- For testing, temporarily set `settings.last_ip_retention_seconds = 1`

### TOTP Pending Cache
- `POST /api/admin/2fa/setup` stores pending secret in Redis under key `totp:pending:<user_id>` with TTL ~600s
- Verify with: `docker exec garant-redis redis-cli KEYS "totp:pending:*"`
- Check TTL: `docker exec garant-redis redis-cli TTL totp:pending:<id>`
- **Note**: Response field is `otpauth_url` (not `otpauth_uri`)

### Alembic Migrations
- Verify single head: `alembic heads`
- Test round-trip: `alembic downgrade -1 && alembic upgrade head`

### Creating Admin Users
```bash
# 1. Create user via API
curl -H 'Authorization: tma {"id":99999,"username":"admin"}' http://localhost:8080/api/me
# 2. Promote to admin
docker exec garant-pg psql -U garant -d garant -c \
  "UPDATE users SET is_admin = true WHERE tg_user_id = 99999;"
```

## Health Checks
```bash
curl http://localhost:8080/health          # {"status":"ok","db":"ok"}
docker exec garant-redis redis-cli ping    # PONG
```

## Ports
- Backend: 8080
- Frontend: 5173
- Postgres: 5432
- Redis: 6379
