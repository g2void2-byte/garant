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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select

from ..auth_2fa import TotpUser
from ..deps import AdminUser, CurrentUser, SessionDep
from ..models import (
    AppSettings,
    Category,
    Service,
    ServiceComment,
    ServiceStatus,
    User,
)
from ..rate_limit import RLServiceComment, RLServiceCreate, rate_limit
from ..schemas import (
    CategoryOut,
    ServiceCommentCreate,
    ServiceCommentOut,
    ServiceCreate,
    ServiceDetailOut,
    ServiceModerationDecision,
    ServiceOut,
    ServiceOwnerOut,
    ServiceUpdate,
)
from ..search import build_prefix_tsquery

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


def _owner_out(user: User | None) -> ServiceOwnerOut | None:
    if user is None:
        return None
    good = int(user.good or 0)
    bad = int(user.bad or 0)
    total = good + bad
    rating = (good / total) * 5 if total else 0.0
    return ServiceOwnerOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or (user.username or ""),
        photo_url=user.photo_url,
        rating=round(rating, 2),
        deals_count=int(user.deals_total or 0),
        good=good,
        bad=bad,
        is_admin=bool(user.is_admin),
        is_arbiter=bool(user.is_arbiter),
    )


def _comment_out(c: ServiceComment) -> ServiceCommentOut:
    return ServiceCommentOut(
        id=c.id,
        service_id=c.service_id,
        author_id=c.author_id,
        author_username=c.author.username if c.author else None,
        author_display_name=(c.author.display_name or (c.author.username or ""))
        if c.author
        else "",
        author_photo_url=c.author.photo_url if c.author else None,
        text=c.text,
        rating=c.rating,
        created_at=c.created_at,
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
    response: Response,
    category: str | None = Query(None),
    q: str | None = Query(None),
    owner: str | None = Query(None),
    status: str | None = Query(
        None,
        description="Filter by status; default behaviour is 'active' for the public catalog. "
        "Owners and admins can pass any of draft|active|paused|banned.",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=200,
        description="Max rows to return. Capped at 200 to protect the DB.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Row offset for cursorless pagination.",
    ),
):
    # R7/H-12 \u2014 always join ``Service.owner`` so we have a single
    # well-known join target for the ``is_hidden_profile`` filter below.
    # The owner relation is also already eager-loaded by the ORM for
    # ``_service_out``, so the extra join is free.
    stmt = select(Service).join(Service.owner)
    if category:
        stmt = stmt.join(Category).where(Category.slug == category)
    ts_q = build_prefix_tsquery(q) if q else None
    fts_rank = None
    if ts_q:
        tsq = func.to_tsquery("simple", ts_q)
        stmt = stmt.where(Service.search_vector.op("@@")(tsq))
        fts_rank = func.ts_rank(Service.search_vector, tsq)
    if owner:
        stmt = stmt.where(User.username == owner)

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

    # R7/H-12 — services whose owner has flipped the "hide my profile"
    # switch are excluded from the public catalog. The owner themself
    # and admins keep seeing them so the owner can still toggle paused/
    # active without losing visibility into their own catalogue.
    if not (user.is_admin or target_owner_self):
        stmt = stmt.where(User.is_hidden_profile.is_(False))

    # Materialise the total before pagination so the client can render
    # a "page N of M" affordance without a second round-trip. Surface it
    # through ``X-Total-Count`` rather than wrapping the body in an
    # envelope so the existing TanStack-Query clients (``useServices``
    # decodes ``ServiceDto[]``) keep working unchanged.
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    if fts_rank is not None:
        stmt = stmt.order_by(fts_rank.desc(), Service.created_at.desc())
    else:
        stmt = stmt.order_by(Service.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    response.headers["X-Total-Count"] = str(int(total))
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

    # M-22 — lock the owner row before counting active services so two
    # concurrent POSTs can't both pass the ``active < max`` check and
    # leave the user with ``max + 1`` active services. The user row is
    # a natural serialization point because every active-service mutation
    # already touches the same user; the lock is released on commit.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())

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


@router.get("/{service_id}", response_model=ServiceDetailOut)
async def get_service(service_id: int, user: CurrentUser, session: SessionDep):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    # Hide non-active rows from everyone except the owner and admins.
    if service.status != ServiceStatus.active and not (
        user.is_admin or service.owner_id == user.id
    ):
        raise HTTPException(404, "Услуга не найдена")

    count_stmt = select(func.count(ServiceComment.id)).where(
        ServiceComment.service_id == service.id
    )
    comments_count = int((await session.execute(count_stmt)).scalar_one())

    rating_stmt = select(
        func.avg(ServiceComment.rating),
        func.count(ServiceComment.rating),
    ).where(
        ServiceComment.service_id == service.id,
        ServiceComment.rating.is_not(None),
    )
    rating_row = (await session.execute(rating_stmt)).one()
    rating_avg = float(rating_row[0]) if rating_row[0] is not None else None
    rating_count = int(rating_row[1] or 0)

    base = _service_out(service)
    return ServiceDetailOut(
        **base.model_dump(),
        owner=_owner_out(service.owner),
        comments_count=comments_count,
        rating_avg=round(rating_avg, 2) if rating_avg is not None else None,
        rating_count=rating_count,
    )


@router.get("/{service_id}/comments", response_model=list[ServiceCommentOut])
async def list_service_comments(
    service_id: int,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    if service.status != ServiceStatus.active and not (
        user.is_admin or service.owner_id == user.id
    ):
        raise HTTPException(404, "Услуга не найдена")
    stmt = (
        select(ServiceComment)
        .where(ServiceComment.service_id == service.id)
        .order_by(ServiceComment.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [_comment_out(c) for c in result.scalars().all()]


@router.post(
    "/{service_id}/comments",
    response_model=ServiceCommentOut,
    status_code=201,
)
async def create_service_comment(
    service_id: int,
    body: ServiceCommentCreate,
    user: CurrentUser,
    session: SessionDep,
    _rl: RLServiceComment,
):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    if service.status != ServiceStatus.active and not (
        user.is_admin or service.owner_id == user.id
    ):
        raise HTTPException(404, "Услуга не найдена")
    if service.owner_id == user.id:
        raise HTTPException(400, "Нельзя оставлять комментарий к своей услуге")
    text = (body.text or "").strip()
    if not text and body.rating is None:
        raise HTTPException(400, "Введите комментарий или оценку")

    comment = ServiceComment(
        service_id=service.id,
        author_id=user.id,
        text=text,
        rating=body.rating,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    # ``refresh`` doesn't materialise the relationship; reload explicitly.
    await session.refresh(comment, attribute_names=["author"])
    return _comment_out(comment)


@router.delete("/{service_id}/comments/{comment_id}")
async def delete_service_comment(
    service_id: int,
    comment_id: int,
    user: CurrentUser,
    session: SessionDep,
):
    comment = await session.get(ServiceComment, comment_id)
    if not comment or comment.service_id != service_id:
        raise HTTPException(404, "Комментарий не найден")
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    is_author = comment.author_id == user.id
    is_owner = service.owner_id == user.id
    if not (is_author or is_owner or user.is_admin):
        raise HTTPException(403, "Нет доступа")
    await session.delete(comment)
    await session.commit()
    return {"ok": True}


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


admin_router = APIRouter(
    prefix="/api/admin/services",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


@admin_router.get("", response_model=list[ServiceOut])
async def admin_list_services(
    _admin: AdminUser,
    session: SessionDep,
    status: str | None = Query(None),
    q: str | None = Query(None),
):
    stmt = select(Service)
    if status:
        try:
            wanted = ServiceStatus(status)
        except ValueError as exc:
            raise HTTPException(400, "Неизвестный статус услуги") from exc
        stmt = stmt.where(Service.status == wanted)
    ts_q = build_prefix_tsquery(q) if q else None
    if ts_q:
        tsq = func.to_tsquery("simple", ts_q)
        stmt = stmt.where(Service.search_vector.op("@@")(tsq))
        stmt = stmt.order_by(
            func.ts_rank(Service.search_vector, tsq).desc(),
            Service.created_at.desc(),
        )
    else:
        stmt = stmt.order_by(Service.created_at.desc())
    result = await session.execute(stmt)
    return [_service_out(s) for s in result.scalars().all()]


@admin_router.post("/{service_id}/moderate", response_model=ServiceOut)
async def admin_moderate(
    service_id: int,
    body: ServiceModerationDecision,
    admin: TotpUser,
    session: SessionDep,
):
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
