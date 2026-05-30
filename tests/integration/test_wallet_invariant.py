"""V5-D-11 — wallet credit-path invariant (post-H-1).

Pre-H-1 the platform had two parallel deposit surfaces:

* a legacy USD ``Invoice`` ledger that bumped the per-row
  ``users.balance`` ``Numeric(14,2)`` column via
  ``services.credit_invoice``;
* the multi-currency ``WalletDeposit`` flow that bumps the matching
  ``user_balances(user_id, currency_id)`` row via
  ``services_wallet.credit_deposit``.

H-1 retired the legacy ledger entirely. The credit path now has a
single entry point — ``credit_deposit`` — that must:

* bump exactly one ``user_balances`` row (the one for
  ``(user_id, currency_id)`` matching the ``WalletDeposit``);
* never touch ``user_balances.locked`` (only the withdrawal hold
  path is allowed to touch ``locked``);
* never touch a ``user_balances`` row for a *different* currency the
  user happens to also have a balance in;
* be idempotent — a second call on an already-paid ``WalletDeposit``
  must be a no-op (no double-credit).

The tests below freeze that contract: they snapshot every
``user_balances`` row owned by the user before each ``credit_deposit``
call, run the helper, and assert that exactly the matching row's
``amount`` moved by the deposit amount and nothing else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
)
from backend.app.services_wallet import credit_deposit


async def _seed_user(tg_user_id: int) -> int:
    async with async_session() as session:
        u = User(
            tg_user_id=tg_user_id,
            username=f"inv{tg_user_id}",
            display_name="invariant",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


async def _seed_balance(user_id: int, code: str, amount: Decimal) -> tuple[int, int]:
    """Create a ``UserBalance`` row with the given starting ``amount``.

    Returns ``(currency_id, balance_id)`` so the test can re-fetch the
    same row by primary key without going through the seed code.
    """
    async with async_session() as session:
        currency = (
            await session.execute(select(Currency).where(Currency.code == code))
        ).scalar_one()
        bal = UserBalance(
            user_id=user_id,
            currency_id=currency.id,
            amount=amount,
            locked=Decimal("0"),
        )
        session.add(bal)
        await session.commit()
        await session.refresh(bal)
        return currency.id, bal.id


async def _seed_deposit(
    user_id: int,
    currency_id: int,
    amount: Decimal,
    provider_invoice_id: str,
    status: WalletDepositStatus = WalletDepositStatus.pending,
    purpose: str = "wallet",
) -> int:
    async with async_session() as session:
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=currency_id,
            amount=amount,
            provider_invoice_id=provider_invoice_id,
            pay_url="http://example.com/pay",
            status=status,
            purpose=purpose,
        )
        session.add(dep)
        await session.commit()
        await session.refresh(dep)
        return dep.id


async def _snapshot(user_id: int) -> dict[int, tuple[Decimal, Decimal]]:
    """Return ``{balance_id: (amount, locked)}`` for the user's wallet rows."""
    async with async_session() as session:
        rows = (
            (await session.execute(select(UserBalance).where(UserBalance.user_id == user_id)))
            .scalars()
            .all()
        )
        return {r.id: (Decimal(str(r.amount)), Decimal(str(r.locked))) for r in rows}


@pytest.mark.asyncio
async def test_credit_deposit_only_touches_matching_user_balance():
    """``credit_deposit`` must bump exactly the matching
    ``UserBalance(user_id, currency_id)`` row's ``amount`` field and
    leave every other ``UserBalance`` row (including a different
    currency for the same user) plus every ``locked`` field
    untouched.
    """
    user_id = await _seed_user(50_002)

    usdt_id, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("100"))
    _, ton_bal_id = await _seed_balance(user_id, "TON", Decimal("3.5"))

    before = await _snapshot(user_id)
    assert before == {
        usdt_bal_id: (Decimal("100"), Decimal("0")),
        ton_bal_id: (Decimal("3.5"), Decimal("0")),
    }

    deposit_amount = Decimal("15.75")
    deposit_id = await _seed_deposit(user_id, usdt_id, deposit_amount, "cb-dep-only-1")

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit)

    after = await _snapshot(user_id)
    expected_usdt_amount = before[usdt_bal_id][0] + deposit_amount
    assert after == {
        usdt_bal_id: (expected_usdt_amount, Decimal("0")),
        ton_bal_id: before[ton_bal_id],
    }, (
        "credit_deposit must move only the matching (user, currency) row's "
        f"amount; before={before} after={after}"
    )

    async with async_session() as session:
        dep = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        assert dep.status == WalletDepositStatus.paid
        assert dep.paid_at is not None


@pytest.mark.asyncio
async def test_credit_deposit_is_idempotent_and_does_not_re_touch_balances():
    """Crediting an already-paid ``WalletDeposit`` is a no-op.

    A second call on the same row must not bump ``UserBalance.amount``
    a second time and must not touch ``UserBalance.locked``.
    """
    user_id = await _seed_user(50_004)
    usdt_id, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("0"))

    deposit_amount = Decimal("8.0")
    deposit_id = await _seed_deposit(user_id, usdt_id, deposit_amount, "cb-dep-idemp-1")

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit)

    after_first = await _snapshot(user_id)
    assert after_first == {usdt_bal_id: (deposit_amount, Decimal("0"))}

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit)

    after_second = await _snapshot(user_id)
    assert after_second == after_first, (
        "credit_deposit must be idempotent — a repeat call on a paid "
        f"deposit must not move any balance; first={after_first} "
        f"second={after_second}"
    )


@pytest.mark.asyncio
async def test_credit_deposit_credits_webhook_reported_overpayment():
    """Wallet deposits credit the actual paid amount when it is higher
    than the invoice nominal amount."""
    user_id = await _seed_user(50_006)
    usdt_id, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("0"))
    deposit_id = await _seed_deposit(user_id, usdt_id, Decimal("10"), "cb-dep-overpay-1")

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit, paid_amount=Decimal("12"))

    after = await _snapshot(user_id)
    assert after == {usdt_bal_id: (Decimal("12.00000000"), Decimal("0"))}
    async with async_session() as session:
        dep = await session.get(WalletDeposit, deposit_id)
        assert dep is not None
        assert Decimal(str(dep.amount)) == Decimal("12.00000000")
        assert Decimal(str(dep.paid_amount)) == Decimal("12.00000000")


@pytest.mark.asyncio
async def test_credit_trust_deposit_credits_webhook_reported_overpayment():
    """Trust deposits use the same actual-paid overpayment rule."""
    user_id = await _seed_user(50_007)
    usdt_id, _ = await _seed_balance(user_id, "USDT", Decimal("0"))
    deposit_id = await _seed_deposit(
        user_id,
        usdt_id,
        Decimal("25"),
        "cb-trust-overpay-1",
        purpose="trust",
    )

    async with async_session() as session:
        deposit = await session.get(WalletDeposit, deposit_id)
        assert deposit is not None
        await credit_deposit(session, deposit, paid_amount=Decimal("30"))

    async with async_session() as session:
        user = await session.get(User, user_id)
        dep = await session.get(WalletDeposit, deposit_id)
        assert user is not None and dep is not None
        assert Decimal(str(user.trust_deposit_balance)) == Decimal("30.00000000")
        assert Decimal(str(dep.amount)) == Decimal("30.00000000")
        assert Decimal(str(dep.paid_amount)) == Decimal("30.00000000")
