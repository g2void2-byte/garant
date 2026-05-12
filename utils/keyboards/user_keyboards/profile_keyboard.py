from aiogram.utils.keyboard import InlineKeyboardBuilder



def profile_markup():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='💳 Пополнение', callback_data='add_money')
    keyboard.button(text='💸 Вывод', callback_data='withdraw_money')
    keyboard.button(text="🔙 Назад", callback_data="back_menu")


    keyboard.adjust(1)
    return keyboard.as_markup()