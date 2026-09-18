"""Single-user: всё, что пришло не от OWNER_ID, молча игнорируется —
01-ARCHITECTURE.md §5. Один middleware на весь Dispatcher, а не проверка
в каждом хендлере."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from core.config import settings


class OwnerOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.id != settings.owner_id:
            return None
        return await handler(event, data)
