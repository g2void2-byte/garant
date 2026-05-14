"""Static / templated message text for the bot menu (P3.2).

All copy lives here so the handler module stays focused on routing.
HTML parse-mode is assumed — see ``runner.py``'s ``DefaultBotProperties``.
"""

from __future__ import annotations

from html import escape

from ..models import User

WELCOME = (
    "Добро пожаловать в Garant!\n\n"
    "Я бот-эскроу для безопасных сделок. Используйте кнопки внизу, чтобы "
    "перейти в нужный раздел, или откройте мини-приложение."
)


SEARCH_DESCRIPTION = (
    "Кнопка «🥷 Поиск пользователя» служит для просмотра информации о "
    "пользователе и создания сделок — в открывшемся, после нажатия на "
    "кнопку, окне введите имя пользователя или юзернейм.\n\n"
    "Кнопка «🛒 Поиск услуг» откроет страницу где при вводе запроса "
    "отобразятся все услуги содержащие запрос, а так же информация о "
    "продавце."
)


HELP_DESCRIPTION = (
    "⁉️ Для перехода в чат, где Вы можете задать вопросы другим "
    'пользователям нажмите на кнопку "Наш чат", если вопрос не может быть '
    'решен пользователями нажмите кнопку "Помощь" и выберите '
    "соответствующего администратора из списка."
)


def _format_money(amount: float, *, symbol: str = "$") -> str:
    """Format a USD-style number with up to 2 decimals, trimming trailing zeros."""
    if amount == int(amount):
        return f"{symbol}{int(amount)}"
    return f"{symbol}{amount:.2f}".rstrip("0").rstrip(".")


def _format_currency_amount(amount: float, decimals: int) -> str:
    """Format a per-currency amount honouring the currency's native precision.

    M-5 — BTC needs 8 decimals while USDT needs 2; rendering them with
    the same precision either loses sat-level info or pads stable-coin
    figures with noise. Trailing zeros and a trailing decimal point are
    trimmed for readability.
    """
    decimals = max(0, min(int(decimals), 18))
    if decimals == 0:
        return f"{int(round(amount))}"
    text = f"{amount:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_by_currency(by_currency: list[dict[str, float | int]], key: str) -> str:
    """Render a comma-separated ``amount CODE`` list, hiding empty buckets.

    Returns ``"—"`` when every bucket has ``0``.
    """
    parts: list[str] = []
    for b in by_currency:
        amount = float(b.get(key, 0) or 0)
        if amount <= 0:
            continue
        decimals = int(b.get("decimals", 2) or 2)
        code = escape(str(b.get("code", "")))
        parts.append(f"{_format_currency_amount(amount, decimals)} {code}")
    return ", ".join(parts) if parts else "—"


def _format_by_currency_combined(by_currency: list[dict[str, float | int]]) -> str:
    """Sum buys + sales per currency and render a comma-separated list."""
    parts: list[str] = []
    for b in by_currency:
        amount = float(b.get("buys_sum", 0) or 0) + float(b.get("sales_sum", 0) or 0)
        if amount <= 0:
            continue
        decimals = int(b.get("decimals", 2) or 2)
        code = escape(str(b.get("code", "")))
        parts.append(f"{_format_currency_amount(amount, decimals)} {code}")
    return ", ".join(parts) if parts else "—"


def deals_summary(
    *,
    by_currency: list[dict[str, float | int]],
    total_count: int,
    buys_count: int,
    sales_count: int,
    pending_payment_count: int,
) -> str:
    """Render the ``Сделки`` card. ``by_currency`` is a sorted list of
    per-currency buckets (largest combined volume first); see
    :func:`backend.app.bot.sections._deals_stats`.
    """
    volume_line = _format_by_currency_combined(by_currency)
    return (
        "📁 <b>Сделки</b>\n\n"
        f"💰 Сумма сделок: <b>{volume_line}</b>\n"
        f"📊 Количество сделок: <b>{total_count}</b>\n\n"
        f"🛒 Покупок: <b>{buys_count}</b>\n"
        f"🎁 Продаж: <b>{sales_count}</b>\n"
        f"⏰ Ожидающие оплаты: <b>{pending_payment_count}</b>"
    )


def _user_status(user: User) -> str:
    if user.is_admin:
        return "Администратор"
    if user.is_arbiter:
        return "Арбитр"
    return "Пользователь"


def _rating(user: User) -> str:
    total_votes = user.good + user.bad
    if total_votes == 0:
        return "0/5.0 (0)"
    score = 5.0 * user.good / total_votes
    return f"{score:.1f}/5.0 ({total_votes})"


def profile_summary(
    user: User,
    *,
    buys_count: int,
    sales_count: int,
    by_currency: list[dict[str, float | int]],
) -> str:
    """Render the profile card. ``by_currency`` lines split buys/sales
    sums per currency code; mixed-currency users see one line per asset.
    """
    username = f"@{user.username}" if user.username else "—"
    name = escape(user.display_name) if user.display_name else "—"
    deposit_value = float(user.deposit_total)
    deposit_str = _format_money(deposit_value) if deposit_value > 0 else "—"
    buys_sum_line = _format_by_currency(by_currency, "buys_sum")
    sales_sum_line = _format_by_currency(by_currency, "sales_sum")
    return (
        f"🎖 <b>Мой профиль:</b> {username}\n\n"
        f"👤 <b>Имя</b> [<code>{user.tg_user_id}</code>]: {name}\n"
        f"🎫 <b>Статус:</b> {_user_status(user)}\n"
        f"⭐ <b>Рейтинг:</b> {_rating(user)}\n"
        f"💼 <b>Депозит:</b> {deposit_str}\n\n"
        f"🛒 <b>Покупок:</b> {buys_count} шт, на сумму: {buys_sum_line}\n"
        f"🎁 <b>Продаж:</b> {sales_count} шт, на сумму: {sales_sum_line}"
    )


def settings_summary(user: User) -> str:
    username = f"@{user.username}" if user.username else "—"
    return (
        f"⚙️ <b>Настройки профиля</b> для {username}\n\n"
        "Включите анонимность, чтобы скрыть юзернейм во вновь создаваемых "
        "сделках. Скрытый профиль не отображается в публичном поиске."
    )


def search_caption() -> str:
    return "🔎 <b>Поиск</b>\n\n" + SEARCH_DESCRIPTION


def help_caption() -> str:
    return "⚙️ <b>Помощь</b>\n\n" + HELP_DESCRIPTION
