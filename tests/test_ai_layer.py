"""Тесты для ИИ-слоя L1 (Шаги 0.8 и 0.9).

Проверяем критические инварианты:
1. RED mode и mentor_enabled=False исключают жёсткие тон-блоки
2. Fallback при отказе провайдера
3. Сборка контекста
4. Фильтр PII
"""

from unittest.mock import AsyncMock, patch

import pytest

from core.ai.constitution.loader import build_system_prompt
from core.ai.context import build_context_packet
from core.ai.privacy import scrub_pii
from core.ai.providers.base import LLMMessage, LLMResponse
from core.ai.router import LLMRouter
from core.db.models import Profile, StateCurrent, StateDaily, Task
from core.utils.time import now_local, today_local


@pytest.mark.asyncio
async def test_red_mode_excludes_harsh_tone(async_session):
    """КРИТИЧЕСКИЙ ИНВАРИАНТ: при mode=RED жёсткие тон-блоки физически исключены."""
    profile = Profile(id=1, mentor_enabled=True)
    state = StateCurrent(id=1, mode="red", hp=50)
    async_session.add(profile)
    async_session.add(state)
    await async_session.commit()

    prompt_red = build_system_prompt(mode="red", mentor_enabled=True)

    # Проверяем, что жёсткие фразы из norm/pressure отсутствуют
    assert "провал" not in prompt_red.lower()
    assert "слил" not in prompt_red.lower()
    assert "саботаж" not in prompt_red.lower()

    # Проверяем, что есть мягкий тон
    assert "мягкий" in prompt_red.lower() or "поддерживающ" in prompt_red.lower()


@pytest.mark.asyncio
async def test_mentor_disabled_excludes_harsh_tone(async_session):
    """КРИТИЧЕСКИЙ ИНВАРИАНТ: при mentor_enabled=False жёсткие тон-блоки исключены."""
    profile = Profile(id=1, mentor_enabled=False)
    state = StateCurrent(id=1, mode="normal", hp=100)
    async_session.add(profile)
    async_session.add(state)
    await async_session.commit()

    prompt = build_system_prompt(mode="normal", mentor_enabled=False)

    # Проверяем, что жёсткие фразы отсутствуют
    assert "провал" not in prompt.lower()
    assert "требовательн" not in prompt.lower()

    # Проверяем, что включён восстановительный тон
    assert "мягкий" in prompt.lower() or "поддерживающ" in prompt.lower()


@pytest.mark.asyncio
async def test_router_fallback_on_error():
    """Проверка fallback при отказе основного провайдера."""
    with patch("core.ai.router.OpenAICompatProvider") as MockProvider:
        provider1 = AsyncMock()
        provider1.complete.side_effect = Exception("Timeout")

        provider2 = AsyncMock()
        provider2.complete.return_value = LLMResponse(
            content="Fallback работает",
            tool_calls=None,
            finish_reason="stop",
        )

        MockProvider.side_effect = [provider1, provider2]

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = """
providers:
  groq:
    base_url: https://api.groq.com/openai/v1
    api_key_env: GROQ_API_KEY
  gemini:
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    api_key_env: GEMINI_API_KEY
roles:
  voice:
    provider: groq
    model: test-model
    timeout: 3
    temperature: 0.8
    max_tokens: 1200
fallback:
  voice:
    - gemini
"""
            router = LLMRouter()
            router.providers["groq"] = provider1
            router.providers["gemini"] = provider2

            messages = [LLMMessage(role="user", content="Тест")]
            response = await router.complete_for_role("voice", messages)

            assert response.content == "Fallback работает"
            assert provider2.complete.called


@pytest.mark.asyncio
async def test_context_builder_format(async_session):
    """Проверка формата контекст-пакета."""
    profile = Profile(id=1, name="Test User", mentor_enabled=True)
    state = StateCurrent(id=1, mode="normal", hp=85, xp_total=1200, level=3, streak_days=5)
    today = today_local()
    daily = StateDaily(local_date=today, completion_pct=60.0, deep_minutes=120, xp=150)

    async_session.add(profile)
    async_session.add(state)
    async_session.add(daily)
    await async_session.commit()

    context = await build_context_packet(async_session)

    assert "=== Сейчас ===" in context
    assert "=== Режим ===" in context
    assert "NORMAL" in context
    assert "HP: 85/100" in context
    assert "Стрик: 5 дней" in context
    assert "=== Метрики дня ===" in context
    assert "Выполнение: 60" in context


def test_pii_scrubber():
    """Проверка маскирования чувствительных данных."""
    assert "[CARD]" in scrub_pii("Моя карта 4276 1234 5678 9012")
    assert "4276" not in scrub_pii("Моя карта 4276 1234 5678 9012")
    
    assert "[API_KEY]" in scrub_pii("Ключ: sk-proj-abc123def456ghi789")
    assert "sk-proj" not in scrub_pii("Ключ: sk-proj-abc123def456ghi789")
    
    assert "[API_KEY]" in scrub_pii("gsk_1234567890abcdefghij")
    assert "[REDACTED]" in scrub_pii("password: mySecretPass123")
    assert "[PHONE]" in scrub_pii("Мой номер +7 999 123-45-67")
    
    text_clean = "Сегодня сделал все задачи"
    assert scrub_pii(text_clean) == text_clean


@pytest.mark.asyncio
async def test_context_packet_with_tasks(async_session):
    """Проверка контекста с задачами."""
    state = StateCurrent(id=1, mode="normal", hp=100, xp_total=0, level=1, streak_days=0)
    async_session.add(state)

    now = now_local()
    task1 = Task(
        title="Глубокая работа",
        sphere="work",
        importance=4,
        difficulty=3,
        planned_start=now.replace(hour=9, minute=0),
        planned_duration_min=120,
        deep_work=True,
        proof="report",
        status="done",
    )
    task2 = Task(
        title="Тренировка",
        sphere="health",
        importance=3,
        difficulty=2,
        planned_start=now.replace(hour=18, minute=0),
        planned_duration_min=60,
        deep_work=False,
        proof="confirm",
        status="planned",
    )

    async_session.add(task1)
    async_session.add(task2)
    await async_session.commit()

    context = await build_context_packet(async_session)

    assert "=== Задачи сегодня (2) ===" in context
    assert "Глубокая работа" in context
    assert "Тренировка" in context
    assert "✅" in context
    assert "⏳" in context


