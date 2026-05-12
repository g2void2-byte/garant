from AsyncPayments.cryptoBot import AsyncCryptoBot
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from misc import config
from aiogram import types, F, Router, Bot

from utils.keyboards.user_keyboards import payments_keyboard, manage_deal_keyboard
from utils.keyboards.utils.backs import back_profile
from utils.database.db import DB
from aiogram.fsm.context import FSMContext
import random
from AsyncPayments.exceptions.exceptions import RequestError

router = Router()

async def create_add_money_request(amount: float):
    crypto_bot = AsyncCryptoBot(token=config.cryptobot_token)
    result = await crypto_bot.create_invoice(amount=amount, asset='USDT')
    return result


async def check_invoice(invoice_id: str):
    crypto_bot = AsyncCryptoBot(token=config.cryptobot_token)
    result = await crypto_bot.get_invoices(asset='USDT', invoice_ids=invoice_id)
    return result

async def withdraw_money(user_id, amount: float):
    crypto_bot = AsyncCryptoBot(token=config.cryptobot_token)
    spend = f'{user_id}_{random.randint(0, 9999)}'
    print(user_id, amount)
    print(spend)
    result = await crypto_bot.transfer(user_id=int(user_id), amount=float(amount), asset='USDT', spend_id=spend)
    return result


def withdraw_admin_keyboard(request_id: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Подтвердить", callback_data=f"approve_withdraw:{request_id}")
    keyboard.button(text="Отклонить", callback_data=f"decline_withdraw:{request_id}")
    return keyboard.as_markup()


class WithdrawState(StatesGroup):
    get_amount = State()


# Обработчик запроса на вывод (кнопка в профиле, например, "withdraw_money")
@router.callback_query(F.data == 'withdraw_money')
async def withdraw_money_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("<b>Введите сумму для вывода в $:</b>", reply_markup=back_profile())
    await state.set_state(WithdrawState.get_amount)


# Обработчик ввода суммы пользователем
@router.message(WithdrawState.get_amount, F.text)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)

        user = await DB().get_user_by_username(message.from_user.username.lower())

        if user.balance < amount:
            await message.answer('Недостаточно средств!', reply_markup=back_profile())
            await state.clear()
            return
        # Создаём клавиатуру для подтверждения запроса на вывод с callback data, содержащей сумму
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="Подтвердить вывод", callback_data=f"withdraw_{amount}")
        keyboard.button(text="Отмена", callback_data="cancel")
        await message.answer(f"<b>Вы хотите вывести {amount}$?</b>", reply_markup=keyboard.as_markup())
        await state.clear()
    except ValueError:
        await message.answer("<b>Неверный формат. Введите числовое значение, например: 10 или 10.5</b>", reply_markup=back_profile())


