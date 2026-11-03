"""Telegram-бот без сети: подставные API и голова."""

import unittest
from typing import Any

from arvix.telegram import templates as tpl
from arvix.telegram.bot import Bot, parse_quick_task
from arvix.telegram.scheduler import Scheduler

from tests.helpers import ArvixCase, moscow

OWNER = 111


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []

    def send(self, chat_id: int, text: str, buttons: Any = None) -> None:
        assert chat_id == OWNER
        self.sent.append((text, buttons))

    def answer_callback(self, *a: Any, **k: Any) -> None:
        pass

    def drop_buttons(self, *a: Any) -> None:
        pass

    def typing(self, *a: Any) -> None:
        pass

    @property
    def last(self) -> str:
        return self.sent[-1][0]


class FakeBrain:
    def __init__(self) -> None:
        self.answers: list[dict | None] = []
        self.calls: list[dict[str, Any]] = []

    def ask(self, **kwargs: Any) -> dict | None:
        self.calls.append(kwargs)
        return self.answers.pop(0) if self.answers else None

    def available(self) -> bool:
        return True


class BotCase(ArvixCase):
    def setUp(self) -> None:
        super().setUp()
        self.api = FakeAPI()
        self.brain = FakeBrain()
        self.bot = Bot(self.core, self.api, self.brain, OWNER)
        self.scheduler = Scheduler(self.bot)

    def text(self, text: str, sender: int = OWNER) -> None:
        self.bot.handle({"update_id": 1, "message": {"from": {"id": sender}, "chat": {"id": sender}, "text": text}})

    def press(self, data: str) -> None:
        self.bot.handle({"update_id": 2, "callback_query": {"id": "c", "from": {"id": OWNER}, "data": data, "message": {"chat": {"id": OWNER}, "message_id": 5}}})


class InboxTest(BotCase):
    def test_strangers_are_ignored(self) -> None:
        self.text("/status", sender=999)
        self.assertEqual(self.api.sent, [])

    def test_start_runs_onboarding_and_answers_flow(self) -> None:
        self.text("/start")
        self.assertIn("Как к тебе обращаться?", self.api.last)
        self.text("Дастан")
        self.assertIn("роде", self.api.last)
        self.press("q:skip:address")
        self.assertIn("Город", self.api.last)
        self.assertEqual(self.core.state.profile["name"], "Дастан")

    def test_block_end_runs_one_extraction_call(self) -> None:
        for qid in ("name", "address", "city", "sleep", "week", "main_goal"):
            self.core.interview_answer(qid, "ответ" if qid != "sleep" else "01:00-09:00, хочу 23:30-07:30")
        self.bot.ask_question(self.core.interview_next())
        self.brain.answers.append({"summary": "Записал цель.", "actions": [{"type": "remember", "topic": "goal", "fact": "хочет уйти со смен"}]})
        self.text("Чтобы уйти со смен")
        self.assertEqual(len(self.brain.calls), 1)
        self.assertTrue(any("Записал цель" in t for t, _ in self.api.sent))
        self.assertIn("Продолжаем", self.api.last)

    def test_report_button_flow(self) -> None:
        task = self.core.add_task("Физика", importance=3, start="12:00")
        self.press(f"t:{task.id}:yes")
        self.assertEqual(self.api.last, tpl.ASK_REPORT)
        self.text("решил 10 задач")
        self.assertIn("+", self.api.last)
        self.assertEqual(self.core.state.tasks[task.id].status, "done")
        self.assertEqual(self.brain.calls, [])  # кнопки и отчёт — без модели

    def test_fail_button_asks_reason_then_converses(self) -> None:
        task = self.core.add_task("Экзамен", importance=5, start="12:00")
        self.press(f"t:{task.id}:no")
        self.assertIn("ушла в долг", self.api.last)
        self.brain.answers.append({"reply": "Причина записана. Завтра 09:00 — первым делом.", "actions": []})
        self.text("проспал")
        self.assertEqual(self.core.state.tasks[task.id].reason, "проспал")
        self.assertIn("09:00", self.api.last)

    def test_safety_marker_switches_off_mentor_without_model(self) -> None:
        self.text("я не хочу жить")
        self.assertFalse(self.core.state.mentor_enabled)
        self.assertIn("112", self.api.last)
        self.assertEqual(self.brain.calls, [])
        self.text("/mentor on")
        self.assertTrue(self.core.state.mentor_enabled)

    def test_brain_down_gives_template(self) -> None:
        self.text("как дела?")
        self.assertEqual(self.api.last, tpl.FALLBACK)

    def test_actions_are_applied_and_reported_honestly(self) -> None:
        task = self.core.add_task("Английский", importance=2, start="12:00", sphere="work")
        self.brain.answers.append({"reply": "Принято.", "actions": [
            {"type": "complete_task", "task": task.id},
            {"type": "complete_task", "task": "несуществующая"},
        ]})
        self.text("английский сделал")
        self.assertIn("✅ Английский", self.api.last)
        self.assertIn("Не выполнено", self.api.last)

    def test_report_falls_back_to_user_words_and_deadline_to_start(self) -> None:
        """Живой прогон показал: модель забывает report и пишет «до 20:30» в deadline."""
        task = self.core.add_task("Английский", importance=3, start="12:00")
        self.brain.answers.append({"reply": "Принято.", "actions": [
            {"type": "complete_task", "task": task.id},
            {"type": "add_task", "title": "Матан", "duration_min": 60, "deadline": "20:30", "importance": 4},
        ]})
        self.text("английский сделал: 30 карточек")
        self.assertEqual(self.core.state.tasks[task.id].report, "английский сделал: 30 карточек")
        added = next(t for t in self.core.state.tasks.values() if t.title == "Матан")
        self.assertEqual(added.start, "19:30")
        self.assertNotIn("Не выполнено", self.api.last)

    def test_gentle_validator_replaces_harsh_reply(self) -> None:
        self.core.sos(True)
        self.brain.answers += [{"reply": "Дисциплина важнее, выполнение 0%.", "actions": []}, {"reply": "Опять про продуктивность.", "actions": []}]
        self.text("мне тяжело сегодня")
        self.assertEqual(self.api.last, tpl.GENTLE_FALLBACK)

    def test_quick_add_parser(self) -> None:
        fields = parse_quick_task("Физика: задачи 18:00 60м !4 deep завтра")
        self.assertEqual(fields, {"start": "18:00", "duration_min": 60, "importance": 4, "deep_work": True, "day": "tomorrow", "title": "Физика: задачи"})

    def test_sleep_answer_after_brief(self) -> None:
        self.bot.send_brief()
        self.text("7:20")
        self.assertEqual(self.core.state.days[self.core.today()].sleep_min, 440)


