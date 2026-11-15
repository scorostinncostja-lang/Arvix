"""Event log в SQLite (03-DATA-MODEL §1).

Единственный способ изменить состояние — append() события. UPDATE и DELETE по
таблице events запрещены триггерами: исправление делается только компенсирующим
событием (инвариант 5). Состояние — производное, его собирает state.State.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    local_date  TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind <> ''),
    entity_id   TEXT,
    payload     TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_date ON events (local_date);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events (kind, id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
-- Транспортное состояние (offset Telegram, чего бот ждёт от пользователя).
-- Не доменное: ни XP, ни HP, ни задач здесь нет.
CREATE TABLE IF NOT EXISTS runtime (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Event:
    id: int
    at: datetime
    local_date: date
    kind: str
    entity_id: str | None
    payload: dict[str, Any]
    source: str


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, timeout=15, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=15000")
        self._conn.executescript(SCHEMA)
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE берёт блокировку записи сразу: бот, MCP-сервер и CLI —
        разные процессы, и без этого два из них могут закрыть один день дважды.
        Вложенный вызов переиспользует внешнюю транзакцию."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._depth = 0

    def append(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        at: datetime,
        local_date: date,
        source: str,
        entity_id: str | None = None,
    ) -> Event:
        body = json.dumps(payload, ensure_ascii=False, default=str)
        cursor = self._conn.execute(
            "INSERT INTO events (at, local_date, kind, entity_id, payload, source) VALUES (?, ?, ?, ?, ?, ?)",
            (at.isoformat(), local_date.isoformat(), kind, entity_id, body, source),
        )
        # payload перечитывается из JSON, чтобы in-process apply() видел ровно то,
        # что потом увидит rebuild() из базы (datetime → str и т.п.).
        return Event(int(cursor.lastrowid or 0), at, local_date, kind, entity_id, json.loads(body), source)

    def read(self, after_id: int = 0) -> list[Event]:
        rows = self._conn.execute(
            "SELECT id, at, local_date, kind, entity_id, payload, source FROM events WHERE id > ? ORDER BY id",
            (after_id,),
        ).fetchall()
        return [
            Event(row[0], datetime.fromisoformat(row[1]), date.fromisoformat(row[2]), row[3], row[4], json.loads(row[5]), row[6])
            for row in rows
        ]

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM runtime WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO runtime (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )

    def kv_del(self, key: str) -> None:
        self._conn.execute("DELETE FROM runtime WHERE key = ?", (key,))

    def close(self) -> None:
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 — на выходе из процесса соединение может быть уже закрыто
            pass
