"""Роутер LLM-запросов: роли → провайдеры, fallback, rate-limiting.

Загружает конфигурацию из roles.yaml и роутит запросы по ролям.
При отказе основного провайдера автоматически переключается на fallback.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import yaml

from core.ai.providers.base import LLMMessage, LLMResponse
from core.ai.providers.openai_compat import OpenAICompatProvider
from core.config import settings


class RateLimiter:
    """In-memory token bucket rate limiter."""

    def __init__(self, requests_per_minute: int, tokens_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self.request_tokens = requests_per_minute
        self.token_tokens = tokens_per_minute
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int = 1000) -> None:
        """Ждать, пока можно будет выполнить запрос."""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill

            # Пополняем токены пропорционально времени
            if elapsed > 0:
                self.request_tokens = min(
                    self.requests_per_minute,
                    self.request_tokens + (self.requests_per_minute * elapsed / 60),
                )
                self.token_tokens = min(
                    self.tokens_per_minute,
                    self.token_tokens + (self.tokens_per_minute * elapsed / 60),
                )
                self.last_refill = now

            # Ждем, если лимит исчерпан
            while self.request_tokens < 1 or self.token_tokens < estimated_tokens:
                await asyncio.sleep(0.5)
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.request_tokens = min(
                    self.requests_per_minute,
                    self.request_tokens + (self.requests_per_minute * elapsed / 60),
                )
                self.token_tokens = min(
                    self.tokens_per_minute,
                    self.token_tokens + (self.tokens_per_minute * elapsed / 60),
                )
                self.last_refill = now

            # Вычитаем токены
            self.request_tokens -= 1
            self.token_tokens -= estimated_tokens


class LLMRouter:
    """Роутер LLM-запросов с поддержкой fallback и rate-limiting."""

    def __init__(self, config_path: Path | None = None):
        """Инициализация роутера.

        Args:
            config_path: Путь к roles.yaml (по умолчанию core/ai/roles.yaml)
        """
        if config_path is None:
            config_path = Path(__file__).parent / "roles.yaml"

        with config_path.open() as f:
            self.config = yaml.safe_load(f)

        self.providers: dict[str, OpenAICompatProvider] = {}
        self.rate_limiters: dict[str, RateLimiter] = {}

        # Инициализируем провайдеры
        for provider_name, provider_config in self.config["providers"].items():
            api_key = self._get_api_key(provider_config)
            if not api_key:
                continue

            base_url = self._get_base_url(provider_config)
            timeout = provider_config.get("timeout", 30)

            self.providers[provider_name] = OpenAICompatProvider(base_url, api_key, timeout)

            # Создаем rate limiter
            rate_limit = provider_config.get("rate_limit", {})
            self.rate_limiters[provider_name] = RateLimiter(
                requests_per_minute=rate_limit.get("requests_per_minute", 60),
                tokens_per_minute=rate_limit.get("tokens_per_minute", 100000),
            )

    def _get_api_key(self, provider_config: dict[str, Any]) -> str | None:
        """Получить API-ключ из настроек."""
        env_var = provider_config.get("api_key_env")
        if not env_var:
            return None
        return getattr(settings, env_var.lower(), None)

    def _get_base_url(self, provider_config: dict[str, Any]) -> str:
        """Получить base_url из конфига или env."""
        if "base_url_env" in provider_config:
            env_var = provider_config["base_url_env"]
            return getattr(settings, env_var.lower(), provider_config.get("base_url", ""))
        return provider_config.get("base_url", "")

    async def complete_for_role(
        self,
        role: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Выполнить completion для указанной роли с fallback.

        Args:
            role: Роль (voice, analyst, planner, researcher, vision, chief)
            messages: История диалога
            tools: JSON-схемы доступных функций

        Returns:
            Ответ модели

        Raises:
            RuntimeError: Если все провайдеры недоступны
        """
        role_config = self.config["roles"].get(role)
        if not role_config:
            raise ValueError(f"Unknown role: {role}")

        # Формируем цепочку провайдеров: основной + fallback
        provider_names = [role_config["provider"]]
        fallback_chain = self.config.get("fallback", {}).get(role, [])
        provider_names.extend(fallback_chain)

        last_error = None

        for provider_name in provider_names:
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            try:
                # Ждем rate limiter
                rate_limiter = self.rate_limiters.get(provider_name)
                if rate_limiter:
                    await rate_limiter.acquire(estimated_tokens=2000)

                # Выполняем запрос
                response = await provider.complete(
                    messages=messages,
                    tools=tools,
                    max_tokens=role_config.get("max_tokens", 2000),
                    temperature=role_config.get("temperature", 0.7),
                    model=role_config.get("model", "default"),
                )
                return response

            except Exception as e:
                last_error = e
                continue

        # Если все провайдеры упали, возвращаем безопасный L0-фоллбэк
        return LLMResponse(
            content="Связь потеряна. План на день в приложении. Работай.",
            tool_calls=None,
            finish_reason="error",
        )

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        role: str = "stt",
    ) -> str:
        """Транскрибировать аудио через провайдер роли STT."""
        role_config = self.config["roles"].get(role, self.config["roles"]["stt"])
        provider_name = role_config["provider"]
        provider = self.providers.get(provider_name)

        if not provider:
            raise RuntimeError(f"Provider {provider_name} not available for STT")

        rate_limiter = self.rate_limiters.get(provider_name)
        if rate_limiter:
            await rate_limiter.acquire(estimated_tokens=500)

        return await provider.transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            model=role_config.get("model", "whisper-large-v3-turbo"),
        )


# Глобальный экземпляр роутера
router = LLMRouter()
