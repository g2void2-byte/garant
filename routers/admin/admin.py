from aiogram import F, types, Bot, Router
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.keyboards.admin_keyboards import admin_keyboard
from routers.utils.cryptobot import withdraw_money
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from utils.filters.filter_username import UsernameFilter
from utils.database.db import DB
from utils.keyboards.admin_keyboards.admin_keyboard import back_admin_menu
from utils.keyboards.utils import backs
from routers.utils.status_deals import *

router = Router()

class SetArbitrState(StatesGroup):
    get_username = State()

class RemoveArbitrState(StatesGroup):
    get_username = State()



@router.callback_query(F.data == 'admin_panel')
async def admin_panel(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()

    try:
        await callback.message.edit_text(f'''<b>
Админ-панель</b>''', reply_markup=admin_keyboard.main_admin_menu())

    except:
        await callback.message.delete()
        await callback.message.answer(f'''<b>
Админ-панель</b>''', reply_markup=admin_keyboard.main_admin_menu())


# ================= СТАТИСТИКА ====================
@router.callback_query(F.data == 'admin_stats')
async def show_admin_stats(callback: types.CallbackQuery):
    users = await DB().get_all_users()
    deals = await DB().get_deal_by_status("SUCCESS")

    total_users = len(users)
    total_deals = len(deals)
    total_volume = sum([float(deal["sum"]) for deal in deals])

    text = f"""<b>📊 Общая статистика бота</b>

👥 Пользователей: {total_users}
💼 Завершённых сделок: {total_deals}
💰 Общий объём сделок: {total_volume}$
    """
    await callback.message.edit_text(text, reply_markup=back_admin_menu())


# ================= ПОЛЬЗОВАТЕЛИ ====================
class ManageUserState(StatesGroup):
    search_username = State()
    adjust_balance = State()
    ban_user = State()


@router.callback_query(F.data.startswith("admin_users"))
async def list_users(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1]) if ":" in callback.data else 1
    per_page = 10
    offset = (page - 1) * per_page

    users = await DB().get_users_paginated(limit=per_page, offset=offset)
    total_users = await DB().count_users()
    total_pages = (total_users + per_page - 1) // per_page

    keyboard = InlineKeyboardBuilder()

    # 👤 Пользователи по одному в строке
    for user in users:
        btn_text = f"@{user.username}" if user.username else f"ID: {user.user_id}"
        keyboard.row(
            InlineKeyboardButton(text=btn_text, callback_data=f"user_info:{user.username}")
        )

    # 🔁 Навигация
    navigation_buttons = []
    if page > 1:
        navigation_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_users:{page-1}"))
    if page < total_pages:
        navigation_buttons.append(InlineKeyboardButton(text="➡️ Вперёд", callback_data=f"admin_users:{page+1}"))
    if navigation_buttons:
        keyboard.row(*navigation_buttons)

    # 🔍 Поиск и 🔙 Назад
    keyboard.row(InlineKeyboardButton(text="🔍 Поиск по username", callback_data="admin_search_user"))
    keyboard.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))

    await callback.message.edit_text(
        f"👥 Список пользователей (стр. {page}/{total_pages}):",
        reply_markup=keyboard.as_markup()
    )


@router.callback_query(F.data == "admin_search_user")
async def ask_username(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🔍 Введите username пользователя:")
    await state.set_state(ManageUserState.search_username)


@router.callback_query(F.data.startswith("user_info:"))
async def open_user_from_list(callback: types.CallbackQuery, state: FSMContext):
    username = callback.data.split(":")[1]
    print(username)
    await state.set_state(ManageUserState.search_username)
    await search_user(callback.message, state, username)

@router.message(ManageUserState.search_username, UsernameFilter())
async def search_user(message: types.Message, state: FSMContext, username_g = None):

    if username_g:
        username = username_g.lower().replace('@', '')
    else:
        username = message.text.lower().replace('@', '')

    print(username)
    user = await DB().get_user_by_username(username)

    if user:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="💰 Изменить баланс", callback_data=f"change_balance:{username}")
        if not user.ban:
            keyboard.button(text="⛔ Забанить", callback_data=f"ban_user:{username}")
        else:
            keyboard.button(text=f'⛔ Разбанить', callback_data=f'unban_user:{username}')

        # Арбитражные действия
        if user.admin >= 1:
            keyboard.button(text="🗑 Снять арбитра", callback_data=f"remove_arbitr:{username}")
        else:
            keyboard.button(text="🚨 Назначить арбитра", callback_data=f"set_arbitr:{username}")

        keyboard.button(text="🔙 Назад", callback_data="admin_users")
        keyboard.adjust(1)

        text = f"""👤 <b>Пользователь @{username}</b>
🆔 ID: {user.user_id}
💰 Баланс: {user.balance}$
👍 Хороших отзывов: {user.good}
👎 Плохих отзывов: {user.bad}
🔐 Статус: {"Арбитр" if user.admin >= 1 else "Пользователь"}"""

        try:
            await message.edit_text(text, reply_markup=keyboard.as_markup())
        except:
            await message.answer(text, reply_markup=keyboard.as_markup())
        await state.clear()
    else:
        await message.edit_text("❌ Пользователь не найден. Попробуйте снова.", reply_markup=back_admin_menu())


