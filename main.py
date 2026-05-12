"""Entrypoint that boots the aiogram bot together with the FastAPI API.

Running ``python main.py`` starts both the Telegram polling loop and the
FastAPI server hosting the Mini App in the same process so they share the
same event loop and ``Bot`` instance.

Set ``RUN_BOT=0`` or ``RUN_API=0`` to disable one half of the stack.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums.parse_mode import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from misc import config
from routers.admin import admin, arbitr
from routers.user import (
    arbitr as arbitr_user,
    deal,
    deal_lists,
    information,
    manage_deal,
    profile,
    search_user,
    start,
)
from routers.utils import backs, cryptobot
from utils.database.db import DB
from utils.database.extras import WebDB
from utils.database.models import ALL_MODELS, db
from utils.middlewares.user_exists_middleware import RegistrationMiddleware
from utils.notifier import notifier

logger = logging.getLogger(__name__)


def _build_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=config.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(RegistrationMiddleware())
    dp.callback_query.middleware(RegistrationMiddleware())
    dp.include_routers(
        start.router,
        profile.router,
        backs.router,
        search_user.router,
        information.router,
        deal.router,
        deal_lists.router,
        cryptobot.router,
        manage_deal.router,
        arbitr_user.router,
        arbitr.router,
        admin.router,
    )
    return bot, dp


def _init_database() -> None:
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS)
    try:
        db.execute_sql("PRAGMA journal_mode=WAL;")
    except Exception:
        logger.exception("Could not enable WAL journal mode")
    WebDB().seed_default_categories()


async def _run_api() -> None:
    cfg = uvicorn.Config(
        "webapp.backend.app:app",
        host=config.WEBAPP_HOST,
        port=config.WEBAPP_PORT,
        log_level="info",
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(cfg)
    await server.serve()


async def _run_bot(bot: Bot, dp: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _init_database()

    tasks: list[asyncio.Task] = []

    if config.RUN_BOT:
        bot, dp = _build_bot()
        notifier.attach_bot(bot)
        await DB().get_or_create_percents()
        tasks.append(asyncio.create_task(_run_bot(bot, dp), name="bot"))

    if config.RUN_API:
        tasks.append(asyncio.create_task(_run_api(), name="api"))

    if not tasks:
        raise RuntimeError("Both RUN_BOT and RUN_API are disabled")

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


if __name__ == "__main__":
    asyncio.run(main())
