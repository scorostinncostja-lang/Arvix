"""Общая обвязка тестов: временные каталоги вместо ~/.local/share и фиксированные часы."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arvix import clock
from arvix.config import load_config
from arvix.core import Core
from arvix.store import Store

TZ = ZoneInfo("Europe/Moscow")


def moscow(year: int, month: int, day: int, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class ArvixCase(unittest.TestCase):
    """Каждый тест — своя база, своё хранилище, свои часы."""

    start = moscow(2026, 11, 2, 10, 0)  # понедельник

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="arvix-test-"))
        self._env = {k: os.environ.get(k) for k in ("ARVIX_DATA_DIR", "ARVIX_CONFIG_DIR")}
        os.environ["ARVIX_DATA_DIR"] = str(self.tmp / "data")
        os.environ["ARVIX_CONFIG_DIR"] = str(self.tmp / "cfg")
        self.vault = self.tmp / "vault"
        (self.vault / ".obsidian").mkdir(parents=True)
        clock.set_now(self.start)
        self.core = self.make_core()

    def tearDown(self) -> None:
        clock.set_now(None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_core(self) -> Core:
        cfg = load_config()
        cfg.raw["vault"] = str(self.vault)
        cfg.raw["timezone"] = "Europe/Moscow"
        return Core(cfg, Store(self.tmp / "arvix.db"))

    def at(self, value: datetime) -> None:
        clock.set_now(value)
