"""Тесты требуют живой Postgres (DATABASE_URL) со схемой из `make migrate` —
JSONB/UUID-типы завязаны на диалект Postgres, SQLite не подходит.

Фикстура ничего не коммитит и в конце откатывает транзакцию, поэтому
дев-базу не пачкает."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import async_session_factory


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with async_session_factory() as sess:
        try:
            yield sess
        finally:
            await sess.rollback()
