"""Cron-триггеры L0. Шаг 0.4: только материализация дня в 04:30, in-memory
scheduler. Шаг 0.5 добавляет напоминания по конкретным задачам."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from core.bot.instance import bot
from core.bot.keyboards import completion_check_keyboard, reminder_t_minus_5_keyboard
from core.bot.templates import reminder_completion_check, reminder_started, reminder_t_minus_5
from core.config import settings
from core.db.session import async_session_factory
from core.domain.tasks import start_task
from core.scheduler.materialize import materialize_day
from core.utils.time import now_local, today_local

if TYPE_CHECKING:
    from core.db.models import Task

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def _materialize_today_job() -> None:
    async with async_session_factory() as session:
        await materialize_day(session, today_local())
        await session.commit()


async def _send_reminder_t_minus_5(task_id: str, task_title: str, duration: int, importance: int) -> None:
    """Напоминание за 5 минут до начала задачи."""
    text = reminder_t_minus_5(task_title, duration, importance)
    keyboard = reminder_t_minus_5_keyboard(task_id)
    await bot.send_message(settings.owner_id, text, reply_markup=keyboard)


async def _send_reminder_start(task_id: str, task_title: str, duration: int) -> None:
    """Уведомление о начале блока (T+0). Если задача еще planned, переводим в active."""
    from core.db.models import Task

    async with async_session_factory() as session:
        task = await session.get(Task, task_id)
        if task and task.status == "planned":
            await start_task(session, task.id, source="scheduler")
            await session.commit()

    text = reminder_started(task_title, duration)
    await bot.send_message(settings.owner_id, text)


async def _send_reminder_completion(task_id: str, task_title: str, proof: str) -> None:
    """Запрос подтверждения выполнения (T + duration)."""
    text = reminder_completion_check(task_title)
    keyboard = completion_check_keyboard(task_id, proof)
    await bot.send_message(settings.owner_id, text, reply_markup=keyboard)


async def _debrief_job() -> None:
    """Вечерний разбор в 22:30."""
    from core.bot.handlers.debrief import scheduled_debrief

    await scheduled_debrief()


async def _morning_brief_job() -> None:
    """Утренний брифинг в 07:30."""
    from core.bot.handlers.debrief import morning_brief

    await morning_brief()


def schedule_task_reminders(scheduler: AsyncIOScheduler, task: "Task") -> None:
    """Создать 3 job'а для напоминаний о задаче: T-5, T+0, T+duration.
    
    Использует replace_existing=True для защиты от дублирования при повторном
    вызове (например, после defer_task). Job'ы создаются только если время еще
    в будущем."""
    now = now_local()
    task_id_str = str(task.id)

    # T-5 мин
    t_minus_5 = task.planned_start - timedelta(minutes=5)
    if t_minus_5 > now:
        scheduler.add_job(
            _send_reminder_t_minus_5,
            DateTrigger(run_date=t_minus_5),
            args=[task_id_str, task.title, task.planned_duration_min, task.importance],
            id=f"rem_{task_id_str}_t5",
            replace_existing=True,
        )

    # T+0 (начало)
    if task.planned_start > now:
        scheduler.add_job(
            _send_reminder_start,
            DateTrigger(run_date=task.planned_start),
            args=[task_id_str, task.title, task.planned_duration_min],
            id=f"rem_{task_id_str}_t0",
            replace_existing=True,
        )

    # T + duration (завершение)
    t_end = task.planned_start + timedelta(minutes=task.planned_duration_min)
    if t_end > now:
        scheduler.add_job(
            _send_reminder_completion,
            DateTrigger(run_date=t_end),
            args=[task_id_str, task.title, task.proof],
            id=f"rem_{task_id_str}_end",
            replace_existing=True,
        )


async def sync_today_jobs(scheduler: AsyncIOScheduler) -> None:
    """Синхронизировать задачи сегодняшнего дня с APScheduler.
    
    Вызывается при старте приложения (main.py) и после materialize_day().
    Гарантирует, что рестарт контейнера не теряет напоминания."""
    from core.db.models import Task

    today = today_local()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=now_local().tzinfo)
    day_end = datetime.combine(today, datetime.max.time(), tzinfo=now_local().tzinfo)

    async with async_session_factory() as session:
        result = await session.execute(
            select(Task).where(
                Task.planned_start >= day_start,
                Task.planned_start <= day_end,
                Task.status.in_(["planned", "active"]),
            )
        )
        tasks = result.scalars().all()

        for task in tasks:
            schedule_task_reminders(scheduler, task)


def start_scheduler() -> None:
    # Материализация дня в 04:30
    scheduler.add_job(
        _materialize_today_job,
        CronTrigger(hour=4, minute=30),
        id="materialize_today",
        replace_existing=True,
    )

    # Вечерний разбор в 22:30
    scheduler.add_job(
        _debrief_job,
        CronTrigger(hour=22, minute=30),
        id="debrief",
        replace_existing=True,
    )

    # Утренний брифинг в 07:30
    scheduler.add_job(
        _morning_brief_job,
        CronTrigger(hour=7, minute=30),
        id="morning_brief",
        replace_existing=True,
    )

    scheduler.start()

