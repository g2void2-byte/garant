"""L-9 — Client-side error collector.

The frontend ``ErrorBoundary`` catches uncaught render errors but only
logs them to ``console.error``. This endpoint gives the TMA a place to
POST structured error reports so they surface in the server-side log
(and downstream in Loki / Sentry when configured).

Public + unauthenticated by design (the error may occur before the PIN
session is established), and rate-limited by client IP.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from ..rate_limit import rate_limit_anon

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["errors"])

RLClientError = Annotated[None, Depends(rate_limit_anon("client-error", limit=10, window=60))]


class ClientErrorReport(BaseModel):
    message: str = Field(max_length=2000)
    stack: str = Field(default="", max_length=8000)
    component_stack: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2000)
    user_agent: str = Field(default="", max_length=500)


@router.post(
    "/errors/report",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def report_client_error(
    body: ClientErrorReport,
    request: Request,
    _rl: RLClientError,
) -> Response:
    logger.warning(
        "client error: %s",
        body.message[:200],
        extra={
            "event": "client_error.report",
            "error_message": body.message,
            "error_stack": body.stack[:2000] if body.stack else "",
            "component_stack": body.component_stack[:1000] if body.component_stack else "",
            "page_url": body.url,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
