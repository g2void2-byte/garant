"""``/api/admin/settings`` — global :class:`AppSettings` editor.

There is exactly **one** row in ``app_settings`` (singleton pattern,
seeded on first start). ``GET`` returns the current row; ``PATCH``
performs a partial update with audit logging and rollback on error.

The maintenance flag is editable here, but a thin convenience endpoint
``/api/settings/maintenance`` is also exposed (read-only, unauth) so the
TMA + bot can poll the banner without an admin session.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ...admin_audit import log_admin_action
from ...auth_2fa import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import AppSettings
from ...rate_limit import rate_limit
from ...schemas import AdminSettingsOut, AdminSettingsUpdateIn

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


def _to_out(row: AppSettings) -> AdminSettingsOut:
    return AdminSettingsOut(
        deal_commission_percent=float(row.deal_commission_percent),
        invoice_commission_percent=float(row.invoice_commission_percent),
        vip_commission_percent=float(row.vip_commission_percent),
        min_deposit=float(row.min_deposit),
        min_withdraw=float(row.min_withdraw),
        inactivity_pending_confirmation_days=row.inactivity_pending_confirmation_days,
        inactivity_pending_cancellation_days=row.inactivity_pending_cancellation_days,
        max_active_services_per_user=row.max_active_services_per_user,
        maintenance_enabled=bool(row.maintenance_enabled),
        maintenance_message=row.maintenance_message,
        auto_withdraw_enabled=bool(row.auto_withdraw_enabled),
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

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    changed = False
    for key, new in fields.items():
        old = getattr(row, key)
        old_cmp = float(old) if isinstance(old, (int, float, Decimal)) else old
        new_cmp = float(new) if isinstance(new, (int, float, Decimal)) else new
        if old_cmp != new_cmp:
            before[key] = old_cmp
            after[key] = new_cmp
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
        payload={"before": before, "after": after},
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_out(row)
