from aiogram import Dispatcher

from core.bot.handlers import day, start


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    dp.include_router(day.router)
