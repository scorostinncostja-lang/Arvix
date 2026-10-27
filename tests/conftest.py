"""Тесты требуют живой Postgres (DATABASE_URL) со схемой из `make migrate` —
JSONB/UUID-типы завязаны на диалект Postgres, SQLite не подходит.

Фикстура использует вложенную транзакцию (savepoint) для изоляции каждого теста."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import async_session_factory


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Основная фикстура. Имя `session` используют test_projections.py и test_materialize.py."""
    async with async_session_factory() as sess, sess.begin_nested():  # Создаем savepoint
        try:
            yield sess
        finally:
            await sess.rollback()  # Откатываем к savepoint после каждого теста


@pytest_asyncio.fixture
async def async_session(session: AsyncSession) -> AsyncSession:
    """Алиас для test_ai_layer.py и test_tasks_domain.py: та же сессия и тот же savepoint."""
    return session
