from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSettings, Category, Currency

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
    result = await session.execute(select(AppSettings).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    session.add(
        AppSettings(
            deal_commission_percent=5.0,
            invoice_commission_percent=0.0,
            min_deposit=1.0,
            min_withdraw=1.0,
        )
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
            )
        )
    await session.commit()


async def run_seed(session: AsyncSession) -> None:
    await seed_categories(session)
    await seed_settings(session)
    await seed_currencies(session)
