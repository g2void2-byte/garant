from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import SessionDep
from ..models import Category, Service
from ..schemas import CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(session: SessionDep):
    count_sub = (
        select(func.count(Service.id))
        .where(Service.category_id == Category.id)
        .correlate(Category)
        .scalar_subquery()
    )
    stmt = select(Category, count_sub.label("cnt")).order_by(Category.id)
    rows = (await session.execute(stmt)).all()
    return [
        CategoryOut(
            id=cat.id,
            slug=cat.slug,
            name=cat.name,
            icon_key=cat.icon,
            services_count=cnt,
        )
        for cat, cnt in rows
    ]
