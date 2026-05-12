from aiogram import types, Bot, F, Router
from routers.user import start, profile, deal_lists, search_user
from routers.admin.arbitr import arbitr_panel, arbitr_deals
router = Router()

from aiogram.fsm.context import FSMContext

@router.callback_query(F.data == 'back_menu')
async def back_menu(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await start.start(callback, bot) 


@router.callback_query(F.data == 'back_profile')
async def back_profile(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await profile.profile(callback, bot)


@router.callback_query(F.data == 'back_deals')
async def back_deals(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await deal_lists.my_deal(callback, bot)


@router.callback_query(F.data == 'back_arbitr_menu')
async def back_arbitr_menu(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await arbitr_panel(callback, bot)


@router.callback_query(F.data == 'back_arbitr_deals')
async def back_arbit_deals(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await arbitr_deals(callback, bot)

@router.callback_query(F.data == 'back_arbitr_my_deals')
async def back_arbitr_my_deals(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await arbitr_deals(callback, bot)


@router.callback_query(F.data.startswith('back_search'))
async def back_search(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    username = callback.data.split('_')[2]
    await search_user.search_menu(callback, username)