from arvix.web import api

from tests.test_telegram import BotCase


class ActionIntentTest(BotCase):
    def setUp(self):
        super().setUp()
        self.task = self.core.add_task("Физика", start="18:00", duration_min=45, sphere="learning")

    def test_advice_after_bad_sleep_does_not_move_task_or_start_timer_in_web(self):
        self.brain.answers.append({"reply": "Перенёс на 20:45. Таймер идёт.", "actions": [
            {"type": "defer_task", "task": self.task.id, "start": "20:45"},
            {"type": "start_focus", "task": self.task.id, "minutes": 20},
            {"type": "profile_set", "key": "wake_target", "value": "05:30"},
        ]})
        api.chat("Спал четыре часа. Физику переносить не хочу, просто помоги решить, с чего начать.")(self.bot)
        self.assertEqual(self.core.state.tasks[self.task.id].start, "18:00")
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertNotIn("wake_target", self.core.state.profile)
        self.assertEqual(len(self.brain.calls), 1)
        self.assertIn("<action_permissions>", self.brain.calls[0]["raw_prompt"])
        replies = api.messages_view(self.core)
        self.assertNotIn("Перенёс на 20:45", replies[-1]["text"])

    def test_explicit_focus_preserves_other_tasks_and_rejects_extra_reschedule(self):
        self.brain.answers.append({"reply": "Запускаю фокус.", "actions": [
            {"type": "defer_task", "task": self.task.id, "start": "20:45"},
            {"type": "start_focus", "task": self.task.id, "minutes": 15},
            {"type": "add_task", "title": "Математика", "start": "20:30"},
        ]})
        self.text("Запусти фокус по физике на 15 минут, а задачи не переноси.")
        self.assertEqual(self.core.store.kv_get("focus")["minutes"], 15)
        self.assertEqual(self.core.state.tasks[self.task.id].start, "18:00")
        self.assertEqual(len(self.core.state.tasks), 1)

    def test_quoted_command_or_bare_agreement_is_not_permission(self):
        for text in ('Что означает "перенеси физику"?', "Давай.", "Если понадобится, запусти таймер."):
            self.brain.answers.append({"reply": "Готово", "actions": [
                {"type": "defer_task", "task": self.task.id, "start": "20:45"},
                {"type": "start_focus", "task": self.task.id, "minutes": 15},
            ]})
            self.text(text)
            self.assertEqual(self.core.state.tasks[self.task.id].start, "18:00")
            self.assertIsNone(self.core.store.kv_get("focus"))

    def test_advice_does_not_get_consumed_as_pending_task_report(self):
        self.bot.await_set("report", task=self.task.id)
        self.brain.answers.append({"reply": "На каком шаге ты обычно застреваешь?", "actions": []})
        self.text("Просто задай один вопрос. Ничего не записывай.")
        self.assertEqual(self.core.state.tasks[self.task.id].status, "planned")
        self.assertEqual(self.bot.await_get()["kind"], "report")
        self.assertIn("На каком шаге", self.api.last)

    def test_debrief_does_not_move_a_task_based_on_a_suggestion(self):
        self.brain.answers.append({"reply": "Перенёс на 20:45.", "actions": [
            {"type": "defer_task", "task": self.task.id, "start": "20:45"},
        ]})
        self.bot.debrief_answer("Застрял в начале решения. Может быть, завтра получится.")
        self.assertEqual(self.core.state.tasks[self.task.id].start, "18:00")
        self.assertNotIn("Перенёс на 20:45", self.api.last)

    def test_stop_command_does_not_restart_a_timer_or_close_the_task(self):
        self.bot.start_focus(15, self.task.id)
        self.brain.answers.append({"reply": "Останавливаю.", "actions": [
            {"type": "stop_focus"}, {"type": "complete_task", "task": self.task.id},
        ]})
        self.text("Стоп таймер.")
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertEqual(self.core.state.tasks[self.task.id].status, "active")
