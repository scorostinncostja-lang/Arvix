"""Хендлер свободных сообщений и голосового ввода (L1 Voice)."""

from aiogram import F, Router
from aiogram.types import Message

from core.ai.constitution.loader import build_system_prompt
from core.ai.context import build_context_packet
from core.ai.privacy import scrub_pii
from core.ai.providers.base import LLMMessage
from core.ai.router import router as llm_router
from core.ai.tools.executor import execute_tool
from core.ai.tools.schemas import ALL_TOOLS
from core.bot.instance import bot
from core.config import settings
from core.db.models import Profile, StateCurrent
from core.db.session import async_session_factory
from core.events.kinds import EventKind, EventSource
from core.events.log import emit

router = Router()


@router.message(F.voice)
async def handle_voice(message: Message) -> None:
    """Обработать голосовое сообщение: распознать через STT и передать в L1."""
    if message.from_user is None or message.from_user.id != settings.owner_id:
        return

    # Скачиваем аудио
    voice = message.voice
    if not voice:
        return

    file = await bot.get_file(voice.file_id)
    if not file.file_path:
        return

    audio_bytes = await bot.download_file(file.file_path)
    if not audio_bytes:
        return

    # Транскрибируем через Groq Whisper
    try:
        text = await llm_router.transcribe(
            audio_bytes=audio_bytes.read(),
            filename="voice.ogg",
        )
    except Exception:
        await message.answer("Не удалось распознать голос. Попробуй еще раз.")
        return

    # Записываем событие входящего сообщения
    async with async_session_factory() as session:
        await emit(
            session,
            EventKind.MESSAGE_IN,
            {"text": text, "from": "voice"},
            source=EventSource.USER,
        )
        await session.commit()

    # Обрабатываем распознанный текст как обычное сообщение
    await _process_freeform_text(message, text)


@router.message(F.text)
async def handle_text(message: Message) -> None:
    """Обработать текстовое сообщение (не команду)."""
    if message.from_user is None or message.from_user.id != settings.owner_id:
        return

    if not message.text or message.text.startswith("/"):
        return

    # Записываем событие входящего сообщения
    async with async_session_factory() as session:
        await emit(
            session,
            EventKind.MESSAGE_IN,
            {"text": message.text},
            source=EventSource.USER,
        )
        await session.commit()

    await _process_freeform_text(message, message.text)


async def _process_freeform_text(message: Message, text: str) -> None:
    """Обработать свободный текст через L1 Voice."""
    # Отправляем typing action
    await bot.send_chat_action(message.chat.id, "typing")

    async with async_session_factory() as session:
        # Получаем профиль и состояние
        profile = await session.get(Profile, 1)
        state = await session.get(StateCurrent, 1)

        mode = state.mode if state else "normal"
        mentor_enabled = profile.mentor_enabled if profile else True

        # Собираем системный промпт
        system_prompt = build_system_prompt(mode=mode, mentor_enabled=mentor_enabled)

        # Собираем контекст-пакет
        context = await build_context_packet(session)

        # Фильтруем приватные данные
        safe_text = scrub_pii(text)

        # Формируем сообщения для модели
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="system", content=f"КОНТЕКСТ:\n{context}"),
            LLMMessage(role="user", content=safe_text),
        ]

        # Вызываем L1 Voice (максимум 2 круга tool calls)
        tool_iterations = 0
        max_iterations = 2

        while tool_iterations < max_iterations:
            response = await llm_router.complete_for_role(
                role="voice",
                messages=messages,
                tools=ALL_TOOLS,
            )

            # Если есть tool calls, выполняем их
            if response.tool_calls:
                tool_iterations += 1

                # Выполняем все tool calls
                tool_results = []
                for tc in response.tool_calls:
                    result = await execute_tool(session, tc.name, tc.arguments)
                    tool_results.append(result)

                # Добавляем результаты в историю
                messages.append(LLMMessage(role="assistant", content=response.content or ""))
                for i, tc in enumerate(response.tool_calls):
                    messages.append(
                        LLMMessage(
                            role="user",
                            content=f"Результат {tc.name}: {tool_results[i]}",
                        )
                    )

                # Коммитим изменения после выполнения инструментов
                await session.commit()

                # Продолжаем цикл для следующей итерации
                continue

            # Нет tool calls — отправляем ответ
            if response.content:
                await message.answer(response.content)

                # Записываем событие исходящего сообщения
                await emit(
                    session,
                    EventKind.MESSAGE_OUT,
                    {"text": response.content},
                    source=EventSource.BOT,
                )
                await session.commit()

            break
