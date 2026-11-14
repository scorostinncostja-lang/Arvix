"""Тесты требуют живой Postgres (DATABASE_URL) со схемой из `make migrate` —
JSONB/UUID-типы завязаны на диалект Postgres, SQLite не подходит.

Изоляция: внешняя транзакция на соединении + сессия с join_transaction_mode="create_savepoint".
Любой `session.commit()` внутри теста/доменного кода лишь освобождает savepoint, а в конце
теста внешний rollback откатывает всё — в БД ничего не остаётся."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import engine


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Основная фикстура. Имя `session` используют test_projections.py и test_materialize.py."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        sess = AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield sess
        finally:
            await sess.close()
            await outer.rollback()


@pytest_asyncio.fixture
async def async_session(session: AsyncSession) -> AsyncSession:
    """Алиас для test_ai_layer.py и test_tasks_domain.py: та же сессия и тот же savepoint."""
    return session
