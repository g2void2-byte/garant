from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSettings, Category, Currency

# V5-B-4 — keep ``CURRENCY_ADDRESS_REGEX`` in lockstep with the back-fill
# in ``alembic/versions/d9f1c3a8e205_currencies_address_regex.py``. The
# migration is responsible for existing installs; this dict is the
# source of truth for fresh seeds and for the model default.
CURRENCY_ADDRESS_REGEX: dict[str, str] = {
    "USDT": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
    "USDC": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
    "TRX": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
    "TON": r"^(EQ|UQ|kQ|0Q)[A-Za-z0-9_-]{46}$",
    "BTC": r"^(bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,42})$",
    "LTC": r"^(ltc1[a-z0-9]{25,87}|[LM][a-km-zA-HJ-NP-Z1-9]{25,42})$",
    "ETH": r"^0x[a-fA-F0-9]{40}$",
    "BNB": r"^0x[a-fA-F0-9]{40}$",
    "DOGE": r"^D[5-9A-HJ-NP-U][1-9A-HJ-NP-Za-km-z]{32}$",
    "SOL": r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
}


CURRENCIES: list[tuple[str, str, str, int, float, float, int]] = [
    # (code, name, network, decimals, min_deposit, min_withdraw, sort_order)
    ("USDT", "Tether", "TRC20", 2, 1.0, 1.0, 10),
    ("TON", "Toncoin", "TON", 2, 0.5, 0.5, 20),
    ("BTC", "Bitcoin", "BTC", 8, 0.00005, 0.00005, 30),
    ("ETH", "Ethereum", "ERC20", 6, 0.001, 0.001, 40),
    ("USDC", "USD Coin", "TRC20", 2, 1.0, 1.0, 50),
    ("LTC", "Litecoin", "LTC", 4, 0.05, 0.05, 60),
    ("BNB", "BNB", "BSC", 4, 0.01, 0.01, 70),
    ("TRX", "TRON", "TRC20", 2, 5.0, 5.0, 80),
    ("DOGE", "Dogecoin", "DOGE", 2, 5.0, 5.0, 90),
    ("SOL", "Solana", "SOL", 4, 0.05, 0.05, 100),
]


CATEGORIES = [
    ("avia-i-oteli", "Авиа и отели", "plane"),
    ("akkaunty-i-podpiski", "Аккаунты и подписки", "user"),
    ("verifikaciya", "Верификация", "check-circle"),
    ("vizy-shengen", "Визы/шенген", "globe"),
    ("debetovye-karty", "Дебетовые карты", "credit-card"),
    ("dizajn", "Дизайн", "palette"),
    ("konsultacii", "Консультации", "message-square"),
    ("kopirajting", "Копирайтинг", "pen-tool"),
    ("obmenniki", "Обменники", "repeat"),
    ("obuchenie-i-kursy", "Обучение и курсы", "book-open"),
    ("perevody-tekstov", "Переводы текстов", "languages"),
    ("razrabotka", "Разработка", "code"),
    ("smm-i-reklama", "SMM и реклама", "megaphone"),
    ("yuridicheskie-uslugi", "Юридические услуги", "scale"),
    ("prochee", "Прочее", "more-horizontal"),
]


async def seed_categories(session: AsyncSession) -> None:
    result = await session.execute(select(Category).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    for slug, name, icon in CATEGORIES:
        session.add(Category(slug=slug, name=name, icon=icon))
    await session.commit()


async def seed_settings(session: AsyncSession) -> None:
    # V11 review-follow-up — the singleton ``app_settings`` row is
    # protected by the unique expression-index
    # ``ix_app_settings_singleton`` (migration ``d2a7c9b5e4f1``).
    # Pre-fix this seeder did a naked ``session.add()`` which, under
    # two parallel cold-start workers, would race the SELECT guard
    # and explode on the loser with an ``IntegrityError`` that
    # propagated up as a startup crash. Same class of bug the
    # ``services_deals._settings()`` change fixed; same remedy here:
    # an unqualified ``ON CONFLICT DO NOTHING`` lets the loser commit
    # a no-op against any row-level uniqueness violation (the
    # singleton index is the only one on this table, so we can't
    # accidentally swallow an unrelated conflict).
    result = await session.execute(select(AppSettings).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    await session.execute(
        pg_insert(AppSettings)
        .values(
            deal_commission_percent=5.0,
            invoice_commission_percent=0.0,
            min_deposit=1.0,
            min_withdraw=1.0,
        )
        .on_conflict_do_nothing()
    )
    await session.commit()


async def seed_currencies(session: AsyncSession) -> None:
    result = await session.execute(select(Currency).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    for code, name, network, decimals, min_deposit, min_withdraw, sort_order in CURRENCIES:
        session.add(
            Currency(
                code=code,
                name=name,
                network=network,
                decimals=decimals,
                min_deposit=min_deposit,
                min_withdraw=min_withdraw,
                sort_order=sort_order,
                is_active=True,
                address_regex=CURRENCY_ADDRESS_REGEX.get(code, ""),
            )
        )
    await session.commit()


async def run_seed(session: AsyncSession) -> None:
    await seed_categories(session)
    await seed_settings(session)
    await seed_currencies(session)
