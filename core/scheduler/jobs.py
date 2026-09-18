"""Cron-триггеры L0. Шаг 0.4: только материализация дня в 04:30, in-memory
scheduler. Шаг 0.5 добавит persistent jobstore в Postgres (переживает
рестарт) и напоминания по конкретным задачам."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.db.session import async_session_factory
from core.scheduler.materialize import materialize_day
from core.utils.time import today_local

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def _materialize_today_job() -> None:
    async with async_session_factory() as session:
        await materialize_day(session, today_local())
        await session.commit()


def start_scheduler() -> None:
    scheduler.add_job(
        _materialize_today_job,
        CronTrigger(hour=4, minute=30),
        id="materialize_today",
        replace_existing=True,
    )
    scheduler.start()
