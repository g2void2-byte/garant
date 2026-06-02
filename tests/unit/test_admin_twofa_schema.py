from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.auth_2fa import generate_secret, totp_now, verify_totp_and_counter
from backend.app.schemas import Admin2faConfirmIn, Admin2faVerifyIn


def test_admin_2fa_confirm_normalizes_secret_and_codes() -> None:
    secret = generate_secret().lower()

    body = Admin2faConfirmIn(
        secret=f"  {secret[:8]} {secret[8:]}  ",
        code=" 123456 ",
        current_code=" 654321 ",
    )

    assert body.secret == secret.upper()
    assert body.code == "123456"
    assert body.current_code == "654321"


@pytest.mark.parametrize(
    "bad_secret",
    ["", "short", "!" * 16, "JBSWY3DPEHPK3PX0", "A" * 65],
)
def test_admin_2fa_confirm_rejects_invalid_base32_secret(bad_secret: str) -> None:
    with pytest.raises(ValidationError):
        Admin2faConfirmIn(secret=bad_secret, code="123456")


@pytest.mark.parametrize(
    "bad_code",
    ["", "12345", "1234567", "12345678", "12 3456", "abcdef", 123456],
)
def test_admin_2fa_verify_rejects_non_six_digit_codes(bad_code: object) -> None:
    with pytest.raises(ValidationError):
        Admin2faVerifyIn(code=bad_code)


def test_totp_verifier_returns_none_for_invalid_stored_secret() -> None:
    assert verify_totp_and_counter("!" * 16, "123456") is None


def test_totp_verifier_still_accepts_valid_secret() -> None:
    secret = generate_secret()
    code = totp_now(secret)

    assert verify_totp_and_counter(secret, code) is not None
