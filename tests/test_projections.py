"""Инвариант 03-DATA-MODEL.md §3.1: пересчёт проекций из events даёт те же
числа, что накопленное инкрементальное состояние — всегда."""

import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import StateCurrent, StateDaily, StateWeekly
from core.events.kinds import EventKind, EventSource
from core.events.log import emit
from core.events.projections import rebuild

SPHERES = ["sport", "social", "novelty", "learning"]
MODES = ["normal", "pressure", "yellow", "red"]


def _random_events(n: int, base_date: date, seed: int = 42) -> list[tuple[EventKind, dict, datetime]]:
    rng = random.Random(seed)
    events = []
    for _ in range(n):
        day = base_date + timedelta(days=rng.randint(0, 27))
        at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=rng.randint(6, 23))
        kind = rng.choice(
            [
                EventKind.XP_AWARDED,
                EventKind.HP_CHANGED,
                EventKind.SLEEP_RECORDED,
                EventKind.FOCUS_SESSION,
                EventKind.MODE_CHANGED,
                EventKind.QUOTA_MET,
                EventKind.QUOTA_MISSED,
            ]
        )
        if kind == EventKind.XP_AWARDED:
            payload = {"amount": rng.randint(1, 40), "reason": "test"}
        elif kind == EventKind.HP_CHANGED:
            payload = {"amount": rng.randint(-20, 10), "reason": "test"}
        elif kind == EventKind.SLEEP_RECORDED:
            payload = {"duration_min": rng.randint(300, 540)}
        elif kind == EventKind.FOCUS_SESSION:
            payload = {"duration_min": rng.randint(15, 120), "task_id": None, "interruptions": rng.randint(0, 3)}
        elif kind == EventKind.MODE_CHANGED:
            payload = {"from": "normal", "to": rng.choice(MODES)}
        else:
            payload = {"sphere": rng.choice(SPHERES), "target": 3, "actual": rng.randint(0, 3)}
        events.append((kind, payload, at))
    return events


async def _snapshot(session: AsyncSession):
    daily = (await session.execute(select(StateDaily).order_by(StateDaily.local_date))).scalars().all()
    weekly = (await session.execute(select(StateWeekly).order_by(StateWeekly.week_start))).scalars().all()
    current = await session.get(StateCurrent, 1)
    return (
        [(d.local_date, d.xp, d.hp_end, d.sleep_min, d.deep_minutes, d.mode) for d in daily],
        [(w.week_start, w.deep_min, w.quotas) for w in weekly],
        (current.xp_total, current.hp, current.mode) if current else None,
    )


async def test_rebuild_matches_incremental(session: AsyncSession):
    base_date = date(2026, 1, 5)  # понедельник

    for kind, payload, at in _random_events(500, base_date):
        await emit(session, kind, payload, source=EventSource.SCHEDULER, at=at)
    await session.flush()

    incremental = await _snapshot(session)

    await rebuild(session)

    rebuilt = await _snapshot(session)

    assert incremental == rebuilt


async def test_hp_stays_in_bounds(session: AsyncSession):
    base_date = date(2026, 1, 5)

    for _ in range(50):
        await emit(
            session,
            EventKind.HP_CHANGED,
            {"amount": -30, "reason": "test"},
            source=EventSource.SCHEDULER,
            at=datetime.combine(base_date, datetime.min.time(), tzinfo=UTC),
        )
    await session.flush()

    current = await session.get(StateCurrent, 1)
    assert current is not None
    assert 0 <= current.hp <= 100
