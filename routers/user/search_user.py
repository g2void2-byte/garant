from aiogram import Bot, types, F, Router
from utils.keyboards.user_keyboards.search_user_keyboard import search_keyboard, manage_keyboard_with_user, back_to_search_menu
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.filters.filter_username import UsernameFilter
from utils.database.db import DB
from utils.keyboards.utils.backs import back_menu

router = Router()

class GetUsername(StatesGroup):
    get_username = State()


@router.callback_query(F.data == 'find_user')
async def find_user(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(f'Выберите тип поиска:', reply_markup=search_keyboard())

    except:
        await callback.message.delete()
        await callback.message.answer(f'Выберите тип поиска:', reply_markup=search_keyboard())


@router.callback_query(F.data == 'find_by_username')
async def find_by_username(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(f'Введите @юзернейм пользователя:')
    await state.set_state(GetUsername.get_username)


async def search_menu(callback: types.CallbackQuery, username):
    await callback.message.edit_text(f'Пользователь @{username} найден!', reply_markup=manage_keyboard_with_user(username))


@router.message(GetUsername.get_username, UsernameFilter())
async def get_username_func(message: types.Message, state: FSMContext):
    db = DB()
    username = message.text.replace('@', '').lower()
    if await db.get_user_by_username(username) is not None:
        if username == message.from_user.username.lower():
            await message.answer('Вы не можете найти себя!', reply_markup=back_menu())
            await state.clear()
            return
        await message.answer(f'Пользователь @{message.text.replace("@", "")} найден!', reply_markup=manage_keyboard_with_user(message.text.replace('@', '')))
        await state.clear()

    else:
        await message.answer('Пользователя не существует!', reply_markup=back_menu())




@router.callback_query(F.data.startswith('stats'))
async def stats_user(callback: types.CallbackQuery):
    db = DB()
    username = callback.data.split(':')[1]
    stat = await db.get_stat_by_username(username)
    sum_sell = stat[1]['seller_stat']['sum_sells']
    sum_buy = stat[0]['buyer_stat']['sum_sells']
    sum_sell_deal = stat[1]['seller_stat']['all_sum']
    sum_buy_deal = stat[0]['buyer_stat']['all_sum']
    raiting = raiting = await db.get_grades(username)
    text = f'''
🔍 Статистика пользователя: @{username}
➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖➖
🎁 Кол-во продаж: {sum_sell} шт
🛒 Кол-во покупок: {sum_buy} шт
📥 Сумма продаж: {sum_sell_deal} $
📤 Сумма покупок: {sum_buy_deal} $
⭐️ Рейтинг: 👍 {raiting['good']} 👎 {raiting['bad']}
'''
    
    await callback.message.edit_text(text=text, reply_markup=back_to_search_menu(username))
    
