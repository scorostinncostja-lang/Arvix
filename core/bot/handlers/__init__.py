from aiogram import Dispatcher

from core.bot.handlers import start


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(start.router)
