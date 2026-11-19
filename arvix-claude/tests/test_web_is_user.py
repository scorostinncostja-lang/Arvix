"""Приложение — тот же человек, что и Telegram (D51). Раньше события из приложения шли с источником
`web`, которого нет в USER_SOURCES: кто пишет и отмечает задачи только в приложении, для протокола
игнора «молчал» — и на третий день получал «вернись»."""

from __future__ import annotations

from datetime import timedelta

from arvix.web import api
from tests.helpers import moscow
from tests.test_telegram import BotCase


class WebIsUserTest(BotCase):
    start = moscow(2026, 11, 2, 9, 0)

    def bot_writes(self) -> None:
        self.core.message_out("☀️ брифинг")

    def test_chat_in_the_app_is_a_user_action(self) -> None:
        self.bot_writes()
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        api.chat("привет")(self.bot)
        self.assertEqual(self.core.state.days[self.core.today()].user_actions, 1)

    def test_task_done_in_the_app_breaks_the_silence(self) -> None:
        task = self.core.add_task("Физика", start="10:00", duration_min=30, importance=2, source="l0")
        for offset in range(3):  # три дня бот пишет, человек отвечает только в приложении
            self.at(self.start + timedelta(days=offset))
            self.bot_writes()
        api.task_op(task.id, "done", {})(self.bot)
        self.assertEqual(self.core.state.ignore_streak(self.core.today()), 0)

    def test_app_alone_does_not_trigger_the_ignore_protocol(self) -> None:
        self.core.profile_set("wake_target", "07:30", source="l0")
        for offset in range(3):
            self.at(moscow(2026, 11, 2 + offset, 8, 0))
            self.scheduler.tick()
            self.brain.answers.append({"reply": "Ок.", "actions": []})
            api.chat("сделал зарядку")(self.bot)
        self.at(moscow(2026, 11, 5, 8, 0))
        self.scheduler.tick()
        self.assertEqual(self.core.state.ignore_streak(moscow(2026, 11, 4).date()), 0)
        self.assertTrue(any(t.startswith("☀️") for t, _ in self.api.sent[-3:]), "обычный брифинг, а не протокол игнора")
