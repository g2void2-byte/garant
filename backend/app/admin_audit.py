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
from collections.abc import Mapping
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
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream surfaces *which* admin action lost its payload
        # (rather than a free-form keys list buried in the message).
        logger.warning(
            "admin audit payload is not JSON-serialisable; dropping (keys=%s)",
            sorted(payload.keys()) if isinstance(payload, dict) else None,
            extra={
                "event": "admin_audit.payload.non_serialisable",
                "payload_keys": (sorted(payload.keys()) if isinstance(payload, dict) else None),
            },
        )
        return None
    if len(encoded.encode("utf-8")) > ADMIN_AUDIT_PAYLOAD_MAX_BYTES:
        logger.warning(
            "admin audit payload exceeds %d bytes, dropping (keys=%s)",
            ADMIN_AUDIT_PAYLOAD_MAX_BYTES,
            sorted(payload.keys()),
            extra={
                "event": "admin_audit.payload.oversize",
                "payload_size_bytes": len(encoded.encode("utf-8")),
                "payload_max_bytes": ADMIN_AUDIT_PAYLOAD_MAX_BYTES,
                "payload_keys": sorted(payload.keys()),
            },
        )
        return None
    return payload


def state_change_payload(
    *,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical state-change audit payload.

    V11-L-12 — the ``admin_audit_log.payload`` JSONB column historically
    accepted any shape; the v9 audit (Comment 39) capped it at 4 KB but
    didn't standardise the schema, so similar admin actions (settings
    update, user-role change, taxonomy edit) ended up writing different
    structures — some used ``{"before": ..., "after": ...}``, others
    flat key/value, others nested ``{"changes": {...}}``. That made the
    audit viewer harder to reason about and ad-hoc consumers (Sentry,
    bigquery export, future diff renderers) had to special-case each
    action.

    This helper produces the canonical shape for any *state-change*
    action::

        {
            "before": {<attr>: <old value>, ...},
            "after":  {<attr>: <new value>, ...},
            "diff":   [<attr>, ...],          # keys whose values differ
            "context": {...},                 # optional caller-supplied extras
        }

    ``diff`` is precomputed so the viewer / downstream consumers don't
    need to re-derive it (and so a future schema migration can rely on
    ``diff`` being authoritative even if ``before``/``after`` get
    redacted for size). Keys present in only one of ``before`` / ``after``
    are treated as changed.

    Free-form / non-state-change actions (e.g. ``user.ban`` with just a
    reason, ``balance.adjust`` recording an immutable transaction)
    continue to pass ``payload=`` directly to :func:`log_admin_action`
    — this helper is purely for the diff pattern.
    """
    # ``None`` and ``{}`` are *different* states for the schema:
    # ``before=None`` means "the entity did not exist" (create branch),
    # ``after=None`` means "the entity was deleted", and ``{}`` would
    # be a degenerate "exists but has zero recorded attributes". Keep
    # the distinction so the admin viewer can render
    # "first-time-creation" vs "no-op patch" differently.
    before_dict = dict(before) if before is not None else None
    after_dict = dict(after) if after is not None else None
    b_keys: set[str] = set(before_dict) if before_dict is not None else set()
    a_keys: set[str] = set(after_dict) if after_dict is not None else set()
    keys = sorted(b_keys | a_keys)
    _missing = object()

    def _get(side: dict[str, Any] | None, key: str) -> Any:
        if side is None:
            return _missing
        return side.get(key, _missing)

    diff_keys = [k for k in keys if _get(before_dict, k) != _get(after_dict, k)]
    payload: dict[str, Any] = {
        "before": before_dict,
        "after": after_dict,
        "diff": diff_keys,
    }
    if extra:
        payload["context"] = dict(extra)
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
