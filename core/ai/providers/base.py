"""Базовые структуры данных и протокол для LLM-провайдеров."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMMessage:
    """Сообщение в диалоге с LLM."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ToolCall:
    """Вызов инструмента, запрошенный моделью."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Ответ от LLM-провайдера."""

    content: str | None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    """Протокол для LLM-провайдера (OpenAI-compatible API)."""

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> LLMResponse:
        """Выполнить completion запрос к LLM.

        Args:
            messages: История диалога
            tools: JSON-схемы доступных функций
            max_tokens: Максимум токенов в ответе
            temperature: Температура генерации
            stream: Включить стриминг (пока не реализовано)

        Returns:
            Ответ модели с текстом и/или вызовами инструментов
        """
        ...

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        model: str = "whisper-large-v3-turbo",
    ) -> str:
        """Транскрибировать аудио в текст (STT).

        Args:
            audio_bytes: Байты аудиофайла
            filename: Имя файла (для MIME-type)
            model: Модель для транскрипции

        Returns:
            Распознанный текст
        """
        ...
