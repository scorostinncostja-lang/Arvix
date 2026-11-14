"""Доменный слой задач: жизненный цикл через emit() событий (02-MECHANICS.md §1, 2, 3).

Формулы XP/HP из 02-MECHANICS.md §2-3:
- XP = base × K_diff × K_imp × K_proof × K_time
- HP урон: importance 1-2: -2, 3: -5, 4-5: -12
- Важные задачи (importance >= 4) при провале уходят в долг (debt)
"""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Task
from core.events.kinds import EventKind, EventSource
from core.events.log import emit
from core.scheduler.materialize import derive_proof
from core.utils.time import LOCAL_TZ, now_local

# Коэффициенты XP из 02-MECHANICS.md §2
K_DIFF = {1: 0.6, 2: 0.8, 3: 1.0, 4: 1.4, 5: 2.0}
K_IMP = {1: 0.7, 2: 0.9, 3: 1.0, 4: 1.3, 5: 1.6}
K_PROOF = {"confirm": 1.0, "report": 1.1, "photo": 1.3}

# Урон HP из 02-MECHANICS.md §3
HP_DAMAGE = {1: -2, 2: -2, 3: -5, 4: -12, 5: -12}


async def get_day_tasks(session: AsyncSession, target_date: date) -> list[Task]:
    """Список задач на день, отсортированный по planned_start."""
    day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=LOCAL_TZ)
    day_end = datetime.combine(target_date, datetime.max.time(), tzinfo=LOCAL_TZ)

    result = await session.execute(
        select(Task)
        .where(Task.planned_start >= day_start, Task.planned_start <= day_end)
        .order_by(Task.planned_start)
    )
    return list(result.scalars().all())


async def create_task(
    session: AsyncSession,
    title: str,
    sphere: str,
    importance: int,
    difficulty: int,
    planned_start: datetime,
    planned_duration_min: int,
    *,
    deep_work: bool = False,
    source: str = "user",
    goal_id: uuid.UUID | None = None,
) -> Task:
    """Создать задачу и записать событие TASK_CREATED."""
    proof = derive_proof(importance, sphere, deep_work)

    task = Task(
        title=title,
        sphere=sphere,
        importance=importance,
        difficulty=difficulty,
        planned_start=planned_start,
        planned_duration_min=planned_duration_min,
        deep_work=deep_work,
        proof=proof,
        source=source,
        goal_id=goal_id,
    )
    session.add(task)
    await session.flush()

    await emit(
        session,
        EventKind.TASK_CREATED,
        {
            "title": task.title,
            "sphere": task.sphere,
            "importance": task.importance,
            "difficulty": task.difficulty,
            "planned_start": task.planned_start.isoformat(),
            "duration_min": task.planned_duration_min,
            "deep_work": task.deep_work,
            "proof": task.proof,
        },
        source=EventSource(source),
        entity_id=task.id,
    )

    return task


async def start_task(session: AsyncSession, task_id: uuid.UUID, *, source: str = "user") -> Task:
    """Перевести задачу в active, записать actual_start."""
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.status != "planned":
        raise ValueError(f"Task {task_id} is already {task.status}, cannot start")

    task.status = "active"
    task.actual_start = now_local()

    await emit(
        session,
        EventKind.TASK_STARTED,
        {"at": task.actual_start.isoformat()},
        source=EventSource(source),
        entity_id=task.id,
    )

    return task


def _calculate_xp(task: Task, *, on_time: bool = True) -> int:
    """Расчет XP по формуле из 02-MECHANICS.md §2."""
    base = 10
    k_diff = K_DIFF.get(task.difficulty, 1.0)
    k_imp = K_IMP.get(task.importance, 1.0)
    k_proof = K_PROOF.get(task.proof, 1.0)

    # K_time: 1.0 если в окне ±15 мин, 0.8 если опоздал >15 мин, 1.15 если раньше
    k_time = 1.0
    if task.actual_start and task.planned_start:
        delta_minutes = (task.actual_start - task.planned_start).total_seconds() / 60
        if delta_minutes < -15:
            k_time = 1.15  # начал раньше
        elif delta_minutes > 15:
            k_time = 0.8  # опоздал
        else:
            k_time = 1.0  # вовремя

    xp = int(base * k_diff * k_imp * k_proof * k_time)
    return xp


async def complete_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    quality: int = 5,
    proof_kind: str = "confirm",
    report_text: str | None = None,
    source: str = "user",
) -> Task:
    """Завершить задачу: проверить инвариант, рассчитать XP, записать события."""
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    # Инвариант из 03-DATA-MODEL.md §3: завершенную задачу нельзя перевести обратно
    if task.status in ("done", "failed"):
        raise ValueError(f"Task {task_id} is already {task.status}, cannot complete again")

    task.status = "done"
    task.actual_end = now_local()
    task.quality = quality

    # Расчет XP
    xp = _calculate_xp(task)
    if quality < 5:
        # Частичное выполнение: снижаем XP пропорционально quality
        xp = int(xp * quality / 5)

    await emit(
        session,
        EventKind.TASK_COMPLETED,
        {
            "quality": quality,
            "proof_kind": proof_kind,
            "report_text": report_text,
            "xp": xp,
        },
        source=EventSource(source),
        entity_id=task.id,
    )

    await emit(
        session,
        EventKind.XP_AWARDED,
        {"amount": xp, "reason": f"task_completed:{task.title}", "balance_after": 0},
        source=EventSource(source),
        entity_id=task.id,
    )

    return task


async def fail_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    reason: str | None = None,
    source: str = "user",
) -> Task:
    """Провал задачи: урон HP, перевод в debt при importance >= 4."""
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.status in ("done", "failed", "debt"):
        raise ValueError(f"Task {task_id} is already {task.status}, cannot fail")

    # Важные задачи уходят в долг
    if task.importance >= 4:
        task.status = "debt"
        task.debt_since = now_local().date()
        await emit(
            session,
            EventKind.TASK_DEBTED,
            {"reason": reason or "failed_important"},
            source=EventSource(source),
            entity_id=task.id,
        )
    else:
        task.status = "failed"

    await emit(
        session,
        EventKind.TASK_FAILED,
        {"reason": reason or "user_marked"},
        source=EventSource(source),
        entity_id=task.id,
    )

    # Урон HP по таблице из 02-MECHANICS.md §3
    hp_damage = HP_DAMAGE.get(task.importance, -5)
    await emit(
        session,
        EventKind.HP_CHANGED,
        {"amount": hp_damage, "reason": f"task_failed:{task.title}", "balance_after": 0},
        source=EventSource(source),
        entity_id=task.id,
    )

    return task


async def defer_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    minutes: int = 15,
    *,
    source: str = "user",
) -> Task:
    """Отложить задачу: сдвинуть planned_start на N минут вперед."""
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.status != "planned":
        raise ValueError(f"Task {task_id} is {task.status}, cannot defer")

    old_start = task.planned_start
    task.planned_start = old_start + timedelta(minutes=minutes)

    await emit(
        session,
        EventKind.TASK_DEFERRED,
        {
            "from": old_start.isoformat(),
            "to": task.planned_start.isoformat(),
            "minutes": minutes,
        },
        source=EventSource(source),
        entity_id=task.id,
    )

    return task

