from base64 import b64encode
from datetime import timedelta

from arvix.core import ArvixError
from arvix.state import State
from arvix.telegram.templates import brief
from arvix.web import api

from tests.test_telegram import BotCase, FakeSTT


class LearningFocusTest(BotCase):
    def study(self, action="open", current=None, task=None, **fields):
        body = {"action": action, "topic": "График пути", "revision": current and current["revision"], **fields}
        return api.study(body, task and task.id)(self.bot)

    def test_open_tab_and_record_without_task_timer_or_model(self):
        opened = self.study()
        self.assertEqual(self.core.state.study_focus, {})
        saved = self.study("record", opened, attempt="7 из 10", review=True)
        self.assertEqual(saved["review_due"], (self.core.today() + timedelta(days=1)).isoformat())
        self.assertEqual(api.state_view(self.core)["study_topics"][0]["result"], "7 из 10")
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertEqual(self.brain.calls, [])
        replay = State.rebuild(self.core.store.read(0))
        self.assertEqual(replay.study_focus["график пути"]["result"], "7 из 10")

    def test_repeat_due_appears_in_tab_and_advances_after_record(self):
        first = self.study("record", attempt="Прочитал график", review=True)
        self.at(self.core.now() + timedelta(days=1))
        self.assertEqual(api.state_view(self.core)["study_topics"][0]["review_due"], self.core.today().isoformat())
        self.assertIn("Пора повторить: График пути", brief(self.core))
        second = self.study("record", first, attempt="Решил новые задачи", review=True)
        self.assertEqual(second["review_due"], (self.core.today() + timedelta(days=7)).isoformat())
        self.assertNotIn("Пора повторить", brief(self.core))

    def test_task_start_is_timer_only_and_topics_can_cross_tasks(self):
        first = self.core.add_task("Физика — 1–5", sphere="learning", duration_min=45)
        second = self.core.add_task("Физика — 6–10", sphere="learning")
        result = api.task_op(first.id, "start", {})(self.bot)
        self.assertNotIn("study", result)
        self.assertEqual(api.state_view(self.core)["focus"]["minutes"], 45)
        self.study("record", task=first, attempt="решил 1–5")
        self.assertEqual(self.study(task=second)["result"], "решил 1–5")
        with self.assertRaisesRegex(ArvixError, "текущий фокус"):
            api.task_op(second.id, "start", {})(self.bot)
        self.assertEqual(self.brain.calls, [])

    def test_request_model_only_for_supplied_attempt_and_separate_photo(self):
        opened = self.study()
        with self.assertRaisesRegex(ArvixError, "вопрос"):
            self.study("attempt", opened)
        self.assertEqual(self.brain.calls, [])
        self.brain.answers.append({"feedback": "Уточни вертикальную ось", "next_step": "Сверь с учебником"})
        image = b64encode(b"\xff\xd8\xff" + b"test").decode()
        reply = self.study("attempt", opened, photo=image)
        self.assertEqual(reply["feedback"], "Уточни вертикальную ось")
        call = self.brain.calls[-1]
        self.assertEqual(call["image"].parent.name, "Учебные попытки")
        self.assertFalse(call["web"])
        with self.assertRaisesRegex(ArvixError, "уже обновилась"):
            self.study("record", opened, attempt="Устаревший результат")

    def test_opening_the_note_keeps_user_edits(self):
        first = self.study("note")
        path = self.vault / first["note_path"]
        path.write_text("Мой конспект", encoding="utf-8")
        self.assertEqual(self.study("note", first), first)
        self.assertEqual(path.read_text(encoding="utf-8"), "Мой конспект")

    def test_voice_transcription_is_a_draft(self):
        self.bot.stt = FakeSTT("  скорость равна нулю  ")
        self.assertEqual(api.study_transcribe(b"voice", "voice.webm")(self.bot), {"text": "скорость равна нулю"})
        self.assertEqual(self.brain.calls, [])
        self.assertEqual(self.core.state.study_focus, {})
