from aiogram import types, F, Router
from utils.keyboards.utils import backs

router = Router()



@router.callback_query(F.data == 'information')
async def information(message: types.CallbackQuery):
    try:
        await message.message.edit_text(f'''
📌 Лучший гарант-бот, который позволяет действительно безопасно проводит сделки, реализуя лучшие решения для Вас. 

👉🏻 Мы стремимся к созданию продукта, который будет славится своим качеством, а основной которого лежит честность в проведении сделок. 

❗️ Обязательно ознакомиться с правилами гаранта и инструкцие: @EndWaySupportbot

🔥 По вопросам арбитража и техничкой поддержки - @endwaysupport
                                    ''', reply_markup=backs.back_menu())
        
    except:
        await message.message.delete()
        await message.message.answer(f'''
📌 Лучший гарант-бот, который позволяет действительно безопасно проводит сделки, реализуя лучшие решения для Вас. 

👉🏻 Мы стремимся к созданию продукта, который будет славится своим качеством, а основной которого лежит честность в проведении сделок. 

❗️ Обязательно ознакомиться с правилами гаранта и инструкцие: @EndWaySupportbot

🔥 По вопросам арбитража и техничкой поддержки - @endwaysupport
                                    ''', reply_markup=backs.back_menu())