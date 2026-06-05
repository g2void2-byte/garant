"""``/api/admin/categories`` and ``/api/admin/currencies`` \u2014 taxonomy CRUD.

Two small editors for the platform's reference data. Categories drive
the service catalog; currencies control wallet visibility and
deposit/withdrawal limits.

Both endpoints support ``PUT`` upsert by code/slug \u2014 useful for
import-from-spec workflows where the natural key is stable.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ...admin_audit import log_admin_action, state_change_payload
from ...admin_guard import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import (
    Category,
    Currency,
    Deal,
    Service,
    UserBalance,
    WalletDeposit,
    WalletWithdrawal,
)
from ...rate_limit import rate_limit
from ...schemas import (
    AdminCategoryOut,
    AdminCategoryUpsertIn,
    AdminCurrencyOut,
    AdminCurrencyUpsertIn,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:taxonomy", limit=600, window=60))],
)


# ── Categories ─────────────────────────────────────────


def _cat_to_out(c: Category) -> AdminCategoryOut:
    return AdminCategoryOut(id=c.id, slug=c.slug, name=c.name, icon=c.icon)


@router.get("/categories", response_model=list[AdminCategoryOut])
async def list_categories(_admin: AdminUser, session: SessionDep):
    rows = (await session.execute(select(Category).order_by(Category.id))).scalars().all()
    return [_cat_to_out(c) for c in rows]


@router.put("/categories", response_model=AdminCategoryOut)
async def upsert_category(
    body: AdminCategoryUpsertIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    existing = (
        await session.execute(select(Category).where(Category.slug == body.slug))
    ).scalar_one_or_none()
    before: dict | None = None
    if existing is None:
        existing = Category(slug=body.slug, name=body.name, icon=body.icon)
        session.add(existing)
        await session.flush()
        action = "category.create"
    else:
        before = {"name": existing.name, "icon": existing.icon}
        existing.name = body.name
        existing.icon = body.icon
        action = "category.update"

    await log_admin_action(
        session,
        actor=admin,
        action=action,
        target_type="category",
        target_id=existing.id,
        payload=state_change_payload(
            before=before,
            after={"name": existing.name, "icon": existing.icon},
            extra={"slug": existing.slug},
        ),
        request=request,
    )
    await session.commit()
    # V11-L-19 — no ``session.refresh()`` here. ``expire_on_commit=False``
    # keeps the in-memory ``existing`` attributes loaded after commit,
    # and ``_cat_to_out`` only reads ``id`` / ``slug`` / ``name`` /
    # ``icon`` — none of which are populated by a server-side default
    # (``id`` was set by the post-``flush`` INSERT RETURNING, the
    # rest came straight from the request body). The refresh used to
    # be a free network round-trip that did nothing observable.
    return _cat_to_out(existing)


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    c = await session.get(Category, category_id)
    if c is None:
        raise HTTPException(404, "Категория не найдена")
    # Block deletion if any service still references this category.
    has_services = (
        await session.execute(select(Service.id).where(Service.category_id == c.id).limit(1))
    ).scalar_one_or_none()
    if has_services is not None:
        raise HTTPException(409, "К категории привязаны услуги, удаление невозможно")
    payload = {"slug": c.slug, "name": c.name, "icon": c.icon}
    await session.delete(c)
    await log_admin_action(
        session,
        actor=admin,
        action="category.delete",
        target_type="category",
        target_id=category_id,
        payload=payload,
        request=request,
    )
    await session.commit()
    return {"ok": True}


# ── Currencies ─────────────────────────────────────────


def _cur_to_out(c: Currency) -> AdminCurrencyOut:
    # Audit §13.7.2 — pass ``Decimal`` straight through to the schema;
    # ``AdminCurrencyOut.min_deposit`` / ``min_withdraw`` are
    # ``MoneyDecimal`` so the JSON wire format stays ``number`` but
    # internal arithmetic keeps the full ``Numeric(28, 8)`` precision.
    # Audit §13.7.3 — surface ``address_regex`` so the admin UI can
    # round-trip the value through the upsert endpoint.
    # Cast through ``Decimal`` because the SQLAlchemy ``Mapped`` type on
    # ``Currency.min_deposit`` / ``min_withdraw`` is declared as
    # ``Mapped[float]`` (the column is ``Numeric(28, 8)``; the type-hint
    # mismatch is a long-standing minor in the model). At runtime
    # ``c.min_deposit`` is already a ``Decimal``, so this is a no-op
    # call but it silences pyright on the ``MoneyDecimal`` field.
    return AdminCurrencyOut(
        id=c.id,
        code=c.code,
        name=c.name,
        network=c.network,
        icon_url=c.icon_url,
        decimals=c.decimals,
        min_deposit=Decimal(c.min_deposit),
        min_withdraw=Decimal(c.min_withdraw),
        is_active=bool(c.is_active),
        sort_order=c.sort_order,
        address_regex=c.address_regex or "",
        kind=c.kind or "crypto",
    )


def _currency_audit_snapshot(c: Currency) -> dict:
    return {
        "code": c.code,
        "name": c.name,
        "network": c.network,
        "icon_url": c.icon_url,
        "decimals": c.decimals,
        "min_deposit": str(Decimal(str(c.min_deposit))),
        "min_withdraw": str(Decimal(str(c.min_withdraw))),
        "is_active": bool(c.is_active),
        "sort_order": c.sort_order,
        "address_regex": c.address_regex or "",
        "kind": c.kind or "crypto",
    }


@router.get("/currencies", response_model=list[AdminCurrencyOut])
async def list_currencies_admin(_admin: AdminUser, session: SessionDep):
    rows = (
        (await session.execute(select(Currency).order_by(Currency.sort_order, Currency.id)))
        .scalars()
        .all()
    )
    return [_cur_to_out(c) for c in rows]


@router.put("/currencies", response_model=AdminCurrencyOut)
async def upsert_currency(
    body: AdminCurrencyUpsertIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    existing = (
        await session.execute(select(Currency).where(Currency.code == body.code))
    ).scalar_one_or_none()
    before: dict | None = None
    if existing is None:
        existing = Currency(
            code=body.code,
            name=body.name or body.code,
            network=body.network or "",
            icon_url=body.icon_url or "",
            decimals=body.decimals if body.decimals is not None else 2,
            # Audit §13.7.2 — ``Decimal`` straight into the
            # ``Numeric(28, 8)`` column; no float round-trip.
            min_deposit=body.min_deposit if body.min_deposit is not None else Decimal("1"),
            min_withdraw=body.min_withdraw if body.min_withdraw is not None else Decimal("1"),
            is_active=body.is_active if body.is_active is not None else True,
            sort_order=body.sort_order if body.sort_order is not None else 0,
            # Audit §13.7.3 — accept ``address_regex`` on create. ``None``
            # falls back to the column server_default (``""`` = validation
            # disabled), preserving back-compat with admins who haven't
            # filled the field in yet.
            address_regex=body.address_regex if body.address_regex is not None else "",
            kind=body.kind if body.kind is not None else "crypto",
        )
        session.add(existing)
        await session.flush()
        action = "currency.create"
    else:
        before = _currency_audit_snapshot(existing)
        if body.name is not None:
            existing.name = body.name
        if body.network is not None:
            existing.network = body.network
        if body.icon_url is not None:
            existing.icon_url = body.icon_url
        if body.decimals is not None:
            existing.decimals = body.decimals
        if body.min_deposit is not None:
            existing.min_deposit = body.min_deposit
        if body.min_withdraw is not None:
            existing.min_withdraw = body.min_withdraw
        if body.is_active is not None:
            existing.is_active = body.is_active
        if body.sort_order is not None:
            existing.sort_order = body.sort_order
        if body.address_regex is not None:
            existing.address_regex = body.address_regex
        if body.kind is not None:
            existing.kind = body.kind
        action = "currency.update"

    await log_admin_action(
        session,
        actor=admin,
        action=action,
        target_type="currency",
        target_id=existing.id,
        payload=state_change_payload(
            before=before,
            after=_currency_audit_snapshot(existing),
            extra={"code": existing.code},
        ),
        request=request,
    )
    await session.commit()
    # V11-L-19 — same as the category upsert above: ``_cur_to_out``
    # reads only the manually-set fields plus ``id`` (set by INSERT
    # RETURNING during ``flush``). Nothing reads a server-side
    # default column, so the post-commit ``refresh`` was redundant.
    return _cur_to_out(existing)


# Audit §3.4 — guard tables we refuse to orphan when a currency is
# dropped. Each entry is ``(model, column, label)``; the label is
# surfaced in the 409 error so the admin knows which table still
# references the row. Order matters only for the error message
# (most user-visible first) — we check every table regardless so the
# audit-log payload can capture the full reference count.
_CURRENCY_REFERENCES: tuple[tuple[type, str, str], ...] = (
    (Deal, "currency_id", "deals"),
    (Service, "currency_id", "services"),
    (UserBalance, "currency_id", "user_balances"),
    (WalletDeposit, "currency_id", "wallet_deposits"),
    (WalletWithdrawal, "currency_id", "wallet_withdrawals"),
)


@router.delete("/currencies/{currency_id}")
async def delete_currency(
    currency_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    """Delete a currency that no other row references.

    Audit §3.4 — closes the ``ПУСТЫШКА`` gap (no DELETE route existed
    for currencies even though categories had one). The guard mirrors
    ``delete_category``: any referencing row in deals / services /
    balances / wallet deposits / wallet withdrawals turns the call
    into a 409 so we never orphan a FK.
    """
    c = await session.get(Currency, currency_id)
    if c is None:
        raise HTTPException(404, "Валюта не найдена")

    blockers: dict[str, int] = {}
    for model, column, label in _CURRENCY_REFERENCES:
        col = model.__table__.columns[column]
        exists = (
            await session.execute(select(col).where(col == c.id).limit(1))
        ).scalar_one_or_none()
        if exists is not None:
            blockers[label] = 1
    if blockers:
        # 409 keeps parity with the category delete path. The list of
        # referencing tables is exposed so the admin UI can surface a
        # specific message instead of a generic conflict.
        raise HTTPException(
            409,
            {
                "detail": "К валюте привязаны данные, удаление невозможно",
                "referenced_by": sorted(blockers.keys()),
            },
        )

    payload = _currency_audit_snapshot(c)
    await session.delete(c)
    await log_admin_action(
        session,
        actor=admin,
        action="currency.delete",
        target_type="currency",
        target_id=currency_id,
        payload=payload,
        request=request,
    )
    await session.commit()
    return {"ok": True}
