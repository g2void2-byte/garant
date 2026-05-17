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

from ...admin_audit import log_admin_action, state_change_payload
from ...admin_guard import TotpUser
from ...deps import AdminUser, SessionDep
from ...maintenance import invalidate_cache as invalidate_maintenance_cache
from ...models import AppSettings
from ...rate_limit import rate_limit
from ...schemas import AdminSettingsOut, AdminSettingsUpdateIn

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)

# Defence-in-depth: only ``AppSettings`` columns named here are allowed
# to be mutated by the PATCH endpoint, regardless of what Pydantic
# accepts. Keeps an accidental new ``Optional`` field on
# :class:`AdminSettingsUpdateIn` from silently exposing an arbitrary
# attribute on the ORM model.
_EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "deal_commission_percent",
        "invoice_commission_percent",
        "vip_commission_percent",
        "min_deposit",
        "min_withdraw",
        "inactivity_pending_confirmation_days",
        "inactivity_pending_cancellation_days",
        "max_active_services_per_user",
        "maintenance_enabled",
        "maintenance_message",
        "auto_withdraw_enabled",
    }
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
        if key not in _EDITABLE_FIELDS:
            # Pydantic already filters unknown fields out, so this is
            # only reachable if the schema and the allowlist drift
            # apart. Reject loudly rather than silently writing.
            raise HTTPException(400, f"Поле '{key}' не редактируется")
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
