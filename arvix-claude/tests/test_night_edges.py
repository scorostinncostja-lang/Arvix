"""Стык суток и забытые ожидания (D53): то, что владелец ломал бы каждую неделю.

- После полуночи, до смены дня (04:00), вчерашнее ещё живо: его видно в приложении и голове,
  проверка «Сделано?» приходит, а не задача молча уходит в долг.
- План урока без ▶️ не глушит проверку в конце блока; «✅ Да» по нему — отчёт, а не второй «Сделано?».
- «Ложусь» — прощание, а не ответ на висящий вопрос; вопрос прошлого дня сгорает на смене дня.
- В ленте приложения у закрытой задачи нет кнопок.
"""

from arvix import context
from arvix.web import api

from tests.helpers import moscow
from tests.test_telegram import BotCase


class AfterMidnight(BotCase):
    start = moscow(2026, 11, 2, 20, 0)

    def test_late_task_gets_its_check_after_midnight(self) -> None:
        task = self.core.add_task("Английский слова", start="23:30", duration_min=40, importance=4, source="telegram")
        self.at(moscow(2026, 11, 3, 0, 15))  # конец блока — уже другое число
        self.scheduler.tick()
        self.assertTrue(any("Сделано: Английский слова" in t for t in self.api.texts))
        self.press(f"t:{task.id}:yes")
        self.text("30 слов из Unit 5")
        self.assertEqual(self.core.state.tasks[task.id].status, "done")
        self.at(moscow(2026, 11, 3, 4, 5))
        self.scheduler.tick()
        self.assertEqual(self.core.state.debts(), [])

    def test_open_yesterday_only_until_rollover(self) -> None:
        task = self.core.add_task("Химия § 12", start="21:00", duration_min=30, source="telegram")
        self.at(moscow(2026, 11, 3, 1, 0))
        self.assertEqual([t.id for t in self.core.open_yesterday()], [task.id])
        view = api.state_view(self.core)
        self.assertEqual([t["id"] for t in view["yesterday"]], [task.id])
        self.assertIn("ВЧЕРА НЕ ЗАКРЫТО", context.build_context(self.core))
        self.at(moscow(2026, 11, 3, 4, 30))
        self.core.refresh()
        self.assertEqual(self.core.open_yesterday(), [])
        self.assertEqual(api.state_view(self.core)["yesterday"], [])

    def test_done_yesterday_is_not_listed(self) -> None:
        task = self.core.add_task("Химия § 12", start="21:00", duration_min=30, source="telegram")
        self.core.complete_task(task.id, report="прочитал", source="telegram")
        self.at(moscow(2026, 11, 3, 1, 0))
        self.assertEqual(self.core.open_yesterday(), [])


class LessonWithoutTimer(BotCase):
    start = moscow(2026, 11, 2, 15, 0)

    def lesson_task(self):  # голова молчит (FakeBrain без ответов) — план кодом, без вопросов проверки
        task = self.core.add_task("Математика ОГЭ вариант", start="16:00", duration_min=60, importance=5,
                                  sphere="learning", deep_work=True, source="telegram")
        self.at(moscow(2026, 11, 2, 16, 0))
        self.scheduler.tick()
        self.assertTrue(self.bot.lesson_pending(task.id))
        return task

    def test_check_comes_even_if_lesson_was_never_started(self) -> None:
        self.lesson_task()
        self.at(moscow(2026, 11, 2, 17, 1))
        self.scheduler.tick()
        self.assertTrue(any("Сделано: Математика" in t for t in self.api.texts))

    def test_yes_on_lesson_without_questions_asks_report_once(self) -> None:
        task = self.lesson_task()
        self.press(f"t:{task.id}:yes")
        self.assertNotIn("Сделано", self.api.last)
        self.text("решил 18 из 31, ошибки в геометрии")
        self.assertEqual(self.core.state.tasks[task.id].status, "done")

    def test_running_lesson_timer_still_owns_the_check(self) -> None:
        task = self.lesson_task()
        self.press(f"l:{task.id}:go")
        self.assertTrue(self.bot.lesson_running(task.id))
        sent = len(self.api.sent)
        self.at(moscow(2026, 11, 2, 16, 59))  # конец блока по плану, таймер ещё идёт
        self.scheduler.reminders(self.core.now())
        self.assertFalse(any("Сделано: Математика" in t for t, _ in self.api.sent[sent:]))


class GoodnightAndStaleQuestions(BotCase):
    start = moscow(2026, 11, 2, 22, 30)

    def test_goodnight_is_not_a_debrief_answer(self) -> None:
        self.bot.send_debrief()
        self.text("ложусь")
        self.assertFalse(self.core.state.days[self.core.today()].debrief)
        self.assertEqual((self.bot.await_get() or {}).get("kind"), "debrief")
        self.assertEqual(self.core.state.days[moscow(2026, 11, 3).date()].bed_noted, "22:30")

    def test_debrief_question_expires_at_rollover(self) -> None:
        self.bot.send_debrief()
        self.at(moscow(2026, 11, 3, 8, 0))
        self.assertIsNone(self.bot.await_get())

    def test_question_after_midnight_lives_until_rollover(self) -> None:
        self.at(moscow(2026, 11, 3, 0, 30))
        self.bot.await_set("report", task="x")
        self.at(moscow(2026, 11, 3, 3, 30))
        self.assertEqual((self.bot.await_get() or {}).get("kind"), "report")

    def test_interview_waits_across_days(self) -> None:
        self.bot.await_set("interview", qid="name")
        self.at(moscow(2026, 11, 5, 10, 0))
        self.assertEqual((self.bot.await_get() or {}).get("kind"), "interview")


class ClosedTaskButtons(BotCase):
    def test_chat_hides_buttons_of_closed_task(self) -> None:
        task = self.core.add_task("Тренировка", start="10:30", duration_min=30, source="telegram")
        other = self.core.add_task("Чтение", start="11:30", duration_min=30, source="telegram")
        self.bot.send("Сделано?", [[("✅ Да", f"t:{task.id}:yes"), ("❌ Нет", f"t:{task.id}:no")],
                                   [("✅ Чтение", f"t:{other.id}:yes")], [("📱 App", "app:open")]])
        self.core.complete_task(task.id, report="3 подхода", source="web")
        buttons = api.messages_view(self.core)[-1]["buttons"]
        flat = [b[1] for row in buttons for b in row]
        self.assertNotIn(f"t:{task.id}:yes", flat)
        self.assertIn(f"t:{other.id}:yes", flat)
        self.assertIn("app:open", flat)
