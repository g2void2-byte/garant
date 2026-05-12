from aiogram import types, F, Bot, Router
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from utils.keyboards.utils.backs import back_menu
from utils.keyboards.user_keyboards import deal_keyboard
from utils.database.db import DB
from routers.utils.status_deals import *
from routers.utils.cryptobot import *

router = Router()


class create_deal(StatesGroup):
    get_sum = State()
    get_description = State()
    get_position = State()
    get_pay_comission = State()


@router.callback_query(F.data.startswith('start_deal'))
async def start_deal(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    username = callback.data.split(':')[1].lower()
    await state.update_data(partner=username)
    await callback.message.edit_text(f'<b>Введите сумму сделки в USDT:</b>')
    await state.set_state(create_deal.get_sum)


@router.message(create_deal.get_sum, F.text)
async def get_sum_func(message: types.Message, state: FSMContext):
    if isinstance(float(message.text), float):
        await state.update_data(sum=message.text)
        await message.answer(f'<b>Введите условия сделки:</b>')
        await state.set_state(create_deal.get_description)
    
    else:
        await message.answer('Укажите числовое значение!', reply_markup=back_menu())



@router.message(create_deal.get_description, F.text)
async def get_description_func(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)

    await message.answer(f'<b>Кто платит комиссию сделки?</b>', reply_markup=deal_keyboard.pay_comission())
    await state.set_state(create_deal.get_pay_comission)

    # await message.answer('Выберите свою позицию в сделке: ', reply_markup=deal_keyboard.position_keyboard())
    # await state.set_state(create_deal.get_position)

@router.callback_query(create_deal.get_pay_comission, F.data.startswith('pay_comission'))
async def get_pay_comission_func(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    pay_comission = callback.data.split('_')[2]
    await state.update_data(pay_comission=pay_comission)

    await callback.message.answer('Выберите свою позицию в сделке: ', reply_markup=deal_keyboard.position_keyboard())
    await state.set_state(create_deal.get_position)


@router.callback_query(create_deal.get_position, F.data.startswith('position'))
async def get_position_func(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    position = callback.data.split('_')[1]
    data = await state.get_data()
    db = DB()
    if position == 'buyer':
        await state.update_data(buyer=callback.from_user.username.lower())
        await state.update_data(seller=data['partner'])

    elif position == 'seller':
        await state.update_data(seller=callback.from_user.username.lower())
        await state.update_data(buyer=data['partner'])


    data = await state.get_data()
    await state.clear()

    id_deal = await db.create_deal(data['buyer'], data['seller'], data['sum'], data['description'], data['pay_comission'], WAIT_CONFIRM)

    pay_comission = ['Покупатель' if data['pay_comission'] == 'buyer' else 'Продавец']
    if data['buyer'] == callback.from_user.username.lower():
        
        print(data)
        user_id = await db.get_userid_by_username(data['seller'])
        await bot.send_message(user_id, f'''<b>Вам отправили предложение совершения сделки!</b>
<b>Номер сделки: №{id_deal}</b>
<b>Ваша позиция: Продавец</b>
<b>Покупатель: @{data["buyer"]}</b>
<b>Сумма сделки: {data["sum"]} USDT</b>
<b>Комиссию оплачивает: {pay_comission[0]}</b>
<b>Условия сделки: {data["description"]}</b>
                               ''', reply_markup=deal_keyboard.confirmation_deal(id_deal))
        await callback.message.answer(f'Ваша сделка создана! Ожидайте подтверждения от <b>@{data["seller"]}</b>', reply_markup=deal_keyboard.created_deal(id_deal))

    elif data['seller'] == callback.from_user.username.lower():
        
        user_id = await db.get_userid_by_username(data['buyer'])
        print(data['buyer'])
        print(user_id)
        await bot.send_message(user_id, f'''<b>Вам отправили предложение совершения сделки!</b>
<b>Номер сделки: №{id_deal}</b>
<b>Ваша позиция: Покупатель</b>
<b>Продавец: @{data["seller"]}</b>
<b>Сумма сделки: {data["sum"]} USDT</b>
<b>Комиссию оплачивает: {pay_comission[0]}</b>
<b>Условия сделки: {data["description"]}</b>
                               ''', reply_markup=deal_keyboard.confirmation_deal(id_deal))
        await callback.message.answer(f'Ваша сделка создана! Ожидайте подтверждения от <b>@{data["buyer"]}</b>', reply_markup=deal_keyboard.created_deal(id_deal))



async def confirmation_deal_func(message, bot, id_deal, resend: bool):
    db = DB()
    
    
    deal = await db.get_deal_by_id(int(id_deal))
    deal_percent = await db.get_percent_deal()
    percent_deal = float(deal.sum / 100 * deal_percent)
    final_sum = float(deal.sum) + float((deal.sum / 100 * deal_percent))
    percent = await db.get_percent_invoice()

    if deal.status == FAILED:
        if resend == False:
            await message.message.edit_text(f'<b>Сделка отменена другой стороной!</b>', reply_markup=back_menu())
            return
    
    if deal is not None:
        balance = await db.get_balance_by_username(deal.buyer)
        byuer_id = await db.get_userid_by_username(deal.buyer)
        seller_id = await db.get_userid_by_username(deal.seller)

        if deal.pay_comission == 'buyer':
            print(balance)
            print(final_sum)
            if balance < final_sum:
                sum_payment = float(deal.sum - balance) + float(((deal.sum - balance) / 100 * percent)) + percent_deal
                await message.message.delete()
                await bot.send_message(seller_id, f'<b>У покупателя недостаточно средств на счету! Свяжитесь с ним либо дождитесь, пока он пополнит баланс!\nСделка отменена автоматически!</b>')
                await bot.send_message(byuer_id, f'<b>Пользователь подтвердил сделку, но возникла ошибка!\n\nНедостаточно средств на счету!\n\nПополните счёт на {round(sum_payment, 3)}$ и предложите сделку ещё раз.\nСделка отменена автоматически!</b>\n\nСумма на пополнение указана с учетом комиссии на пополнение ({percent}%) и сделки ({deal_percent}%)', reply_markup=await deal_keyboard.no_balance_deals(sum_payment, id_deal))
                await db.update_status_deal(id_deal, FAILED)

            else:
                
                await message.message.delete()
                await db.remove_balance_by_username(deal.buyer, deal.sum)

                if message.from_user.username.lower() == deal.seller:
                    await bot.send_message(seller_id, f'<b>Сделка подтверждена!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                    await bot.send_message(byuer_id, f'<b>Продавец подтвердил сделку! Деньги списаны с вашего баланса!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                elif message.from_user.username.lower() == deal.buyer:
                    await bot.send_message(seller_id, f'<b>Покупатель подтвердил сделку!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                    await bot.send_message(byuer_id, f'<b>Сделка подтверждена! Деньги списаны с вашего баланса!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                await db.update_status_deal(id_deal, CONFIRMED)
        else:
            if balance < deal.sum:
                sum_payment = float(deal.sum - balance) + float(((deal.sum - balance) / 100 * percent))
                await message.message.delete()
                await bot.send_message(seller_id, f'<b>У покупателя недостаточно средств на счету! Свяжитесь с ним либо дождитесь, пока он пополнит баланс!\nСделка отменена автоматически!</b>')
                await bot.send_message(byuer_id, f'<b>Пользователь подтвердил сделку, но возникла ошибка!\n\nНедостаточно средств на счету!\n\nПополните счёт на {round(sum_payment, 3)}$ и предложите сделку ещё раз.\nСделка отменена автоматически!</b>\n\nСумма на пополнение указана с учетом комиссии на пополнение ({percent}%)', reply_markup=await deal_keyboard.no_balance_deals(round(sum_payment, 3), id_deal))
                await db.update_status_deal(id_deal, FAILED)
        
            else:
                await message.message.delete()
                await db.remove_balance_by_username(deal.buyer, deal.sum)

                if message.from_user.username.lower() == deal.seller:
                    await bot.send_message(seller_id, f'<b>Сделка подтверждена!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                    await bot.send_message(byuer_id, f'<b>Продавец подтвердил сделку! Деньги списаны с вашего баланса!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                elif message.from_user.username.lower() == deal.buyer:
                    await bot.send_message(seller_id, f'<b>Покупатель подтвердил сделку!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                    await bot.send_message(byuer_id, f'<b>Сделка подтверждена! Деньги списаны с вашего баланса!</b>', reply_markup=await deal_keyboard.to_deal(deal.id))
                await db.update_status_deal(id_deal, CONFIRMED)

@router.callback_query(F.data.startswith('confirm_deal'))
async def confirmation_deal(message: types.CallbackQuery, bot: Bot):
    db = DB()
    id_deal = message.data.split('_')[2]
    await confirmation_deal_func(message, bot, id_deal, False)

    # await db.update_status_deal(id_deal, CONFIRMED)
    # await message.message.edit_text(f'<b>Сделка подтверждена!</b>', reply_markup=back_menu())
            
@router.callback_query(F.data.startswith('resend_deal'))
async def resend_deal(callback: types.CallbackQuery, bot: Bot):
    id_deal = callback.data.split('_')[2]
    await confirmation_deal_func(callback, bot, id_deal, True)

@router.callback_query(F.data.startswith('unconfirm_deal'))
async def unconfirm_deal(message: types.CallbackQuery, bot: Bot):
    db = DB()
    id_deal = message.data.split('_')[2]
    deal = await db.get_deal_by_id(int(id_deal))
    
    if deal.status == FAILED:
        await message.message.edit_text(f'<b>Сделка уже отменена!</b>', reply_markup=back_menu())
        return
    
    await db.update_status_deal(id_deal, FAILED)
    
    if message.from_user.username.lower() == deal.buyer:
        user_id = await db.get_userid_by_username(deal.seller)
        await bot.send_message(user_id, f'<b>Покупатель отменил сделку!</b>', reply_markup=back_menu())
    elif message.from_user.username.lower() == deal.seller:
        user_id = await db.get_userid_by_username(deal.buyer)
        await bot.send_message(user_id, f'<b>Продавец отменил сделку!</b>', reply_markup=back_menu())
    await message.message.edit_text(f'<b>Сделка отменена!</b>', reply_markup=back_menu())




