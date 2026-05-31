from __future__ import annotations

import time

from backend.app.services_wallet import _safe_fullmatch


def test_safe_fullmatch_accepts_normal_regex():
    assert _safe_fullmatch(r"^[A-Z0-9]{6}$", "ABC123") is True
    assert _safe_fullmatch(r"^[A-Z0-9]{6}$", "ABC1234") is False


def test_safe_fullmatch_kills_pathological_regex():
    started = time.monotonic()
    assert _safe_fullmatch(r"^(a+)+$", "a" * 256 + "!") is False
    assert time.monotonic() - started < 5
