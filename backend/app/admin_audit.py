"""Helpers for writing rows to ``admin_audit_log``.

Every admin-panel mutation goes through :func:`log_admin_action` so the
``/admin/audit`` viewer can show *who* did *what*, *when*, *why*, and
*from where*.

Why a helper instead of an ORM hook: the audit row needs the request
context (IP, actor) which is only available inside the route handler,
not in a global ``after_flush`` listener.

Trusted-proxy assumption (V5-C-5)
---------------------------------
:func:`_client_ip_from_request` reads ``X-Forwarded-For`` /
``X-Real-IP`` only when the direct peer is in
``settings.trusted_proxies``.  When ``TRUSTED_PROXIES`` is unset (the
default, suitable for a single-proxy / single-host deploy) the
function trusts every peer — matching the long-standing semantics of
:func:`backend.app.deps._client_ip` and keeping the legacy behaviour
for callers who terminate TLS on the same machine running the app.

Operators terminating TLS in front of multiple reverse proxies **must**
populate ``TRUSTED_PROXIES`` with the proxy's IP / CIDR; otherwise an
admin acting through the panel could spoof the audit-log ``ip`` column
by forging an ``X-Forwarded-For`` header, hiding their real address
behind whatever value they care to send.  The same warning lives next
to :func:`backend.app.deps._client_ip` so both code paths agree on the
threat model.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import _client_ip
from .models import AdminAuditLog, User

logger = logging.getLogger(__name__)

# V5-C-4 — cap the serialised ``payload`` JSON at 4 KB.  Audit rows
# fan out to the admin viewer and to any future Sentry / log
# aggregator, so an unbounded blob there is both a DoS knob (any
# admin endpoint could enqueue megabytes per call) and a footgun for
# PII / secret leakage.  4 KB matches the ``notifier.push``
# ``NOTIFICATION_PAYLOAD_MAX_BYTES`` (Comment 39 in audit v9); a
# structured before/after diff fits comfortably within it and an
# oversized payload is almost certainly accidental (e.g. dumping a
# whole user row).
ADMIN_AUDIT_PAYLOAD_MAX_BYTES = 4096


def _client_ip_from_request(request: Request | None) -> str | None:
    """Best-effort caller IP for the audit row.

    Delegates to :func:`backend.app.deps._client_ip` so the
    ``TRUSTED_PROXIES`` gate stays in one place.  Returns ``None``
    when no ``Request`` is available (background-task callers).
    """
    if request is None:
        return None
    return _client_ip(request)


def _serialize_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Enforce the 4 KB cap on the ``payload`` JSON.

    Returns the original mapping when it serialises under the cap, or
    ``None`` (with a warning) when it does not.  Dropping the payload
    rather than truncating mirrors :func:`backend.app.notifier._serialize_payload`
    — half-JSON is worse than no JSON for the admin viewer, which
    pretty-prints the column as a tree.  The surrounding ``action`` /
    ``actor`` / ``target_*`` columns still record that the action
    happened, so an oversized payload doesn't lose the audit
    breadcrumb itself; only the structured context is dropped.
    """
    if not payload:
        return None
    try:
        encoded = json.dumps(payload, default=str)
    except Exception:
        # ``json.dumps`` raises ``TypeError`` for unsupported types and
        # ``ValueError`` for non-finite floats; ``default=str`` can also
        # surface arbitrary exceptions from a user-defined ``__str__`` /
        # ``__repr__``.  We catch them all because the audit row is
        # *advisory* — failing the surrounding admin transaction would
        # be a far worse outcome than silently dropping the payload.
        logger.warning(
            "admin audit payload is not JSON-serialisable; dropping (keys=%s)",
            sorted(payload.keys()) if isinstance(payload, dict) else None,
        )
        return None
    if len(encoded.encode("utf-8")) > ADMIN_AUDIT_PAYLOAD_MAX_BYTES:
        logger.warning(
            "admin audit payload exceeds %d bytes, dropping (keys=%s)",
            ADMIN_AUDIT_PAYLOAD_MAX_BYTES,
            sorted(payload.keys()),
        )
        return None
    return payload


async def log_admin_action(
    session: AsyncSession,
    *,
    actor: User,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AdminAuditLog:
    """Append a row to ``admin_audit_log``.

    Caller is responsible for committing the surrounding transaction —
    we add to the session but don't flush so the row is visible only if
    the parent operation succeeds.
    """
    entry = AdminAuditLog(
        actor_id=actor.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        payload=_serialize_payload(payload),
        ip=_client_ip_from_request(request),
    )
    session.add(entry)
    return entry
