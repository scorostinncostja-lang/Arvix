"""Сборщик контекст-пакета для L1 из состояния БД.

Собирает компактный текстовый пакет: текущее время, режим, метрики,
задачи на сегодня, активные директивы, профиль.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Directive, Profile, StateCurrent, StateDaily, Task
from core.utils.time import now_local, today_local


async def build_context_packet(session: AsyncSession) -> str:
    """Собрать текстовый контекст-пакет из БД.

    Returns:
        Компактная текстовая сводка состояния системы (~800-1500 токенов)
    """
    sections = []

    # 1. Текущее время
    now = now_local()
    sections.append(f"=== Сейчас ===\n{now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')})")

    # 2. Профиль и режим
    profile = await session.get(Profile, 1)
    state = await session.get(StateCurrent, 1)

    if profile and state:
        mentor_status = "включён" if profile.mentor_enabled else "выключен"
        sections.append(
            f"=== Режим ===\n"
            f"Burnout Guard: {state.mode.upper()}\n"
            f"Ментор: {mentor_status}\n"
            f"HP: {state.hp}/100 | XP: {state.xp_total} (уровень {state.level})\n"
            f"Стрик: {state.streak_days} дней"
        )

    # 3. Задачи на сегодня
    today = today_local()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=now.tzinfo)
    day_end = datetime.combine(today, datetime.max.time(), tzinfo=now.tzinfo)

    result = await session.execute(
        select(Task)
        .where(Task.planned_start >= day_start, Task.planned_start <= day_end)
        .order_by(Task.planned_start)
    )
    tasks = list(result.scalars().all())

    if tasks:
        task_lines = []
        for t in tasks:
            status_emoji = {
                "planned": "⏳",
                "active": "▶️",
                "done": "✅",
                "failed": "❌",
                "debt": "🔴",
            }.get(t.status, "❓")
            time_str = t.planned_start.strftime("%H:%M")
            task_lines.append(
                f"{status_emoji} {time_str} | {t.title} | {t.sphere} | "
                f"imp={t.importance} diff={t.difficulty} | {t.planned_duration_min}мин"
            )
        sections.append(f"=== Задачи сегодня ({len(tasks)}) ===\n" + "\n".join(task_lines))

    # 4. Метрики дня
    daily = await session.get(StateDaily, today)
    if daily:
        completion = daily.completion_pct or 0
        sections.append(
            f"=== Метрики дня ===\n"
            f"Выполнение: {completion}%\n"
            f"Глубокая работа: {daily.deep_minutes} мин\n"
            f"XP за день: {daily.xp}"
        )

    # 5. Активные директивы из L2
    result = await session.execute(
        select(Directive)
        .where(Directive.valid_until.is_(None) | (Directive.valid_until >= today))
        .order_by(Directive.priority.asc(), Directive.created_at.desc())
        .limit(3)
    )
    directives = list(result.scalars().all())

    if directives:
        directive_lines = [f"- [{d.priority}] {d.text}" for d in directives]
        sections.append("=== Директивы L2 ===\n" + "\n".join(directive_lines))

    # 6. Долги (если есть)
    result = await session.execute(select(Task).where(Task.status == "debt"))
    debts = list(result.scalars().all())
    if debts:
        debt_lines = [f"- {d.title} (с {d.debt_since})" for d in debts]
        sections.append(f"=== Долги ({len(debts)}) ===\n" + "\n".join(debt_lines))

    return "\n\n".join(sections)
