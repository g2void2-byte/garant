from aiogram import F, types, Router, Bot
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from utils.keyboards.utils import backs
from utils.database.db import DB
from routers.utils.status_deals import ARBITRAGE

router = Router()

class arbitration_deal_state(StatesGroup):
    get_reason = State()

@router.callback_query(F.data.startswith('arbitration_deal'))
async def arbitration_deal(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    deal_id = callback.data.split('_')[2]
    await callback.message.edit_text(text='<b>Укажите причину арбитража:</b>', reply_markup=backs.back_deal(deal_id))
    await state.update_data(deal_id=deal_id)
    await state.set_state(arbitration_deal_state.get_reason)


@router.message(arbitration_deal_state.get_reason, F.text)
async def get_reason(message: types.Message, bot: Bot, state: FSMContext):
    db = DB()
    data = await state.get_data()
    deal = await db.get_deal_by_id(data['deal_id'])
    seller_id = await db.get_userid_by_username(deal.seller)
    buyer_id = await db.get_userid_by_username(deal.buyer)
    await db.add_arbitr(data['deal_id'], message.text, message.from_user.username.lower())
    await db.update_status_deal(data['deal_id'], ARBITRAGE)
    await bot.send_message(message.from_user.id, f'<b>Арбитраж на сделку №{data["deal_id"]} успешно подан с причиной:\n{message.text}</b>', reply_markup=backs.back_deal(data['deal_id']))
    if deal.buyer == message.from_user.username.lower():
        await bot.send_message(seller_id, f'<b>На сделку №{data["deal_id"]} покупатель подал в арбитраж!\nСкоро с вами свяжутся арбитры для разбора ситуации!</b>', reply_markup=backs.back_deal(data['deal_id']))
    elif deal.seller == message.from_user.username.lower():
        await bot.send_message(buyer_id, f'<b>На сделку №{data["deal_id"]} продавец подал в арбитраж!\nСкоро с вами свяжутся арбитры для разбора ситуации!</b>', reply_markup=backs.back_deal(data['deal_id']))
    await state.clear()
    