@router.callback_query(F.data.startswith("change_balance:"))
async def change_balance_prompt(callback: types.CallbackQuery, state: FSMContext):
    username = callback.data.split(":")[1]
    await callback.message.edit_text(f"Введите новое значение баланса для @{username}:", reply_markup=back_admin_menu())
    await state.set_state(ManageUserState.adjust_balance)
    await state.update_data(username=username)


@router.message(ManageUserState.adjust_balance, F.text.regexp(r'^\d+(\.\d+)?$'))
async def update_balance(message: types.Message, state: FSMContext):
    data = await state.get_data()
    username = data["username"]
    new_balance = float(message.text)
    print(username)
    user = await DB().get_user_by_username(username)
    print(user.balance, user.user_id)
    user.balance = new_balance
    user.save()

    await message.answer(f"✅ Баланс @{username} обновлён до {new_balance}$", reply_markup=back_admin_menu())
    await state.clear()

@router.callback_query(F.data.startswith("set_arbitr:"))
async def set_arbitrator(callback: types.CallbackQuery, bot: Bot):
    username = callback.data.split(":")[1]
    user = await DB().get_user_by_username(username)
    user.admin = 1
    user.save()
    await callback.message.edit_text(f"✅ @{username} назначен арбитром.", reply_markup=back_admin_menu())
    await bot.send_message(user.user_id, f'<b>Вы были назначены арбитром!\n\nПропишите /start чтобы зайти в панель!</b>')

@router.callback_query(F.data.startswith("remove_arbitr:"))
async def remove_arbitrator(callback: types.CallbackQuery, bot: Bot):
    username = callback.data.split(":")[1]
    user = await DB().get_user_by_username(username)
    user.admin = 0
    user.save()
    await callback.message.edit_text(f"🗑 @{username} снят с роли арбитра.", reply_markup=back_admin_menu())
    await bot.send_message(user.user_id, f'''<b>Вы были сняты с должности арбитра!</b>''')


@router.callback_query(F.data.startswith("ban_user:"))
async def ban_user(callback: types.CallbackQuery, bot: Bot):
    username = callback.data.split(":")[1]
    user = await DB().get_user_by_username(username)
    user.ban = True  # Предположим, -1 означает бан
    user.save()

    await callback.message.edit_text(f"🚫 Пользователь @{username} забанен.", reply_markup=back_admin_menu())
    await bot.send_message(user.user_id, f'<b>🚫 Вы были заблокированы!</b>')


@router.callback_query(F.data.startswith("unban_user:"))
async def ban_user(callback: types.CallbackQuery, bot: Bot):
    username = callback.data.split(":")[1]
    user = await DB().get_user_by_username(username)
    user.ban = False  # Предположим, -1 означает бан
    user.save()

    await callback.message.edit_text(f"🚫 Пользователь @{username} разбанен!", reply_markup=back_admin_menu())
    await bot.send_message(user.user_id, f'<b>🚫 Вы были разблокированы!</b>')


# ================= АРБИТРЫ ====================
@router.callback_query(F.data == 'admin_arbiters')
async def list_arbiters(callback: types.CallbackQuery):
    users = await DB().get_all_users()
    arbiters = [user for user in users if user['admin'] >= 1]

    if not arbiters:
        text = "⚖️ Арбитры не найдены."
    else:
        text = "<b>⚖️ Список арбитров:</b>\n\n" + "\n".join(
            [f"@{a['username']} | ID: {a['user_id']}" for a in arbiters])

    await callback.message.edit_text(text, reply_markup=back_admin_menu())