# Основной обработчик запроса на вывод (сумма передаётся через callback data)
@router.callback_query(F.data.startswith('withdraw_'))
async def withdraw_confirm(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    db = DB()
    # callback.data имеет вид "withdraw_<amount>"
    amount = float(callback.data.split('_')[1])
    username = callback.from_user.username.lower()

    # Получаем режим вывода из настроек
    withdraw_mode = await db.get_withdraw_mode()

    if withdraw_mode == 'auto':
        # Автоматический вывод
        await db.remove_balance_by_username(username, amount)
        await callback.message.edit_text("<b>Происходит отправка средств...</b>")
        try:
            result = await withdraw_money(callback.from_user.id, amount)
            if result.status == 'completed':
                await callback.message.edit_text(
                    f"<b>{amount} $ успешно выведены на профиль @CryptoBot!</b>",
                    reply_markup=back_profile()
                )
                await db.add_withdraw(callback.from_user.id, result.amount, result.transfer_id)
            else:
                await db.add_balance_by_username(username, amount)
                await callback.message.edit_text(
                    "<b>Ошибка! Попробуйте вывести средства позже или свяжитесь с администрацией.\nДеньги возвращены на баланс.</b>",
                    reply_markup=back_profile()
                )
        except Exception as e:
            await db.add_balance_by_username(username, amount)
            await callback.message.edit_text(
                "<b>Ошибка! Попробуйте вывести средства позже или свяжитесь с администрацией.\nДеньги возвращены на баланс.</b>",
                reply_markup=back_profile()
            )
    elif withdraw_mode == 'manual':
        # Ручной режим: создаём запрос на вывод
        await db.remove_balance_by_username(username, amount)
        request_id = await db.create_withdraw_request(user_id=callback.from_user.id, amount=amount)
        await callback.message.edit_text(
            "<b>Запрос на вывод создан и ожидает подтверждения администратора.</b>",
            reply_markup=back_profile()
        )
        admin_chat_id = config.ADMIN_CHAT_ID  # должен быть указан в конфиге
        admin_message = (
            f"Новый запрос на вывод:\n"
            f"Пользователь: @{username}\n"
            f"Сумма: {amount} $\n"
            f"Запрос ID: {request_id}\n\n"
            "Выберите действие:"
        )
        await bot.send_message(admin_chat_id, admin_message, reply_markup=withdraw_admin_keyboard(request_id))
    else:
        await callback.message.edit_text(
            "<b>Ошибка: режим вывода не задан. Обратитесь к администрации.</b>",
            reply_markup=back_profile()
        )


# Обработка отмены (если пользователь нажал кнопку "Отмена")
@router.callback_query(F.data == 'cancel')
async def cancel_withdraw(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("<b>Действие отменено.</b>", reply_markup=back_profile())
    await state.clear()


class Addmoney(StatesGroup):
    get_amount = State()


@router.callback_query(F.data.startswith('check_deal_cryptobot'))
async def check_deal_cryptobot_invoice(message: types.CallbackQuery, bot: Bot):
    invoice_id = message.data.split('_')[3]
    deal_id = message.data.split('_')[4]
    result = await check_invoice(invoice_id)
    if result[0].status == 'paid':
        db = DB()
        percent = await db.get_percent_invoice()
        deal_percent = await db.get_percent_deal()
        print(result[0].paid_amount)
        print(result[0].fee_amount)
        result_amount = float(result[0].paid_amount) - (float(result[0].paid_amount) / 100 * float(percent)) + float(
            result[0].paid_amount) / 100 * float(deal_percent)
        await db.add_balance_by_username(message.from_user.username.lower(), result_amount)
        await db.add_invoice(message.from_user.id, result_amount, result[0].invoice_id)
        await message.message.edit_text(f'''
<b>
На ваш баланс успешно зачислено {round(result_amount, 2)} $!
                                        </b>

''', reply_markup=manage_deal_keyboard.redeal_keyboard(deal_id))

    else:
        await message.answer('Платёж не поступил.')


@router.callback_query(F.data.startswith('check_cryptobot'))
async def check_cryptobot_invoice(message: types.CallbackQuery, bot: Bot):
    invoice_id = message.data.split('_')[2]
    result = await check_invoice(invoice_id)
    if result[0].status == 'paid':
        db = DB()
        percent = await db.get_percent_invoice()
        deal_percent = await db.get_percent_deal()
        print(result[0].paid_amount)
        print(result[0].fee_amount)
        result_amount = float(result[0].paid_amount) - (float(result[0].paid_amount) / 100 * float(percent)) + float(
            result[0].paid_amount) / 100 * float(deal_percent)
        await db.add_balance_by_username(message.from_user.username.lower(), result_amount)
        await db.add_invoice(message.from_user.id, result_amount, result[0].invoice_id)
        await message.message.edit_text(f'''
<b>
На ваш баланс успешно зачислено {round(result_amount, 2)} $!
                                        </b>

''', reply_markup=back_profile())

    else:
        await message.answer('Платёж не поступил.')


@router.callback_query(F.data == 'add_money')
async def create_cryptobot_invoice(message: types.CallbackQuery, bot: Bot, state: FSMContext):
    await message.message.edit_text(f'''
<b>Укажите сумму для пополнения в $</b>:
''', reply_markup=back_profile())
    await state.set_state(Addmoney.get_amount)


@router.message(Addmoney.get_amount, F.text)
async def get_amount(message: types.Message, bot: Bot, state: FSMContext):
    if isinstance(float(message.text), float):
        db = DB()
        percent = await db.get_percent_invoice()
        print(percent)
        amount = float(message.text) + float(message.text) / 100 * float(percent)
        print(amount)
        result = await create_add_money_request(amount)

        await message.answer(f'''
<b>Выставлен чек на {amount} $ с учетом комиссии {percent}%</b>:
''', reply_markup=payments_keyboard.keyboard_payment(result, amount))

        await state.clear()


    else:
        await message.answer('<b>Неверный формат! Укажите числовое значение (0, 0.5).</b>', reply_markup=back_profile())