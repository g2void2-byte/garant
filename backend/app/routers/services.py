"""Service catalog routes.

PR-6 adds a moderation lifecycle to services:

* ``draft``  — owner is still editing; hidden from public catalog.
* ``active`` — visible in catalog / search.
* ``paused`` — owner-side hide (row kept but not in catalog).
* ``banned`` — admin-side ban (owner cannot reactivate; admin-only).

The number of simultaneously-active services per user is capped by
``AppSettings.max_active_services_per_user`` (default 10).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ..deps import CurrentUser, SessionDep
from ..models import AppSettings, Category, Service, ServiceStatus, User
from ..rate_limit import RLServiceCreate
from ..schemas import (
    CategoryOut,
    ServiceCreate,
    ServiceModerationDecision,
    ServiceOut,
    ServiceUpdate,
)

router = APIRouter(prefix="/api/services", tags=["services"])


def _service_out(s: Service) -> ServiceOut:
    return ServiceOut(
        id=s.id,
        owner_username=s.owner.username if s.owner else None,
        title=s.title,
        description=s.description,
        price=float(s.price),
        currency="USD",
        status=s.status.value if isinstance(s.status, ServiceStatus) else str(s.status),
        category=CategoryOut(
            id=s.category.id,
            slug=s.category.slug,
            name=s.category.name,
            icon_key=s.category.icon,
            services_count=0,
        ),
        created_at=s.created_at,
    )


async def _get_max_active(session) -> int:
    settings = (await session.execute(select(AppSettings).limit(1))).scalar_one_or_none()
    if not settings:
        return 10
    return int(settings.max_active_services_per_user or 10)


async def _count_active(session, owner_id: int) -> int:
    stmt = select(func.count(Service.id)).where(
        Service.owner_id == owner_id, Service.status == ServiceStatus.active
    )
    return int((await session.execute(stmt)).scalar_one())


@router.get("", response_model=list[ServiceOut])
async def list_services(
    session: SessionDep,
    user: CurrentUser,
    category: str | None = Query(None),
    q: str | None = Query(None),
    owner: str | None = Query(None),
    status: str | None = Query(
        None,
        description="Filter by status; default behaviour is 'active' for the public catalog. "
        "Owners and admins can pass any of draft|active|paused|banned.",
    ),
):
    stmt = select(Service)
    if category:
        stmt = stmt.join(Category).where(Category.slug == category)
    if q:
        stmt = stmt.where(Service.title.ilike(f"%{q}%"))
    if owner:
        stmt = stmt.join(Service.owner).where(User.username == owner)

    target_owner_self = owner and owner == (user.username or "")

    if status:
        try:
            wanted = ServiceStatus(status)
        except ValueError as exc:
            raise HTTPException(400, "Неизвестный статус услуги") from exc
        # only owner-of-listing and admins can ask for non-active rows.
        if wanted != ServiceStatus.active and not (user.is_admin or target_owner_self):
            raise HTTPException(403, "Нет доступа к этому статусу")
        stmt = stmt.where(Service.status == wanted)
    elif target_owner_self or user.is_admin:
        # owner or admin: show every row of the requested owner
        pass
    else:
        # public catalog: active only
        stmt = stmt.where(Service.status == ServiceStatus.active)

    stmt = stmt.order_by(Service.created_at.desc())
    result = await session.execute(stmt)
    return [_service_out(s) for s in result.scalars().all()]


@router.post("", response_model=ServiceOut, status_code=201)
async def create_service(
    body: ServiceCreate, user: CurrentUser, session: SessionDep, _rl: RLServiceCreate
):
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "Введите название услуги")
    if len(title) > 256:
        raise HTTPException(400, "Название слишком длинное (≤256)")
    if body.price < 0:
        raise HTTPException(400, "Цена не может быть отрицательной")

    stmt = select(Category).where(Category.slug == body.category_slug)
    result = await session.execute(stmt)
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Категория не найдена")

    active_now = await _count_active(session, user.id)
    max_active = await _get_max_active(session)
    if active_now >= max_active:
        raise HTTPException(
            400,
            f"Достигнут лимит активных услуг ({max_active}). Поставьте часть на паузу или удалите.",
        )

    service = Service(
        owner_id=user.id,
        category_id=cat.id,
        title=title,
        description=body.description or "",
        price=body.price,
        status=ServiceStatus.active,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return _service_out(service)


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: int, body: ServiceUpdate, user: CurrentUser, session: SessionDep
):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    if service.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Нет доступа")

    if service.status == ServiceStatus.banned and not user.is_admin:
        raise HTTPException(403, "Услуга заблокирована администрацией")

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "Введите название услуги")
        if len(title) > 256:
            raise HTTPException(400, "Название слишком длинное (≤256)")
        service.title = title
    if body.description is not None:
        service.description = body.description
    if body.price is not None:
        if body.price < 0:
            raise HTTPException(400, "Цена не может быть отрицательной")
        service.price = body.price

    if body.status is not None:
        try:
            wanted = ServiceStatus(body.status)
        except ValueError as exc:
            raise HTTPException(400, "Неизвестный статус услуги") from exc
        if wanted == ServiceStatus.banned and not user.is_admin:
            raise HTTPException(403, "Только администратор может банить услуги")
        if (
            wanted == ServiceStatus.active
            and service.status != ServiceStatus.active
            and not user.is_admin
        ):
            active_now = await _count_active(session, service.owner_id)
            max_active = await _get_max_active(session)
            if active_now >= max_active:
                raise HTTPException(
                    400,
                    f"Достигнут лимит активных услуг ({max_active}).",
                )
        service.status = wanted
        if wanted != ServiceStatus.banned:
            service.ban_reason = None

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


# ── Admin moderation ──────────────────────────────────


admin_router = APIRouter(prefix="/api/admin/services", tags=["services-admin"])


@admin_router.get("", response_model=list[ServiceOut])
async def admin_list_services(
    user: CurrentUser,
    session: SessionDep,
    status: str | None = Query(None),
    q: str | None = Query(None),
):
    if not user.is_admin:
        raise HTTPException(403, "Только для администратора")
    stmt = select(Service)
    if status:
        try:
            wanted = ServiceStatus(status)
        except ValueError as exc:
            raise HTTPException(400, "Неизвестный статус услуги") from exc
        stmt = stmt.where(Service.status == wanted)
    if q:
        stmt = stmt.where(Service.title.ilike(f"%{q}%"))
    stmt = stmt.order_by(Service.created_at.desc())
    result = await session.execute(stmt)
    return [_service_out(s) for s in result.scalars().all()]


@admin_router.post("/{service_id}/moderate", response_model=ServiceOut)
async def admin_moderate(
    service_id: int,
    body: ServiceModerationDecision,
    user: CurrentUser,
    session: SessionDep,
):
    if not user.is_admin:
        raise HTTPException(403, "Только для администратора")
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    if body.action == "ban":
        service.status = ServiceStatus.banned
        service.ban_reason = body.reason or "Нарушение правил"
    elif body.action == "unban":
        service.status = ServiceStatus.active
        service.ban_reason = None
    else:
        raise HTTPException(400, "Неизвестное действие")
    await session.commit()
    await session.refresh(service)
    return _service_out(service)
