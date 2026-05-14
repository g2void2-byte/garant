"""``/api/admin/2fa`` — TOTP enrolment & verification.

Flow:

1. ``GET  /api/admin/2fa/status``       — whether the caller has 2FA on.
2. ``POST /api/admin/2fa/setup``        — server returns a fresh secret +
   ``otpauth://`` URL. The secret is *not* persisted yet.
3. ``POST /api/admin/2fa/enable``       — admin sends the secret back
   together with a TOTP code; on success we persist
   ``users.totp_secret`` and set ``totp_enabled=True``.
4. ``POST /api/admin/2fa/disable``      — turn it off (still requires
   a valid code so a stolen session cannot silently disable 2FA).

The treasury withdrawal endpoint depends on ``auth_2fa.require_totp``
which reads the ``X-Totp-Code`` header.

Replay protection: every accepted code's counter is recorded on
``users.totp_last_counter`` so the same 6-digit value can't be reused
inside its 30-second window (RFC 6238 §5.2). Rotation of an
already-enabled 2FA secret additionally requires a valid ``current_code``
to prove ownership of the existing secret — otherwise a stolen session
could silently swap the secret to one the attacker controls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...admin_audit import log_admin_action
from ...auth_2fa import (
    generate_secret,
    otpauth_url,
    verify_totp_and_counter,
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
    # Rotation guard: if 2FA is already on, the caller must prove they
    # hold the *current* secret before we accept a new one. Without this
    # a stolen admin session could silently replace the secret.
    rotated = False
    if admin.totp_enabled and admin.totp_secret:
        if not body.current_code:
            raise HTTPException(401, "Введите текущий код 2FA для ротации")
        current_counter = verify_totp_and_counter(admin.totp_secret, body.current_code)
        if current_counter is None or current_counter <= (admin.totp_last_counter or -1):
            raise HTTPException(401, "Неверный текущий код 2FA")
        admin.totp_last_counter = current_counter
        rotated = True

    new_counter = verify_totp_and_counter(body.secret, body.code)
    if new_counter is None:
        raise HTTPException(401, "Неверный код")

    admin.totp_secret = body.secret
    admin.totp_enabled = True
    admin.totp_last_counter = new_counter
    session.add(admin)
    await log_admin_action(
        session,
        actor=admin,
        action="2fa.rotate" if rotated else "2fa.enable",
        target_type="user",
        target_id=admin.id,
        payload={"enabled": True, "rotated": rotated},
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
    matched = verify_totp_and_counter(admin.totp_secret, body.code)
    if matched is None or matched <= (admin.totp_last_counter or -1):
        raise HTTPException(401, "Неверный код")
    # Burn the counter before clearing so a concurrent disable can't
    # reuse the same 6-digit value to disable a re-enabled secret.
    admin.totp_last_counter = matched
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
