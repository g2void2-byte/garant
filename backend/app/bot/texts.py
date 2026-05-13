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


def deals_summary(
    *,
    total_volume: float,
    total_count: int,
    buys_count: int,
    sales_count: int,
    pending_payment_count: int,
) -> str:
    return (
        "📁 <b>Сделки</b>\n\n"
        f"💰 Сумма сделок: <b>{_format_money(total_volume)}</b>\n"
        f"📊 Количество сделок: <b>{total_count}</b>\n\n"
        f"🛒 Покупок: <b>{buys_count}</b>\n"
        f"🎁 Продаж: <b>{sales_count}</b>\n"
        f"⏰ Ожидающие оплаты: <b>{pending_payment_count}</b>"
    )


def _user_status(user: User) -> str:
    if user.is_admin:
        return "Администратор"
    if user.is_moderator:
        return "Модератор"
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
    buys_sum: float,
    sales_count: int,
    sales_sum: float,
) -> str:
    username = f"@{user.username}" if user.username else "—"
    name = escape(user.display_name) if user.display_name else "—"
    deposit_str = (
        _format_money(float(user.frozen_balance)) if float(user.frozen_balance) > 0 else "—"
    )
    return (
        f"🎖 <b>Мой профиль:</b> {username}\n\n"
        f"👤 <b>Имя</b> [<code>{user.tg_user_id}</code>]: {name}\n"
        f"🎫 <b>Статус:</b> {_user_status(user)}\n"
        f"⭐ <b>Рейтинг:</b> {_rating(user)}\n"
        f"💼 <b>Депозит:</b> {deposit_str}\n\n"
        f"🛒 <b>Покупок:</b> {buys_count} шт, на сумму: {_format_money(buys_sum)}\n"
        f"🎁 <b>Продаж:</b> {sales_count} шт, на сумму: {_format_money(sales_sum)}"
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
