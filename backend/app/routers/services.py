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

from decimal import ROUND_HALF_EVEN, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select

from ..admin_audit import log_admin_action
from ..admin_guard import TotpUser
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
        price=s.price,
        currency=s.currency.code if s.currency else "USD",
        status=s.status.value if isinstance(s.status, ServiceStatus) else str(s.status),
        category=CategoryOut(
            id=s.category.id,
            slug=s.category.slug,
            name=s.category.name,
            icon_key=s.category.icon,
            services_count=0,
        ),
        created_at=s.created_at,
        photo_urls=list(s.photo_urls or []),
    )


def _owner_out(user: User | None) -> ServiceOwnerOut | None:
    if user is None:
        return None
    good = int(user.good or 0)
    bad = int(user.bad or 0)
    total = good + bad
    # ``ServiceOwnerOut.rating`` is a ``MoneyDecimal`` — keep the math
    # in ``Decimal`` so we never round-trip through ``float`` and the
    # 2dp ``ROUND_HALF_EVEN`` quantise matches the rest of the wallet
    # surface.
    if total:
        rating = (Decimal(good) * 5 / Decimal(total)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
    else:
        rating = Decimal("0.00")
    return ServiceOwnerOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or (user.username or ""),
        photo_url=user.photo_url,
        rating=rating,
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
    # L-9: lean on FastAPI/Pydantic enum validation instead of the
    # old ``status: str`` + manual ``ServiceStatus(status)`` try/except.
    # An unknown value now surfaces as a typed ``422`` straight from
    # the framework so OpenAPI clients can introspect the allowed set.
    status: ServiceStatus | None = Query(
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

    if status is not None:
        # only owner-of-listing and admins can ask for non-active rows.
        if status != ServiceStatus.active and not (user.is_admin or target_owner_self):
            raise HTTPException(403, "Нет доступа к этому статусу")
        stmt = stmt.where(Service.status == status)
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

    # Add ``Service.id.desc()`` as the final tie-breaker so pages stay
    # stable when two services share the same ``created_at`` (bulk
    # inserts can produce identical timestamps) or the same FTS rank;
    # without it, ``offset``/``limit`` could silently drop or duplicate
    # rows across page transitions.
    if fts_rank is not None:
        stmt = stmt.order_by(fts_rank.desc(), Service.created_at.desc(), Service.id.desc())
    else:
        stmt = stmt.order_by(Service.created_at.desc(), Service.id.desc())
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
    #
    # L-3 (audit v12) — the per-user limit is the only quota that
    # exists today, so the ``users.id`` row-lock is sufficient.  If a
    # *per-category* cap is ever introduced (e.g. "≤ N active services
    # per category, globally") the new serialization point will be
    # ``categories.id``, not ``users.id``, and this block will need a
    # second ``SELECT … FOR UPDATE`` against the category row before
    # the count.  Filing this here so the extension point is obvious
    # to whoever lands that requirement.
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
        photo_urls=list(body.photo_urls or []),
    )
    session.add(service)
    await session.commit()
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
    # M-11: the catalog listing already filters out services whose
    # owner has ``is_hidden_profile`` set, but the direct-link route
    # was open — anyone with a service id could still pull the owner
    # username + profile snippet through ``_owner_out`` below. Apply
    # the same gate here (owner + admins keep direct-link access so
    # the owner can still QA their listing from the deep link).
    owner_hidden = bool(service.owner and service.owner.is_hidden_profile)
    if owner_hidden and not (user.is_admin or service.owner_id == user.id):
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
    rating_avg = Decimal(str(rating_row[0])) if rating_row[0] is not None else None
    rating_count = int(rating_row[1] or 0)

    base = _service_out(service)
    return ServiceDetailOut(
        **base.model_dump(),
        owner=_owner_out(service.owner),
        comments_count=comments_count,
        rating_avg=rating_avg.quantize(Decimal("0.01")) if rating_avg is not None else None,
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
    # M-11: mirror ``get_service`` — owners with ``is_hidden_profile``
    # set must not leak comments via the public listing endpoint.
    if (
        service.owner
        and service.owner.is_hidden_profile
        and not (user.is_admin or service.owner_id == user.id)
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
    # M-11: a hidden-profile owner must also be invisible to commenters
    # via the direct-link endpoint. Admins and the owner themselves
    # remain unaffected (and the owner can't comment on their own
    # service anyway — see the next guard).
    if (
        service.owner
        and service.owner.is_hidden_profile
        and not (user.is_admin or service.owner_id == user.id)
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
    # ``expire_on_commit=False`` + SA 2.0 eager-defaults RETURNING
    # keep the column attributes (``id``, ``created_at``, …) fresh
    # without an explicit ``refresh``. The relationship is not
    # materialised by either of those mechanisms, so reload only the
    # ``author`` collection explicitly.
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
        # Audit §4.21 — the user-facing PATCH does not carry ``ban_reason``,
        # so an admin who banned a service through this endpoint left the
        # ``ban_reason`` empty (or stale from a previous ban) without any
        # way to attach context. Route the ban through the dedicated
        # admin endpoint (``POST /api/admin/content/services/{id}``)
        # which has ``ban_reason`` wired into the audit log.
        if wanted == ServiceStatus.banned:
            raise HTTPException(
                400,
                "Бан услуги — через админ-эндпойнт /api/admin/content/services/{id}",
            )
        if (
            wanted == ServiceStatus.active
            and service.status != ServiceStatus.active
            and not user.is_admin
        ):
            # Audit 4.22 — lock the owner row before counting active
            # services so two concurrent PATCH ``paused → active``
            # requests can't both pass the ``active < max`` check and
            # leave the user with ``max + 1`` active services. Mirrors
            # the M-22 ``FOR UPDATE`` lock in ``create_service`` above.
            await session.execute(
                select(User.id).where(User.id == service.owner_id).with_for_update()
            )
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

    if body.photo_urls is not None:
        # V12-UI — owner-side gallery edit. Pydantic already enforced
        # the per-entry scheme + length cap, so just persist the cleaned
        # list. Empty list clears the gallery.
        service.photo_urls = list(body.photo_urls)

    await session.commit()
    return _service_out(service)


@router.delete("/{service_id}")
async def delete_service(
    service_id: int,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    if service.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Нет доступа")
    # M-10 — user-driven deletes of one's own service stay un-audited
    # (regular user activity is logged via notifications, not the
    # admin audit log). However, when an *admin* deletes someone
    # else's service through this endpoint we must drop an audit
    # breadcrumb — otherwise the only trace of the deletion is the
    # cascaded ``service_comments`` row removal, which is
    # indistinguishable from the owner self-deleting. ``admin/content
    # .delete_service`` (the dedicated moderator endpoint) is the
    # preferred path and already does this; this branch covers admins
    # who hit the user-facing route by hand or via a script.
    if user.is_admin and service.owner_id != user.id:
        await log_admin_action(
            session,
            actor=user,
            action="service.delete",
            target_type="service",
            target_id=service.id,
            reason=None,
            payload={
                "id": service.id,
                "owner_id": service.owner_id,
                "title": service.title,
                "description": service.description,
                "price": str(service.price),
                "status": service.status.value,
                "via": "user_route",
            },
            request=request,
        )
    # Audit 4.11 — explicitly delete child ``service_comments`` rows
    # so this user-facing endpoint matches ``admin/content.delete_service``
    # instead of relying on the model-level ``ondelete="CASCADE"``. The
    # ORM ``ondelete`` is only emitted in DDL when the FK is *(re)created*
    # by a migration, and per audit §15.1 no existing migration applied
    # those cascades — so the production DB FK is still
    # ``ON DELETE NO ACTION`` and the unguarded ``session.delete(service)``
    # would fail / orphan rows depending on the DB. Doing the delete
    # explicitly here makes the path safe under both old (no CASCADE)
    # and future (CASCADE applied) schemas.
    await session.execute(delete(ServiceComment).where(ServiceComment.service_id == service.id))
    await session.delete(service)
    await session.commit()
    return {"ok": True}


# ── Admin moderation ──────────────────────────────────


admin_router = APIRouter(
    prefix="/api/admin/services",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:services", limit=600, window=60))],
)


@admin_router.get("", response_model=list[ServiceOut])
async def admin_list_services(
    _admin: AdminUser,
    session: SessionDep,
    # L-9: same upgrade as the public ``list_services`` endpoint.
    status: ServiceStatus | None = Query(None),
    q: str | None = Query(None),
    # M-3: pagination support.
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(Service)
    if status is not None:
        stmt = stmt.where(Service.status == status)
    ts_q = build_prefix_tsquery(q) if q else None
    if ts_q:
        tsq = func.to_tsquery("simple", ts_q)
        stmt = stmt.where(Service.search_vector.op("@@")(tsq))
        stmt = stmt.order_by(
            func.ts_rank(Service.search_vector, tsq).desc(),
            Service.created_at.desc(),
            Service.id.desc(),
        )
    else:
        stmt = stmt.order_by(Service.created_at.desc(), Service.id.desc())
    # M-3: paginate instead of returning all rows.
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return [_service_out(s) for s in result.scalars().all()]


@admin_router.post("/{service_id}/moderate", response_model=ServiceOut)
async def admin_moderate(
    service_id: int,
    body: ServiceModerationDecision,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    service = await session.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Услуга не найдена")
    old_status = (
        service.status.value if isinstance(service.status, ServiceStatus) else str(service.status)
    )
    if body.action == "ban":
        service.status = ServiceStatus.banned
        service.ban_reason = body.reason or "Нарушение правил"
    elif body.action == "unban":
        service.status = ServiceStatus.active
        service.ban_reason = None
    else:
        raise HTTPException(400, "Неизвестное действие")
    new_status = (
        service.status.value if isinstance(service.status, ServiceStatus) else str(service.status)
    )
    # M-4: audit-log the moderation action.
    await log_admin_action(
        session,
        actor=admin,
        action=f"service.{body.action}",
        target_type="service",
        target_id=service.id,
        reason=body.reason,
        payload={
            "service_id": service.id,
            "owner_id": service.owner_id,
            "title": service.title,
            "old_status": old_status,
            "new_status": new_status,
        },
        request=request,
    )
    await session.commit()
    return _service_out(service)
