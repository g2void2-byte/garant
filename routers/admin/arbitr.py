from aiogram import types, F, Router, Bot
from utils.database.db import DB
from routers.utils.status_arbitrs import *
from routers.utils.status_deals import *
from utils.keyboards.admin_keyboards import arbitr_keyboard
from utils.keyboards.user_keyboards.deal_keyboard import to_deal


router = Router()


@router.callback_query(F.data == 'arbitr_panel')
async def arbitr_panel(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    try:
        await callback.message.edit_text(text=f'''
<b>🩸 Панель управления арбитражами:
----------------------------------------------------------------
📜 Статистика:
----------------------------------------------------------------
🏷 Все спорные сделки: {await db.get_all_arbitr()} шт.
⏳ Ожидающие вердикта: {await db.get_all_arbitr(WAIT_VERDICT)} шт.
⏳ Ожидающие подтверждения: {await db.get_all_arbitr(WAIT_CONFIRMATION)} шт.
✔️ Решенных спорных сделок: {await db.get_all_arbitr(VERDICT)} шт.
                                     
                                     </b>''', reply_markup=await arbitr_keyboard.arbitr_main_menu())
    except:
        await callback.message.delete()
        await callback.message.answer(text=f'''
<b>🩸 Панель управления арбитражами:
----------------------------------------------------------------
📜 Статистика:
----------------------------------------------------------------
🏷 Все спорные сделки: {await db.get_all_arbitr()} шт.
⏳ Ожидающие вердикта: {await db.get_all_arbitr(WAIT_VERDICT)} шт.
⏳ Ожидающие подтверждения: {await db.get_all_arbitr(WAIT_CONFIRMATION)} шт.
✔️ Решенных спорных сделок: {await db.get_all_arbitr(VERDICT)} шт.
                                     
                                     </b>''', reply_markup=await arbitr_keyboard.arbitr_main_menu())
    





@router.callback_query(F.data == 'arbitr_deals')
async def arbitr_deals(callback: types.CallbackQuery, bot: Bot):
    await callback.message.edit_text(text=f'''<b>
❗️ Спорные сделки:                                     
                                     </b>''', reply_markup=await arbitr_keyboard.arbitr_deals_menu())
    






@router.callback_query(F.data.startswith('arbitr_arbitration_deal'))
async def arbitration_deal(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[3]
    deal = await db.get_deal_by_id(deal_id)
    arbitr_deal = await db.get_arbitr_deal(deal_id)
    await callback.message.edit_text(text=f'''<b>
Сделка №{deal_id}:
Участники:
    Покупатель: @{deal.buyer}
    Продавец: @{deal.seller}
Сумма сделки: {deal.sum}$
Условия: {deal.description}
---
Инициатор: {arbitr_deal.initiator}
Причина арбитража: {arbitr_deal.reason}
                                     </b>''', reply_markup=arbitr_keyboard.manage_arbitr_deal(deal_id))
    


@router.callback_query(F.data.startswith('get_deal_on_review'))
async def get_deal_on_review(callback: types.CallbackQuery, bot: Bot):
    deal_id = callback.data.split('_')[4]
    db = DB()
    await db.update_status_arbitr(deal_id, WAIT_VERDICT, callback.from_user.username.lower())
    deal = await db.get_deal_by_id(deal_id)
    buyer_id = await db.get_userid_by_username(deal.buyer)
    seller_id = await db.get_userid_by_username(deal.seller)

    await bot.send_message(buyer_id, f'''<b>Сделку №{deal_id}, которая находится в арбитраже, находится на рассмотрении у арбитра @{callback.from_user.username}. Ожидайте, пока с Вами свяжутся.</b>''', reply_markup=await to_deal(deal_id))
    await bot.send_message(seller_id, f'''<b>Сделку №{deal_id}, которая находится в арбитраже, находится на рассмотрении у арбитра @{callback.from_user.username}. Ожидайте, пока с Вами свяжутся.</b>''', reply_markup=await to_deal(deal_id))

    await callback.message.edit_reply_markup(callback.inline_message_id, arbitr_keyboard.manage_my_arbitr_deal(deal_id))


@router.callback_query(F.data == 'arbitr_my_deals')
async def arbitr_my_deals(callback: types.CallbackQuery, bot: Bot):
    await callback.message.edit_text(text=f'''<b>Сделки, находящиеся на Вашем рассмотрении:</b>''', reply_markup=await arbitr_keyboard.my_arbitr_deal(callback.from_user.username.lower()))



@router.callback_query(F.data.startswith('arbitr_arbitration_my_deal'))
async def arbitr_arbitration_my_deal(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[4]
    deal = await db.get_deal_by_id(deal_id)
    arbitr_deal = await db.get_arbitr_deal(deal_id)
    await callback.message.edit_text(text=f'''<b>
Сделка №{deal_id}:
Участники:
    Покупатель: @{deal.buyer}
    Продавец: @{deal.seller}
Сумма сделки: {deal.sum}$
Условия: {deal.description}
---
Инициатор: {arbitr_deal.initiator}
Причина арбитража: {arbitr_deal.reason}
                                     </b>''', reply_markup=arbitr_keyboard.manage_my_arbitr_deal(deal_id))
    


@router.callback_query(F.data.startswith('close_arbitr_deal'))
async def close_arbitr_deal(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[3]
    position = callback.data.split('_')[4]
    deal = await db.get_deal_by_id(deal_id)
    buyer_id = await db.get_userid_by_username(deal.buyer)
    seller_id = await db.get_userid_by_username(deal.seller)

    
    
    if position == 'buyer':
        await db.update_status_arbitr(deal_id, VERDICT, callback.from_user.username.lower(), 'buyer')
        await bot.send_message(buyer_id, f'''<b>Сделка №{deal_id} закрыта в Вашу пользу.</b>''', reply_markup=await to_deal(deal_id))
        await bot.send_message(seller_id, f'''<b>Сделка №{deal_id} закрыта в пользу покупателя @{deal.buyer}.</b>. <b>{deal.sum}$ списаны с вашего счёта и возвращены покупателю. Сделка отменена.</b>''', reply_markup=await to_deal(deal_id))
        await db.remove_balance_by_username(deal.seller, deal.sum)
        await db.add_balance_by_username(deal.buyer, deal.sum)
        await db.update_status_deal(deal_id, FAILED)

    elif position == 'seller':
        await db.update_status_arbitr(deal_id, VERDICT, callback.from_user.username.lower(), 'seller')
        await bot.send_message(seller_id, f'''<b>Сделка №{deal_id} закрыта в Вашу пользу.</b>''', reply_markup=await to_deal(deal_id))
        await bot.send_message(buyer_id, f'''<b>Сделка №{deal_id} закрыта в пользу продавца @{deal.seller}.</b>.''', reply_markup=await to_deal(deal_id))
        await db.update_status_deal(deal_id, SUCCESS)

    await callback.message.edit_text(text=f'''<b>Сделка №{deal_id} закрыта.</b>''', reply_markup=arbitr_keyboard.success_my_arbitr_deal(deal_id))



@router.callback_query(F.data == 'arbitr_completed')
async def arbitr_completed(callback: types.CallbackQuery, bot: Bot):
    await callback.message.edit_text(f'<b>Закрытые Вами сделки:</b>', reply_markup=await arbitr_keyboard.completed_arbitr_deal(callback.from_user.username.lower()))

@router.callback_query(F.data.startswith('arbitr_arbitration_completed_deal'))
async def arbitr_arbitration_completed_deal(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[4]
    deal = await db.get_deal_by_id(deal_id)
    arbitr_deal = await db.get_arbitr_deal(deal_id)
    if arbitr_deal.verdict == 'buyer':
        verdict = 'покупателя'
    elif arbitr_deal.verdict == 'seller':
        verdict = 'продавца'
    await callback.message.edit_text(text=f'''<b>
Сделка №{deal_id}:
Участники:
    Покупатель: @{deal.buyer}
    Продавец: @{deal.seller}
Сумма сделки: {deal.sum}$
Условия: {deal.description}
---
Инициатор: {arbitr_deal.initiator}
Причина арбитража: {arbitr_deal.reason}
---
Сделка закрыта в пользу {verdict}.                                 
                                     </b>''', reply_markup=arbitr_keyboard.success_my_arbitr_deal(deal_id))