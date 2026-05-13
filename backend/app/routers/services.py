from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..deps import CurrentUser, SessionDep
from ..models import Category, Service
from ..schemas import CategoryOut, ServiceCreate, ServiceOut

router = APIRouter(prefix="/api/services", tags=["services"])


def _service_out(s: Service) -> ServiceOut:
    return ServiceOut(
        id=s.id,
        owner_username=s.owner.username if s.owner else None,
        title=s.title,
        description=s.description,
        price=float(s.price),
        currency="USD",
        status="active",
        category=CategoryOut(
            id=s.category.id,
            slug=s.category.slug,
            name=s.category.name,
            icon_key=s.category.icon,
            services_count=0,
        ),
        created_at=s.created_at,
    )


@router.get("", response_model=list[ServiceOut])
async def list_services(
    session: SessionDep,
    category: str | None = Query(None),
    q: str | None = Query(None),
    owner: str | None = Query(None),
):
    stmt = select(Service)
    if category:
        stmt = stmt.join(Category).where(Category.slug == category)
    if q:
        stmt = stmt.where(Service.title.ilike(f"%{q}%"))
    if owner:
        from ..models import User
        stmt = stmt.join(Service.owner).where(User.username == owner)
    stmt = stmt.order_by(Service.created_at.desc())
    result = await session.execute(stmt)
    return [_service_out(s) for s in result.scalars().all()]


@router.post("", response_model=ServiceOut, status_code=201)
async def create_service(body: ServiceCreate, user: CurrentUser, session: SessionDep):
    stmt = select(Category).where(Category.slug == body.category_slug)
    result = await session.execute(stmt)
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Категория не найдена")

    service = Service(
        owner_id=user.id,
        category_id=cat.id,
        title=body.title,
        description=body.description,
        price=body.price,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return _service_out(service)


@router.delete("/{service_id}")
async def delete_service(service_id: int, user: CurrentUser, session: SessionDep):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    if service.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Нет доступа")
    await session.delete(service)
    await session.commit()
    return {"ok": True}
