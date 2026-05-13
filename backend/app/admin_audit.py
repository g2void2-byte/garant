"""Helpers for writing rows to ``admin_audit_log``.

Every admin-panel mutation goes through :func:`log_admin_action` so the
``/admin/audit`` viewer can show *who* did *what*, *when*, *why*, and
*from where*.

Why a helper instead of an ORM hook: the audit row needs the request
context (IP, actor) which is only available inside the route handler,
not in a global ``after_flush`` listener.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AdminAuditLog, User


def _client_ip_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else None


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
        payload=payload,
        ip=_client_ip_from_request(request),
    )
    session.add(entry)
    return entry
