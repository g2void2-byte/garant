"""``/api/admin/2fa`` \u2014 TOTP enrolment & verification.

Flow:

1. ``GET  /api/admin/2fa/status``       \u2014 whether the caller has 2FA on.
2. ``POST /api/admin/2fa/setup``        \u2014 server returns a fresh secret +
   ``otpauth://`` URL. The secret is *not* persisted yet.
3. ``POST /api/admin/2fa/enable``       \u2014 admin sends the secret back
   together with a TOTP code; on success we persist
   ``users.totp_secret`` and set ``totp_enabled=True``.
4. ``POST /api/admin/2fa/disable``      \u2014 turn it off (still requires
   a valid code so a stolen session cannot silently disable 2FA).

The treasury withdrawal endpoint depends on ``auth_2fa.require_totp``
which reads the ``X-Totp-Code`` header.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...admin_audit import log_admin_action
from ...auth_2fa import (
    generate_secret,
    otpauth_url,
    verify_totp,
)
from ...deps import AdminUser, SessionDep
from ...rate_limit import rate_limit
from ...schemas import (
    Admin2faConfirmIn,
    Admin2faSetupOut,
    Admin2faStatusOut,
    Admin2faVerifyIn,
)

router = APIRouter(
    prefix="/api/admin/2fa",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


@router.get("/status", response_model=Admin2faStatusOut)
async def status(admin: AdminUser):
    return Admin2faStatusOut(enabled=bool(admin.totp_enabled and admin.totp_secret))


@router.post("/setup", response_model=Admin2faSetupOut)
async def setup(admin: AdminUser):
    secret = generate_secret()
    account = admin.username or f"id{admin.id}"
    return Admin2faSetupOut(secret=secret, otpauth_url=otpauth_url(secret, account=account))


@router.post("/enable", response_model=Admin2faStatusOut)
async def enable(
    body: Admin2faConfirmIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    if not verify_totp(body.secret, body.code):
        raise HTTPException(401, "Неверный код")
    admin.totp_secret = body.secret
    admin.totp_enabled = True
    session.add(admin)
    await log_admin_action(
        session,
        actor=admin,
        action="2fa.enable",
        target_type="user",
        target_id=admin.id,
        payload={"enabled": True},
        request=request,
    )
    await session.commit()
    return Admin2faStatusOut(enabled=True)


@router.post("/disable", response_model=Admin2faStatusOut)
async def disable(
    body: Admin2faVerifyIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    if not admin.totp_enabled or not admin.totp_secret:
        return Admin2faStatusOut(enabled=False)
    if not verify_totp(admin.totp_secret, body.code):
        raise HTTPException(401, "Неверный код")
    admin.totp_enabled = False
    admin.totp_secret = None
    session.add(admin)
    await log_admin_action(
        session,
        actor=admin,
        action="2fa.disable",
        target_type="user",
        target_id=admin.id,
        payload={"enabled": False},
        request=request,
    )
    await session.commit()
    return Admin2faStatusOut(enabled=False)
