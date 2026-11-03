"""Журнал событий и операции L0: инварианты 03-DATA-MODEL §3."""

import random
import sqlite3
import unittest
from datetime import timedelta

from arvix.core import ArvixError
from arvix.state import State

from tests.helpers import ArvixCase, moscow


class EventLogTest(ArvixCase):
    def test_append_only(self) -> None:
        self.core.add_task("Тест", start="12:00")
        conn = sqlite3.connect(self.tmp / "arvix.db")
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE events SET kind = 'x'")
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM events")
        conn.close()

    def test_rebuild_equals_incremental_on_random_history(self) -> None:
        """Инвариант 1: пересчёт из журнала = накопленное состояние. Плюс HP в
        [0, 100] (инв. 2) и сумма xp_awarded = xp_total (инв. 4)."""
        rnd = random.Random(42)
        day = moscow(2026, 11, 2, 8, 0)
        for step in range(220):
            self.at(day + timedelta(minutes=step * 37))
            op = rnd.choice(["add", "add", "done", "fail", "sleep", "spend", "defer", "remember"])
            open_tasks = [t for t in self.core.state.tasks.values() if t.is_open]
            try:
                if op == "add":
                    self.core.add_task(f"Задача {step}", importance=rnd.randint(1, 5), difficulty=rnd.randint(1, 5),
                                       start=f"{rnd.randint(6, 22):02d}:00", sphere=rnd.choice(["learning", "sport", "work"]))
                elif op == "done" and open_tasks:
                    self.core.complete_task(rnd.choice(open_tasks).id, report="сделано", done_pct=rnd.choice([100, 60]))
                elif op == "fail" and open_tasks:
                    self.core.fail_task(rnd.choice(open_tasks).id, reason="тест")
                elif op == "sleep":
                    self.core.log_sleep(rnd.choice(["4:30", "5:40", "7:30", "8:10"]))
                elif op == "spend":
                    self.core.log_expense(rnd.randint(100, 3000), "еда", impulse=rnd.random() < 0.3)
                elif op == "defer" and open_tasks:
                    self.core.defer_task(rnd.choice([t for t in open_tasks if t.status == "planned"] or open_tasks).id, 15)
                elif op == "remember":
                    self.core.remember("general", f"факт {step}")
            except ArvixError:
                pass
            self.core.refresh()  # закрытие дней, режим
        events = self.core.store.read(0)
        fresh = State.rebuild(events)
        live = self.core.state
        self.assertEqual(fresh.xp_total, live.xp_total)
        self.assertEqual(fresh.hp, live.hp)
        self.assertEqual({k: t.status for k, t in fresh.tasks.items()}, {k: t.status for k, t in live.tasks.items()})
        self.assertEqual({d: x.closed for d, x in fresh.days.items()}, {d: x.closed for d, x in live.days.items()})
        self.assertTrue(0 <= live.hp <= 100)
        self.assertEqual(sum(int(e.payload["amount"]) for e in events if e.kind == "xp_awarded"), live.xp_total)
        self.assertTrue(all(int(e.payload["amount"]) >= 0 for e in events if e.kind == "xp_awarded"))
        self.assertGreaterEqual(sum(1 for e in events if e.kind == "day_closed"), 5)

    def test_other_process_writes_are_seen(self) -> None:
        other = self.make_core()
        other.add_task("Из другого процесса", start="15:00")
        self.core.refresh()
        self.assertIn("Из другого процесса", [t.title for t in self.core.state.tasks.values()])