# ================= РАССЫЛКА ====================
class BroadcastState(StatesGroup):
    get_text = State()


@router.callback_query(F.data == 'admin_broadcast')
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✉️ Введите текст рассылки:", reply_markup=back_admin_menu())
    await state.set_state(BroadcastState.get_text)


@router.message(BroadcastState.get_text)
async def send_broadcast(message: types.Message, bot: Bot, state: FSMContext):
    users = await DB().get_all_users()
    count = 0

    for user in users:
        try:
            await bot.copy_message(user['user_id'], message.chat.id, message.message_id)
            count += 1
        except:
            continue

    await message.answer(f"📤 Рассылка отправлена {count} пользователям.", reply_markup=back_admin_menu())
    await state.clear()




# ================= НАСТРОЙКИ (ЗАГЛУШКА) ====================
@router.callback_query(F.data == 'admin_settings')
async def open_settings(callback: types.CallbackQuery, state: FSMContext):
    db = DB()
    comission = await db.get_percent_invoice()
    comission_deal = await db.get_percent_deal()
    status_withdraws = await db.get_withdraw_mode()
    await callback.message.edit_text(f'''<b>
Настройки
------------
Комиссия на пополнения: {comission}%
Комиссия на сделки: {comission_deal}%

Выберите, что хотите изменить:</b>''', reply_markup=admin_keyboard.settings_menu(status_withdraws))

class EditPercentState(StatesGroup):
    get_percent = State()

class EditPercentDealState(StatesGroup):
    get_percent = State()
