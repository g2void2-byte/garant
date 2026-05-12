from aiogram import types



def back_profile():
    buttons = [
        [
            types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_profile")
        ]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    return markup


def back_menu():
    buttons = [
        [
            types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")
        ]
    ]

    markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    return markup


def back_deal(deal_id):
    buttons = [
        [
            types.InlineKeyboardButton(text="🔙 Посмотреть сделку", callback_data=f"deal_{deal_id}")
        ]
    ]

    markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    return markup

