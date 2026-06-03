from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    MAX_CATEGORY_SLUG_LEN,
    MAX_DESCRIPTION_LEN,
    MAX_SERVICE_TITLE_LEN,
    ServiceCreate,
    ServiceModerationDecision,
    ServiceUpdate,
    UserUpdate,
)


def test_service_create_trims_title_and_category_slug() -> None:
    body = ServiceCreate(category_slug="  Services ", title="  Title  ")

    assert body.category_slug == "services"
    assert body.title == "Title"


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_SERVICE_TITLE_LEN + 1)])
def test_service_create_rejects_empty_or_too_long_title(bad: str) -> None:
    with pytest.raises(ValidationError):
        ServiceCreate(category_slug="services", title=bad)


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_CATEGORY_SLUG_LEN + 1)])
def test_service_create_rejects_empty_or_too_long_category_slug(bad: str) -> None:
    with pytest.raises(ValidationError):
        ServiceCreate(category_slug=bad, title="Title")


def test_service_photo_urls_accept_https_and_media_urls_with_dedupe() -> None:
    body = ServiceCreate(
        category_slug="services",
        title="Title",
        photo_urls=[
            " https://cdn.example/photo.png ",
            "/media/service/photo.png",
            "https://cdn.example/photo.png",
            "",
        ],
    )

    assert body.photo_urls == [
        "https://cdn.example/photo.png",
        "/media/service/photo.png",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "http://cdn.example/photo.png",
        "https:///photo.png",
        "https://:443/photo.png",
        "https://cdn.example:bad/photo.png",
        "https://cdn.example@evil.example/photo.png",
        "https://cdn.example/photo\nnext.png",
        "/media/service/../admin.png",
        "/media/service/%2e%2e/admin.png",
        "/media/service//photo.png",
    ],
)
def test_service_photo_urls_reject_malformed_links(bad: str) -> None:
    with pytest.raises(ValidationError):
        ServiceCreate(category_slug="services", title="Title", photo_urls=[bad])


@pytest.mark.parametrize(
    "bad",
    [
        "/media/avatar/../admin.png",
        "/media/avatar/%2e%2e/admin.png",
        "/media/avatar//photo.png",
        "https://:443/avatar.png",
        "https://cdn.example:bad/avatar.png",
    ],
)
def test_profile_image_urls_reject_malformed_media_and_https_links(bad: str) -> None:
    with pytest.raises(ValidationError):
        UserUpdate(photo_url=bad)
    with pytest.raises(ValidationError):
        UserUpdate(banner_url=bad)


def test_service_update_trims_optional_title() -> None:
    assert ServiceUpdate(title="  Title  ").title == "Title"
    assert ServiceUpdate(title=None).title is None


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_SERVICE_TITLE_LEN + 1)])
def test_service_update_rejects_empty_or_too_long_title(bad: str) -> None:
    with pytest.raises(ValidationError):
        ServiceUpdate(title=bad)


@pytest.mark.parametrize("status", ["draft", "active", "paused", None])
def test_service_update_accepts_public_statuses(status: str | None) -> None:
    assert ServiceUpdate(status=status).status == status


@pytest.mark.parametrize("bad", ["banned", "deleted", " active "])
def test_service_update_rejects_admin_only_or_unknown_statuses(bad: str) -> None:
    with pytest.raises(ValidationError):
        ServiceUpdate(status=bad)


@pytest.mark.parametrize("action", ["ban", "unban"])
def test_service_moderation_decision_accepts_known_actions(action: str) -> None:
    assert ServiceModerationDecision(action=action).action == action


@pytest.mark.parametrize("bad", ["delete", "freeze", " ban "])
def test_service_moderation_decision_rejects_unknown_actions(bad: str) -> None:
    with pytest.raises(ValidationError):
        ServiceModerationDecision(action=bad)


def test_service_moderation_reason_uses_description_limit() -> None:
    reason = "x" * MAX_DESCRIPTION_LEN
    assert ServiceModerationDecision(action="ban", reason=reason).reason == reason

    with pytest.raises(ValidationError):
        ServiceModerationDecision(action="ban", reason="x" * (MAX_DESCRIPTION_LEN + 1))