# изменение комиссии на пополнение
@router.callback_query(F.data == 'admin_edit_percent')
async def edit_percent(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.edit_text(f'''<b>Укажите новый процент на пополнение:</b>''', reply_markup=admin_keyboard.back_admin_menu())
    await state.set_state(EditPercentState.get_percent)

@router.message(EditPercentState.get_percent, F.text.isdigit())
async def edit_percent_finish(message: types.Message, bot: Bot, state: FSMContext):
    db = DB()
    await db.update_percent_invoice(int(message.text))
    await message.answer(f'''<b>Комиссия {int(message.text)}% на пополнение установлена!</b>''', reply_markup=admin_keyboard.back_admin_menu())
    await state.clear()


# изменение комиссии на сделки
@router.callback_query(F.data == 'admin_edit_deal_percent')
async def admin_edit_deal_percent(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.edit_text(f'''<b>Укажите новый процент на сделки:</b>''', reply_markup=admin_keyboard.back_admin_menu())
    await state.set_state(EditPercentDealState.get_percent)

@router.message(EditPercentDealState.get_percent, F.text.isdigit())
async def edit_percent_deal_finish(message: types.Message, bot: Bot, state: FSMContext):
    db = DB()
    await db.update_percent_deal(int(message.text))
    await message.answer(f'''<b>Комиссия {int(message.text)}% на сделки установлена!</b>''', reply_markup=admin_keyboard.back_admin_menu())
    await state.clear()



########### СДЕЛКИ


@router.callback_query(F.data == 'admin_deals_list')
async def admin_deals_list(callback: types.CallbackQuery):
    db = DB()
    deals = await db.get_all_deals()

    if not deals:
        await callback.message.edit_text(
            "<b>📭 Сделок пока нет.</b>",
            reply_markup=admin_keyboard.back_admin_menu()
        )
        return

    status_icons = {
        "WAIT_CONFIRM": "⏳",
        "CONFIRMED": "✅",
        "SUCCESS": "🎉",
        "FAILED": "❌",
        "ARBITRAGE": "⚖️",
        "WAIT_FINAL_CONFIRM": "⏳🔚"
    }

    keyboard = InlineKeyboardBuilder()

    for deal in deals:
        icon = status_icons.get(deal.status.upper(), "❓")
        keyboard.row(
            types.InlineKeyboardButton(
                text=f"{icon} #{deal.id} | {deal.sum}$",
                callback_data=f"admin_deal_info:{deal.id}"
            )
        )

    keyboard.row(
        types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"),
        types.InlineKeyboardButton(text="🏠 В меню", callback_data="admin_panel")
    )

    await callback.message.edit_text(
        "<b>📋 Список сделок:</b>",
        reply_markup=keyboard.as_markup()
    )


@router.callback_query(F.data.startswith('admin_deal_info:'))
async def admin_deal_info(callback: types.CallbackQuery):
    db = DB()
    deal_id = int(callback.data.split(':')[1])
    deal = await db.get_deal_by_id(deal_id)

    if not deal:
        await callback.message.edit_text("<b>❌ Сделка не найдена</b>", reply_markup=admin_keyboard.back_admin_menu())
        return

    status_emoji = {
        "WAIT_CONFIRM": "⏳",
        "CONFIRMED": "✅",
        "SUCCESS": "🎉",
        "FAILED": "❌",
        "ARBITRAGE": "⚖️",
        "WAIT_FINAL_CONFIRM": "⏳🔚"
    }.get(deal.status.upper(), "🔘")

    text = f"""
<b>📄 Сделка #{deal.id}</b>
────────────
👤 <b>Покупатель:</b> <code>{deal.buyer}</code>
👤 <b>Продавец:</b> <code>{deal.seller}</code>
💬 <b>Описание:</b> {deal.description}
💰 <b>Сумма:</b> {deal.sum}$
📎 <b>Кто платит комиссию:</b> {deal.pay_comission}
📦 <b>Статус:</b> {status_emoji} {deal.status}
✅ <b>Подтвердил покупатель:</b> {"Да" if deal.confirm_buyer else "Нет"}
✅ <b>Подтвердил продавец:</b> {"Да" if deal.confirm_seller else "Нет"}
"""

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 Назад к списку", callback_data="admin_deals_list")
    keyboard.button(text="🏠 В панель", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())



@router.callback_query(F.data.startswith("set_withdraw_mode:"))
async def set_withdraw_mode(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    db = DB()
    await db.set_withdraw_mode(mode)
    await callback.message.edit_text(f"<b>Режим вывода изменён на {mode.upper()}</b>", reply_markup=back_admin_menu())

# Страница просмотра ожидающих запросов на вывод (только для ручного режима)
@router.callback_query(F.data == 'admin_pending_withdraws')
async def list_pending_withdraws(callback: types.CallbackQuery):
    db = DB()
    pending_requests = await db.get_pending_withdraw_requests()
    if not pending_requests:
        await callback.message.edit_text("<b>Нет запросов на вывод.</b>", reply_markup=back_admin_menu())
        return
    text = "<b>Запросы на вывод:</b>\n"
    keyboard = InlineKeyboardBuilder()
    for req in pending_requests:
        text += f"Запрос ID: {req.id} | Пользователь ID: {req.user_id} | Сумма: {req.amount} $\n"
        keyboard.button(text=f"ID {req.id}", callback_data=f"process_withdraw:{req.id}")
    keyboard.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())

# Обработка отдельного запроса (показать варианты подтверждения/отклонения)
@router.callback_query(F.data.startswith("process_withdraw:"))
async def process_withdraw(callback: types.CallbackQuery, state: FSMContext):
    req_id = int(callback.data.split(":")[1])
    text = f"<b>Обработка запроса ID {req_id}:</b>\nВыберите действие:"
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Подтвердить", callback_data=f"approve_withdraw:{req_id}")
    keyboard.button(text="Отклонить", callback_data=f"decline_withdraw:{req_id}")
    keyboard.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_pending_withdraws"))
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())

# Подтверждение запроса на вывод
@router.callback_query(F.data.startswith("approve_withdraw:"))
async def approve_withdraw(callback: types.CallbackQuery, state: FSMContext):
    req_id = int(callback.data.split(":")[1])
    db = DB()
    # Передаём функцию withdraw_money из cryptobot для выполнения операции
    success = await db.approve_withdraw_request(req_id)
    if success:
        await callback.message.edit_text(f"<b>Запрос ID {req_id} подтверждён и выполнен.</b>", reply_markup=back_admin_menu())
    else:
        await callback.message.edit_text(f"<b>Ошибка при выполнении запроса ID {req_id}.</b>", reply_markup=back_admin_menu())

# Отклонение запроса на вывод
@router.callback_query(F.data.startswith("decline_withdraw:"))
async def decline_withdraw(callback: types.CallbackQuery, state: FSMContext):
    req_id = int(callback.data.split(":")[1])
    db = DB()
    await db.decline_withdraw_request(req_id)
    await callback.message.edit_text(f"<b>Запрос ID {req_id} отклонён. Средства возвращены пользователю.</b>")