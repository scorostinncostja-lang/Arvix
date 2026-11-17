"""Фокус-таймер: длительность на выбор, пауза, отмена, тема без задачи, заметка «что сделал»."""

from __future__ import annotations

from arvix.state import State
from arvix.telegram import templates as tpl
from arvix.web import api as web_api

from tests import test_v04
from tests.helpers import moscow
from tests.test_telegram import BotCase


class FocusControlTest(BotCase):
    start = moscow(2026, 11, 2, 15, 55)

    def setUp(self) -> None:
        super().setUp()
        self.math = self.core.add_task("Математика ОГЭ", start="16:00", duration_min=40, importance=3, deep_work=True)

    def sessions(self) -> list[dict]:
        return self.core.state.days[self.core.today()].focus

    def test_pause_time_is_not_counted(self) -> None:
        self.press("f:go:45")
        self.at(moscow(2026, 11, 2, 16, 5))   # 10 мин работы
        self.press("f:pause")
        self.assertIn("пауза", self.api.edited[-1][1])
        self.assertEqual(self.api.edited[-1][2][0][0], ("▶ Продолжить", "f:resume"))
        self.at(moscow(2026, 11, 2, 16, 15))  # 10 мин паузы
        self.press("f:resume")
        self.assertEqual(self.core.store.kv_get("focus")["until"][11:16], "16:50")  # конец сдвинулся на паузу
        self.at(moscow(2026, 11, 2, 16, 25))  # ещё 10 мин работы
        self.press("f:stop")
        self.assertEqual(self.sessions()[-1]["minutes"], 20)
        self.assertEqual(self.core.state.tasks[self.math.id].focus_min, 20)

    def test_long_pause_closes_session_with_worked_minutes(self) -> None:
        self.press("f:go:25")
        self.at(moscow(2026, 11, 2, 16, 3))
        self.press("f:pause")
        self.at(moscow(2026, 11, 2, 16, 3 + tpl.FOCUS_MAX_PAUSE_MIN + 1))
        self.scheduler.tick()
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertEqual(self.sessions()[-1]["minutes"], 8)
        self.assertTrue(any(f"Пауза дольше {tpl.FOCUS_MAX_PAUSE_MIN} минут" in t for t in self.api.texts))

    def test_cancel_records_nothing(self) -> None:
        """Случайно нажал «фокус» — отмена без следов: ни сессии, ни глубокой работы."""
        self.press("f:go:25")
        self.at(moscow(2026, 11, 2, 16, 10))
        self.press("f:cancel")
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.core.state.tasks[self.math.id].focus_min, 0)
        self.assertIn("ничего не записано", self.api.last)

    def test_topic_without_task_goes_to_deep_work(self) -> None:
        self.text("/focus 30 физика")  # задачи «физика» нет — это тема, а не ошибка
        state = self.core.store.kv_get("focus")
        self.assertEqual((state["task_id"], state["topic"]), (None, "физика"))
        self.assertIn("· физика", self.api.sent[-1][0])
        self.at(moscow(2026, 11, 2, 16, 26))
        self.scheduler.tick()
        self.press("f:ok:30")
        self.assertEqual(self.sessions()[-1]["topic"], "физика")
        self.assertEqual(self.core.state.days[self.core.today()].deep_min, 30)

    def test_note_after_session_is_a_separate_event(self) -> None:
        self.press("f:go:25")
        self.at(moscow(2026, 11, 2, 16, 15))
        self.press("f:stop")
        self.assertIn("Что успел?", self.api.last)
        self.text("§12: 5 задач, одна с ошибкой в единицах")
        self.assertEqual(self.sessions()[-1]["note"], "§12: 5 задач, одна с ошибкой в единицах")
        kinds = [e.kind for e in self.core.store.read(0)]
        self.assertEqual(kinds.count("focus_session"), 1)
        self.assertIn("focus_noted", kinds)
        fresh = State.rebuild(self.core.store.read(0))  # свёртка журнала с нуля даёт то же
        self.assertEqual(fresh.days[self.core.today()].focus[-1]["note"], "§12: 5 задач, одна с ошибкой в единицах")

    def test_question_after_session_is_conversation_not_note(self) -> None:
        self.press("f:go:25")
        self.at(moscow(2026, 11, 2, 16, 15))
        self.press("f:stop")
        self.brain.answers.append({"reply": "Следующий блок — алгебра в 17:00.", "actions": []})
        self.text("что дальше по плану?")
        self.assertIsNone(self.sessions()[-1]["note"])
        self.assertIn("алгебра", self.api.last)


