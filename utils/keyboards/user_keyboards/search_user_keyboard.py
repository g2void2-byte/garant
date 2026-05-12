from aiogram.utils.keyboard import InlineKeyboardBuilder


def search_keyboard():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔎 Поиск по @username', callback_data='find_by_username')
    keyboard.button(text="🔙 Назад", callback_data="back_menu")

    keyboard.adjust(1)

    return keyboard.as_markup()





def manage_keyboard_with_user(username):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text=f'💌 Статистика @{username}', callback_data=f'stats:{username}')
    keyboard.button(text=f'📩 Начать сделку с @{username}', callback_data=f'start_deal:{username}')
    keyboard.button(text="🔙 Назад", callback_data="back_menu")
    keyboard.adjust(1)
    return keyboard.as_markup()


def back_to_search_menu(username):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 Назад", callback_data=f"back_search_{username}")
    keyboard.adjust(1)
    return keyboard.as_markup()