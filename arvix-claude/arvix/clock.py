"""Единый источник времени. Тесты подменяют его через set_now()."""

from __future__ import annotations

from datetime import UTC, datetime

_fixed: datetime | None = None


def now() -> datetime:
    return _fixed if _fixed is not None else datetime.now(UTC)


def set_now(value: datetime | None) -> None:
    global _fixed
    _fixed = value
