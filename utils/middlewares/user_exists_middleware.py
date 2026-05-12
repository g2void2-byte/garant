import asyncio
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from utils.database.models import Users




class RegistrationMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
            
            
    ) -> Any:
        user = Users.get_or_none(Users.user_id == event.from_user.id)

        if user is None:
            if event.from_user.username:
                Users.create(user_id=event.from_user.id, username=event.from_user.username.lower())
                await event.bot.send_message(event.from_user.id, "Вы успешно зарегистрировались в боте!")
            else:
                await event.bot.send_message(event.from_user.id, "Установите username для удобного использования ботом и возвращайтесь снова!")
                return None

        else:
            if user.ban:
                await event.answer(f'Вы заблокированы!')
                return
            user.username = event.from_user.username.lower()
            user.save()
        result = await handler(event, data)
        return result