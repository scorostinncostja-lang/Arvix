from datetime import timedelta

from arvix.core import ArvixError
from arvix.state import State
from arvix.web import api

from tests.test_telegram import BotCase


class LearningFocusTest(BotCase):
    def start_learning(self):
        task = self.core.add_task("График пути", duration_min=45, sphere="learning", source="web")
        self.assertTrue(api.task_op(task.id, "start", {})(self.bot)["study"])
        focus = api.state_view(self.core)["focus"]
        self.assertTrue(focus["study"])
        self.assertEqual(focus["minutes"], 45)
        return task

    def step(self, task, action="open", current=None, assessment="correct"):
        self.brain.answers.append({"instruction": "Построй график на бумаге", "assessment": assessment,
                                   "next_step": "Проверь горизонтальный участок"})
        return api.task_study(task.id, {"action": action, "attempt": "Путь не изменился",
                                        "revision": current and current["revision"]})(self.bot)

    def test_learning_checks_independent_work_and_restores_journal(self):
        task = self.start_learning()
        recall = self.step(task)
        self.assertEqual(recall["stage"], "recall")
        self.assertEqual(api.task_study(task.id, {"action": "open"})(self.bot), recall)
        practice = self.step(task, "attempt", recall)
        check = self.step(task, "attempt", practice)
        hint = self.step(task, "hint", check)
        self.assertTrue(hint["assisted"])
        self.assertEqual(self.step(task, "attempt", hint)["stage"], "check")
        check = self.core.state.study_focus["график пути"]
        done = self.step(task, "attempt", check)
        self.assertEqual(done["stage"], "finish")
        self.assertEqual(done["review_due"], (self.core.today() + timedelta(days=1)).isoformat())
        rebuilt = State.rebuild(self.core.store.read(0))
        self.assertEqual(rebuilt.study_focus["график пути"], done)

    def test_stale_attempt_and_model_outage_preserve_the_step(self):
        task = self.start_learning()
        current = self.step(task)
        with self.assertRaisesRegex(ArvixError, "изменилось"):
            api.task_study(task.id, {"action": "hint", "revision": 0})(self.bot)
        with self.assertRaisesRegex(ArvixError, "не ответил"):
            api.task_study(task.id, {"action": "hint", "revision": current["revision"]})(self.bot)
        self.assertEqual(self.core.state.study_focus["график пути"], current)

    def test_cannot_overwrite_a_different_focus(self):
        api.focus_start(30, None, "Работа")(self.bot)
        task = self.core.add_task("График пути", duration_min=45, sphere="learning", source="web")
        with self.assertRaisesRegex(ArvixError, "текущий фокус"):
            api.task_op(task.id, "start", {})(self.bot)
        self.assertEqual(self.core.state.tasks[task.id].status, "planned")

    def test_opening_the_note_keeps_user_edits(self):
        task = self.start_learning()
        self.step(task)
        cmd = api.task_study(task.id, {"action": "note"})
        first = cmd(self.bot)
        path = self.vault / first["note_path"]
        path.write_text("Мой конспект", encoding="utf-8")
        self.assertEqual(cmd(self.bot), first)
        self.assertEqual(path.read_text(encoding="utf-8"), "Мой конспект")

    def test_early_finish_continues_at_next_focus(self):
        task = self.start_learning()
        recall = self.step(task)
        practice = self.step(task, "attempt", recall)
        summary = api.task_study(task.id, {"action": "finish", "revision": practice["revision"]})(self.bot)
        self.assertEqual(summary["resume_stage"], "practice")
        api.focus_op("cancel")(self.bot)
        self.at(self.core.now() + timedelta(days=1))
        next_task = self.start_learning()
        self.assertEqual(self.step(next_task)["stage"], "practice")
