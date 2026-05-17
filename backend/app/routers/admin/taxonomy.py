"""``/api/admin/categories`` and ``/api/admin/currencies`` \u2014 taxonomy CRUD.

Two small editors for the platform's reference data. Categories drive
the service catalog; currencies control wallet visibility and
deposit/withdrawal limits.

Both endpoints support ``PUT`` upsert by code/slug \u2014 useful for
import-from-spec workflows where the natural key is stable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ...admin_audit import log_admin_action, state_change_payload
from ...admin_guard import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import Category, Currency, Service
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
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
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
    return AdminCurrencyOut(
        id=c.id,
        code=c.code,
        name=c.name,
        network=c.network,
        icon_url=c.icon_url,
        decimals=c.decimals,
        min_deposit=float(c.min_deposit),
        min_withdraw=float(c.min_withdraw),
        is_active=bool(c.is_active),
        sort_order=c.sort_order,
    )


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
            min_deposit=body.min_deposit if body.min_deposit is not None else 1.0,
            min_withdraw=body.min_withdraw if body.min_withdraw is not None else 1.0,
            is_active=body.is_active if body.is_active is not None else True,
            sort_order=body.sort_order if body.sort_order is not None else 0,
        )
        session.add(existing)
        await session.flush()
        action = "currency.create"
    else:
        before = {
            "name": existing.name,
            "network": existing.network,
            "icon_url": existing.icon_url,
            "decimals": existing.decimals,
            "min_deposit": float(existing.min_deposit),
            "min_withdraw": float(existing.min_withdraw),
            "is_active": bool(existing.is_active),
            "sort_order": existing.sort_order,
        }
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
        action = "currency.update"

    await log_admin_action(
        session,
        actor=admin,
        action=action,
        target_type="currency",
        target_id=existing.id,
        payload=state_change_payload(
            before=before,
            after=_cur_to_out(existing).model_dump(),
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
