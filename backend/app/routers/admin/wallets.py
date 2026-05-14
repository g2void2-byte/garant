"""``/api/admin/wallets`` — per-user balance inspection and manual adjustment.

Endpoints:

* ``GET /api/admin/wallets`` — paginated list of users with their
  per-currency balances. Supports a ``q`` search (username /
  display_name) and ``currency`` filter.
* ``GET /api/admin/wallets/:user_id`` — full balance breakdown for a
  single user.
* ``POST /api/admin/wallets/:user_id/adjust`` — credit/debit a user's
  balance in a specific currency. Reason is optional per the user's
  spec; the audit row captures ``before``/``after`` for both
  ``amount`` and ``locked``.

Concurrency: the user's balance row is locked with ``FOR UPDATE`` so
two parallel adjustments can't race on the same column.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from ...admin_audit import log_admin_action
from ...auth_2fa import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import Currency, User, UserBalance
from ...rate_limit import rate_limit
from ...schemas import (
    AdminUserBalanceOut,
    AdminWalletAdjustIn,
    AdminWalletListItem,
    AdminWalletListOut,
)
from ...sql_filters import escape_like_wildcards

router = APIRouter(
    prefix="/api/admin/wallets",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


def _balance_row(user: User, currency: Currency, bal: UserBalance | None) -> AdminUserBalanceOut:
    amount = Decimal(str(bal.amount)) if bal else Decimal(0)
    locked = Decimal(str(bal.locked)) if bal else Decimal(0)
    return AdminUserBalanceOut(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        currency_id=currency.id,
        currency_code=currency.code,
        currency_name=currency.name,
        decimals=currency.decimals,
        amount=amount,
        locked=locked,
        total=amount + locked,
        updated_at=bal.updated_at if bal else None,
    )


@router.get("", response_model=AdminWalletListOut)
async def list_wallets(
    _admin: AdminUser,
    session: SessionDep,
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    # Pull active currencies once; balance rows are joined per-user.
    currencies = (
        (
            await session.execute(
                select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)
            )
        )
        .scalars()
        .all()
    )

    stmt = select(User)
    if q:
        like = f"%{escape_like_wildcards(q)}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(like, escape="\\"),
                User.display_name.ilike(like, escape="\\"),
            )
        )

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    rows = (
        (
            await session.execute(
                stmt.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    user_ids = [u.id for u in rows]
    bal_rows = []
    if user_ids:
        bal_rows = (
            (await session.execute(select(UserBalance).where(UserBalance.user_id.in_(user_ids))))
            .scalars()
            .all()
        )
    by_user: dict[int, dict[int, UserBalance]] = {}
    for b in bal_rows:
        by_user.setdefault(b.user_id, {})[b.currency_id] = b

    items: list[AdminWalletListItem] = []
    for u in rows:
        per_currency = [_balance_row(u, c, by_user.get(u.id, {}).get(c.id)) for c in currencies]
        # Very rough USD estimate: pretend 1:1 for stables, else multiply
        # by 1.0 (we don't have rates wired up yet; the field is shown
        # in the UI as an approximation only).
        usd = sum((b.total for b in per_currency), Decimal(0))
        items.append(
            AdminWalletListItem(
                user_id=u.id,
                username=u.username,
                display_name=u.display_name,
                photo_url=u.photo_url,
                is_admin=u.is_admin,
                is_arbiter=u.is_arbiter,
                is_vip=u.is_vip,
                is_banned=u.is_banned,
                is_frozen=u.is_frozen,
                balances=per_currency,
                total_usd_estimate=usd,
            )
        )

    return AdminWalletListOut(items=items, total=int(total), page=page, page_size=page_size)


@router.get("/{user_id}", response_model=list[AdminUserBalanceOut])
async def user_wallet_detail(user_id: int, _admin: AdminUser, session: SessionDep):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    currencies = (
        (
            await session.execute(
                select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)
            )
        )
        .scalars()
        .all()
    )
    bal_rows = (
        (await session.execute(select(UserBalance).where(UserBalance.user_id == user.id)))
        .scalars()
        .all()
    )
    by_currency = {b.currency_id: b for b in bal_rows}
    return [_balance_row(user, c, by_currency.get(c.id)) for c in currencies]


@router.post("/{user_id}/adjust", response_model=AdminUserBalanceOut)
async def adjust_user_balance(
    user_id: int,
    body: AdminWalletAdjustIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")

    currency = (
        await session.execute(select(Currency).where(Currency.code == body.currency_code))
    ).scalar_one_or_none()
    if currency is None:
        raise HTTPException(404, f"Валюта {body.currency_code} не найдена")

    # Lock the balance row for the duration of the adjustment so a
    # concurrent admin can't race us on the same column.
    bal = (
        await session.execute(
            select(UserBalance)
            .where(
                UserBalance.user_id == user.id,
                UserBalance.currency_id == currency.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if bal is None:
        bal = UserBalance(user_id=user.id, currency_id=currency.id, amount=0, locked=0)
        session.add(bal)
        await session.flush()

    before_amount = Decimal(str(bal.amount))
    delta = Decimal(str(body.amount))
    new_amount = before_amount + delta
    if new_amount < 0:
        raise HTTPException(
            400,
            f"Недостаточно средств: текущий баланс {before_amount}, корректировка {delta}",
        )
    # M5: persist as Decimal so the ``Numeric(18,8)`` precision is
    # preserved end-to-end — admin adjustments on the BTC/USDT side
    # otherwise lose the last few sat / cents on every save.
    bal.amount = new_amount

    await log_admin_action(
        session,
        actor=admin,
        action="wallet.adjust",
        target_type="user",
        target_id=user.id,
        reason=body.reason,
        payload={
            "currency": currency.code,
            # M-20: persist audit numbers as strings so the trail keeps
            # full ``Numeric(18,8)`` precision instead of losing the
            # tail digits to a ``float`` round-trip in the JSONB column.
            "delta": str(delta),
            "before_amount": str(before_amount),
            "after_amount": str(new_amount),
        },
        request=request,
    )
    await session.commit()
    await session.refresh(bal)
    return _balance_row(user, currency, bal)
