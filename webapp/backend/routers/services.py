from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import ServiceCreate, ServiceOut

router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
async def list_services(
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: Users = Depends(get_current_user),
) -> list[ServiceOut]:
    rows = await run_in_threadpool(
        WebDB().list_services, category, q, owner, limit, offset
    )
    return [ServiceOut(**row) for row in rows]


@router.post("", response_model=ServiceOut, status_code=201)
async def create_service(
    payload: ServiceCreate,
    user: Users = Depends(get_current_user),
) -> ServiceOut:
    try:
        row = await run_in_threadpool(
            WebDB().create_service,
            user.username,
            payload.category_slug,
            payload.title,
            payload.description,
            payload.price,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return ServiceOut(**row)


@router.delete("/{service_id}")
async def delete_service(
    service_id: int,
    user: Users = Depends(get_current_user),
) -> dict:
    ok = await run_in_threadpool(WebDB().delete_service, service_id, user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}
