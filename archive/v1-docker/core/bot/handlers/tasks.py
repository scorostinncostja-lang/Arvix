"""Обработчики команд и callback'ов для задач (05-BOT-TWA.md §3.2, §4)."""

import uuid
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from core.bot.keyboards import completion_check_keyboard
from core.bot.states import TaskProofStates
from core.bot.templates import (
    ask_for_partial_report,
    ask_for_report,
    task_completed_message,
    task_deferred_message,
    task_failed_message,
    task_started_message,
)
from core.db.session import async_session_factory
from core.domain import tasks as domain_tasks
from core.scheduler.jobs import schedule_task_reminders, scheduler
from core.utils.time import LOCAL_TZ, today_local

router = Router(name="tasks")


# --- Команды ---


@router.message(Command("add"))
async def cmd_add_task(message: Message) -> None:
    """Быстрое добавление задачи текстом. Пока простейший парсинг: /add <название>"""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /add <название задачи>")
        return

    title = parts[1].strip()
    # Упрощенные дефолты для Фазы 0
    planned_start = datetime.now(LOCAL_TZ).replace(second=0, microsecond=0)
    
    async with async_session_factory() as session:
        task = await domain_tasks.create_task(
            session,
            title=title,
            sphere="learning",
            importance=3,
            difficulty=3,
            planned_start=planned_start,
            planned_duration_min=60,
            deep_work=False,
            source="user",
        )
        await session.commit()
        # Планируем напоминания
        schedule_task_reminders(scheduler, task)

    await message.answer(f"✅ Задача добавлена: {title}")


@router.message(Command("done"))
async def cmd_done(message: Message) -> None:
    """Показать активные/сегодняшние задачи для быстрого закрытия."""
    today = today_local()
    async with async_session_factory() as session:
        tasks = await domain_tasks.get_day_tasks(session, today)

    active_tasks = [t for t in tasks if t.status in ("planned", "active")]
    if not active_tasks:
        await message.answer("Нет активных задач на сегодня.")
        return

    lines = ["Задачи на закрытие:"]
    for task in active_tasks:
        status_emoji = "▶️" if task.status == "active" else "⏱"
        lines.append(f"{status_emoji} {task.title}")

    # Отправляем с кнопками для первой задачи (упрощенная версия для Фазы 0)
    text = "\n".join(lines)
    if active_tasks:
        keyboard = completion_check_keyboard(str(active_tasks[0].id), active_tasks[0].proof)
        await message.answer(text, reply_markup=keyboard)
    else:
        await message.answer(text)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Показать текущие XP, HP, уровень, стрик и выполнение за сегодня."""
    from core.db.models import StateCurrent, StateDaily

    today = today_local()
    async with async_session_factory() as session:
        current = await session.get(StateCurrent, 1)
        daily = await session.get(StateDaily, today)

    if not current:
        await message.answer("Статистика еще не инициализирована.")
        return

    lines = [
        "📊 Статус:",
        f"Уровень: {current.level}",
        f"XP: {current.xp_total}",
        f"HP: {current.hp}/100",
        f"Стрик: {current.streak_days} дней",
        f"Режим: {current.mode.upper()}",
    ]

    if daily:
        completion = daily.completion_pct or 0
        lines.append(f"\nСегодня: {completion}% выполнено")
        lines.append(f"Глубокая работа: {daily.deep_minutes} мин")
        if daily.xp:
            lines.append(f"XP за день: {daily.xp}")

    await message.answer("\n".join(lines))


# --- Callback-хендлеры для кнопок напоминаний ---


@router.callback_query(F.data.startswith("task_start:"))
async def cb_task_start(callback: CallbackQuery) -> None:
    """Нажатие [▶️ Начать сейчас] → start_task(), убрать кнопки."""
    task_id = uuid.UUID(callback.data.split(":", 1)[1])
    
    async with async_session_factory() as session:
        task = await domain_tasks.start_task(session, task_id, source="user")
        await session.commit()

    await callback.message.edit_text(task_started_message(task.title), reply_markup=None)
    await callback.answer()


@router.callback_query(F.data.startswith("task_defer:"))
async def cb_task_defer(callback: CallbackQuery) -> None:
    """Нажатие [⏳ +15 мин] → defer_task(), перепланировать job'ы."""
    task_id = uuid.UUID(callback.data.split(":", 1)[1])
    
    async with async_session_factory() as session:
        task = await domain_tasks.defer_task(session, task_id, minutes=15, source="user")
        await session.commit()
        
        # Перепланируем напоминания
        schedule_task_reminders(scheduler, task)

    new_time = task.planned_start.strftime("%H:%M")
    await callback.message.edit_text(
        task_deferred_message(task.title, new_time),
        reply_markup=None
    )
    await callback.answer()


