from aiogram.utils.keyboard import InlineKeyboardBuilder
from routers.utils.cryptobot import create_add_money_request



def created_deal(id):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='❌ Отклонить', callback_data=f'unconfirm_deal_{id}')
    keyboard.button(text='🔙 Назад', callback_data='back_menu')

    keyboard.adjust(1)
    return keyboard.as_markup()


def position_keyboard():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔮 Покупатель', callback_data='position_buyer')
    keyboard.button(text='🔑 Продавец', callback_data='position_seller')


    keyboard.adjust(2)
    return keyboard.as_markup()


def pay_comission():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔮 Покупатель', callback_data='pay_comission_buyer')
    keyboard.button(text='🔑 Продавец', callback_data='pay_comission_seller')

    keyboard.adjust(1)
    return keyboard.as_markup()



def confirmation_deal(id):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='✅ Подтвердить', callback_data=f'confirm_deal_{id}')
    keyboard.button(text='❌ Отклонить', callback_data=f'unconfirm_deal_{id}')

    keyboard.adjust(2)
    return keyboard.as_markup()



async def no_balance_deals(summa, deal_id):
    keyboard = InlineKeyboardBuilder()
    url = await create_add_money_request(round(summa, 2))
    keyboard.button(text=f'💳 Пополнение на {round(summa, 2)} $', url=url.pay_url)
    keyboard.button(text=f'💰 Проверка пополнения', callback_data=f'check_deal_cryptobot_{url.invoice_id}_{deal_id}')
    keyboard.button(text='🔙 Назад', callback_data='back_menu')

    keyboard.adjust(1)

    return keyboard.as_markup()



async def to_deal(deal_id):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🏷 Перейти к сделке', callback_data=f'deal_{deal_id}')
    keyboard.button(text='🔙 Назад', callback_data='back_menu')

    keyboard.adjust(1)

    return keyboard.as_markup()