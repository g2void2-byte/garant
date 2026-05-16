"""V5-D-11 — wallet credit-path invariant.

The wallet has two parallel deposit surfaces that pre-date the
multi-currency rewrite and were left in place for back-compat:

* **Legacy USD ``Invoice``** — credits land on the per-row
  ``User.balance`` numeric column.  Used by the deprecated
  ``/api/payments/*`` routes and the ``services.credit_invoice``
  helper.
* **Multi-currency ``WalletDeposit``** — credits land on the matching
  ``UserBalance(user_id, currency_id)`` row's ``amount`` field.  Used
  by ``/api/wallet/*`` and ``services_wallet.credit_deposit``.

Each path must touch exactly its own balance column and *no* part of
the other path's balance column.  A regression in either direction
silently corrupts the wallet — for example, a future refactor that
also bumped ``User.balance`` from ``credit_deposit`` would
double-credit any user who happens to have a stale legacy invoice
sitting in ``status='paid'``; the opposite mistake (``credit_invoice``
also bumping a ``UserBalance`` row) would similarly inflate the
multi-currency aggregate, breaking the withdrawal-cap check in
``services_wallet.create_withdrawal``.

The invariant matters most because:

* The two columns are completely disjoint at the DB level
  (``users.balance`` is a single Numeric on ``users``;
  ``user_balances`` is a separate ``(user_id, currency_id)`` row), so
  a wrong write goes through silently — no FK, no check constraint.
* Both code paths converge on the same ``handle_invoice_paid`` /
  ``check_invoice`` / ``poll_deposit_status`` plumbing further out,
  so the wrong helper getting wired into the wrong branch is a
  plausible-looking refactor mistake.

The tests below freeze the contract: for each entry point we
snapshot every potentially-affected balance before crediting, run
the credit helper, and assert that only the column owned by that
path moved.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    Invoice,
    InvoiceProvider,
    InvoiceStatus,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
)
from backend.app.services import credit_invoice
from backend.app.services_wallet import credit_deposit


async def _seed_user(tg_user_id: int) -> int:
    async with async_session() as session:
        u = User(
            tg_user_id=tg_user_id,
            username=f"inv{tg_user_id}",
            display_name="invariant",
            balance=Decimal("0"),
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


async def _seed_invoice(
    owner_id: int,
    amount: Decimal,
    provider_invoice_id: str,
    status: InvoiceStatus = InvoiceStatus.pending,
) -> int:
    async with async_session() as session:
        inv = Invoice(
            owner_id=owner_id,
            provider=InvoiceProvider.cryptobot,
            provider_invoice_id=provider_invoice_id,
            amount=amount,
            status=status,
        )
        session.add(inv)
        await session.commit()
        await session.refresh(inv)
        return inv.id


async def _seed_deposit(
    user_id: int,
    currency_id: int,
    amount: Decimal,
    provider_invoice_id: str,
    status: WalletDepositStatus = WalletDepositStatus.pending,
) -> int:
    async with async_session() as session:
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=currency_id,
            amount=amount,
            provider_invoice_id=provider_invoice_id,
            pay_url="http://example.com/pay",
            status=status,
        )
        session.add(dep)
        await session.commit()
        await session.refresh(dep)
        return dep.id


async def _snapshot(user_id: int) -> tuple[Decimal, dict[int, Decimal]]:
    """Return ``(legacy_balance, {balance_id: amount})`` for the user."""
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        rows = (
            (await session.execute(select(UserBalance).where(UserBalance.user_id == user_id)))
            .scalars()
            .all()
        )
        return Decimal(str(user.balance)), {r.id: Decimal(str(r.amount)) for r in rows}


@pytest.mark.asyncio
async def test_credit_invoice_only_touches_legacy_user_balance():
    """``credit_invoice`` must bump ``User.balance`` and leave every
    ``UserBalance(user_id, *)`` row untouched.

    Setup: user has two ``UserBalance`` rows seeded with explicit
    non-zero ``amount`` and ``locked`` so a stray write to either
    column is obvious in the assertion.  A pending ``Invoice`` for
    the same user is then crediteded — the legacy USD column should
    move by ``invoice.amount`` and nothing else.
    """
    user_id = await _seed_user(50_001)

    usdt_id, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("12.5"))
    ton_id, ton_bal_id = await _seed_balance(user_id, "TON", Decimal("7.25"))

    legacy_before, multi_before = await _snapshot(user_id)
    assert legacy_before == Decimal("0")
    assert multi_before == {usdt_bal_id: Decimal("12.5"), ton_bal_id: Decimal("7.25")}

    invoice_amount = Decimal("42.10")
    invoice_id = await _seed_invoice(user_id, invoice_amount, "cb-inv-only-1")

    async with async_session() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one()
        await credit_invoice(session, invoice)

    legacy_after, multi_after = await _snapshot(user_id)
    assert legacy_after == invoice_amount, (
        f"legacy User.balance must move by exactly the invoice amount, got {legacy_after}"
    )
    assert multi_after == multi_before, (
        "no UserBalance row may be touched by credit_invoice; "
        f"before={multi_before} after={multi_after}"
    )

    async with async_session() as session:
        inv = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
        assert inv.status == InvoiceStatus.paid
        assert inv.paid_at is not None

    # Belt-and-suspenders: also check the ``locked`` field — the
    # withdrawal path uses it as a hold counter, and a write to it
    # from the deposit side would silently steal funds.
    async with async_session() as session:
        rows = (
            (await session.execute(select(UserBalance).where(UserBalance.user_id == user_id)))
            .scalars()
            .all()
        )
        for row in rows:
            assert Decimal(str(row.locked)) == Decimal("0"), (
                f"UserBalance.locked must not be touched by credit_invoice; "
                f"row={row.id} locked={row.locked}"
            )
    # Silence ruff: ``usdt_id`` / ``ton_id`` exist purely for the
    # seed call's side effect (anchor balance rows to the snapshot).
    del usdt_id, ton_id


@pytest.mark.asyncio
async def test_credit_deposit_only_touches_matching_user_balance():
    """``credit_deposit`` must bump exactly the matching
    ``UserBalance(user_id, currency_id)`` row's ``amount`` field and
    leave ``User.balance`` plus every other ``UserBalance`` row
    untouched.
    """
    user_id = await _seed_user(50_002)

    usdt_id, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("100"))
    ton_id, ton_bal_id = await _seed_balance(user_id, "TON", Decimal("3.5"))

    legacy_before, multi_before = await _snapshot(user_id)
    assert legacy_before == Decimal("0")

    deposit_amount = Decimal("15.75")
    deposit_id = await _seed_deposit(user_id, usdt_id, deposit_amount, "cb-dep-only-1")

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit)

    legacy_after, multi_after = await _snapshot(user_id)
    assert legacy_after == legacy_before == Decimal("0"), (
        "legacy User.balance must not be touched by credit_deposit; "
        f"before={legacy_before} after={legacy_after}"
    )

    expected_usdt = multi_before[usdt_bal_id] + deposit_amount
    assert multi_after == {
        usdt_bal_id: expected_usdt,
        ton_bal_id: multi_before[ton_bal_id],
    }, (
        "credit_deposit must move only the matching (user, currency) row; "
        f"before={multi_before} after={multi_after}"
    )

    async with async_session() as session:
        dep = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        assert dep.status == WalletDepositStatus.paid
        assert dep.paid_at is not None
    del ton_id


@pytest.mark.asyncio
async def test_credit_invoice_is_idempotent_and_does_not_re_touch_balances():
    """Crediting an already-paid invoice is a no-op for *both* sides
    of the wallet — ``User.balance`` must not move twice and no
    ``UserBalance`` row may sprout a phantom write either.
    """
    user_id = await _seed_user(50_003)
    _, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("5"))

    invoice_amount = Decimal("10.00")
    invoice_id = await _seed_invoice(user_id, invoice_amount, "cb-inv-idemp-1")

    async with async_session() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one()
        await credit_invoice(session, invoice)

    legacy_once, multi_once = await _snapshot(user_id)
    assert legacy_once == invoice_amount
    assert multi_once == {usdt_bal_id: Decimal("5")}

    # Second call on the same now-paid invoice — must be a no-op on
    # both columns, the idempotency contract documented in
    # ``credit_invoice``'s docstring.
    async with async_session() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one()
        await credit_invoice(session, invoice)

    legacy_twice, multi_twice = await _snapshot(user_id)
    assert legacy_twice == legacy_once, (
        f"User.balance must not move on a repeat credit_invoice; "
        f"first={legacy_once} second={legacy_twice}"
    )
    assert multi_twice == multi_once, (
        f"no UserBalance row may move on a repeat credit_invoice; "
        f"first={multi_once} second={multi_twice}"
    )


@pytest.mark.asyncio
async def test_credit_deposit_is_idempotent_and_does_not_re_touch_balances():
    """Same shape as the credit_invoice idempotency test but for the
    multi-currency path: crediting an already-paid ``WalletDeposit``
    must not bump the ``UserBalance.amount`` a second time and must
    leave ``User.balance`` at zero throughout.
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

    legacy_once, multi_once = await _snapshot(user_id)
    assert legacy_once == Decimal("0")
    assert multi_once == {usdt_bal_id: deposit_amount}

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit)

    legacy_twice, multi_twice = await _snapshot(user_id)
    assert legacy_twice == legacy_once == Decimal("0"), (
        f"User.balance must remain 0 on a repeat credit_deposit; "
        f"first={legacy_once} second={legacy_twice}"
    )
    assert multi_twice == multi_once, (
        f"UserBalance.amount must not move twice on a repeat credit_deposit; "
        f"first={multi_once} second={multi_twice}"
    )


