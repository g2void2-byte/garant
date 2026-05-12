import asyncio
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.database.db import DB
from routers.utils.status_deals import *

async def deals_keyboard(username):
    db = DB()
    keyboard = InlineKeyboardBuilder()

    deals = await db.get_deals_by_username(username)
    for deal in deals:
        if deal['status'] == WAIT_CONFIRM or deal['status'] == CONFIRMED or deal['status'] == WAIT_FINAL_CONFIRM:
            smile = '⏰'
        elif deal['status'] == SUCCESS:
            smile = '✅'
        elif deal['status'] == FAILED:
            smile = '❌'

        elif deal['status'] == ARBITRAGE:
            smile = '‼️'
        text = f'{smile} №{deal["id"]} | @{deal["buyer"]} + @{deal["seller"]} | {deal["sum"]} $'
        keyboard.button(text=text, callback_data=f'deal_{deal["id"]}')

    keyboard.button(text="🔙 Назад", callback_data="back_menu")
    keyboard.adjust(1)


    return keyboard.as_markup()





async def manage_keyboard(deal_id, username):
    db = DB()

    keyboard = InlineKeyboardBuilder()

    deal = await db.get_deal_by_id(deal_id)

    if deal.status == WAIT_CONFIRM:
        keyboard.button(text=f'🔒 Отменить сделку', callback_data=f'unconfirm_deal_{deal_id}')

    elif deal.status == CONFIRMED:
        keyboard.button(text=f'🤝 Завершить сделку', callback_data=f'finally_confirm_deal_{deal_id}')
        keyboard.button(text=f'📞 Арбитраж', callback_data=f'arbitration_deal_{deal_id}')

    elif deal.status == WAIT_FINAL_CONFIRM:
        if deal.confirm_buyer == True:
            if deal.buyer == username:
                keyboard.button(text=f'⏳ Ожидается завершение сделки', callback_data='eeejfdskjdfsjs')
            else:
                keyboard.button(text=f'⏳ Подтвердить сделку', callback_data=f'finally_verify_deal_{deal_id}_{"buyer"}')
        
        elif deal.confirm_seller == True:
            if deal.seller == username:
                keyboard.button(text=f'⏳ Ожидается завершение сделки', callback_data='eeejfdskjdfsjs')
            else:
                keyboard.button(text=f'⏳ Подтвердить сделку', callback_data=f'finally_verify_deal_{deal_id}_{"seller"}')
            
    
    
    elif deal.status == SUCCESS or deal.status == FAILED:
        keyboard.button(text=f'📞 Арбитраж', callback_data=f'arbitration_deal_{deal_id}')

    elif deal.status == ARBITRAGE:
        keyboard.button(text=f'‼️ Сделка в арбитраже!', callback_data='in_arbitraj')

    keyboard.button(text="🔙 Назад", callback_data="back_deals")

    keyboard.adjust(1)

    return keyboard.as_markup()





    