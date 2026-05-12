from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.database.db import DB


async def arbitr_main_menu():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text=f'❗️ Спорные сделки', callback_data='arbitr_deals')
    keyboard.button(text=f'💰 Взятые сделки', callback_data='arbitr_my_deals')
    keyboard.button(text=f'📝 Завершенные сделки', callback_data='arbitr_completed')
    keyboard.button(text='🔙 Назад', callback_data='back_menu')
    
    keyboard.adjust(1)

    return keyboard.as_markup()


async def arbitr_deals_menu():
    keyboard = InlineKeyboardBuilder()

    db = DB()

    deals = await db.get_all_arbitr_info()

    for deal in deals:
        keyboard.button(text=f'📍 №{deal["deal_id"]} | @{deal["initiator"]}', callback_data=f'arbitr_arbitration_deal_{deal["deal_id"]}')
    keyboard.button(text='🔙 Назад', callback_data='back_arbitr_menu')

    keyboard.adjust(1)

    return keyboard.as_markup()



def manage_arbitr_deal(deal_id):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔑 Взять на рассмотрение', callback_data=f'get_deal_on_review_{deal_id}')
    keyboard.button(text='🔙 Назад', callback_data='back_arbitr_deals')

    keyboard.adjust(1)
    return keyboard.as_markup()


async def my_arbitr_deal(username):
    keyboard = InlineKeyboardBuilder()
    db = DB()

    my_deals = await db.get_my_arbitr_deals(username)

    for deal in my_deals:
        keyboard.button(text=f'📍 №{deal["deal_id"]} | @{deal["initiator"]}', callback_data=f'arbitr_arbitration_my_deal_{deal["deal_id"]}')
    
    keyboard.button(text='🔙 Назад', callback_data='back_arbitr_menu')

    keyboard.adjust(1)
    return keyboard.as_markup()


async def completed_arbitr_deal(username):
    keyboard = InlineKeyboardBuilder()
    db = DB()

    my_completed_deals = await db.get_my_completed_arbitr_deals(username)

    for deal in my_completed_deals:
        if deal['verdict'] == 'buyer':
            verdict = 'Покупатель'
        elif deal['verdict'] == 'seller':
            verdict = 'Продавец'
        keyboard.button(text=f'📍 №{deal["deal_id"]} | @{deal["initiator"]} | {verdict}', callback_data=f'arbitr_arbitration_completed_deal_{deal["deal_id"]}')

    keyboard.button(text='🔙 Назад', callback_data='back_arbitr_menu')

    keyboard.adjust(1)
    return keyboard.as_markup()

def manage_my_arbitr_deal(deal_id):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔐 На Вашем рассмотрении', callback_data='reviewsarbitfjfjf')
    keyboard.button(text=f'💰 Вердикт в/п покупателя', callback_data=f'close_arbitr_deal_{deal_id}_buyer')
    keyboard.button(text=f'💰 Закрыть в/п продавца', callback_data=f'close_arbitr_deal_{deal_id}_seller')
    keyboard.button(text='🔙 Назад', callback_data='arbitr_my_deals')

    keyboard.adjust(1, 2, 1)

    return keyboard.as_markup()


def success_my_arbitr_deal(deal_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=f'🔐 Сделка №{deal_id} рассмотрена!', callback_data='erwdcvsjsdfkjsfda')
    keyboard.button(text='🔙 Назад', callback_data='arbitr_completed')
    
    keyboard.adjust(1)
    return keyboard.as_markup()