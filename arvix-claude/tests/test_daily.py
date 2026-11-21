"""Закрытие дня: долг, протокол игнора, квоты, материализация (02-MECHANICS). Игры нет — D41."""

import unittest
from datetime import timedelta

from tests.helpers import ArvixCase, moscow


class CloseDayTest(ArvixCase):
    def close(self) -> None:
        self.at(self.start + timedelta(days=1, hours=-5))  # 05:00 следующего дня
        self.core.refresh()

    def closed(self, offset: int = 0) -> dict:
        return self.core.state.days[self.start.date() + timedelta(days=offset)].closed

    def test_unasked_tasks_fail_without_debt(self) -> None:
        """Arvix ни разу не спросил (бот выключен) — записывать долгом не за что."""
        self.core.add_task("Важное", importance=5, start="18:00")
        self.close()
        task = next(iter(self.core.state.tasks.values()))
        self.assertEqual(task.status, "failed")
        self.assertEqual(self.core.state.debts(), [])
        self.assertEqual(self.closed()["completion"], 0)

    def test_answered_day_puts_important_into_debt(self) -> None:
        self.core.add_task("Важное", importance=4, start="18:00")
        self.core.add_task("Мелочь", importance=1, start="19:00")
        self.core.message_out("напоминание", key="x")
        self.core.message_in("я тут")
        self.close()
        statuses = sorted(t.status for t in self.core.state.tasks.values())
        self.assertEqual(statuses, ["debt", "failed"])

    def test_frozen_day_means_no_debt_for_unreported(self) -> None:
        """Тихий день (как и 🟥): бот о задачах не напоминал — неотчитанное не уходит в долг."""
        self.core.silent_today()
        self.core.add_task("Важное", importance=5, start="18:00")
        self.core.message_out("разбор", key=f"debrief:{self.start.date().isoformat()}")
        self.close()
        task = next(iter(self.core.state.tasks.values()))
        self.assertEqual(task.status, "failed")
        self.assertEqual(self.core.state.debts(), [])

    def test_declared_reason_keeps_the_day_out_of_debt(self) -> None:
        """Щитов больше нет (D41): заявленная причина просто не даёт важному уйти в долг."""
        self.core.add_task("Экзамен", importance=5, start="18:00")
        self.core.message_out("напоминание", key="x")
        self.core.declare_reason("заболел")
        self.close()
        self.assertEqual(self.core.state.debts(), [])
        self.assertTrue(self.closed()["frozen"])

    def test_day_closed_is_facts_only(self) -> None:
        """Итог дня — выполнение, глубокие минуты и сон. Ни XP, ни HP, ни очка сезона (D41)."""
        task = self.core.add_task("Тренировка", importance=2, start="11:00", sphere="work")
        self.core.complete_task(task.id)
        self.core.log_sleep("7:40")
        self.close()
        closed = self.closed()
        self.assertEqual((closed["completion"], closed["done"], closed["sleep_min"]), (100.0, 1, 460))
        for key in ("hp_end", "sp", "penalty_mult", "xp"):
            self.assertNotIn(key, closed)
        kinds = {e.kind for e in self.core.store.read(0)}
        self.assertFalse(kinds & {"xp_awarded", "hp_changed", "shield_used", "protocol_zero"})

    def test_day_three_of_silence_freezes_debt(self) -> None:
        """Протокол игнора (02-MECHANICS §8): с третьего дня тишины важное в долг не уходит."""
        for offset in range(3):
            self.at(self.start + timedelta(days=offset))
            self.core.refresh()
            self.core.add_task(f"Важное {offset}", importance=5, start="18:00", source="scheduler")
            self.core.message_out("брифинг", key=f"brief:{offset}")
        self.at(self.start + timedelta(days=3, hours=-5))
        self.core.refresh()
        self.assertEqual(sorted(t.title for t in self.core.state.debts()), ["Важное 0", "Важное 1"])
        self.assertTrue(self.closed(2)["frozen"])

    def test_catch_up_is_idempotent(self) -> None:
        self.core.add_task("Что-то", start="12:00")
        self.close()
        other = self.make_core()
        other.refresh()
        self.core.refresh()
        closes = [e for e in self.core.store.read(0) if e.kind == "day_closed"]
        self.assertEqual(len(closes), 1)

    def test_quotas_only_when_week_was_used(self) -> None:
        sunday = moscow(2026, 11, 8, 10)
        self.at(sunday)
        self.core.remember("general", "событие, чтобы журнал не был пуст")
        self.at(sunday + timedelta(hours=19))
        self.core.refresh()
        self.assertFalse([e for e in self.core.store.read(0) if e.kind == "quota_result"])  # неделя не велась


class MaterializeTest(ArvixCase):
    blocks = (
        {"start": "09:00", "duration": 120, "title": "Глубокая: алгоритмы", "sphere": "learning", "importance": 4, "difficulty": 3, "deep_work": True},
        {"start": "18:00", "duration": 60, "title": "Практика", "sphere": "learning", "importance": 3, "difficulty": 2},
    )

    def test_no_template_no_invented_tasks(self) -> None:
        self.core.refresh()
        self.assertEqual(self.core.state.tasks_on(self.core.today()), [])

    def test_template_materializes_future_blocks_once(self) -> None:
        self.core.set_template([0, 1, 2], "study", list(self.blocks))  # сейчас пн 10:00
        self.core.refresh()
        titles = [t.title for t in self.core.state.tasks_on(self.core.today())]
        self.assertEqual(titles, ["Практика"])  # 09:00 уже прошло
        self.at(self.start + timedelta(days=1, hours=-4))  # вт 06:00
        self.core.refresh()
        self.core.refresh()
        self.assertEqual(len(self.core.state.tasks_on(self.core.today())), 2)


if __name__ == "__main__":
    unittest.main()
