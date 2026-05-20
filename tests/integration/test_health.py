"""Health endpoint sanity checks."""

from __future__ import annotations


async def test_health_returns_ok_with_db_ping(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "db": "ok"}


async def test_health_reports_degraded_when_db_unreachable(client, monkeypatch):
    """Force the SELECT 1 to raise and confirm the endpoint surfaces 503.

    Patches ``backend.app.main.async_session`` so that opening a session
    raises a RuntimeError, simulating a DB connection failure without
    actually breaking the running engine.
    """
    from backend.app import main

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("simulated DB outage")

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(main, "async_session", lambda: _BoomSession())
    resp = await client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "down"
