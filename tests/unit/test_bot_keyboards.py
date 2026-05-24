"""Bot DM notification keyboards.

``notification_keyboard()`` is the single switch the notifier uses to
attach a deep-link inline keyboard to every DM. The shape is narrow
on purpose — only the ``deals`` and ``deposits`` buckets carry
structured payload fields, and unrelated buckets fall through to
``None`` so a docs / payload-shape drift never breaks a notification.
"""

from __future__ import annotations

from backend.app.bot.keyboards import (
    CB_NOTIF_BACK,
    CB_TMA_UNAVAILABLE_PREFIX,
    notification_keyboard,
)


def _button_payload(button) -> str:
    """Return either the ``WebApp.url`` or the ``callback_data`` of a button."""
    if button.web_app is not None:
        return button.web_app.url
    return button.callback_data or ""


def test_notification_keyboard_deal_returns_two_rows():
    kb = notification_keyboard("deals", {"deal_id": 42})
    assert kb is not None
    assert len(kb.inline_keyboard) == 2
    first = kb.inline_keyboard[0][0]
    assert "/deals/42" in _button_payload(first)


def test_notification_keyboard_deal_missing_payload_returns_none():
    assert notification_keyboard("deals", None) is None
    assert notification_keyboard("deals", {}) is None
    assert notification_keyboard("deals", {"deal_id": "not-an-int"}) is None


def test_notification_keyboard_deposit_returns_keyboard():
    kb = notification_keyboard("deposits", {"deposit_id": 7})
    assert kb is not None
    assert len(kb.inline_keyboard) == 2
    first = kb.inline_keyboard[0][0]
    # Deposit-credited DMs land the user on /profile (where the
    # freshly credited balance is visible) — not on /deposit, which
    # is the deposit-creation form.
    assert "/profile" in _button_payload(first)
    assert "Открыть профиль" in first.text


def test_notification_keyboard_back_button_uses_callback():
    # Bugfix-plan #9 — the "🔙 Назад" button used to deep-link the
    # Mini App root (``/``), which forced a full TMA launch just to
    # dismiss the keyboard. It now uses a ``callback_data=`` button
    # that the bot handles by stripping the inline keyboard in place.
    for notif_type, payload in (
        ("deals", {"deal_id": 1}),
        ("deposits", {"deposit_id": 1}),
    ):
        kb = notification_keyboard(notif_type, payload)
        assert kb is not None
        back = kb.inline_keyboard[1][0]
        assert back.web_app is None
        assert back.url is None
        assert back.callback_data == CB_NOTIF_BACK
        assert "Назад" in back.text


def test_notification_keyboard_deposit_missing_payload_returns_none():
    assert notification_keyboard("deposits", None) is None
    assert notification_keyboard("deposits", {}) is None
    assert notification_keyboard("deposits", {"deposit_id": "x"}) is None


def test_notification_keyboard_unknown_type_returns_none():
    # System / banner buckets have no deep-link page wired.
    assert notification_keyboard("system", {"any": "value"}) is None
    assert notification_keyboard("", {"deal_id": 1}) is None


def test_notification_keyboard_falls_back_to_callback_data_when_not_https(monkeypatch):
    # _webapp_button drops the ``web_app=`` payload when the TMA URL
    # isn't HTTPS (Telegram rejects HTTP webapp buttons). The
    # CB_TMA_UNAVAILABLE_PREFIX callback handler renders a friendly
    # alert instead.
    from backend.app import config

    monkeypatch.setattr(config.settings, "webapp_url", "http://example.local")
    kb = notification_keyboard("deals", {"deal_id": 99})
    assert kb is not None
    first = kb.inline_keyboard[0][0]
    assert first.web_app is None
    assert first.callback_data is not None
    assert first.callback_data.startswith(CB_TMA_UNAVAILABLE_PREFIX)


def test_webapp_button_raises_on_overlong_callback_data(monkeypatch):
    """Audit L-11 — ``_webapp_button`` must refuse to silently truncate
    ``callback_data`` past Telegram's 64-byte cap. The previous slice
    + ``decode(errors='ignore')`` could collapse two distinct TMA
    paths onto the same cb_data when the path crossed the limit on
    a multibyte boundary; we now raise instead so a regression is
    caught in pytest rather than in production.
    """
    import pytest

    from backend.app import config
    from backend.app.bot.keyboards import _webapp_button

    monkeypatch.setattr(config.settings, "webapp_url", "http://example.local")
    long_path = "/" + ("x" * 80)
    with pytest.raises(ValueError, match="callback_data exceeds"):
        _webapp_button("label", long_path)
