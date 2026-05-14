from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, literal, select

from ..deps import SessionDep
from ..models import User
from ..schemas import UserOut
from ..search import build_prefix_tsquery
from ..serializers import user_to_out

router = APIRouter(prefix="/api/users", tags=["users"])


# Continental's "Рейтинг" radio buckets. Mapping the bucket key -> (min, max).
# Values are 0-5 floats inclusive; ``None`` means "no bound on this side".
_RATING_BUCKETS: dict[str, tuple[float | None, float | None]] = {
    "5.0": (5.0, None),
    "4.5-4.9": (4.5, 4.9),
    "4.0-4.4": (4.0, 4.4),
    "3.5-3.9": (3.5, 3.9),
    "lt3.5": (None, 3.4999),
}

# Continental's "Количество сделок" radio buckets.
_DEALS_BUCKETS: dict[str, tuple[int | None, int | None]] = {
    "0-10": (0, 10),
    "11-50": (11, 50),
    "51-100": (51, 100),
    "101+": (101, None),
}

# Continental's "Префикс" radio. Keys are stringly-typed to match the
# bundle's data attributes.
# Tier 4 (moderator) was retired with the role; keep the three
# remaining levels so the existing filter UI keeps working unchanged.
_STATUS_KEYS = {"5", "3", "2"}


def _parse_date(value: str | None) -> datetime | None:
    """Parse an ISO date string (YYYY-MM-DD) into a midnight ``datetime``."""
    if not value:
        return None
    try:
        return datetime.combine(date.fromisoformat(value), time.min)
    except ValueError as exc:  # pragma: no cover - guarded by Query()
        raise HTTPException(400, f"Неверная дата: {value}") from exc


@router.get("", response_model=list[UserOut])
async def list_users(
    session: SessionDep,
    q: str | None = Query(None),
    filter: str | None = Query(None),
    rating: str | None = Query(None, description="Continental rating bucket"),
    deals: str | None = Query(None, description="Continental deals bucket"),
    deposit_min: float | None = Query(None, ge=0),
    status: str | None = Query(None, description="Continental prefix tier"),
    reg_from: str | None = Query(None, description="ISO date (YYYY-MM-DD)"),
    reg_to: str | None = Query(None, description="ISO date (YYYY-MM-DD)"),
):
    """List users, optionally filtered by Continental's search-page schema.

    ``q`` and ``filter`` keep their pre-PR-4 semantics. ``rating`` / ``deals``
    / ``deposit_min`` / ``status`` / ``reg_from`` / ``reg_to`` correspond
    1:1 to the bottom-sheet sections in Continental's TMA bundle.
    """
    stmt = select(User)
    ts_q = build_prefix_tsquery(q) if q else None
    if ts_q:
        tsq = func.to_tsquery("simple", ts_q)
        stmt = stmt.where(User.search_vector.op("@@")(tsq))
        # ``ts_rank`` orders by relevance; ties fall back to deals_total.
        stmt = stmt.order_by(
            func.ts_rank(User.search_vector, tsq).desc(),
            User.deals_total.desc(),
        )
    else:
        stmt = stmt.order_by(User.deals_total.desc())
    if filter == "arbiters":
        stmt = stmt.where(User.is_arbiter.is_(True))
    elif filter == "admins":
        stmt = stmt.where(User.is_admin.is_(True))

    if rating is not None:
        if rating not in _RATING_BUCKETS:
            raise HTTPException(400, f"Неизвестный rating bucket: {rating}")
        lo, hi = _RATING_BUCKETS[rating]
        # ``rating`` is computed as ``good / (good + bad) * 5``. We materialise
        # the same expression here so the filter operates on the same value
        # the UI displays. Users with zero reviews count as 0.
        total = User.good + User.bad
        rating_expr = case(
            (total > 0, (literal(5.0) * User.good) / func.nullif(total, 0)),
            else_=literal(0.0),
        )
        if lo is not None:
            stmt = stmt.where(rating_expr >= lo)
        if hi is not None:
            stmt = stmt.where(rating_expr <= hi)

    if deals is not None:
        if deals not in _DEALS_BUCKETS:
            raise HTTPException(400, f"Неизвестный deals bucket: {deals}")
        d_lo, d_hi = _DEALS_BUCKETS[deals]
        if d_lo is not None:
            stmt = stmt.where(User.deals_total >= d_lo)
        if d_hi is not None:
            stmt = stmt.where(User.deals_total <= d_hi)

    if deposit_min is not None and deposit_min > 0:
        stmt = stmt.where(User.frozen_balance >= deposit_min)

    if status is not None:
        if status not in _STATUS_KEYS:
            raise HTTPException(400, f"Неизвестный status: {status}")
        if status == "5":
            stmt = stmt.where(User.is_admin.is_(True))
        elif status == "3":
            stmt = stmt.where(User.is_arbiter.is_(True))
        elif status == "2":
            stmt = stmt.where(User.is_vip.is_(True))

    reg_from_dt = _parse_date(reg_from)
    reg_to_dt = _parse_date(reg_to)
    if reg_from_dt is not None:
        stmt = stmt.where(User.created_at >= reg_from_dt)
    if reg_to_dt is not None:
        # ``reg_to`` is inclusive; pad to end-of-day for natural UX.
        end = datetime.combine(reg_to_dt.date(), time.max)
        stmt = stmt.where(User.created_at <= end)

    stmt = stmt.limit(100)
    result = await session.execute(stmt)
    return [user_to_out(u) for u in result.scalars().all()]


@router.get("/{username}", response_model=UserOut)
async def get_user(username: str, session: SessionDep):
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user_to_out(user)
