"""Проекции — производное состояние, пересчитываемое из events (03-DATA-MODEL.md §1).

Здесь только механический перенос уже посчитанных величин в агрегаты
(state_daily/state_current/state_weekly): сколько XP начислено, насколько
изменилось HP, сколько минут сна записано и т.д. Сами формулы (сколько XP
за конкретную задачу, на сколько снять HP за срыв) считает domain/ledger.py
(шаг 1.5) — он решает "сколько" и эмитит xp_awarded/hp_changed с готовой
payload.amount. apply() эту цифру только раскладывает по проекциям.
"""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Event, StateCurrent, StateDaily, StateWeekly
from core.events.kinds import EventKind

Handler = Callable[[AsyncSession, Event], Awaitable[None]]


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _get_or_create_state_current(session: AsyncSession) -> StateCurrent:
    state = await session.get(StateCurrent, 1)
    if state is None:
        # Поля выставлены явно, а не оставлены на ORM default= — так надёжнее:
        # не зависим от того, когда именно SQLAlchemy проставит клиентский default
        # на атрибут (до/после flush), а сразу после создания делаем += на них.
        state = StateCurrent(id=1, xp_total=0, level=1, hp=100, streak_days=0, mode="normal")
        session.add(state)
        await session.flush()
    return state


async def _get_or_create_state_daily(session: AsyncSession, local_date: date) -> StateDaily:
    state = await session.get(StateDaily, local_date)
    if state is None:
        state = StateDaily(local_date=local_date, deep_minutes=0, xp=0)
        session.add(state)
        await session.flush()
    return state


async def _get_or_create_state_weekly(session: AsyncSession, week_start: date) -> StateWeekly:
    state = await session.get(StateWeekly, week_start)
    if state is None:
        state = StateWeekly(week_start=week_start, budget_used_min=0, deep_min=0, quotas={}, expenses={})
        session.add(state)
        await session.flush()
    return state


async def _apply_xp_awarded(session: AsyncSession, event: Event) -> None:
    amount = int(event.payload["amount"])
    current = await _get_or_create_state_current(session)
    current.xp_total += amount
    daily = await _get_or_create_state_daily(session, event.local_date)
    daily.xp += amount


async def _apply_hp_changed(session: AsyncSession, event: Event) -> None:
    amount = int(event.payload["amount"])
    current = await _get_or_create_state_current(session)
    current.hp = max(0, min(100, current.hp + amount))
    daily = await _get_or_create_state_daily(session, event.local_date)
    daily.hp_end = current.hp


async def _apply_mode_changed(session: AsyncSession, event: Event) -> None:
    mode = event.payload["to"]
    current = await _get_or_create_state_current(session)
    current.mode = mode
    daily = await _get_or_create_state_daily(session, event.local_date)
    daily.mode = mode


async def _apply_sleep_recorded(session: AsyncSession, event: Event) -> None:
    daily = await _get_or_create_state_daily(session, event.local_date)
    daily.sleep_min = int(event.payload["duration_min"])


async def _apply_focus_session(session: AsyncSession, event: Event) -> None:
    minutes = int(event.payload.get("duration_min", 0))
    daily = await _get_or_create_state_daily(session, event.local_date)
    daily.deep_minutes += minutes
    weekly = await _get_or_create_state_weekly(session, _week_start(event.local_date))
    weekly.deep_min += minutes


async def _apply_quota(session: AsyncSession, event: Event) -> None:
    sphere = event.payload["sphere"]
    weekly = await _get_or_create_state_weekly(session, _week_start(event.local_date))
    quotas: dict[str, Any] = dict(weekly.quotas or {})
    entry = dict(quotas.get(sphere, {}))
    if "target" in event.payload:
        entry["target"] = event.payload["target"]
    entry["actual"] = event.payload.get("actual", entry.get("actual", 0))
    quotas[sphere] = entry
    weekly.quotas = quotas  # переприсвоение, не мутация — иначе SQLAlchemy не увидит изменение JSONB


HANDLERS: dict[EventKind, Handler] = {
    EventKind.XP_AWARDED: _apply_xp_awarded,
    EventKind.HP_CHANGED: _apply_hp_changed,
    EventKind.MODE_CHANGED: _apply_mode_changed,
    EventKind.SLEEP_RECORDED: _apply_sleep_recorded,
    EventKind.FOCUS_SESSION: _apply_focus_session,
    EventKind.QUOTA_MET: _apply_quota,
    EventKind.QUOTA_MISSED: _apply_quota,
}


async def apply(session: AsyncSession, event: Event) -> None:
    """Инкрементально применяет одно событие к проекциям. Кинды без обработчика
    (task_*, proof_*, expense_logged и т.д.) проекции пока не трогают — это
    домен следующих шагов (ledger/quotas/debt), и rebuild() ниже это учитывает
    ровно так же, событие за событием."""
    handler = HANDLERS.get(EventKind(event.kind))
    if handler is not None:
        await handler(session, event)


async def rebuild(session: AsyncSession) -> None:
    """Полный пересчёт проекций из лога. Источник истины — events, не текущее
    состояние проекций. Инвариант: rebuild() после N инкрементальных apply()
    даёт то же самое состояние (проверяется тестом)."""
    await session.execute(delete(StateDaily))
    await session.execute(delete(StateWeekly))
    await session.execute(delete(StateCurrent))
    await session.flush()

    result = await session.execute(select(Event).order_by(Event.id))
    for event in result.scalars():
        await apply(session, event)
    await session.flush()
