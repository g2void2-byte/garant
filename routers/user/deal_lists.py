from aiogram import types, F, Router, Bot
from utils.keyboards.user_keyboards import list_deal
from utils.database.db import DB
from routers.utils.status_deals import *

router = Router()



@router.callback_query(F.data == 'my_deal')
async def my_deal(callback: types.CallbackQuery, bot: Bot):
    deal = await list_deal.deals_keyboard(callback.from_user.username.lower())
    try:
        await callback.message.edit_text('<b>Ваши сделки:</b>', reply_markup=deal)
    except:
        await callback.message.delete()
        await callback.message.answer('<b>Ваши сделки:</b>', reply_markup=deal)


async def deal_manage(callback: types.CallbackQuery, bot: Bot, deal_id):
    db = DB()
    deal = await db.get_deal_by_id(deal_id)
    if deal.status == WAIT_CONFIRM:
        status = 'Ожидает подтверждения с двух сторон'
    elif deal.status == SUCCESS:
        status = 'Состоялась'
    elif deal.status == FAILED:
        status = 'Отменена'
    elif deal.status == CONFIRMED:
        status = 'Подтверждена двумя сторонами'
    elif deal.status == ARBITRAGE:
        arbitra = await db.get_arbitr_deal(deal.id)
        status = f'В арбитраже\n🚨 Инициатор: @{arbitra.initiator}'
        if arbitra.arbitr != 'None':
            status += f'\n📌 Ваш арбитр: @{arbitra.arbitr}'
    
    elif deal.status == WAIT_FINAL_CONFIRM:
        status = 'Ожидает финального подтверждения c двух сторон'
    
    pay_comission = ['Покупатель' if deal.pay_comission == 'buyer' else 'Продавец']
    await callback.message.edit_text(f'''
<b>🩸 Сделка номер: №{deal.id}:
🫂 Участники:
        🛍 Покупатель: @{deal.buyer}
        💼 Продавец: @{deal.seller}
💰 Сумма сделки: {deal.sum}$
📜 Условия: {deal.description}
🎖 Комиссию оплачивает: {pay_comission[0]}
--------------------------
📍 Статус: {status}

                                      </b>''', reply_markup=await list_deal.manage_keyboard(deal.id, callback.from_user.username))


@router.callback_query(F.data.startswith('deal'))
async def deal(callback: types.CallbackQuery, bot: Bot):
    deal_id = callback.data.split('_')[1]
    await deal_manage(callback, bot, deal_id)