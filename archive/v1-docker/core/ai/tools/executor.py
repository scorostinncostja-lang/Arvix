"""Исполнители инструментов для L1."""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import StateDaily, Task
from core.domain.tasks import complete_task as domain_complete_task
from core.domain.tasks import create_task as domain_create_task
from core.domain.tasks import get_day_tasks
from core.utils.time import LOCAL_TZ


async def execute_get_day(session: AsyncSession, date_str: str) -> str:
    """Получить задачи и метрики дня."""
    target_date = date.fromisoformat(date_str)
    tasks = await get_day_tasks(session, target_date)

    if not tasks:
        return f"На {date_str} задач не найдено."

    lines = [f"=== {date_str} ({len(tasks)} задач) ==="]
    for t in tasks:
        status_emoji = {
            "planned": "⏳",
            "active": "▶️",
            "done": "✅",
            "failed": "❌",
            "debt": "🔴",
        }.get(t.status, "❓")
        time_str = t.planned_start.strftime("%H:%M")
        lines.append(
            f"{status_emoji} {time_str} | {t.title} | {t.sphere} | "
            f"imp={t.importance} diff={t.difficulty}"
        )

    # Метрики дня
    daily = await session.get(StateDaily, target_date)
    if daily:
        lines.append(f"\nВыполнение: {daily.completion_pct or 0}% | XP: {daily.xp}")

    return "\n".join(lines)


async def execute_create_task(
    session: AsyncSession,
    title: str,
    sphere: str,
    importance: int,
    difficulty: int,
    planned_start: str,
    duration_min: int,
    deep_work: bool = False,
) -> str:
    """Создать задачу."""
    start_dt = datetime.fromisoformat(planned_start)

    task = await domain_create_task(
        session,
        title=title,
        sphere=sphere,
        importance=importance,
        difficulty=difficulty,
        planned_start=start_dt,
        planned_duration_min=duration_min,
        deep_work=deep_work,
        source="bot",
    )

    return f"Задача создана: {task.title} на {start_dt.strftime('%Y-%m-%d %H:%M')}"


async def execute_complete_task(
    session: AsyncSession,
    task_id: str,
    quality: int,
    note: str | None = None,
) -> str:
    """Закрыть задачу."""
    task_uuid = uuid.UUID(task_id)
    task = await domain_complete_task(
        session,
        task_uuid,
        quality=quality,
        proof_kind="confirm",
        report_text=note,
        source="bot",
    )

    return f"Задача '{task.title}' закрыта. Качество: {quality}/5."


async def execute_propose_schedule_change(
    session: AsyncSession,
    changes_description: str,
) -> str:
    """Вернуть факты для принятия решения об изменении расписания."""
    from core.db.models import StateCurrent, StateDaily
    from core.utils.time import today_local

    today = today_local()
    daily = await session.get(StateDaily, today)
    state = await session.get(StateCurrent, 1)

    # Считаем задачи сегодня
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=LOCAL_TZ)
    day_end = datetime.combine(today, datetime.max.time(), tzinfo=LOCAL_TZ)

    result = await session.execute(
        select(Task).where(Task.planned_start >= day_start, Task.planned_start <= day_end)
    )
    tasks = list(result.scalars().all())

    completed = sum(1 for t in tasks if t.status == "done")
    total = len(tasks)

    # Долги
    result = await session.execute(select(Task).where(Task.status == "debt"))
    debts = len(list(result.scalars().all()))

    lines = [
        "=== Факты для решения ===",
        f"Запрос: {changes_description}",
        "",
        f"Выполнено сегодня: {completed}/{total}",
        f"Глубокая работа: {daily.deep_minutes if daily else 0} мин",
        f"Режим: {state.mode.upper() if state else 'неизвестно'}",
        f"HP: {state.hp if state else 100}/100",
        f"Долгов: {debts}",
    ]

    if debts > 0:
        lines.append(f"\n⚠️ Есть {debts} задач(и) в долгу — приоритет на закрытие долгов.")

    return "\n".join(lines)


async def execute_tool(session: AsyncSession, tool_name: str, arguments: dict) -> str:
    """Выполнить инструмент по имени.

    Args:
        session: Сессия БД
        tool_name: Имя инструмента
        arguments: Аргументы инструмента

    Returns:
        Результат выполнения инструмента (текстовый)
    """
    if tool_name == "get_day":
        return await execute_get_day(session, **arguments)
    elif tool_name == "create_task":
        return await execute_create_task(session, **arguments)
    elif tool_name == "complete_task":
        return await execute_complete_task(session, **arguments)
    elif tool_name == "propose_schedule_change":
        return await execute_propose_schedule_change(session, **arguments)
    else:
        return f"Неизвестный инструмент: {tool_name}"
