"""Сон без ручного ввода (D48): «спокойной ночи» — отбой, первое сообщение утром — подъём,
код сводит их в догадку, человек подтверждает одним касанием. Молча догадка не пишется:
от сна зависит режим, а последнее сообщение — не момент засыпания."""

from __future__ import annotations

from arvix.web import api
from tests.helpers import moscow
from tests.test_telegram import BotCase


class SleepAutoTest(BotCase):
    start = moscow(2026, 11, 2, 21, 0)

    def night(self, bed_text: str, bed_at: tuple[int, int, int], wake_at: tuple[int, int, int]) -> None:
        self.at(moscow(2026, 11, bed_at[0], bed_at[1], bed_at[2]))
        self.brain.answers.append({"reply": "Спокойной ночи.", "actions": []})
        self.text(bed_text)
        self.at(moscow(2026, 11, wake_at[0], wake_at[1], wake_at[2]))
        self.brain.answers.append({"reply": "Доброе утро.", "actions": []})
        self.text("привет")
        self.at(moscow(2026, 11, wake_at[0], wake_at[1], wake_at[2] + 1))
        self.scheduler.tick()

    def test_goodnight_notes_bedtime_and_head_still_answers(self) -> None:
        """Отбой пишет код, а ответ — по-прежнему один, от головы (D46): шаблон «Отбой — 00:40» был бы холоднее."""
        self.at(moscow(2026, 11, 3, 0, 40))
        self.brain.answers.append({"reply": "Спокойной ночи.", "actions": []})
        self.text("спокойной ночи")
        self.assertEqual(self.core.state.days[self.core.today()].bed_noted, "00:40")
        self.assertEqual(len(self.brain.calls), 1)
        self.assertEqual(len(self.api.sent), 1)

    def test_goodnight_before_midnight_belongs_to_next_morning(self) -> None:
        self.at(moscow(2026, 11, 2, 23, 50))
        self.brain.answers.append({"reply": "Спокойной ночи.", "actions": []})
        self.text("всё, иду спать")
        self.assertEqual(self.core.state.days[moscow(2026, 11, 3).date()].bed_noted, "23:50")

    def test_go_to_sleep_in_daytime_is_a_conversation(self) -> None:
        self.at(moscow(2026, 11, 2, 15, 0))
        self.brain.answers.append({"reply": "Днём лучше 20 минут.", "actions": []})
        self.text("иду спать")
        self.assertEqual(len(self.brain.calls), 1)

    def test_morning_question_pairs_bedtime_with_first_message(self) -> None:
        self.night("иду спать", (2, 23, 50), (3, 7, 50))
        text, buttons = self.api.sent[-1]
        self.assertIn("23:50", text)
        self.assertIn("07:50", text)
        self.assertIn(("✅ Да, 8ч00м", "z:ok:23:50-07:50"), buttons[0])
        self.assertIsNone(self.core.state.days[self.core.today()].sleep_min)  # без подтверждения не пишется
        calls = len(self.brain.calls)
        self.press("z:ok:23:50-07:50")
        self.assertEqual(self.core.state.days[self.core.today()].sleep_min, 480)
        self.assertEqual(len(self.brain.calls), calls)

    def test_last_night_message_is_the_bedtime_guess(self) -> None:
        self.at(moscow(2026, 11, 3, 0, 30))
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.text("завтра контрольная по физике")
        self.at(moscow(2026, 11, 3, 8, 0))
        self.brain.answers.append({"reply": "Доброе утро.", "actions": []})
        self.text("привет")
        self.at(moscow(2026, 11, 3, 8, 1))
        self.scheduler.tick()
        text, buttons = self.api.sent[-1]
        self.assertIn("последнее сообщение", text)
        self.assertIn(("✅ Да, 7ч30м", "z:ok:00:30-08:00"), buttons[0])

    def test_asked_once_and_correction_by_text(self) -> None:
        self.night("спокойной ночи", (2, 23, 0), (3, 7, 0))
        self.scheduler.tick()
        self.assertEqual(sum("Так?" in t for t in self.api.texts), 1)
        self.text("лёг в час, встал в 6:30")
        self.assertEqual(self.core.state.days[self.core.today()].sleep_min, 330)

    def test_no_question_when_sleep_already_recorded(self) -> None:
        self.at(moscow(2026, 11, 3, 7, 0))
        self.core.log_sleep("7:30", source="telegram")
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.text("привет")
        self.at(moscow(2026, 11, 3, 7, 1))
        self.scheduler.tick()
        self.assertFalse(any("Так?" in t or "Как спал" in t for t in self.api.texts))

    def test_bedtime_reminder_has_lying_down_button(self) -> None:
        self.core.profile_set("bedtime_target", "23:30")
        self.at(moscow(2026, 11, 2, 23, 5))
        self.scheduler.tick()
        reminder = next(b for t, b in self.api.sent if t.startswith("🌙"))
        self.assertIn(("🌙 Ложусь", "z:bed"), reminder[0])
        self.at(moscow(2026, 11, 2, 23, 40))
        self.press("z:bed")
        self.assertEqual(self.core.state.days[moscow(2026, 11, 3).date()].bed_noted, "23:40")

    def test_web_card_gets_the_guess(self) -> None:
        self.night("спокойной ночи", (2, 23, 30), (3, 7, 30))
        guess = api.state_view(self.core)["stats"]["sleep_guess"]
        self.assertEqual((guess["bedtime"], guess["wake"], guess["duration_min"]), ("23:30", "07:30", 480))
