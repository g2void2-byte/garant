"""Public stats endpoint for the FAQ stats badge.

Returns the admin-entered showcase values stored on
:class:`AppSettings`. The admin tweaks them in ``/admin/settings``
so the public ``/faq`` page can display round/marketing numbers
without surfacing raw database counts.

Always returns 200 with a payload — never 404 — so the React
component can render zero values gracefully when the row is
missing or the admin has not touched the fields yet.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..deps import SessionDep
from ..models import AppSettings

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/public")
async def public_stats(session: SessionDep) -> dict[str, float | int]:
    row = (await session.execute(select(AppSettings))).scalar_one_or_none()
    if row is None:
        return {"users": 0, "deals": 0, "total_usd": 0.0}
    return {
        "users": int(row.faq_stats_users or 0),
        "deals": int(row.faq_stats_deals or 0),
        "total_usd": float(row.faq_stats_total_usd or 0),
    }
