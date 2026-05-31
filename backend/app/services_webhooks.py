from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from .models import ProviderWebhookEvent, ProviderWebhookOutbox
from .time_utils import utcnow


def raw_event_id(raw: bytes, *, prefix: str = "sha256") -> str:
    return f"{prefix}:{hashlib.sha256(raw).hexdigest()}"


def safe_headers(headers: Headers) -> dict[str, str]:
    deny = {"authorization", "crypto-pay-api-signature", "cookie", "set-cookie"}
    out: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in deny or "signature" in lower:
            out[lower] = "<present>" if value else ""
        else:
            out[lower] = value[:512]
    return out


async def acquire_webhook_event(
    session: AsyncSession,
    *,
    provider: str,
    event_id: str,
    event_type: str,
    provider_invoice_id: str | None,
    payload: dict[str, Any],
    headers: dict[str, str],
    raw: bytes,
) -> tuple[ProviderWebhookEvent, bool]:
    raw_hash = hashlib.sha256(raw).hexdigest()
    stmt = (
        pg_insert(ProviderWebhookEvent)
        .values(
            provider=provider,
            event_id=event_id,
            event_type=event_type,
            provider_invoice_id=provider_invoice_id,
            payload_json=payload,
            headers_json=headers,
            raw_sha256=raw_hash,
            attempts=0,
            status="processing",
            processed_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
        .returning(ProviderWebhookEvent.id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    duplicate = inserted_id is None
    query = select(ProviderWebhookEvent).where(
        ProviderWebhookEvent.provider == provider,
        ProviderWebhookEvent.event_id == event_id,
    )
    if duplicate:
        query = query.with_for_update()
    event = (await session.execute(query)).scalar_one()
    if duplicate:
        event.attempts = int(event.attempts or 0) + 1
    else:
        event.attempts = 1
        event.status = "processing"
    return event, duplicate


def mark_webhook_event(
    event: ProviderWebhookEvent,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    event.status = status
    event.result_json = result
    event.error = error[:2000] if error else None
    event.processed_at = utcnow()


def enqueue_webhook_outbox(
    session: AsyncSession,
    event: ProviderWebhookEvent,
    *,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> ProviderWebhookOutbox:
    row = ProviderWebhookOutbox(
        webhook_event_id=event.id,
        kind=kind,
        payload_json=payload,
        status="ready",
    )
    session.add(row)
    return row
