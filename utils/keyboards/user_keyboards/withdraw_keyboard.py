from aiogram.utils.keyboard import InlineKeyboardBuilder




def withdraw_markup(user):
    keyboard = InlineKeyboardBuilder()

    balance = user.balance
    if balance > 0:
        keyboard.button(text=f'💰 Вывести {balance}$', callback_data=f'withdraw_{balance}')
        keyboard.button(text='🔙 Назад', callback_data='back_profile')
    
        keyboard.adjust(1)
    elif balance <= 0:
        keyboard.button(text='💰 Вывод недоступен!', callback_data='nomoneywithdraw')
        keyboard.button(text='🔙 Назад', callback_data='back_profile')

        keyboard.adjust(1)


    return keyboard.as_markup()