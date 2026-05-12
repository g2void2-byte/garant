from aiogram import F, types, Bot, Router
from utils.database.db import DB
from utils.keyboards.user_keyboards import manage_deal_keyboard
from utils.keyboards.utils import backs
from routers.utils.status_deals import *
from routers.user.deal_lists import deal_manage


router = Router()


@router.callback_query(F.data.startswith('finally_confirm_deal'))
async def finally_confirm_deal(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[3]
    
    await callback.message.edit_text(text='<b>Вы уверены, что хотите завершить сделку?</b>', reply_markup=manage_deal_keyboard.verify_answer_confirm(deal_id=deal_id))







@router.callback_query(F.data.startswith('verify_confirm_deal_yes'))
async def verify_confirm_deal_yes(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[4]

    deal = await db.get_deal_by_id(deal_id)


    if deal.status != SUCCESS:
        confirm = await db.update_deal_confirm(deal_id, callback.from_user.username.lower())
        await db.update_status_deal(deal_id, WAIT_FINAL_CONFIRM)

        if confirm['position'] == 'seller':
            await callback.message.edit_text(f'<b>Ожидайте подтверждения со стороны покупателя.</b>', reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))
            await bot.send_message(confirm['user_id'], f'<b>Покупатель подтвердил завершение сделки. Вы подтверждаете сделку?</b>', reply_markup=manage_deal_keyboard.confirmation_keyboard(deal_id, 'seller'))

        elif confirm['position'] == 'buyer':
            await callback.message.edit_text(f'<b>Ожидайте подтверждения со стороны продавца.</b>', reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))
            await bot.send_message(confirm['user_id'], f'<b>Продавец подтвердил завершение сделки. Вы подтверждаете сделку?</b>', reply_markup=manage_deal_keyboard.confirmation_keyboard(deal_id, 'buyer'))


    elif deal.status == SUCCESS:
        await callback.answer(text='Сделка уже завершена!')
        await deal_manage(callback, bot, deal_id)
        return
    
    elif deal.status == FAILED:
        await callback.answer(text='Сделка уже завершена!')
        await deal_manage(callback, bot, deal_id)
        return


@router.callback_query(F.data.startswith('finally_verify_deal'))
async def finally_verify_deal(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[3]
    position = callback.data.split('_')[4]

    await callback.message.edit_text(text='<b>Вы уверены, что хотите подтвердить сделку?</b>', reply_markup=manage_deal_keyboard.confirmation_keyboard(deal_id, position))

@router.callback_query(F.data.startswith('finally_deal_confirm_yes'))
async def confirm_deal_yes(callback: types.CallbackQuery, bot: Bot):
    await callback.message.delete()
    db = DB()
    deal_id = callback.data.split('_')[4]
    position = callback.data.split('_')[5]

    deal = await db.get_deal_by_id(deal_id)
    
    buyer_id = await db.get_userid_by_username(deal.buyer)
    seller_id = await db.get_userid_by_username(deal.seller)
    percent_deal = await db.get_percent_deal()

    if deal.status != SUCCESS or deal.status != FAILED:
        await db.update_deal_confirm(deal_id, callback.from_user.username.lower())
        await db.update_status_deal(deal_id=deal_id, status=SUCCESS)
        pay_comission = deal.pay_comission
        
        seller_text = f'<b>Сделка №{deal.id} была завершена!</b>'
        if pay_comission == 'buyer':
            summa = deal.sum
        elif pay_comission == 'seller':
            summa = float(deal.sum) - (float(deal.sum) / 100 * float(percent_deal))
            seller_text += f'\n<b>На ваш баланс было зачислено {summa}$\nСумма была высчитана исходя из процента комиссии проведения сделки ботом {percent_deal}%, так как её платите Вы, как продавец.</b>'

        
        await db.add_balance_by_username(deal.seller, summa)
    
        await bot.send_message(seller_id, seller_text, reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))
        await bot.send_message(buyer_id, f'<b>Сделка №{deal.id} была завершена!</b>', reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))



@router.callback_query(F.data.startswith('verify_confirm_deal_no'))
async def verify_confirm_deal_no(callback: types.CallbackQuery, bot: Bot):
    db = DB()
    deal_id = callback.data.split('_')[4]

    await db.update_deal_confirm(deal_id, callback.from_user.username.lower())

    await callback.message.edit_text(text='<b>Отменено!</b>', reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))



@router.callback_query(F.data.startswith('finally_deal_confirm_no'))
async def confirm_deal_no(callback: types.CallbackQuery, bot: Bot):
    await callback.message.delete()
    db = DB()
    deal_id = callback.data.split('_')[4]
    position = callback.data.split('_')[5]
    deal = await db.get_deal_by_id(deal_id)
    
    buyer_id = await db.get_userid_by_username(deal.buyer)
    seller_id = await db.get_userid_by_username(deal.seller)


    await db.update_status_deal(deal_id=deal_id, status=CONFIRMED)

    await bot.send_message(seller_id, f'<b>Завершение сделки было отклонено одним из участников!</b>', reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))
    await bot.send_message(buyer_id, f'<b>Завершение сделки было отклонено одним из участников!</b>', reply_markup=manage_deal_keyboard.seller_keyboard_success(deal_id))

    
@router.callback_query(F.data.startswith('feedback'))
async def feedback(callback: types.CallbackQuery, bot: Bot):
    deal_id = callback.data.split('_')[1]
    db = DB()

    deal = await db.get_deal_by_id(deal_id)

    if callback.from_user.username.lower() == deal.buyer.lower():
        username = deal.seller
    elif callback.from_user.username.lower() == deal.seller.lower():
        username = deal.buyer
    print(username)
    await callback.message.edit_text(text='<b>Оставьте отзыв о партнере!</b>', reply_markup=manage_deal_keyboard.feedback_keyboard(username))


@router.callback_query(F.data.startswith('positive_feedback'))
async def positive_feedback(callback: types.CallbackQuery, bot: Bot):
    username = callback.data.split('_')[2]
    db = DB()

    print(f'positive {username}')
    user_id = await db.get_userid_by_username(username)

    await db.add_good_grade(username)
    await bot.send_message(user_id, '<b>Вам оставили положительный отзыв.</b>', reply_markup=backs.back_menu())
    await callback.message.edit_text(f'<b>Вы оставили положительный отзыв.</b>', reply_markup=backs.back_menu())


@router.callback_query(F.data.startswith('negative_feedback'))
async def negative_feedback(callback: types.CallbackQuery, bot: Bot):
    username = callback.data.split('_')[2]
    db = DB()

    print(f'negative {username}')
    user_id = await db.get_userid_by_username(username)

    await db.add_bad_grade(username)
    await bot.send_message(user_id, '<b>Вам оставили отрицательный отзыв.</b>', reply_markup=backs.back_menu())
    await callback.message.edit_text(f'<b>Вы оставили негативный отзыв.</b>', reply_markup=backs.back_menu())
    