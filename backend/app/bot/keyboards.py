"""Inline + reply keyboards for the bot menu (P3.2)."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from ..config import settings
from ..models import User

# ── Reply keyboard (persistent bottom bar) ─────────────────────────────────

SEARCH_BUTTON = "🔎 Поиск"
DEALS_BUTTON = "📁 Сделки"
PROFILE_BUTTON = "👤 Профиль"
HELP_BUTTON = "⚙ Помощь"


def _button_variants(button: str) -> frozenset[str]:
    """Return every spelling a Telegram client may echo back for a reply tap.

    The reply-keyboard contract says the client sends back the button's
    ``text`` verbatim, but in practice some clients normalise the emoji
    presentation: U+FE0F (the "emoji variation selector") is silently
    added or stripped, and a few will drop the leading emoji entirely
    when the user paraphrases via the keyboard's voice-input pipeline.
    Accepting all three spellings keeps routing stable without widening
    the filter to arbitrary substrings.
    """
    parts = button.split(" ", 1)
    if len(parts) != 2:
        return frozenset({button})
    emoji, keyword = parts
    variants = {button, keyword}
    stripped = emoji.replace("\ufe0f", "")
    if stripped:
        variants.add(f"{stripped} {keyword}")
        variants.add(f"{stripped}\ufe0f {keyword}")
    return frozenset(variants)


SEARCH_BUTTON_TEXTS = _button_variants(SEARCH_BUTTON)
DEALS_BUTTON_TEXTS = _button_variants(DEALS_BUTTON)
PROFILE_BUTTON_TEXTS = _button_variants(PROFILE_BUTTON)
HELP_BUTTON_TEXTS = _button_variants(HELP_BUTTON)

# Callback data prefixes — kept short to fit Telegram's 64-byte cap.
CB_PROFILE = "bot:profile"
CB_SETTINGS = "bot:settings"
CB_TOGGLE_ANON = "bot:tog:anon"
CB_TOGGLE_HIDDEN = "bot:tog:hidden"
# Tapped when the bot is running with a non-HTTPS ``WEBAPP_URL`` and the
# inline Mini App button has been replaced with this callback so the
# section message still goes through. The handler surfaces a single,
# actionable alert with the suffix telling the operator which path was
# requested. See :func:`_webapp_button` for why this exists.
CB_TMA_UNAVAILABLE_PREFIX = "bot:tma_unavail:"


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SEARCH_BUTTON), KeyboardButton(text=DEALS_BUTTON)],
            [KeyboardButton(text=PROFILE_BUTTON), KeyboardButton(text=HELP_BUTTON)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _webapp_url(url_path: str) -> str:
    """Resolve a TMA path against the configured ``WEBAPP_URL`` base."""
    base = settings.webapp_url.rstrip("/")
    suffix = url_path if url_path.startswith("/") else "/" + url_path
    return base + suffix


def webapp_url_is_https() -> bool:
    """Whether the configured ``WEBAPP_URL`` is usable for inline buttons.

    The Telegram Bot API rejects the whole ``sendMessage`` / ``sendPhoto``
    call when the keyboard contains an inline button whose URL is not a
    public HTTPS endpoint. Two failure modes have been observed in this
    repo against the default ``WEBAPP_URL=http://localhost:5173``:

    * ``web_app=WebAppInfo(url="http://...")``
      -> ``Bad Request: BUTTON_TYPE_INVALID``.
    * ``InlineKeyboardButton(url="http://localhost:5173/...")``
      -> ``Bad Request: ... is invalid: Wrong HTTP URL``.

    Either way every section button silently looks dead from the user's
    side because aiogram only logs the error at its own level. We use
    this helper as the single switch between attaching a proper
    ``web_app=...`` (Mini App launch inside Telegram) and falling back to
    a guaranteed-deliverable ``callback_data=...`` button that surfaces
    a diagnostic alert when tapped. See :func:`_webapp_button`.
    """
    return settings.webapp_url.lower().startswith("https://")


def _webapp(url_path: str) -> WebAppInfo:
    """Build a ``WebAppInfo`` pointing at the configured TMA + optional path.

    Callers that build inline-keyboard buttons should prefer
    :func:`_webapp_button` so the keyboard automatically falls back to
    a plain ``url=`` button when ``WEBAPP_URL`` is not HTTPS (see
    :func:`webapp_url_is_https`). This helper stays exported because
    a few call sites (and tests) still want the raw ``WebAppInfo``.
    """
    return WebAppInfo(url=_webapp_url(url_path))


def _webapp_button(text: str, url_path: str) -> InlineKeyboardButton:
    """Build an inline button that opens the TMA, falling back gracefully.

    When ``WEBAPP_URL`` is HTTPS we attach a proper ``web_app=...`` so
    Telegram opens the Mini App inline. When it is not (e.g. the
    ``http://localhost:5173`` default in dev compose), **both** options
    Telegram offers for opening a URL get rejected — ``web_app=`` with
    ``BUTTON_TYPE_INVALID`` and plain ``url=`` with ``Wrong HTTP URL``
    — so the previous ``url=`` fallback (#168) still silently dropped
    the whole section message. We now emit a ``callback_data=`` button
    instead: it has no URL-validation pass on Telegram's side, so the
    ``sendMessage`` / ``sendPhoto`` always succeeds, the user actually
    sees the bot reply, and tapping the button triggers a single,
    actionable diagnostic alert (see ``cb_tma_unavailable`` in
    ``handlers.py``). ``runner.start_polling`` logs a startup warning
    in this mode so operators know to point ``WEBAPP_URL`` at an
    HTTPS endpoint to make the Mini App actually open inline.
    """
    if webapp_url_is_https():
        return InlineKeyboardButton(text=text, web_app=_webapp(url_path))
    # Telegram caps ``callback_data`` at 64 bytes; the webapp paths used
    # in this repo are short (longest known is ``/search/categories``,
    # 18 bytes) so we never hit the limit in practice. Audit L-11 — the
    # previous ``encoded[:64].decode(errors='ignore')`` slice could
    # silently truncate a future longer path AND drop the trailing
    # bytes of a multibyte character, leaving two distinct TMA paths
    # collapsing onto the same ``cb_data``. Treat this as a build-time
    # invariant instead: fail loudly here so a new long path is caught
    # by ``pytest`` / startup rather than producing a user-facing
    # button that doesn't do what its label promises.
    suffix = url_path if url_path.startswith("/") else "/" + url_path
    cb_data = CB_TMA_UNAVAILABLE_PREFIX + suffix
    encoded = cb_data.encode("utf-8")
    if len(encoded) > 64:
        raise ValueError(
            f"callback_data exceeds Telegram's 64-byte cap "
            f"(path={url_path!r}, encoded={len(encoded)}B). "
            f"Shorten the path or pick a shorter prefix."
        )
    return InlineKeyboardButton(text=text, callback_data=cb_data)


# ── Section keyboards ─────────────────────────────────────────────────────


def search_keyboard() -> InlineKeyboardMarkup:
    # "Поиск пользователя" opens the user-search hub; "Поиск услуг" opens
    # the categories grid which is the entry point for service search.
    # The TMA does not consume query strings here, so we use bare routes.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_webapp_button("🥷 Поиск пользователя", "/search")],
            [_webapp_button("🛒 Поиск услуг", "/search/categories")],
        ]
    )


def deals_keyboard(
    *, buys_count: int, sales_count: int, pending_payment_count: int
) -> InlineKeyboardMarkup:
    # The deals list inside the TMA filters by role/status via in-page
    # tabs — it does not consume query strings. All three buttons open
    # /deals; counts in the labels are informational.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _webapp_button(f"🛒 Покупок: {buys_count}", "/deals"),
                _webapp_button(f"🎁 Продаж: {sales_count}", "/deals"),
            ],
            [_webapp_button(f"⏰ Ожидающие оплаты: {pending_payment_count}", "/deals")],
        ]
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    second_row: list[InlineKeyboardButton] = []
    if settings.bot_forums_url:
        second_row.append(InlineKeyboardButton(text="🏛 Форумы", url=settings.bot_forums_url))
    second_row.append(InlineKeyboardButton(text="⚙ Настройки", callback_data=CB_SETTINGS))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_webapp_button("👤 Мой профиль", "/profile")],
            second_row,
            [_webapp_button("💼 Депозит", "/deposit")],
        ]
    )


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    anon_mark = "✅" if user.is_anonymous_deals else "❌"
    hidden_mark = "✅" if user.is_hidden_profile else "❌"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{anon_mark} Анонимность при сделках", callback_data=CB_TOGGLE_ANON
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{hidden_mark} Скрытый профиль", callback_data=CB_TOGGLE_HIDDEN
                )
            ],
            # The TMA has no dedicated PIN settings page — the global
            # PinGate shows a setup/unlock dialog on any protected route,
            # so we route to /profile and let the gate take over.
            [_webapp_button("🔒 PIN", "/profile")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=CB_PROFILE)],
        ]
    )


def notification_keyboard(
    notif_type: str, payload: dict[str, object] | None
) -> InlineKeyboardMarkup | None:
    """Build the inline keyboard attached to a DM notification.

    Wired by :func:`backend.app.notifier.dispatch_after_commit` so every
    DM the notifier sends carries a deep-link button into the relevant
    TMA section. The shape is intentionally narrow — only the two
    notification buckets that already pass structured ``payload``
    fields (``deals`` with ``deal_id``, ``deposits`` with
    ``deposit_id``) get a keyboard. Other notification types fall
    through to ``None`` and the DM is sent unchanged so we never break
    an unrelated flow.
    """
    if not payload:
        return None
    if notif_type == "deals":
        deal_id = payload.get("deal_id")
        if not isinstance(deal_id, int):
            return None
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [_webapp_button("👁 Посмотреть сделку", f"/deals/{deal_id}")],
                [_webapp_button("🔙 Назад", "/")],
            ]
        )
    if notif_type == "deposits":
        deposit_id = payload.get("deposit_id")
        if not isinstance(deposit_id, int):
            return None
        # Wallet deposit pages don't take an id in the URL — the list
        # at ``/deposit`` is keyed by ``WalletDepositOut.id`` server-
        # side, so the button only needs to deep-link the section.
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [_webapp_button("💼 Открыть депозит", "/deposit")],
                [_webapp_button("🔙 Назад", "/")],
            ]
        )
    return None


def help_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.bot_docs_url:
        rows.append([InlineKeyboardButton(text="📖 Инструкция", url=settings.bot_docs_url)])
    if settings.bot_community_chat_url:
        rows.append([InlineKeyboardButton(text="💬 Наш чат", url=settings.bot_community_chat_url)])
    if settings.bot_arbitration_url:
        rows.append([InlineKeyboardButton(text="⚖ Арбитраж", url=settings.bot_arbitration_url)])
    if settings.bot_support_username:
        uname = settings.bot_support_username.lstrip("@")
        rows.append([InlineKeyboardButton(text="👤 Помощь", url=f"https://t.me/{uname}")])
    # Always offer a way back to the TMA if everything else is empty.
    if not rows:
        rows.append([_webapp_button("🪄 Открыть приложение", "/")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
