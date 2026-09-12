"""Единственный способ записать событие (незыблемое правило №3 из CLAUDE.md).
Прямой UPDATE проекций запрещён — emit() пишет events и синхронно накатывает
инкремент на проекции в той же транзакции. Коммит — на совести вызывающего
кода (Unit of Work уровня хендлера/эндпоинта)."""

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Event
from core.events.kinds import EventKind, EventSource
from core.events.projections import apply as apply_projection

LOCAL_TZ = ZoneInfo("Europe/Moscow")


async def emit(
    session: AsyncSession,
    kind: EventKind,
    payload: dict[str, Any],
    *,
    source: EventSource,
    entity_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> Event:
    at = at or datetime.now(UTC)
    event = Event(
        kind=kind.value,
        entity_id=entity_id,
        payload=payload,
        source=source.value,
        at=at,
        local_date=at.astimezone(LOCAL_TZ).date(),
    )
    session.add(event)
    await session.flush()
    await apply_projection(session, event)
    return event
