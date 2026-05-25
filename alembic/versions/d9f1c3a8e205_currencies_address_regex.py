"""V5-B-4: per-currency withdrawal-address regex validator.

Adds ``currencies.address_regex`` so :func:`create_withdrawal` can
reject obviously-malformed payout addresses before holding funds in
``UserBalance.locked`` and queueing a row for the admin. Without this
the only sanity check on ``address`` was Pydantic's strip+non-empty
guard; a user could submit a stray comment, a Telegram username, or
even a plaintext error message and the row would sit in the admin
queue until rejected (returning funds, but wasting admin time and
holding the user's balance hostage for the 24h cool-down).

The column is ``Text`` so we can store anchored ``^...$`` patterns
without worrying about length; an empty string means "skip
validation" (back-compat for future currencies added before their
regex is known).

This migration also back-fills regexes for every seeded currency
(USDT, TON, BTC, ETH, USDC, LTC, BNB, TRX, DOGE, SOL). The patterns
are intentionally permissive — they catch typos and accidental
mis-pastes, NOT cryptographic validity. CryptoBot itself rejects
invalid addresses at ``transfer`` time, and full Base58Check / Bech32
validation in Python would be a checksum dependency we don't want to
own.

Revision ID: d9f1c3a8e205
Revises: c8f4a2e91d35
Create Date: 2026-05-15 23:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9f1c3a8e205"
down_revision: str | None = "c8f4a2e91d35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep in lockstep with ``backend.app.seed.CURRENCY_ADDRESS_REGEX``.
# The seed module is the source of truth for fresh installs; this
# back-fill keeps existing installs aligned without re-running seed.
ADDRESS_REGEX: dict[str, str] = {
    # TRC20 Base58Check, 34 chars, starts with ``T``.
    "USDT": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
    # USDC seeded as TRC20 in :mod:`backend.app.seed`.
    "USDC": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
    "TRX": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
    # TON user-friendly base64url, 48 chars total, prefix encodes
    # bounceable/non-bounceable + testnet bit.
    "TON": r"^(EQ|UQ|kQ|0Q)[A-Za-z0-9_-]{46}$",
    # Bitcoin: legacy P2PKH (``1...``), P2SH (``3...``), or
    # native segwit bech32 (``bc1...``). Length window covers the
    # 25-42 base58 char range for legacy and the bech32 form.
    "BTC": r"^(bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,42})$",
    # Litecoin: ``L`` / ``M`` legacy + ``ltc1...`` bech32.
    "LTC": r"^(ltc1[a-z0-9]{25,87}|[LM][a-km-zA-HJ-NP-Z1-9]{25,42})$",
    # ERC-20 hex address (also BNB on BSC — same format).
    "ETH": r"^0x[a-fA-F0-9]{40}$",
    "BNB": r"^0x[a-fA-F0-9]{40}$",
    # Dogecoin: ``D`` prefix, 34 chars total.
    "DOGE": r"^D[5-9A-HJ-NP-U][1-9A-HJ-NP-Za-km-z]{32}$",
    # Solana base58, 32-44 chars (no fixed length — depends on
    # leading-zero bytes of the underlying ed25519 pubkey).
    "SOL": r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
}


def upgrade() -> None:
    op.add_column(
        "currencies",
        sa.Column("address_regex", sa.Text(), nullable=False, server_default=""),
    )
    # Drop the server_default after the back-fill — we want application
    # code (seed.py + the SQLAlchemy model default) to be the source of
    # truth going forward, not a DDL artefact.
    bind = op.get_bind()
    for code, pattern in ADDRESS_REGEX.items():
        bind.execute(
            sa.text("UPDATE currencies SET address_regex = :p WHERE code = :c"),
            {"p": pattern, "c": code},
        )
    op.alter_column("currencies", "address_regex", server_default=None)


def downgrade() -> None:
    op.drop_column("currencies", "address_regex")
