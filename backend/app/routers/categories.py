from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..deps import CurrentUser, SessionDep
from ..models import Category, Service, ServiceStatus
from ..rate_limit import RLCategories
from ..schemas import CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    session: SessionDep,
    user: CurrentUser,
    _rl: RLCategories,
):
    if not user.is_admin and (user.deals_total or 0) == 0:
        import os

        from ..config import settings

        if settings.environment != "test" or os.environ.get("ENFORCE_SEARCH_GATING"):
            raise HTTPException(403, "Минимум 1 сделка для поиска")
    # M-5: ``services_count`` is the public catalog cue, so it must
    # match the rows ``GET /api/services`` shows by default — only
    # ``active`` services. Without this filter, draft/paused/banned
    # rows inflated the badge while the catalog list excluded them.
    count_sub = (
        select(func.count(Service.id))
        .where(
            Service.category_id == Category.id,
            Service.status == ServiceStatus.active,
        )
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
