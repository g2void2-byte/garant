"""``GET /api/notifications/{id}`` — single-notification detail endpoint."""

from __future__ import annotations

from tests.helpers import (
    auth_headers,
    setup_pin,
    signed_init_data,
)


async def _seed_notification(
    recipient_tg: int,
    title: str = "Тестовое уведомление",
    body: str = "Тело сообщения",
    payload: dict | None = None,
) -> int:
    """Insert a notification row directly via the ORM and return its id."""
    from sqlalchemy import select

    from backend.app.db import async_session
    from backend.app.models import Notification, NotificationType, User

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == recipient_tg))
        ).scalar_one()
        # V11-M-10 — ``Notification.payload`` is now JSONB; pass the
        # dict straight through and let SQLAlchemy serialise.
        notif = Notification(
            recipient_id=user.id,
            type=NotificationType.deals,
            title=title,
            body=body,
            payload=payload,
        )
        session.add(notif)
        await session.commit()
        await session.refresh(notif)
        return notif.id


async def test_notification_detail_returns_owned(client):
    init = signed_init_data(9001, "notif_owner")
    await setup_pin(client, init)
    notif_id = await _seed_notification(
        9001,
        title="Новая сделка",
        body="Сделка #42 ждёт подтверждения",
        payload={"deal_id": 42},
    )
    resp = await client.get(
        f"/api/notifications/{notif_id}",
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == notif_id
    assert data["title"] == "Новая сделка"
    assert data["body"] == "Сделка #42 ждёт подтверждения"
    assert data["payload"] == {"deal_id": 42}


async def test_notification_detail_rejects_foreign(client):
    """A user cannot view a notification that belongs to a different user."""
    owner_init = signed_init_data(9011, "owner")
    stranger_init = signed_init_data(9012, "stranger")
    await setup_pin(client, owner_init)
    await setup_pin(client, stranger_init)

    notif_id = await _seed_notification(9011, title="Чужое")

    resp = await client.get(
        f"/api/notifications/{notif_id}",
        headers=auth_headers(stranger_init),
    )
    assert resp.status_code == 404, resp.text


async def test_notification_detail_404_for_missing(client):
    init = signed_init_data(9021, "missing_user")
    await setup_pin(client, init)
    resp = await client.get("/api/notifications/999999", headers=auth_headers(init))
    assert resp.status_code == 404
