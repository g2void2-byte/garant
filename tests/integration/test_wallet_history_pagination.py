"""Regression coverage for user-facing wallet history pagination."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    User,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data


async def test_wallet_history_lists_support_currency_limit_offset(client):
    init = signed_init_data(52011, "wallet_history_user")
    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.status_code == 200, me.text

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.username == "wallet_history_user"))
        ).scalar_one()
        usd = (await session.execute(select(Currency).where(Currency.code == "USD"))).scalar_one()
        uah = (await session.execute(select(Currency).where(Currency.code == "UAH"))).scalar_one()
        now = utcnow()
        deposits = [
            WalletDeposit(
                user_id=user.id,
                currency_id=usd.id,
                amount=Decimal(idx + 1),
                provider_invoice_id=f"wallet-history-dep-{idx}",
                pay_url="https://example.test/pay",
                status=WalletDepositStatus.paid,
                created_at=now - timedelta(minutes=idx),
            )
            for idx in range(4)
        ]
        other_deposit = WalletDeposit(
            user_id=user.id,
            currency_id=uah.id,
            amount=Decimal("99"),
            provider_invoice_id="wallet-history-dep-other",
            pay_url="https://example.test/pay",
            status=WalletDepositStatus.paid,
            created_at=now + timedelta(minutes=1),
        )
        withdrawals = [
            WalletWithdrawal(
                user_id=user.id,
                currency_id=usd.id,
                amount=Decimal(idx + 1),
                address="TX-1",
                status=WalletWithdrawStatus.pending,
                created_at=now - timedelta(minutes=idx),
            )
            for idx in range(4)
        ]
        other_withdrawal = WalletWithdrawal(
            user_id=user.id,
            currency_id=uah.id,
            amount=Decimal("99"),
            address="TX-2",
            status=WalletWithdrawStatus.pending,
            created_at=now + timedelta(minutes=1),
        )
        session.add_all([*deposits, other_deposit, *withdrawals, other_withdrawal])
        await session.commit()
        expected_deposit_ids = [deposits[1].id, deposits[2].id]
        expected_withdrawal_ids = [withdrawals[1].id, withdrawals[2].id]

    deposit_resp = await client.get(
        "/api/wallet/deposits",
        params={"currency": "usd", "limit": 2, "offset": 1},
        headers=auth_headers(init),
    )
    assert deposit_resp.status_code == 200, deposit_resp.text
    assert int(deposit_resp.headers["X-Total-Count"]) == 4
    deposit_rows = deposit_resp.json()
    assert [row["id"] for row in deposit_rows] == expected_deposit_ids
    assert {row["currency"]["code"] for row in deposit_rows} == {"USD"}

    withdrawal_resp = await client.get(
        "/api/wallet/withdrawals",
        params={"currency": "usd", "limit": 2, "offset": 1},
        headers=auth_headers(init),
    )
    assert withdrawal_resp.status_code == 200, withdrawal_resp.text
    assert int(withdrawal_resp.headers["X-Total-Count"]) == 4
    withdrawal_rows = withdrawal_resp.json()
    assert [row["id"] for row in withdrawal_rows] == expected_withdrawal_ids
    assert {row["currency"]["code"] for row in withdrawal_rows} == {"USD"}
