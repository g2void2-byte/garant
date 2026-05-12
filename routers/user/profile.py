from aiogram import types, Router, Bot, F
from utils.keyboards.user_keyboards import profile_keyboard
from utils.database.db import DB

router = Router()



@router.callback_query(F.data == 'profile')
async def profile(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    user = await db.get_user_by_username(callback.from_user.username.lower())
    stat = await db.get_stat_by_username(callback.from_user.username.lower())
    balance = user.balance
    sum_sell = stat[1]['seller_stat']['sum_sells']
    sum_buy = stat[0]['buyer_stat']['sum_sells']
    sum_sell_deal = stat[1]['seller_stat']['all_sum']
    sum_buy_deal = stat[0]['buyer_stat']['all_sum']
    raiting = await db.get_grades(callback.from_user.username.lower())
    try:
        await callback.message.edit_text(f'''
🔍 Пользователь: @{callback.from_user.username} ({callback.from_user.id})
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
🤖 ID - {callback.from_user.id}
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
💳 Баланс:
 └ {round(balance, 2)} $
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
🎁 Кол-во продаж: {sum_sell} шт
🛒 Кол-во покупок: {sum_buy} шт
📥 Сумма продаж: {sum_sell_deal} $
📤 Сумма покупок: {sum_buy_deal} $
⭐️ Рейтинг: 👍 {raiting['good']} 👎 {raiting['bad']}
                                     ''', reply_markup=profile_keyboard.profile_markup())
    except:
        await callback.message.delete()
        await callback.message.answer(f'''
🔍 Пользователь: @{callback.from_user.username} ({callback.from_user.id})
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
🤖 ID - {callback.from_user.id}
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
💳 Баланс:
 └ {round(balance, 2)} $
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
🎁 Кол-во продаж: {sum_sell} шт
🛒 Кол-во покупок: {sum_buy} шт
📥 Сумма продаж: {sum_sell_deal} $
📤 Сумма покупок: {sum_buy_deal} $
⭐️ Рейтинг: 👍 {raiting['good']} 👎 {raiting['bad']}
                                     ''', reply_markup=profile_keyboard.profile_markup())