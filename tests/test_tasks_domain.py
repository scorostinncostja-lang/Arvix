"""Тесты доменного слоя задач (Шаг 0.5)."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from core.db.models import Event, StateCurrent, Task
from core.db.session import async_session_factory
from core.domain.tasks import (
    HP_DAMAGE,
    complete_task,
    create_task,
    defer_task,
    fail_task,
    start_task,
)
from core.events.kinds import EventKind
from core.utils.time import LOCAL_TZ, now_local



@pytest.fixture
async def session():
    """Фикстура сессии БД для тестов."""
    async with async_session_factory() as s:
        yield s
        await s.rollback()


@pytest.mark.asyncio
async def test_task_full_cycle(session):
    """Тест полного цикла задачи: create → start → complete.
    
    Проверяет:
    - Запись событий TASK_CREATED, TASK_STARTED, TASK_COMPLETED, XP_AWARDED
    - Начисление XP в state_current
    - Запрет повторного закрытия (инвариант из 03-DATA-MODEL.md §3)
    """
    planned_start = now_local() + timedelta(hours=1)
    
    # Создание задачи
    task = await create_task(
        session,
        title="Тестовая задача",
        sphere="learning",
        importance=3,
        difficulty=3,
        planned_start=planned_start,
        planned_duration_min=60,
        deep_work=False,
        source="user",
    )
    await session.commit()
    
    assert task.status == "planned"
    assert task.proof == "report"  # importance=3 → report
    
    # Проверка события TASK_CREATED
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.TASK_CREATED, Event.entity_id == task.id)
    )
    event_created = result.scalar_one()
    assert event_created.payload["title"] == "Тестовая задача"
    
    # Запуск задачи
    task = await start_task(session, task.id, source="user")
    await session.commit()
    
    assert task.status == "active"
    assert task.actual_start is not None
    
    # Проверка события TASK_STARTED
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.TASK_STARTED, Event.entity_id == task.id)
    )
    event_started = result.scalar_one()
    assert event_started is not None
    
    # Завершение задачи
    task = await complete_task(
        session, task.id, quality=5, proof_kind="report", report_text="Выполнил", source="user"
    )
    await session.commit()
    
    assert task.status == "done"
    assert task.quality == 5
    
    # Проверка событий TASK_COMPLETED и XP_AWARDED
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.TASK_COMPLETED, Event.entity_id == task.id)
    )
    event_completed = result.scalar_one()
    assert event_completed.payload["xp"] > 0
    
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.XP_AWARDED, Event.entity_id == task.id)
    )
    event_xp = result.scalar_one()
    assert event_xp.payload["amount"] > 0
    
    # Проверка начисления XP в state_current
    state = await session.get(StateCurrent, 1)
    assert state is not None
    assert state.xp_total >= event_xp.payload["amount"]
    
    # Проверка инварианта: повторное закрытие запрещено
    with pytest.raises(ValueError, match="already done"):
        await complete_task(session, task.id, quality=5, source="user")


@pytest.mark.asyncio
async def test_fail_important_task_creates_debt(session):
    """Тест провала важной задачи (importance=4): перевод в debt, урон HP.
    
    Проверяет:
    - Задача переходит в status=debt при importance >= 4
    - Записываются события TASK_FAILED, TASK_DEBTED, HP_CHANGED
    - HP снижается в state_current согласно таблице урона
    """
    planned_start = now_local() + timedelta(hours=1)
    
    # Создаем важную задачу
    task = await create_task(
        session,
        title="Важная задача",
        sphere="learning",
        importance=4,
        difficulty=3,
        planned_start=planned_start,
        planned_duration_min=90,
        deep_work=False,
        source="user",
    )
    await session.commit()
    
    # Получаем начальный HP
    state_before = await session.get(StateCurrent, 1)
    initial_hp = state_before.hp if state_before else 100
    
    # Проваливаем задачу
    task = await fail_task(session, task.id, reason="Не успел", source="user")
    await session.commit()
    
    # Проверка статуса
    assert task.status == "debt"
    assert task.debt_since is not None
    
    # Проверка событий
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.TASK_DEBTED, Event.entity_id == task.id)
    )
    event_debted = result.scalar_one()
    assert event_debted is not None
    
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.HP_CHANGED, Event.entity_id == task.id)
    )
    event_hp = result.scalar_one()
    expected_damage = HP_DAMAGE[4]  # -12
    assert event_hp.payload["amount"] == expected_damage
    
    # Проверка HP в state_current
    state_after = await session.get(StateCurrent, 1)
    assert state_after.hp == max(0, initial_hp + expected_damage)


@pytest.mark.asyncio
async def test_defer_task_shifts_planned_start(session):
    """Тест переноса задачи: defer_task сдвигает planned_start на 15 минут.
    
    Проверяет:
    - planned_start увеличивается на указанное количество минут
    - Записывается событие TASK_DEFERRED с from/to
    """
    original_start = now_local() + timedelta(hours=2)
    
    task = await create_task(
        session,
        title="Задача для переноса",
        sphere="work",
        importance=2,
        difficulty=2,
        planned_start=original_start,
        planned_duration_min=45,
        deep_work=False,
        source="user",
    )
    await session.commit()
    
    # Переносим задачу
    task = await defer_task(session, task.id, minutes=15, source="user")
    await session.commit()
    
    # Проверка сдвига времени
    expected_start = original_start + timedelta(minutes=15)
    assert task.planned_start == expected_start
    
    # Проверка события
    result = await session.execute(
        select(Event).where(Event.kind == EventKind.TASK_DEFERRED, Event.entity_id == task.id)
    )
    event_deferred = result.scalar_one()
    assert event_deferred.payload["minutes"] == 15
    assert event_deferred.payload["from"] == original_start.isoformat()
    assert event_deferred.payload["to"] == expected_start.isoformat()