class SchedulerTest(BotCase):
    start = moscow(2026, 11, 2, 7, 0)

    def keys(self) -> list[str]:
        return sorted(k for d in self.core.state.days.values() for k in d.out_keys)

    def test_task_reminders_and_dedupe(self) -> None:
        task = self.core.add_task("Алгоритмы", importance=4, start="09:00", duration_min=60)
        self.at(moscow(2026, 11, 2, 8, 56))
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual(sum(1 for t, _ in self.api.sent if "Через" in t), 1)
        self.at(moscow(2026, 11, 2, 9, 1))
        self.scheduler.tick()
        self.assertIn("Блок пошёл", self.api.last)
        self.at(moscow(2026, 11, 2, 10, 2))
        self.scheduler.tick()
        self.assertEqual(self.api.last, f"Сделано: {task.title}?")

    def test_brief_and_debrief_windows(self) -> None:
        self.core.profile_set("wake_target", "07:30")
        self.at(moscow(2026, 11, 2, 7, 50))
        self.scheduler.tick()
        self.assertTrue(any(t.startswith("☀️") for t, _ in self.api.sent))
        self.brain.answers.append({"assessment": "День пустой.", "questions": ["Почему без плана?", "Что завтра первым?"]})
        self.at(moscow(2026, 11, 2, 22, 31))
        self.scheduler.tick()
        self.assertIn("Почему без плана?", self.api.last)
        self.assertEqual(self.core.store.kv_get("tg_await")["kind"], "debrief")
        self.brain.answers.append({"reply": "Вывод: план с вечера.", "actions": []})
        self.text("не составил план")
        self.assertTrue(self.core.state.days[self.core.today()].debrief)

    def test_missed_brief_is_not_sent_hours_later(self) -> None:
        self.core.profile_set("wake_target", "07:30")
        self.at(moscow(2026, 11, 2, 13, 0))
        self.scheduler.tick()
        self.assertFalse(any(t.startswith("☀️") for t, _ in self.api.sent))

    def test_ignore_protocol_day_three(self) -> None:
        self.core.profile_set("wake_target", "07:30", source="l0")  # не действие человека
        for offset in range(2):
            self.at(moscow(2026, 11, 2 + offset, 8, 0))
            self.scheduler.tick()
        self.at(moscow(2026, 11, 4, 8, 0))
        self.scheduler.tick()
        self.assertEqual(self.api.last, tpl.IGNORE[2])

    def test_silent_day_sends_only_debrief(self) -> None:
        self.core.silent_today()
        self.core.add_task("Что-то", start="09:00")
        self.at(moscow(2026, 11, 2, 8, 57))
        self.scheduler.tick()
        self.assertEqual(self.api.sent, [])


if __name__ == "__main__":
    unittest.main()
