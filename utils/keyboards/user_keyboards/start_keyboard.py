from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from aiogram.utils.keyboard import InlineKeyboardBuilder
from misc import config
from utils.database.db import DB



async def start_keyboard(user_id):
    keyboard = InlineKeyboardBuilder()
    if config.WEBAPP_URL:
        keyboard.button(text='🚀 Открыть приложение', web_app=WebAppInfo(url=config.WEBAPP_URL))
    keyboard.button(text='👤 Профиль', callback_data='profile')
    keyboard.button(text='🔍 Найти пользователя', callback_data='find_user')
    keyboard.button(text='📝 Мои сделки', callback_data='my_deal')
    keyboard.button(text='❓ Информация', callback_data='information')

    db = DB()

    admin = await db.get_admin_level(user_id)

    if admin == 1:
        keyboard.button(text='🩸 Арбитраж-панель', callback_data='arbitr_panel')

    elif admin == 2:
        keyboard.button(text='🩸 Арбитраж-панель', callback_data='arbitr_panel')
        keyboard.button(text='📝 Админ-панель', callback_data='admin_panel')


    if config.WEBAPP_URL:
        keyboard.adjust(1, 1, 2, 1)
    else:
        keyboard.adjust(1, 2, 1)
    return keyboard.as_markup()
