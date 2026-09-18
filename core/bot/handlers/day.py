from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.db.session import async_session_factory
from core.scheduler.materialize import materialize_day
from core.utils.time import today_local

router = Router(name="day")


@router.message(Command("day"))
async def cmd_day(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    force = len(args) > 1 and args[1].strip().lower() == "rebuild"

    today = today_local()
    async with async_session_factory() as session:
        tasks = await materialize_day(session, today, force=force)
        await session.commit()

    if not tasks:
        await message.answer("На сегодня задач нет — шаблон дня не задан.")
        return

    lines = [f"План на {today.strftime('%d.%m')}:"]
    for t in sorted(tasks, key=lambda task: task.planned_start):
        lines.append(f"{t.planned_start.strftime('%H:%M')} {t.title} ({t.planned_duration_min} мин)")
    await message.answer("\n".join(lines))
