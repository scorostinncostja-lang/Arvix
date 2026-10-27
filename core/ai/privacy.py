"""Фильтр приватности перед отправкой в LLM (01-ARCHITECTURE.md §5).

Маскирует банковские карты, API-токены, пароли и телефоны по регулярным выражениям.
"""

import re

# Паттерны для распознавания чувствительных данных
PATTERNS = [
    # Банковские карты (16 цифр с опциональными пробелами/дефисами)
    (re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"), "[CARD]"),
    # API-ключи OpenAI, Anthropic, Groq и подобные (включая sk-proj-...)
    (re.compile(r"\b[sa]k-[a-zA-Z0-9\-]{20,}\b"), "[API_KEY]"),
    (re.compile(r"\bgsk_[a-zA-Z0-9]{20,}\b"), "[API_KEY]"),
    # Bearer токены
    (re.compile(r"\bBearer\s+[a-zA-Z0-9\-_\.]+\b", re.IGNORECASE), "Bearer [TOKEN]"),
    # Пароли в очевидных контекстах (password=..., pwd:..., pass: ...)
    (
        re.compile(r"(?:password|pwd|pass|passwd)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
        "password=[REDACTED]",
    ),
    # Номера телефонов (международный формат и локальные)
    (re.compile(r"\+?\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{2,4}"), "[PHONE]"),
]


def scrub_pii(text: str) -> str:
    """Маскирует чувствительные данные в тексте перед отправкой в LLM.

    Args:
        text: Исходный текст (может содержать пароли, карты, токены)

    Returns:
        Текст с замаскированными чувствительными данными
    """
    result = text
    for pattern, replacement in PATTERNS:
        result = pattern.sub(replacement, result)
    return result
