from aiogram import types, F, Router, Bot
from aiogram.filters import Command
from utils.keyboards.user_keyboards import start_keyboard
from aiogram.types.input_file import FSInputFile, InputFile



router = Router()





@router.message(Command('start'))
async def start(message: types.CallbackQuery, bot: Bot):
    photo = FSInputFile('media/start.jpg')
    try:
        await message.message.delete()
        await bot.delete_message(message.from_user.id, message.message.message_id - 1)
        await bot.send_photo(message.from_user.id, photo=photo)
        await bot.send_message(message.from_user.id, f'''
<b>🔥 Самый безопасный и проверенный гарант-бот от EndWay Community. Минимальные комиссии (до 5%) и разные типы сделок, для безопасного и комфортного их проведения.</b>
                         ''', reply_markup=await start_keyboard.start_keyboard(message.from_user.id))
        
    except:
        await bot.send_photo(message.from_user.id, photo=photo, caption=f'''
<b>🔥 Самый безопасный и проверенный гарант-бот от EndWay Community. Минимальные комиссии (до 5%) и разные типы сделок, для безопасного и комфортного их проведения.</b>
                         ''', reply_markup=await start_keyboard.start_keyboard(message.from_user.id))