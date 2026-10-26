from aiogram import Dispatcher

from core.bot.handlers import day, debrief, freeform, start, tasks


def register_handlers(dp: Dispatcher) -> None:
    # Регистрируем роутеры в строгом порядке:
    # 1. Командные роутеры (start, day, tasks, debrief)
    # 2. freeform ПОСЛЕДНИМ - он ловит все текстовые сообщения
    dp.include_router(start.router)
    dp.include_router(day.router)
    dp.include_router(tasks.router)
    dp.include_router(debrief.router)
    dp.include_router(freeform.router)  # СТРОГО ПОСЛЕДНИЙ!

