from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminBroadcastCreateIn


def test_admin_broadcast_audience_ints_accept_explicit_ints_or_none() -> None:
    body = AdminBroadcastCreateIn(
        body="message",
        audience_active_days=7,
        audience_min_deals=0,
    )

    assert body.audience_active_days == 7
    assert body.audience_min_deals == 0
    assert AdminBroadcastCreateIn(body="message").audience_active_days is None


def test_admin_broadcast_requires_at_least_one_delivery_channel() -> None:
    with pytest.raises(ValidationError):
        AdminBroadcastCreateIn(
            body="message",
            dispatch_inapp=False,
            dispatch_dm=False,
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("RU", "ru"),
        (" pt-br ", "pt-br"),
    ],
)
def test_admin_broadcast_language_normalises_ascii_tags(raw: str, expected: str) -> None:
    body = AdminBroadcastCreateIn(body="message", audience_language=raw)

    assert body.audience_language == expected


@pytest.mark.parametrize("bad", ["ru;drop", "ru_ru", "ру", "a" * 17])
def test_admin_broadcast_language_rejects_non_ascii_or_malformed_tags(bad: str) -> None:
    with pytest.raises(ValidationError):
        AdminBroadcastCreateIn(body="message", audience_language=bad)


@pytest.mark.parametrize(
    "url",
    [
        " https://t.me/garant?start=deal_42&x=1 ",
        "tg://resolve?domain=garant_bot",
    ],
)
def test_admin_broadcast_deeplink_accepts_valid_https_and_tg_urls(url: str) -> None:
    assert AdminBroadcastCreateIn(body="message", deeplink=url).deeplink == url.strip()
    assert AdminBroadcastCreateIn(body="message", deeplink="  ").deeplink is None


@pytest.mark.parametrize(
    "bad",
    [
        "http://t.me/garant",
        "https:///garant",
        "https://t.me@evil.example/garant",
        "https://t.me/garant\nnext",
        "tg://",
        "tg:///resolve?domain=garant_bot",
    ],
)
def test_admin_broadcast_deeplink_rejects_malformed_urls(bad: str) -> None:
    with pytest.raises(ValidationError):
        AdminBroadcastCreateIn(body="message", deeplink=bad)


@pytest.mark.parametrize("field", ["audience_active_days", "audience_min_deals"])
@pytest.mark.parametrize("bad", [True, False, "5", 5.0, -1])
def test_admin_broadcast_audience_ints_reject_coerced_or_negative_values(
    field: str,
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminBroadcastCreateIn(body="message", **{field: bad})
