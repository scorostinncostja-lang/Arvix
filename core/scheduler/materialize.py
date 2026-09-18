"""Шаблон дня -> задачи в БД (02-MECHANICS.md §1, §5).

Решение по распределению шаблонов на дни недели (не зафиксировано дословно
в спеке, только намёками — "Глубокий, обычно чт", "Рабочий пт-вс"):
пн-ср Учебный, чт Глубокий, пт-сб Рабочий, вс Восстановительный. Меняется
правкой WEEKDAY_TEMPLATE_KIND, задачи не хардкодят день недели."""

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import DayTemplate, Task
from core.events.kinds import EventKind, EventSource
from core.events.log import emit
from core.utils.time import LOCAL_TZ

WEEKDAY_TEMPLATE_KIND: dict[int, str] = {
    0: "study",
    1: "study",
    2: "study",
    3: "deep",
    4: "work",
    5: "work",
    6: "recovery",
}

DEFAULT_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "study": [
        {
            "start": "09:00", "duration": 120, "sphere": "learning",
            "title": "Глубокая работа: учёба", "deep_work": True,
            "importance": 4, "difficulty": 3,
        },
        {
            "start": "18:00", "duration": 60, "sphere": "learning",
            "title": "Практика", "deep_work": False,
            "importance": 3, "difficulty": 2,
        },
    ],
    "work": [
        {
            "start": "19:00", "duration": 90, "sphere": "work",
            "title": "Своё время после смены", "deep_work": False,
            "importance": 3, "difficulty": 2,
        },
    ],
    "deep": [
        {
            "start": "09:00", "duration": 300, "sphere": "learning",
            "title": "Глубокий блок", "deep_work": True,
            "importance": 4, "difficulty": 4,
        },
    ],
    "recovery": [
        {
            "start": "11:00", "duration": 60, "sphere": "sport",
            "title": "Спорт или прогулка", "deep_work": False,
            "importance": 2, "difficulty": 1,
        },
    ],
}


def derive_proof(importance: int, sphere: str, deep_work: bool) -> str:
    """02-MECHANICS.md §1. deep_work приоритетнее importance/sphere: для
    когнитивной работы таймер+отчёт показательнее фото."""
    if deep_work:
        return "report"
    if importance >= 4 or sphere == "sport":
        return "photo"
    if importance == 3:
        return "report"
    return "confirm"


async def seed_default_templates(session: AsyncSession) -> None:
    """Идемпотентно: создаёт только те kind, которых ещё нет. Коммит — на
    совести вызывающего, как и у emit()."""
    existing = set((await session.execute(select(DayTemplate.kind))).scalars().all())
    for kind, blocks in DEFAULT_TEMPLATES.items():
        if kind not in existing:
            session.add(DayTemplate(kind=kind, weekday=None, blocks=blocks))
    await session.flush()


async def get_template_for_weekday(session: AsyncSession, weekday: int) -> DayTemplate | None:
    kind = WEEKDAY_TEMPLATE_KIND.get(weekday)
    if kind is None:
        return None
    result = await session.execute(select(DayTemplate).where(DayTemplate.kind == kind))
    return result.scalars().first()


async def materialize_day(session: AsyncSession, target_date: date, *, force: bool = False) -> list[Task]:
    """Шаблон дня недели -> задачи на target_date.

    Идемпотентно: без force повторный вызов ничего не создаёт, если задачи на
    эту дату уже материализованы (защита от двойного срабатывания cron).
    force=True (ручной /day rebuild) пересоздаёт только нетронутые (status=
    planned) сгенерированные задачи — то, что уже в работе, закрыто или
    провалено, не трогается никогда.
    """
    day_start = datetime.combine(target_date, time.min, tzinfo=LOCAL_TZ)
    day_end = datetime.combine(target_date, time.max, tzinfo=LOCAL_TZ)

    existing = list(
        (
            await session.execute(
                select(Task).where(
                    Task.source == "recurring",
                    Task.planned_start >= day_start,
                    Task.planned_start <= day_end,
                )
            )
        ).scalars()
    )

    if existing and not force:
        return existing

    if force:
        for task in existing:
            if task.status == "planned":
                await session.delete(task)
        await session.flush()

    template = await get_template_for_weekday(session, target_date.weekday())
    if template is None:
        return [] if force else existing

    created: list[Task] = []
    for block in template.blocks:
        importance = block["importance"]
        sphere = block["sphere"]
        deep_work = block.get("deep_work", False)
        task = Task(
            title=block["title"],
            sphere=sphere,
            importance=importance,
            difficulty=block["difficulty"],
            planned_start=datetime.combine(target_date, time.fromisoformat(block["start"]), tzinfo=LOCAL_TZ),
            planned_duration_min=block["duration"],
            deep_work=deep_work,
            proof=derive_proof(importance, sphere, deep_work),
            source="recurring",
        )
        session.add(task)
        await emit(
            session,
            EventKind.TASK_CREATED,
            {
                "title": task.title,
                "sphere": task.sphere,
                "importance": task.importance,
                "planned_start": task.planned_start.isoformat(),
            },
            source=EventSource.SCHEDULER,
            entity_id=task.id,
        )
        created.append(task)

    return created
