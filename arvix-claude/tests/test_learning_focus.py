from base64 import b64encode
from datetime import timedelta

from arvix import learning_focus as lf
from arvix.core import ArvixError
from arvix.state import State
from arvix.telegram.templates import brief
from arvix.web import api

from tests.test_telegram import BotCase, FakeSTT


class LearningFocusTest(BotCase):
    def study(self, action="open", current=None, task=None, topic="График пути", **fields):
        body = {"action": action, "revision": current and current["revision"], **fields}
        if topic:
            body["topic"] = topic
        return api.study(body, task and task.id)(self.bot)

    def due_in(self, step, days):
        self.assertEqual(step["review_due"], (self.core.today() + timedelta(days=days)).isoformat())

    def test_topic_comes_from_title_without_block_size(self):
        self.assertEqual(lf.topic_from_title("Математика ОГЭ: №20, 2 задачи"), "Математика ОГЭ: №20")
        self.assertEqual(lf.topic_from_title("Повтор: Математика ОГЭ: №20"), "Математика ОГЭ: №20")
        first = self.core.add_task("Математика ОГЭ: №20, 2 задачи", sphere="learning")
        second = self.core.add_task("Математика ОГЭ: №20, 5 задач", sphere="learning", day="tomorrow")
        opened = self.study(task=first, topic=None)
        self.assertEqual(opened["title"], "Математика ОГЭ: №20")
        self.study("record", opened, task=first, topic=None, correct=1, total=2)
        self.assertEqual(self.study(task=second, topic=None)["score"], {"correct": 1, "total": 2})

    def test_record_schedules_review_by_code_without_model_or_checkbox(self):
        opened = self.study()
        step = self.study("record", opened, correct=7, total=10)
        self.due_in(step, 1)  # первая запись темы — повтор завтра
        self.assertEqual(self.brain.calls, [])
        self.assertIsNone(self.core.store.kv_get("focus"))
        replay = State.rebuild(self.core.store.read(0))
        self.assertEqual(replay.study_focus["график пути"]["score"], {"correct": 7, "total": 10})

    def test_ladder_grows_when_clean_and_on_time_resets_on_mistakes(self):
        step = self.study("record", correct=9, total=10)
        self.due_in(step, 1)
        early = self.study("record", step, correct=10, total=10)
        self.due_in(early, 1)  # раньше срока ступенька не растёт
        self.at(self.core.now() + timedelta(days=1))
        self.assertIn("Пора повторить: График пути", brief(self.core))
        step = self.study("record", early, correct=10, total=10)
        self.due_in(step, 3)
        self.assertNotIn("Пора повторить", brief(self.core))
        self.at(self.core.now() + timedelta(days=3))
        step = self.study("record", step, correct=2, total=5, mistakes="знак при переносе")
        self.due_in(step, 1)
        self.assertEqual(step["interval"], 1)
        self.assertEqual([h["clean"] for h in step["history"]], [True, True, True, False])

    def test_top_of_ladder_marks_topic_mastered(self):
        step = self.study("record", result="разобрал правило")
        for days in (1, 3, 7, 14, 30):
            self.assertFalse(step["review"] == "mastered")
            self.at(self.core.now() + timedelta(days=days))
            step = self.study("record", step, correct=5, total=5)
        self.assertEqual(step["review"], "mastered")
        self.assertIsNone(step["review_due"])
        self.assertEqual(lf.reviews_due(self.core), [])

    def test_record_can_close_the_task_with_one_report(self):
        task = self.core.add_task("Математика ОГЭ: №20, 2 задачи", sphere="learning")
        opened = self.study(task=task, topic=None)
        step = self.study("record", opened, task=task, topic=None, correct=1, total=2,
                          mistakes="скобки при подстановке", close=True)
        self.assertTrue(step["closed"])
        done = self.core.state.tasks[task.id]
        self.assertEqual(done.status, "done")
        self.assertIn("1 из 2", done.report)
        self.assertIn("скобки", done.report)

    def test_empty_record_is_refused(self):
        with self.assertRaisesRegex(ArvixError, "итог"):
            self.study("record")

    def test_due_topic_goes_to_plan_once(self):
        step = self.study("record", correct=3, total=5)
        self.at(self.core.now() + timedelta(days=1))
        planned = self.study("plan_review", step)
        task = self.core.state.tasks[planned["review_task"]]
        self.assertEqual((task.title, task.sphere, task.duration_min), ("Повтор: График пути", "learning", 20))
        again = self.study("plan_review", planned)
        self.assertEqual(again["review_task"], task.id)
        self.assertEqual(sum(t.title.startswith("Повтор:") for t in self.core.state.tasks.values()), 1)
        self.assertEqual(self.study(task=task, topic=None)["key"], "график пути")

    def test_task_start_is_timer_only(self):
        first = self.core.add_task("Физика — 1–5", sphere="learning", duration_min=45)
        second = self.core.add_task("Физика — 6–10", sphere="learning")
        result = api.task_op(first.id, "start", {})(self.bot)
        self.assertNotIn("study", result)
        self.assertEqual(api.state_view(self.core)["focus"]["minutes"], 45)
        with self.assertRaisesRegex(ArvixError, "текущий фокус"):
            api.task_op(second.id, "start", {})(self.bot)
        self.assertEqual(self.brain.calls, [])

    def test_help_only_on_request_and_kept_apart_from_result(self):
        step = self.study("record", correct=7, total=10)
        with self.assertRaisesRegex(ArvixError, "не получается"):
            self.study("help", step)
        self.assertEqual(self.brain.calls, [])
        self.brain.answers.append({"feedback": "Уточни вертикальную ось", "next_step": "Сверь с учебником"})
        image = b64encode(b"\xff\xd8\xff" + b"test").decode()
        reply = self.study("help", step, photo=image)
        self.assertEqual(reply["help"]["feedback"], "Уточни вертикальную ось")
        self.assertEqual(reply["score"], {"correct": 7, "total": 10})
        call = self.brain.calls[-1]
        self.assertEqual(call["image"].parent.name, "Учебные попытки")
        self.assertFalse(call["web"])
        with self.assertRaisesRegex(ArvixError, "уже обновилась"):
            self.study("record", step, correct=1, total=1)

    def test_old_snapshot_events_still_fold(self):
        with self.core.tx():
            self.core.emit("study_focus_step", {"topic": "старая тема", "stage": "recall", "feedback": "x",
                                                "review_due": self.core.today().isoformat()}, source="web")
        topic = api.state_view(self.core)["study_topics"][0]
        self.assertEqual((topic["title"], topic["review"]), ("Старая тема", "due"))

    def test_opening_the_note_keeps_user_edits(self):
        first = self.study("note")
        path = self.vault / first["note_path"]
        path.write_text("Мой конспект", encoding="utf-8")
        self.assertEqual(self.study("note", first)["note_path"], first["note_path"])
        self.assertEqual(path.read_text(encoding="utf-8"), "Мой конспект")

    def test_voice_transcription_is_a_draft(self):
        self.bot.stt = FakeSTT("  скорость равна нулю  ")
        self.assertEqual(api.study_transcribe(b"voice", "voice.webm")(self.bot), {"text": "скорость равна нулю"})
        self.assertEqual(self.brain.calls, [])
        self.assertEqual(self.core.state.study_focus, {})