class FocusWebTest(BotCase):
    start = moscow(2026, 11, 2, 15, 55)

    def test_app_controls_focus_and_lists_sessions(self) -> None:
        web_api.focus_start(45, None, "физика: задачи 1–5")(self.bot)
        view = web_api.state_view(self.core)
        self.assertEqual((view["focus"]["title"], view["focus"]["paused_at"]), ("физика: задачи 1–5", None))
        self.at(moscow(2026, 11, 2, 16, 5))
        paused = web_api.focus_op("pause")(self.bot)
        self.assertIsNotNone(paused["focus"]["paused_at"])
        web_api.focus_op("resume")(self.bot)
        self.at(moscow(2026, 11, 2, 16, 25))
        stopped = web_api.focus_op("stop")(self.bot)
        session = stopped["session"]
        self.assertEqual((session["minutes"], session["title"]), (30, "физика: задачи 1–5"))
        self.assertIsNone(self.bot.await_get())  # заметку спрашивает приложение, чат не перехватывается
        web_api.focus_note(session["event_id"], "5 задач, все верно")(self.bot)
        self.assertEqual(web_api.state_view(self.core)["sessions"][-1]["note"], "5 задач, все верно")

    def test_unknown_focus_op_is_refused(self) -> None:
        from arvix.core import ArvixError

        with self.assertRaises(ArvixError):
            web_api.focus_op("explode")


class KeepAliveTest(test_v04.ServerTest):
    def test_post_without_read_body_does_not_poison_next_request(self) -> None:
        """В приложении после ⏸ шёл «GET /api/state → 501 ('{}GET')»: тело POST оставалось в соединении."""
        import http.client
        import json as _json

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Authorization": f"Bearer {self.app.token}", "Content-Type": "application/json"}
        conn.request("POST", "/api/focus/cancel", body="{}", headers=headers)
        first = conn.getresponse()
        first.read()
        self.assertEqual(first.status, 200)
        conn.request("GET", "/api/state", headers=headers)
        second = conn.getresponse()
        raw = second.read()
        self.assertEqual(second.status, 200, raw[:200])
        self.assertIn("tasks", _json.loads(raw))
        conn.close()


class HeatmapTest(BotCase):
    start = moscow(2026, 11, 2, 10, 0)  # понедельник

    def test_levels_come_from_work_not_from_chatting(self) -> None:
        self.assertEqual(web_api.heat_level(None, 0, 0, 60), 0)
        self.assertEqual(web_api.heat_level(None, 20, 0, 60), 1)
        self.assertEqual(web_api.heat_level(50, 0, 1, 60), 2)
        self.assertEqual(web_api.heat_level(70, 0, 2, 60), 3)  # день серии
        self.assertEqual(web_api.heat_level(100, 120, 3, 90), 4)

    def test_year_grid_streak_and_best(self) -> None:
        for day in (2, 3, 4):  # три дня по 100 %
            self.at(moscow(2026, 11, day, 10, 0))
            self.core.refresh()
            task = self.core.add_task(f"Физика {day}", start="11:00", duration_min=30)
            self.core.complete_task(task.id, report="решил")
        self.at(moscow(2026, 11, 5, 10, 0))
        self.core.refresh()
        self.core.add_task("Алгебра", start="11:00", duration_min=30)  # провал 5-го — серия рвётся
        self.at(moscow(2026, 11, 6, 10, 0))
        self.core.refresh()
        heat = web_api.history_view(self.core)["heat"]
        days = heat["days"]
        self.assertEqual(len(days) % 7, 5)  # пн…пт текущей недели
        from datetime import date as _date

        self.assertEqual(_date.fromisoformat(days[0]["date"]).weekday(), 0)
        self.assertEqual(days[-1]["date"], "2026-11-06")
        by = {d["date"]: d for d in days}
        self.assertEqual(by["2026-11-03"]["level"], 3)
        self.assertEqual(by["2026-11-05"]["level"], 0)
        self.assertEqual(by["2026-10-20"]["level"], -1)  # до начала учёта
        self.assertEqual((heat["streak"], heat["best"], heat["active"]), (0, 3, 3))

    def test_red_mode_has_no_heatmap(self) -> None:
        self.core.sos(True, note="плохо")
        self.assertNotIn("heat", web_api.history_view(self.core))
