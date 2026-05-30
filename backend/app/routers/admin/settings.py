"""``/api/admin/settings`` — global :class:`AppSettings` editor.

There is exactly **one** row in ``app_settings`` (singleton pattern,
seeded on first start). ``GET`` returns the current row; ``PATCH``
performs a partial update with audit logging and rollback on error.

The maintenance flag is editable here, but a thin convenience endpoint
``/api/settings/maintenance`` is also exposed (read-only, unauth) so the
TMA + bot can poll the banner without an admin session.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ...admin_audit import log_admin_action, state_change_payload
from ...admin_guard import TotpUser
from ...deps import AdminUser, SessionDep
from ...maintenance import invalidate_cache as invalidate_maintenance_cache
from ...models import AppSettings
from ...rate_limit import rate_limit
from ...schemas import AdminSettingsOut, AdminSettingsUpdateIn
from ...services_wallet import is_cryptopay_configured

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:settings", limit=600, window=60))],
)

# Defence-in-depth: only ``AppSettings`` columns named here are allowed
# to be mutated by the PATCH endpoint, regardless of what Pydantic
# accepts. Keeps an accidental new ``Optional`` field on
# :class:`AdminSettingsUpdateIn` from silently exposing an arbitrary
# attribute on the ORM model.
_EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "deal_commission_percent",
        "vip_commission_percent",
        "inactivity_pending_confirmation_days",
        "inactivity_pending_cancellation_days",
        "max_active_services_per_user",
        "maintenance_enabled",
        "maintenance_message",
        "auto_withdraw_enabled",
        "pending_topup_expiry_hours",
        "pin_reset_price_usd",
        "faq_stats_badge_enabled",
        "faq_stats_users",
        "faq_stats_deals",
        "faq_stats_total_usd",
    }
)


def _to_out(row: AppSettings) -> AdminSettingsOut:
    # ``AdminSettingsOut`` declares money columns as ``MoneyDecimal``
    # (``Annotated[Decimal, PlainSerializer(lambda v: float(v), ...)``)
    # which serialises to a JSON ``float`` on the wire but stores
    # ``Decimal`` in-memory. Passing ``float(row.x)`` used to detour
    # the value through ``float`` *before* Pydantic re-cast it back
    # to ``Decimal``, dropping precision (e.g. ``Decimal('0.10')``
    # → ``float`` 0.1 → ``Decimal('0.1000000000000000055511151231...')``)
    # and producing a noisy wire payload for percentages that happen
    # not to be exact in binary float. Hand the ``Decimal`` straight
    # to Pydantic; ``PlainSerializer`` does the one (and only) cast.
    return AdminSettingsOut(
        deal_commission_percent=Decimal(str(row.deal_commission_percent)),
        vip_commission_percent=Decimal(str(row.vip_commission_percent)),
        inactivity_pending_confirmation_days=row.inactivity_pending_confirmation_days,
        inactivity_pending_cancellation_days=row.inactivity_pending_cancellation_days,
        max_active_services_per_user=row.max_active_services_per_user,
        maintenance_enabled=bool(row.maintenance_enabled),
        maintenance_message=row.maintenance_message,
        auto_withdraw_enabled=bool(row.auto_withdraw_enabled),
        pending_topup_expiry_hours=int(row.pending_topup_expiry_hours or 24),
        pin_reset_price_usd=row.pin_reset_price_usd,
        faq_stats_badge_enabled=bool(row.faq_stats_badge_enabled),
        faq_stats_users=int(row.faq_stats_users or 0),
        faq_stats_deals=int(row.faq_stats_deals or 0),
        faq_stats_total_usd=row.faq_stats_total_usd,
    )


async def _get_settings(session, *, for_update: bool = False) -> AppSettings:
    stmt = select(AppSettings).order_by(AppSettings.id).limit(1)
    if for_update:
        # Row-level lock so two admins editing the singleton concurrently
        # serialise — without this the second commit's audit-log
        # ``before`` snapshot can mismatch the value the user actually
        # saw on the form, even if the final DB state is fine.
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        # Defensive: seed should create it, but if a fresh deployment
        # misses the seed we create a row here so the admin doesn't see
        # a 500.
        row = AppSettings()
        session.add(row)
        await session.flush()
    return row


@router.get("/settings", response_model=AdminSettingsOut)
async def get_settings(_admin: AdminUser, session: SessionDep):
    return _to_out(await _get_settings(session))


@router.patch("/settings", response_model=AdminSettingsOut)
async def update_settings(
    body: AdminSettingsUpdateIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    row = await _get_settings(session, for_update=True)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "Нет изменений")

    # Audit §6.4 — emit a structured WARNING when ``auto_withdraw_enabled``
    # is being flipped on while the CryptoBot token is missing /
    # placeholder. ``admin/withdrawals.py`` already logs at warn-level
    # on the *approval* path when both conditions hold, but the admin
    # who toggled the flag never saw a direct signal — they only
    # discovered the misconfiguration when the payout queue stopped
    # draining hours later. Surfacing the warning at PATCH time too
    # means the broken state is visible in logs at the exact moment
    # the flag is set, which is what operators are actually watching.
    # Soft-warn (rather than a hard 400) so an operator can pre-stage
    # the flag for a token they're about to configure in the same
    # deploy.
    if fields.get("auto_withdraw_enabled") is True and not is_cryptopay_configured():
        logger.warning(
            "admin.settings.update: auto_withdraw_enabled flipped on "
            "while cryptobot_token is unset/placeholder — payout queue "
            "will silently fall back to manual until CRYPTOBOT_TOKEN "
            "is configured.",
            extra={
                "event": "admin.settings.auto_withdraw.missing_token",
                "actor_id": admin.id,
            },
        )

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    changed = False
    for key, new in fields.items():
        if key not in _EDITABLE_FIELDS:
            # Pydantic already filters unknown fields out, so this is
            # only reachable if the schema and the allowlist drift
            # apart. Reject loudly rather than silently writing.
            raise HTTPException(400, f"Поле '{key}' не редактируется")
        old = getattr(row, key)
        # Equality on money columns: compare as ``Decimal`` so the
        # check doesn't round-trip through ``float`` (e.g.
        # ``Decimal('7.5') == float(Decimal('7.5'))`` happens to hold,
        # but ``Decimal('0.10') != float(Decimal('0.10'))`` in general
        # because 0.1 has no exact binary repr). The audit-log payload
        # still keeps the wire-friendly ``float`` shape so the existing
        # admin-UI ``PayloadPreview`` renders numbers, not quoted
        # strings, exactly as before.
        if isinstance(old, Decimal) or isinstance(new, Decimal):
            old_dec = old if isinstance(old, Decimal) else Decimal(str(old))
            new_dec = new if isinstance(new, Decimal) else Decimal(str(new))
            if old_dec != new_dec:
                before[key] = float(old_dec)
                after[key] = float(new_dec)
                setattr(row, key, new)
                changed = True
        elif old != new:
            before[key] = old
            after[key] = new
            setattr(row, key, new)
            changed = True

    if not changed:
        return _to_out(row)

    await log_admin_action(
        session,
        actor=admin,
        action="settings.update",
        target_type="app_settings",
        target_id=row.id,
        payload=state_change_payload(before=before, after=after),
        request=request,
    )
    await session.commit()
    # V11-L-19 — no ``session.refresh()`` here. ``expire_on_commit=False``
    # keeps the in-memory ``row`` attributes loaded after commit, and
    # ``_to_out`` reads only the explicit settings columns set above
    # via ``setattr``. ``AppSettings.updated_at`` has ``onupdate=func.now()``
    # but ``_to_out`` does NOT include it in the response shape, so
    # the post-commit refresh used to be a free network round-trip
    # that nothing read.
    # Drop the in-process maintenance cache so the toggle takes effect
    # on this worker immediately. Other workers / processes catch up
    # within the cache TTL on their own.
    if "maintenance_enabled" in after or "maintenance_message" in after:
        invalidate_maintenance_cache()
    return _to_out(row)
