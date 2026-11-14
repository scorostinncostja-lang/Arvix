# Стандарты кода и стека

- **Python 3.12+**: строгая типизация (type hints везде, `from __future__ import annotations` при необходимости).
- **БД и ORM**: SQLAlchemy 2.0 (строго async, `AsyncSession`, `select()`, никаких legacy `.query()`).
- **Telegram Bot**: `aiogram 3.x` (роутеры, фильтрация по `OWNER_ID`, без устаревших паттернов aiogram 2).
- **Отправка ответов ИИ в Telegram**: НЕ использовать частый `edit_message_text` каждые 400 мс (риск FloodWait). Использовать `send_chat_action("typing")` и отправку готового сообщения целиком.
- **Проверка фото (Proof)**: НЕ проверять EXIF в фото из Telegram (Telegram стирает EXIF). Проверять время прихода сообщения + перцептивный хэш (pHash) + Vision-модель.
- **Зависимости**: единственный источник зависимостей — `pyproject.toml`.
