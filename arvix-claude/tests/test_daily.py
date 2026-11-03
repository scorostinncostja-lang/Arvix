"""Закрытие дня: штрафы, щиты, протокол игнора, квоты, материализация (02-MECHANICS)."""

import unittest
from datetime import timedelta

from tests.helpers import ArvixCase, moscow


class CloseDayTest(ArvixCase):
    def close(self) -> None:
        self.at(self.start + timedelta(days=1, hours=-5))  # 05:00 следующего дня
        self.core.refresh()

    def closed(self, offset: int = 0) -> dict:
        return self.core.state.days[self.start.date() + timedelta(days=offset)].closed

    def test_unasked_tasks_fail_without_damage_or_debt(self) -> None:
        """Арвикс ни разу не спросил (бот выключен) — наказывать не за что."""
        self.core.add_task("Важное", importance=5, start="18:00")
        self.close()
        task = next(iter(self.core.state.tasks.values()))
        self.assertEqual(task.status, "failed")
        self.assertEqual(self.core.state.hp, 100)
        self.assertEqual(self.closed()["completion"], 0)

    def test_answered_day_damages_each_unreported_task_and_debts(self) -> None:
        self.core.add_task("Важное", importance=4, start="18:00")
        self.core.add_task("Мелочь", importance=1, start="19:00")
        self.core.message_out("напоминание", key="x")
        self.core.message_in("я тут")
        self.close()
        statuses = sorted(t.status for t in self.core.state.tasks.values())
        self.assertEqual(statuses, ["debt", "failed"])
        self.assertEqual(self.core.state.hp, 100 - 12 - 2)

    def test_ignored_day_is_one_penalty_and_day_three_freezes(self) -> None:
        for offset in range(3):
            self.at(self.start + timedelta(days=offset))
            self.core.refresh()
            self.core.message_out("брифинг", key=f"brief:{offset}")
        self.at(self.start + timedelta(days=3, hours=-5))
        self.core.refresh()
        self.assertEqual(self.core.state.hp, 80)  # −10, −10, день 3 — заморожен
        self.assertEqual(self.closed(2)["penalty_mult"], 0.0)

    def test_shield_refunds_biggest_damage_of_the_day(self) -> None:
        task = self.core.add_task("Экзамен", importance=5, start="09:00")
        self.core.fail_task(task.id, reason="температура")
        self.core.declare_reason("заболел")
        self.assertEqual(self.core.state.hp, 88)
        self.close()
        self.assertEqual(self.core.state.hp, 100)
        self.assertEqual(self.core.state.shields_used(self.start.date()), 1)

    def test_regen_and_bonuses(self) -> None:
        self.core.emit("hp_changed", {"amount": -20, "reason": "тест"}, source="test")
        task = self.core.add_task("Тренировка", importance=2, start="11:00", sphere="work")
        self.core.complete_task(task.id)
        self.core.log_sleep("7:40")
        xp_before = self.core.state.xp_total
        self.close()
        self.assertEqual(self.core.state.hp, 88)  # +8 регенерация
        self.assertEqual(self.core.state.xp_total, xp_before + 25 + 15)  # 100% дня + сон в норме

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
        self.assertEqual(self.core.state.hp, 100)  # неделя не велась — квоты не штрафуют

    def test_protocol_zero(self) -> None:
        self.core.emit("hp_changed", {"amount": -100, "reason": "тест"}, source="test")
        self.close()
        self.assertTrue(self.core.zero_active())
        self.at(self.start + timedelta(days=3))
        self.core.refresh()
        self.assertFalse(self.core.zero_active())
        self.assertEqual(self.core.state.hp, 50)


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
