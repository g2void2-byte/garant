"""Item 22 — ``deal.updated`` WS event fan-out.

The historic ``notification`` event only reached the recipient of a
stored ``Notification`` row, so the *initiator* of every state-changing
deal op kept a stale React Query cache until the next focus / poll
refetch. ``services_deals`` now also emits a transient
``{event: "deal.updated", data: {deal_id, status}}`` over the WS channel
to every participant (buyer + seller, plus arbiters where relevant) so
both ends of the deal invalidate their cache in real time.

These tests pin the wiring at the integration boundary: drive each
state transition through the public HTTP API and assert that
``manager.publish`` was invoked with the ``deal.updated`` envelope for
*both* parties (not just the notification recipient).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


@pytest.fixture
def capture_publishes(monkeypatch):
    """Record every ``manager.publish(user_id, data)`` call.

    Returns a list of ``(user_id, data)`` tuples in the order
    ``publish`` was called. We patch the ``manager.publish`` attribute
    *as imported from* ``backend.app.notifier`` so both
    ``notifier.dispatch_after_commit`` (stored notifications) and
    ``notifier.publish_deal_update`` (deal.updated signal) route
    through the same recorder.
    """
    calls: list[tuple[int, dict[str, Any]]] = []

    async def _record(user_id: int, data: dict[str, Any]) -> None:
        calls.append((user_id, data))

    monkeypatch.setattr("backend.app.notifier.manager.publish", _record)
    return calls


def _deal_updated_recipients(calls: list[tuple[int, dict[str, Any]]]) -> set[int]:
    return {uid for uid, data in calls if data.get("event") == "deal.updated"}


async def _seed_pair(
    client, *, buyer_tg: int, seller_tg: int
) -> tuple[int, int, str, str, str, str]:
    """Bootstrap buyer + seller, set PINs, and credit the buyer."""
    from backend.app.db import async_session

    buyer_init = signed_init_data(buyer_tg, f"buyer{buyer_tg}")
    seller_init = signed_init_data(seller_tg, f"seller{seller_tg}")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, buyer_tg)
        seller_id = await get_user_id_by_tg(session, seller_tg)
        await credit_balance(session, buyer_id, "USDT", 100)

    return buyer_id, seller_id, buyer_init, seller_init, buyer_pin, seller_pin


async def test_create_deal_emits_deal_updated_to_both_parties(client, capture_publishes):
    """``POST /api/deals`` fires ``deal.updated`` for buyer + seller."""
    buyer_id, seller_id, buyer_init, _, buyer_pin, _ = await _seed_pair(
        client, buyer_tg=51001, seller_tg=51002
    )

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller51002",
            "role": "buyer",
            "amount": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert create_resp.status_code == 201, create_resp.text
    deal_id = create_resp.json()["id"]

    recipients = _deal_updated_recipients(capture_publishes)
    assert buyer_id in recipients, "buyer (initiator) must receive deal.updated"
    assert seller_id in recipients, "seller must receive deal.updated"

    deal_updated_payloads = [
        data for _, data in capture_publishes if data.get("event") == "deal.updated"
    ]
    for envelope in deal_updated_payloads:
        assert envelope["data"]["deal_id"] == deal_id
        assert envelope["data"]["status"] == "pending_confirmation"


async def test_finish_deal_emits_deal_updated_to_both_parties(client, capture_publishes):
    """Item 22 root cause — ``finish_deal`` now reaches the buyer (initiator)."""
    buyer_id, seller_id, buyer_init, seller_init, buyer_pin, seller_pin = await _seed_pair(
        client, buyer_tg=51011, seller_tg=51012
    )

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller51012",
            "role": "buyer",
            "amount": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create_resp.json()["id"]

    await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )

    # Reset the recorder so we only assert on the finish_deal fan-out.
    capture_publishes.clear()

    finish_resp = await client.post(
        f"/api/deals/{deal_id}/finish",
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert finish_resp.status_code == 200, finish_resp.text

    recipients = _deal_updated_recipients(capture_publishes)
    # The pre-fix bug: only the seller got a ``notification`` event, so
    # the buyer's "My Deals" list stayed stuck on ``in_progress`` until
    # they reloaded the TMA. ``deal.updated`` to both sides closes that.
    assert buyer_id in recipients, "buyer (initiator of finish) must receive deal.updated"
    assert seller_id in recipients

    completed_envelope = next(
        (data for _, data in capture_publishes if data.get("event") == "deal.updated"),
        None,
    )
    assert completed_envelope is not None
    assert completed_envelope["data"]["deal_id"] == deal_id
    assert completed_envelope["data"]["status"] == "completed"


async def test_accept_deal_emits_deal_updated_to_both_parties(client, capture_publishes):
    """``accept_deal`` fans out to both buyer (initiator of the original
    deal request) and seller (whose action this is)."""
    buyer_id, seller_id, buyer_init, seller_init, buyer_pin, seller_pin = await _seed_pair(
        client, buyer_tg=51021, seller_tg=51022
    )

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller51022",
            "role": "buyer",
            "amount": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create_resp.json()["id"]

    capture_publishes.clear()

    accept_resp = await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert accept_resp.status_code == 200, accept_resp.text

    recipients = _deal_updated_recipients(capture_publishes)
    assert buyer_id in recipients
    assert seller_id in recipients


async def test_decline_deal_emits_deal_updated_to_both_parties(client, capture_publishes):
    """``decline_deal`` fans out to both buyer and seller."""
    buyer_id, seller_id, buyer_init, seller_init, buyer_pin, seller_pin = await _seed_pair(
        client, buyer_tg=51031, seller_tg=51032
    )

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller51032",
            "role": "buyer",
            "amount": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create_resp.json()["id"]

    capture_publishes.clear()

    decline_resp = await client.post(
        f"/api/deals/{deal_id}/decline",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert decline_resp.status_code == 200, decline_resp.text

    recipients = _deal_updated_recipients(capture_publishes)
    assert buyer_id in recipients
    assert seller_id in recipients


async def test_request_cancel_emits_deal_updated_to_both_parties(client, capture_publishes):
    """``request_cancel`` is initiated by one party; the other gets the
    stored notification, but ``deal.updated`` must reach both so the
    initiator's own list refreshes too."""
    buyer_id, seller_id, buyer_init, seller_init, buyer_pin, seller_pin = await _seed_pair(
        client, buyer_tg=51041, seller_tg=51042
    )

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller51042",
            "role": "buyer",
            "amount": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create_resp.json()["id"]
    await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )

    capture_publishes.clear()

    cancel_resp = await client.post(
        f"/api/deals/{deal_id}/cancel_request",
        json={"reason": "no longer needed"},
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert cancel_resp.status_code == 200, cancel_resp.text

    recipients = _deal_updated_recipients(capture_publishes)
    assert buyer_id in recipients, "buyer (initiator of cancel) must receive deal.updated"
    assert seller_id in recipients


async def test_publish_deal_update_dedupes_recipients(monkeypatch):
    """``publish_deal_update`` deduplicates repeated recipient ids."""
    from backend.app.notifier import publish_deal_update

    calls: list[tuple[int, dict[str, Any]]] = []

    async def _record(user_id: int, data: dict[str, Any]) -> None:
        calls.append((user_id, data))

    monkeypatch.setattr("backend.app.notifier.manager.publish", _record)

    await publish_deal_update(42, [7, 7, 8, 7], status="in_progress")
    recorded = [uid for uid, _ in calls]
    assert recorded == [7, 8]
    for _, data in calls:
        assert data["event"] == "deal.updated"
        assert data["data"] == {"deal_id": 42, "status": "in_progress"}


async def test_publish_deal_update_swallows_publish_errors(monkeypatch, caplog):
    """A broken WS publish must not bubble up past the helper."""
    import logging

    from backend.app.notifier import publish_deal_update

    async def _boom(user_id: int, data: dict[str, Any]) -> None:  # noqa: ARG001
        raise RuntimeError("redis down")

    monkeypatch.setattr("backend.app.notifier.manager.publish", _boom)

    with caplog.at_level(logging.ERROR, logger="backend.app.notifier"):
        await publish_deal_update(13, [1, 2], status="completed")

    assert any("deal.updated publish failed" in r.message for r in caplog.records), (
        "must log the swallowed exception"
    )


async def test_sweep_inactivity_emits_deal_updated_to_both_parties(client, capture_publishes):
    """The cron sweep also fans out the ``deal.updated`` signal so any
    sessions still open on the cancelled deal refresh in real time."""
    import datetime as dt

    from backend.app.db import async_session
    from backend.app.models import Deal
    from backend.app.services_deals import sweep_inactivity
    from backend.app.time_utils import utcnow

    buyer_id, seller_id, buyer_init, _, buyer_pin, _ = await _seed_pair(
        client, buyer_tg=51051, seller_tg=51052
    )

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller51052",
            "role": "buyer",
            "amount": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create_resp.json()["id"]

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        deal.created_at = utcnow() - dt.timedelta(days=30)
        await session.commit()

    capture_publishes.clear()

    async with async_session() as session:
        affected = await sweep_inactivity(session)
        assert affected == 1

    recipients = _deal_updated_recipients(capture_publishes)
    assert buyer_id in recipients
    assert seller_id in recipients

    # Status reflects the auto-cancel target.
    statuses = {
        data["data"]["status"]
        for _, data in capture_publishes
        if data.get("event") == "deal.updated"
    }
    assert "cancelled_for_inactivity" in statuses


async def test_finish_deal_via_pytest_capture_module_level_helper():
    """Smoke test the bare helper signature (no kwargs) is callable."""
    from backend.app.notifier import publish_deal_update

    # Should not raise even with an empty recipient list and no status.
    await publish_deal_update(99, [])
    await publish_deal_update(99, (), status=None)


async def test_capture_publishes_fixture_resets_between_tests(client, capture_publishes):
    """Sanity — the recorder is freshly empty at the start of each test."""
    assert capture_publishes == []
    # Touch the test client so it does not get flagged as unused.
    assert client is not None


@pytest.mark.parametrize(
    "deal_id,recipients",
    [
        (1, [10, 20]),
        (2, [10]),
        (3, []),
    ],
)
async def test_publish_deal_update_handles_varied_inputs(monkeypatch, deal_id, recipients):
    """The helper accepts any iterable shape without inserting DB rows."""
    from backend.app.db import async_session
    from backend.app.models import Notification
    from backend.app.notifier import publish_deal_update

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("backend.app.notifier.manager.publish", _noop)

    async with async_session() as session:
        before = (await session.execute(select(Notification))).scalars().all()
    await publish_deal_update(deal_id, recipients, status="in_progress")
    async with async_session() as session:
        after = (await session.execute(select(Notification))).scalars().all()
    assert len(before) == len(after), (
        "publish_deal_update is a pure WS signal — it must not insert Notification rows"
    )