@pytest.mark.asyncio
async def test_credit_paths_compose_without_cross_contamination():
    """The strongest form of the invariant: drive both paths
    end-to-end against the same user and assert that the two
    side-effects sum cleanly.  If either helper ever started
    writing to the other side's column, this composition would
    overshoot on whichever column was being double-credited.
    """
    user_id = await _seed_user(50_005)
    usdt_id, usdt_bal_id = await _seed_balance(user_id, "USDT", Decimal("0"))
    _, ton_bal_id = await _seed_balance(user_id, "TON", Decimal("0"))

    invoice_amount = Decimal("17.00")
    deposit_amount = Decimal("4.50")
    invoice_id = await _seed_invoice(user_id, invoice_amount, "cb-mix-inv-1")
    deposit_id = await _seed_deposit(user_id, usdt_id, deposit_amount, "cb-mix-dep-1")

    async with async_session() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one()
        await credit_invoice(session, invoice)

    async with async_session() as session:
        deposit = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == deposit_id))
        ).scalar_one()
        await credit_deposit(session, deposit)

    legacy, multi = await _snapshot(user_id)
    assert legacy == invoice_amount, (
        f"User.balance must equal exactly the invoice credit amount, "
        f"got {legacy}; if this drifts upward, credit_deposit is "
        f"leaking into the legacy column."
    )
    assert multi == {
        usdt_bal_id: deposit_amount,
        ton_bal_id: Decimal("0"),
    }, (
        f"UserBalance must reflect exactly the WalletDeposit credit, "
        f"got {multi}; an inflated USDT row means credit_invoice is "
        f"leaking into the multi-currency column, and a non-zero TON "
        f"row means credit_deposit is touching the wrong currency."
    )
