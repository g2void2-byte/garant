from aiogram.utils.keyboard import InlineKeyboardBuilder


def verify_answer_confirm(deal_id):
    keyboard = InlineKeyboardBuilder()


    keyboard.button(text='☑️ Да', callback_data=f'verify_confirm_deal_yes_{deal_id}')
    keyboard.button(text='❌ Нет', callback_data=f'verify_confirm_deal_no_{deal_id}')
    keyboard.button(text='🔙 Назад', callback_data=f'deal_{deal_id}')

    keyboard.adjust(2)

    return keyboard.as_markup()


def seller_keyboard_success(deal_id):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='🔙 Посмотреть сделку', callback_data=f'deal_{deal_id}')
    keyboard.button(text='⭐️ Оставить отзыв', callback_data=f'feedback_{deal_id}')
    keyboard.button(text='🔙 Вернуться в меню', callback_data='back_menu')

    keyboard.adjust(1)
    return keyboard.as_markup()


def confirmation_keyboard(deal_id, position):
    keyboard = InlineKeyboardBuilder()

    keyboard.button(text='✅ Да', callback_data=f'finally_deal_confirm_yes_{deal_id}_{position}')
    keyboard.button(text='❌ Нет', callback_data=f'finally_deal_confirm_no_{deal_id}_{position}')
    keyboard.button(text='🔙 Посмотреть сделку', callback_data=f'deal_{deal_id}')

    keyboard.adjust(2)
    return keyboard.as_markup()

def redeal_keyboard(deal_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text='🔃 Повторно отправить сделку', callback_data=f'resend_deal_{deal_id}')
    keyboard.button(text='🔙 Вернуться в меню', callback_data='back_menu')
    
    keyboard.adjust(1)

    return keyboard.as_markup()

def feedback_keyboard(username):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text='👍', callback_data=f'positive_feedback_{username}')
    keyboard.button(text='👎', callback_data=f'negative_feedback_{username}')

    keyboard.adjust(2)
    return keyboard.as_markup()