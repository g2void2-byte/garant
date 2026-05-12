from aiogram.utils.keyboard import InlineKeyboardBuilder



def keyboard_payment(url, amount):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=f'💳 Пополнение на {amount} $', url=url.pay_url)
    keyboard.button(text=f'💰 Проверка пополнения', callback_data=f'check_cryptobot_{url.invoice_id}')
    keyboard.button(text='🔙 Назад', callback_data='back_menu')

    keyboard.adjust(1)

    return keyboard.as_markup()