# Стандарты кода и стека

- **Python 3.12+**: строгая типизация (type hints везде, `from __future__ import annotations` при необходимости).
- **БД и ORM**: SQLAlchemy 2.0 (строго async, `AsyncSession`, `select()`, никаких legacy `.query()`).
- **Telegram Bot**: `aiogram 3.x` (роутеры, фильтрация по `OWNER_ID`, без устаревших паттернов aiogram 2).
- **Отправка ответов ИИ в Telegram**: НЕ использовать частый `edit_message_text` каждые 400 мс (риск FloodWait). Использовать `send_chat_action("typing")` и отправку готового сообщения целиком.
- **Подтверждение задач (Proof)**: фото-верификации нет (EXIF, pHash, Vision — убраны, `docs/12-DECISIONS.md` D6). Уровни `proof`: `none` | `confirm` | `report` (одна фраза о выполнении DoD). Фото можно приложить к отчёту как артефакт, без проверки.
- **Колбэки Telegram**: `callback.answer()` первым делом; повторное нажатие — идемпотентно («Уже отмечено»), без исключений и без новых событий.
- **Зависимости**: единственный источник зависимостей — `pyproject.toml`.
