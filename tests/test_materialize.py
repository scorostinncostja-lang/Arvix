"""materialize_day — 02-MECHANICS.md §1, §5: шаблон дня недели -> задачи."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Task
from core.scheduler.materialize import derive_proof, materialize_day, seed_default_templates

MONDAY = date(2026, 1, 5)  # weekday() == 0 -> study


async def test_materialize_creates_tasks_from_template(session: AsyncSession):
    await seed_default_templates(session)

    tasks = await materialize_day(session, MONDAY)

    assert {t.title for t in tasks} == {"Глубокая работа: учёба", "Практика"}
    assert all(t.source == "recurring" for t in tasks)


async def test_materialize_is_idempotent_without_force(session: AsyncSession):
    await seed_default_templates(session)

    first = await materialize_day(session, MONDAY)
    await session.flush()
    second = await materialize_day(session, MONDAY)

    assert {t.id for t in first} == {t.id for t in second}

    rows = (await session.execute(select(Task).where(Task.source == "recurring"))).scalars().all()
    assert len(rows) == len(first)


async def test_force_rebuild_keeps_non_planned_tasks(session: AsyncSession):
    await seed_default_templates(session)

    tasks = await materialize_day(session, MONDAY)
    await session.flush()

    done_task = tasks[0]
    done_task.status = "done"
    await session.flush()

    rebuilt = await materialize_day(session, MONDAY, force=True)
    await session.flush()

    remaining = (await session.execute(select(Task).where(Task.source == "recurring"))).scalars().all()
    remaining_ids = {t.id for t in remaining}

    assert done_task.id in remaining_ids
    assert len(remaining) == 1 + len(rebuilt)


def test_derive_proof_prioritizes_deep_work_over_importance():
    assert derive_proof(importance=5, sphere="sport", deep_work=True) == "report"


def test_derive_proof_photo_for_high_importance_or_sport():
    assert derive_proof(importance=5, sphere="learning", deep_work=False) == "photo"
    assert derive_proof(importance=2, sphere="sport", deep_work=False) == "photo"


def test_derive_proof_report_for_importance_three():
    assert derive_proof(importance=3, sphere="learning", deep_work=False) == "report"


def test_derive_proof_confirm_for_low_importance():
    assert derive_proof(importance=1, sphere="learning", deep_work=False) == "confirm"
