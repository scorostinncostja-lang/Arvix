"""Хендлер вечернего разбора (Ритуал Debrief)."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.ai.constitution.loader import build_system_prompt
from core.ai.context import build_context_packet
from core.ai.providers.base import LLMMessage
from core.ai.router import router as llm_router
from core.config import settings
from core.db.models import Profile, StateCurrent, StateDaily
from core.db.session import async_session_factory
from core.events.kinds import EventKind, EventSource
from core.events.log import emit
from core.utils.time import today_local

router = Router()


@router.message(Command("debrief"))
async def handle_debrief(message: Message) -> None:
    """Команда /debrief: вечерний разбор дня."""
    if message.from_user is None or message.from_user.id != settings.owner_id:
        return

    await message.answer("Готовлю разбор дня...")

    async with async_session_factory() as session:
        # Получаем данные
        profile = await session.get(Profile, 1)
        state = await session.get(StateCurrent, 1)
        today = today_local()
        daily = await session.get(StateDaily, today)

        mode = state.mode if state else "normal"
        mentor_enabled = profile.mentor_enabled if profile else True

        # Собираем контекст
        context = await build_context_packet(session)

        # Системный промпт
        system_prompt = build_system_prompt(mode=mode, mentor_enabled=mentor_enabled)

        # Формируем запрос на разбор
        debrief_prompt = (
            "Проведи вечерний разбор дня. Сводка фактов:\n"
            f"- Дата: {today}\n"
            f"- Выполнение: {daily.completion_pct if daily else 0}%\n"
            f"- XP за день: {daily.xp if daily else 0}\n"
            f"- Глубокая работа: {daily.deep_minutes if daily else 0} мин\n"
            f"- HP на конец дня: {daily.hp_end if daily else 100}/100\n\n"
            "Задай 2 коротких вопроса по итогам дня для понимания, что сработало и что нет."
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="system", content=f"КОНТЕКСТ:\n{context}"),
            LLMMessage(role="user", content=debrief_prompt),
        ]

        # Вызываем модель
        response = await llm_router.complete_for_role(
            role="voice",
            messages=messages,
            tools=None,
        )

        if response.content:
            await message.answer(response.content)

            # Записываем событие разбора
            await emit(
                session,
                EventKind.DEBRIEF_COMPLETED,
                {"date": str(today), "summary": response.content[:500]},
                source=EventSource.BOT,
            )


async def scheduled_debrief() -> None:
    """Автоматический вечерний разбор в 22:30 (вызывается из scheduler)."""
    async with async_session_factory() as session:
        profile = await session.get(Profile, 1)
        state = await session.get(StateCurrent, 1)
        today = today_local()
        daily = await session.get(StateDaily, today)

        mode = state.mode if state else "normal"
        mentor_enabled = profile.mentor_enabled if profile else True

        context = await build_context_packet(session)
        system_prompt = build_system_prompt(mode=mode, mentor_enabled=mentor_enabled)

        debrief_prompt = (
            "Вечерний разбор. Факты:\n"
            f"- Дата: {today}\n"
            f"- Выполнение: {daily.completion_pct if daily else 0}%\n"
            f"- XP: {daily.xp if daily else 0}\n"
            f"- Глубокая работа: {daily.deep_minutes if daily else 0} мин\n"
            f"- HP: {daily.hp_end if daily else 100}/100\n\n"
            "Дай краткую оценку дня (2-3 предложения) и задай 2 вопроса."
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="system", content=f"КОНТЕКСТ:\n{context}"),
            LLMMessage(role="user", content=debrief_prompt),
        ]

        response = await llm_router.complete_for_role(
            role="voice",
            messages=messages,
            tools=None,
        )

        if response.content:
            from core.bot.instance import bot

            await bot.send_message(settings.owner_id, f"📊 Разбор дня\n\n{response.content}")

            await emit(
                session,
                EventKind.DEBRIEF_COMPLETED,
                {"date": str(today), "summary": response.content[:500]},
                source=EventSource.SCHEDULER,
            )
            await session.commit()


async def morning_brief() -> None:
    """Утренний брифинг: L0-шаблон + короткая фраза от модели."""
    from core.bot.instance import bot

    async with async_session_factory() as session:
        profile = await session.get(Profile, 1)
        state = await session.get(StateCurrent, 1)

        mode = state.mode if state else "normal"
        mentor_enabled = profile.mentor_enabled if profile else True

        # L0-шаблон утреннего брифинга
        mode_emoji = {"normal": "🟢", "yellow": "🟡", "red": "🟥"}.get(mode, "⚪")
        brief_text = (
            f"{mode_emoji} Режим: {mode.upper()}\n"
            f"HP: {state.hp if state else 100}/100\n"
            f"Стрик: {state.streak_days if state else 0} дней"
        )

        # Короткая фраза от модели
        context = await build_context_packet(session)
        system_prompt = build_system_prompt(mode=mode, mentor_enabled=mentor_enabled)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="system", content=f"КОНТЕКСТ:\n{context}"),
            LLMMessage(
                role="user",
                content="Доброе утро. Дай одну короткую фразу-установку на день (до 20 слов).",
            ),
        ]

        response = await llm_router.complete_for_role(
            role="voice",
            messages=messages,
            tools=None,
        )

        final_text = brief_text
        if response.content:
            final_text += f"\n\n💬 {response.content}"

        await bot.send_message(settings.owner_id, final_text)