@router.callback_query(F.data.startswith("task_fail:"))
async def cb_task_fail(callback: CallbackQuery) -> None:
    """Нажатие [❌ Не смогу] / [❌ Нет] → fail_task()."""
    task_id = uuid.UUID(callback.data.split(":", 1)[1])
    
    async with async_session_factory() as session:
        task = await domain_tasks.fail_task(session, task_id, source="user")
        await session.commit()

    # Рассчитываем урон HP для отображения
    hp_damage = domain_tasks.HP_DAMAGE.get(task.importance, -5)
    is_debt = task.status == "debt"
    
    await callback.message.edit_text(
        task_failed_message(task.title, hp_damage, is_debt),
        reply_markup=None
    )
    await callback.answer()


@router.callback_query(F.data.startswith("task_done:"))
async def cb_task_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Нажатие [✅ Да] → проверить proof, либо сразу закрыть, либо запросить отчет."""
    parts = callback.data.split(":")
    task_id = uuid.UUID(parts[1])
    proof = parts[2]
    
    if proof == "confirm":
        # Простое подтверждение — сразу закрываем
        async with async_session_factory() as session:
            task = await domain_tasks.complete_task(
                session, task_id, quality=5, proof_kind="confirm", source="user"
            )
            await session.commit()
            
            # Получаем начисленный XP из payload события
            xp = domain_tasks._calculate_xp(task)

        await callback.message.edit_text(
            task_completed_message(task.title, xp),
            reply_markup=None
        )
        await callback.answer()
    else:
        # report или photo — переводим в FSM
        await state.update_data(task_id=str(task_id), proof=proof)
        await state.set_state(TaskProofStates.waiting_for_report)
        await callback.message.edit_text(ask_for_report(), reply_markup=None)
        await callback.answer()


@router.callback_query(F.data.startswith("task_partial:"))
async def cb_task_partial(callback: CallbackQuery, state: FSMContext) -> None:
    """Нажатие [⚠️ Частично] → запросить отчет о частичном выполнении."""
    task_id = uuid.UUID(callback.data.split(":", 1)[1])
    
    await state.update_data(task_id=str(task_id))
    await state.set_state(TaskProofStates.waiting_for_partial)
    await callback.message.edit_text(ask_for_partial_report(), reply_markup=None)
    await callback.answer()


# --- FSM-хендлеры для отчетов ---


@router.message(TaskProofStates.waiting_for_report)
async def handle_report(message: Message, state: FSMContext) -> None:
    """Получен текстовый отчет о выполнении → закрыть задачу."""
    data = await state.get_data()
    task_id = uuid.UUID(data["task_id"])
    report_text = message.text or ""
    
    async with async_session_factory() as session:
        task = await domain_tasks.complete_task(
            session,
            task_id,
            quality=5,
            proof_kind=data.get("proof", "report"),
            report_text=report_text,
            source="user",
        )
        await session.commit()
        
        xp = domain_tasks._calculate_xp(task)

    await message.answer(task_completed_message(task.title, xp))
    await state.clear()


@router.message(TaskProofStates.waiting_for_partial)
async def handle_partial_report(message: Message, state: FSMContext) -> None:
    """Получен отчет о частичном выполнении → закрыть с quality=3."""
    data = await state.get_data()
    task_id = uuid.UUID(data["task_id"])
    report_text = message.text or ""
    
    async with async_session_factory() as session:
        task = await domain_tasks.complete_task(
            session,
            task_id,
            quality=3,
            proof_kind="report",
            report_text=report_text,
            source="user",
        )
        await session.commit()
        
        xp = domain_tasks._calculate_xp(task)
        # quality=3 снижает XP
        xp = int(xp * 3 / 5)

    await message.answer(task_completed_message(task.title, xp))
    await state.clear()