class TaskOpsTest(ArvixCase):
    def test_done_cannot_go_back(self) -> None:
        """Инвариант 3: выполненную задачу нельзя закрыть или провалить повторно."""
        task = self.core.add_task("Отжимания", importance=2, start="12:00", sphere="work")
        self.core.complete_task(task.id)
        with self.assertRaises(ArvixError):
            self.core.complete_task(task.id)
        with self.assertRaises(ArvixError):
            self.core.fail_task(task.id, reason="передумал")

    def test_report_required_for_important_task(self) -> None:
        task = self.core.add_task("Алгоритмы", importance=4, start="12:00", deep_work=True)
        with self.assertRaises(ArvixError):
            self.core.complete_task(task.id)
        result = self.core.complete_task(task.id, report="графы, 3 задачи")
        self.assertGreater(result["xp"], 0)
        self.assertEqual(self.core.state.days[task.local_date].deep_min, task.duration_min)

    def test_important_failure_goes_to_debt_and_blocks_optional(self) -> None:
        for title in ("Курсовая", "Экзамен"):
            task = self.core.add_task(title, importance=5, start="09:00")
            result = self.core.fail_task(task.id, reason="не успел")
            self.assertTrue(result["debt"])
            self.assertEqual(result["hp"], -12)
        self.assertEqual(self.core.state.hp, 76)
        with self.assertRaises(ArvixError) as ctx:
            self.core.add_task("Кино с друзьями", sphere="social", start="19:00")
        self.assertIn("Долг", str(ctx.exception))
        self.core.add_task("Учёба", sphere="learning", start="19:00")  # обязательное — можно

    def test_resolve_by_title_and_prefix(self) -> None:
        task = self.core.add_task("Физика: задачи", start="18:00")
        self.assertEqual(self.core.resolve_task("физика").id, task.id)
        self.assertEqual(self.core.resolve_task(task.id[:4]).id, task.id)
        with self.assertRaises(ArvixError):
            self.core.resolve_task("химия")

    def test_directive_requires_evidence(self) -> None:
        """Инвариант 6: директива без доказательств отклоняется."""
        self.core.add_task("Что-то", start="10:30")
        with self.assertRaises(ArvixError):
            self.core.add_directive("warning", "Вторники проседают", evidence=[])
        with self.assertRaises(ArvixError):
            self.core.add_directive("warning", "Вторники проседают", evidence=[99999])
        self.core.add_directive("warning", "Вторники проседают", evidence=[1])
        self.assertEqual(len(self.core.state.active_directives(self.core.today())), 1)

    def test_mentor_cannot_be_reenabled_via_profile(self) -> None:
        self.core.safety_flag("high", "тест")
        self.assertFalse(self.core.state.mentor_enabled)
        with self.assertRaises(ArvixError):
            self.core.profile_set("mentor_enabled", True)
        self.assertEqual(self.core.effective_mode(), "red")
        self.core.set_mentor(True, by="test")
        self.assertTrue(self.core.state.mentor_enabled)

    def test_interview_flow_extracts_profile(self) -> None:
        self.assertEqual(self.core.interview_next()["id"], "name")
        self.core.interview_answer("name", "Дастан")
        self.core.interview_answer("address", "сделал")
        result = self.core.interview_answer("city", "Алматы")
        self.assertEqual(result["extracted"]["timezone"], "Asia/Almaty")
        self.assertEqual(self.core.tz.key, "Asia/Almaty")
        self.core.interview_skip("sleep")
        self.core.interview_answer("week", "пн-пт колледж 8:30-14:00, пт-вс смены")
        self.core.interview_answer("main_goal", "Фронтенд-джун к июню 2027")
        result = self.core.interview_answer("main_goal_why", "Чтобы зарабатывать и уйти со смен")
        self.assertTrue(result["block_done"])
        self.assertEqual(result["next"]["block"], "study")
        goals = list(self.core.state.goals.values())
        self.assertEqual(goals[0]["why"], "Чтобы зарабатывать и уйти со смен")

    def test_sleep_parsing(self) -> None:
        for raw, minutes in (("7:30", 450), ("7.5", 450), ("7ч30м", 450), ("450м", 450), ("6", 360)):
            self.assertEqual(self.core.log_sleep(raw)["duration_min"], minutes, raw)


if __name__ == "__main__":
    unittest.main()
