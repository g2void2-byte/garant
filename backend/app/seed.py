from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSettings, Category

CATEGORIES = [
    ("avia-i-oteli", "Авиа и отели", "plane"),
    ("akkaunty-kriptobirzh-i-eps", "Аккаунты криптобирж и ЭПС", "bitcoin"),
    ("anonimnost-i-bezopasnost", "Анонимность и безопасность", "shield"),
    ("brutfors", "Брутфорс", "key"),
    ("verifikaciya", "Верификация", "check-circle"),
    ("vzlom", "Взлом", "unlock"),
    ("vizy-shengen", "Визы/шенген", "globe"),
    ("debetovye-karty", "Дебетовые карты", "credit-card"),
    ("dizajn", "Дизайн", "palette"),
    ("izgotovlenie-dokumentov", "Изготовление документов", "file-text"),
    ("izgotovlenie-pechatej-i-shtampov", "Изготовление печатей и штампов", "stamp"),
    ("kopirajting", "Копирайтинг", "pen-tool"),
    ("kredity", "Кредиты", "dollar-sign"),
    ("obmenniki", "Обменники", "repeat"),
    ("obnal-servisy", "Обнал сервисы", "briefcase"),
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

    session.add(AppSettings(
        deal_commission_percent=5.0,
        invoice_commission_percent=0.0,
        min_deposit=1.0,
        min_withdraw=1.0,
    ))
    await session.commit()


async def run_seed(session: AsyncSession) -> None:
    await seed_categories(session)
    await seed_settings(session)
