"""Универсальный провайдер для OpenAI-compatible API (Groq, Gemini, DeepSeek, OpenRouter, APINET)."""

from __future__ import annotations

import io
from typing import Any

from openai import AsyncOpenAI, Timeout

from core.ai.providers.base import LLMMessage, LLMResponse, ToolCall


class OpenAICompatProvider:
    """Универсальная реализация на базе openai.AsyncOpenAI."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        """Инициализация провайдера.

        Args:
            base_url: Базовый URL API (например, https://api.groq.com/openai/v1)
            api_key: API-ключ провайдера
            timeout: Таймаут запросов в секундах
        """
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=Timeout(timeout, connect=5.0),
        )
        self.timeout = timeout

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        stream: bool = False,
        model: str = "default",
    ) -> LLMResponse:
        """Выполнить completion запрос к LLM.

        Args:
            messages: История диалога
            tools: JSON-схемы доступных функций
            max_tokens: Максимум токенов в ответе
            temperature: Температура генерации
            stream: Включить стриминг (пока игнорируется)
            model: Имя модели

        Returns:
            Ответ модели с текстом и/или вызовами инструментов
        """
        # Преобразуем LLMMessage в формат OpenAI
        openai_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        # Собираем параметры запроса
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if tools:
            kwargs["tools"] = tools

        # Выполняем запрос
        response = await self.client.chat.completions.create(**kwargs)

        # Разбираем ответ
        choice = response.choices[0]
        content = choice.message.content
        finish_reason = choice.finish_reason

        # Извлекаем tool calls, если есть
        tool_calls_data = None
        if choice.message.tool_calls:
            tool_calls_data = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=eval(tc.function.arguments),  # OpenAI возвращает JSON-строку
                )
                for tc in choice.message.tool_calls
            ]

        # Собираем статистику использования
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls_data,
            finish_reason=finish_reason,
            usage=usage,
        )

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
        # Создаем file-like объект из байтов
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        # Вызываем API транскрипции
        transcript = await self.client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )

        return transcript.text
