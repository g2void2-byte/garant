# `tests/` layout

The backend test suite is split into three buckets so the cost
of running a quick sanity loop stays small and the failure
surface of any one bucket is obvious from the path.

The split mirrors the one the v12 security/code audit asked for
(`audit-report-2026-05-20.md`, item **N-7**).

## `tests/unit/`

Pure-Python tests that exercise a single module in isolation.

* No `client` fixture, no real DB session, no Redis, no Postgres.
* Touch SQLAlchemy *metadata* (column types, indices) — not rows.
* Cover string/JSON helpers, schema validators, money helpers,
  bot keyboards, etc.

These should be fast (≤ 100 ms each) and need no infrastructure
beyond an interpreter.

## `tests/integration/`

Tests that drive **one feature or endpoint at a time** through the
full FastAPI app, real Postgres, fakeredis where applicable, and
the live SQLAlchemy session factory.

This is the biggest bucket and where most regression tests live.
A test belongs here if it:

* Uses the `client` async-HTTP fixture, **or**
* Opens a real `async_session`, **or**
* Drives the WebSocket / Redis layers,

and exercises a single bounded slice of behaviour (a route, a
service helper, a webhook).

## `tests/e2e/`

Multi-actor, multi-step user-journey tests — buyer ⇄ seller ⇄
arbiter ⇄ admin orchestrated through the same HTTP surface a
real Mini-App client would use.

A test belongs here if it follows a *story*: deal lifecycle,
arbitration, multi-actor griefing scenarios, race-condition
reproductions.

## Shared fixtures

`tests/conftest.py` and `tests/helpers.py` stay at the package root
and are inherited by all three buckets through pytest's
hierarchical conftest discovery + the `tests.helpers` import path
that every test uses.

No CI configuration change is required — `pytest -v` still walks
`testpaths = ["tests"]` recursively and picks up every bucket.
