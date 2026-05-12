from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.database.db import DB


def main_admin_menu():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='📊 Статистика', callback_data='admin_stats')
    keyboard.button(text='👥 Пользователи', callback_data='admin_users')
    keyboard.button(text='💼 Сделки', callback_data='admin_deals_list')
    keyboard.button(text='⚖️ Арбитры', callback_data='admin_arbiters')
    keyboard.button(text='📣 Рассылка', callback_data='admin_broadcast')
    keyboard.button(text='⚙️ Настройки', callback_data='admin_settings')

    keyboard.adjust(1, 2, 1, 2)  # 2 кнопки в ряд

    return keyboard.as_markup()

def settings_menu(status_withdraw):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text='📝 Изменить комиссию на пополнение', callback_data='admin_edit_percent')
    keyboard.button(text='📝 Изменить комиссию на сделки', callback_data='admin_edit_deal_percent')
    if status_withdraw == 'auto':
        keyboard.button(text=f'💰 Тип вывода: Автоматический', callback_data=f'set_withdraw_mode:manual')
    else:
        keyboard.button(text=f'💰 Тип вывода: Полуавтоматический', callback_data='set_withdraw_mode:auto')
    keyboard.button(text='🔙 Назад', callback_data='admin_panel')
    keyboard.adjust(1)
    return keyboard.as_markup()


def back_admin_menu():
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔙 Назад', callback_data='admin_panel')

    keyboard.adjust(1)

    return keyboard.as_markup()
