import re
from aiogram import types
from aiogram.filters import BaseFilter

class UsernameFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        pattern = r"@[\w\d_]+"
        text = message.text
        search = re.search(pattern, text)

        if bool(search):
            return True
        
        await message.answer("Неправильный формат имени пользователя")
        return False
        
        