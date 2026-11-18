"""Проверки ввода (02-MECHANICS §13): Арвикс не верит на слово — замечает, объясняет, исправляет."""

import unittest
from datetime import date

from arvix import checks
from arvix.brain import apply_actions
from arvix.context import build_context
from arvix.mcp_server import Server
from arvix.prompt import hook_context, system_prompt

from tests.helpers import ArvixCase, moscow

TODAY = date(2026, 11, 2)


def goal(gid: str, title: str, **kw) -> dict:
    return {"id": gid, "title": title, "kind": "yearly", "status": "active", "deadline": "2027-05-30", "metric": "оценка 5", **kw}


class GoalIssuesTest(unittest.TestCase):
    def issues(self, g: dict, *others: dict) -> str:
        goals = {x["id"]: x for x in (g, *others)}
        return " | ".join(checks.goal_issues(g, goals, TODAY))

    def test_good_goal_and_dream_pass(self) -> None:
        self.assertEqual(self.issues(goal("a", "ОГЭ: математика на 5")), "")
        self.assertEqual(self.issues({"id": "d", "title": "Своя игровая студия", "kind": "dream", "status": "active"}), "")

    def test_missing_deadline_and_metric(self) -> None:
        text = self.issues(goal("a", "Стать лучше", deadline=None, metric=None))
        self.assertIn("нет срока", text)
        self.assertIn("нет метрики", text)

    def test_past_and_too_far_deadline(self) -> None:
        self.assertIn("уже прошёл", self.issues(goal("a", "Английский B1", deadline="2026-09-01")))
        self.assertIn("это мечта", self.issues(goal("a", "Своя компания", deadline="2034-01-01")))

    def test_duplicate_second_main_and_too_many(self) -> None:
        base = goal("a", "Выучить английский до B1", kind="main")
        self.assertIn("дубль", self.issues(goal("b", "Английский B1 к маю"), base))
        self.assertIn("главная цель уже есть", self.issues(goal("c", "Похудеть на 5 кг", kind="main"), base))
        many = [goal(x, f"Цель номер {x} про разное {i}") for i, x in enumerate("pqr")]
        self.assertIn("4-я активная цель года", self.issues(goal("s", "Научиться плавать"), *many))

    def test_stage_without_parent_or_past_parent_deadline(self) -> None:
        self.assertIn("без родительской", self.issues(goal("m", "Задания 1–12", kind="milestone")))
        parent = goal("p", "ОГЭ", deadline="2027-05-30")
        late = goal("m", "Пробник 25 баллов", kind="milestone", parent_id="p", deadline="2027-06-15")
        self.assertIn("позже цели", self.issues(late, parent))


class CoreChecksTest(ArvixCase):
    def test_task_overlap_fixed_bedtime_length_past(self) -> None:
        self.core.profile_set("bedtime_target", "23:00")
        self.core.set_template([0], "study", [{"start": "08:30", "duration": 360, "title": "Школа", "fixed": True}])
        algebra = self.core.add_task("Алгебра", start="16:00", duration_min=90)
        text = " | ".join(self.core.task_warnings(self.core.add_task("Физика", start="16:30", duration_min=60)))
        self.assertIn("пересекается с «Алгебра»", text)
        self.assertIn("обязательное «Школа»", " | ".join(self.core.task_warnings(self.core.add_task("Чтение", start="12:00", duration_min=30))))
        self.assertIn("меньше часа до отбоя", " | ".join(self.core.task_warnings(self.core.add_task("Поздно", start="22:30", duration_min=30))))
        self.assertIn("разбей", " | ".join(self.core.task_warnings(self.core.add_task("Марафон", start="17:00", duration_min=240, day="tomorrow"))))
        self.assertIn("уже прошло", " | ".join(self.core.task_warnings(self.core.add_task("Утро", start="07:00", duration_min=30))))
        # Утренняя задача — не «впритык к отбою»: раньше всё, что кончалось до полудня, считалось завтрашней ночью
        self.assertNotIn("до отбоя", " | ".join(self.core.task_warnings(self.core.add_task("Зарядка", start="09:00", duration_min=60, day="tomorrow"))))
        self.core.profile_set("bedtime_target", "00:30")
        self.assertIn("до отбоя", " | ".join(self.core.task_warnings(self.core.add_task("Ночью", start="23:45", duration_min=30, day="tomorrow"))))
        self.assertNotIn("до отбоя", " | ".join(self.core.task_warnings(self.core.add_task("Вечер", start="20:00", duration_min=60, day="tomorrow"))))
        self.assertEqual(self.core.task_warnings(algebra), [f"пересекается с «Физика» 16:30–17:30"])

    def test_report_that_numbers_do_not_believe(self) -> None:
        """Отчёт записывается, но сомнение видно — и в ответе, и в журнале для разбора."""
        future = self.core.add_task("Английский", start="18:00", duration_min=60, importance=2, sphere="work")
        result = self.core.complete_task(future.id)
        self.assertIn("стоит на 18:00, а отмечена в 10:00", result["warnings"][0])
        task = self.core.add_task("Алгоритмы", start="10:00", duration_min=90, importance=2, sphere="work")
        self.core.start_task(task.id)
        self.at(moscow(2026, 11, 2, 10, 30))
        result = self.core.complete_task(task.id)
        self.assertIn("прошло 30 мин из 90", result["warnings"][0])
        doubts = [e.payload.get("doubts") for e in self.core.store.read(0) if e.kind == "task_completed"]
        self.assertTrue(all(doubts))
        self.assertEqual(self.core.complete_task(self.core.add_task("Честно", start="09:00", duration_min=30, sphere="work", importance=2).id)["warnings"], [])

    def test_implausible_sleep(self) -> None:
        self.assertIn("опечатку", self.core.log_sleep("15")["warnings"][0])
        self.assertEqual(self.core.log_sleep("8:10")["warnings"], [])

    def test_audit_reaches_model_context_but_not_red(self) -> None:
        self.core.interview_answer("sleep", "сейчас 02:00–08:00, хочу 01:00–07:00")
        self.core.interview_answer("main_goal", "Стать программистом")
        self.core.interview_answer("main_goal_why", "Нравится")
        text = build_context(self.core)
        self.assertIn("ПРОВЕРИТЬ:", text)
        self.assertIn("нет срока", text)
        self.assertIn("меньше 7 ч", text)
        self.core.sos(True)
        self.assertNotIn("ПРОВЕРИТЬ", build_context(self.core))

    def test_model_fixes_a_goal_through_actions(self) -> None:
        """Голова получила ⚠️, исправила цель тем же id — сомнений больше нет."""
        done, failed, warnings = apply_actions(self.core, [{"type": "set_goal", "title": "Японский N2 к лету", "why": "аниме", "kind": "yearly"}])
        self.assertEqual(failed, [])
        self.assertTrue(any("нет срока" in w for w in warnings))
        gid = next(iter(self.core.state.goals))  # в квитанции для человека id больше нет
        done, failed, warnings = apply_actions(self.core, [{"type": "set_goal", "goal_id": gid, "kind": "dream"}])
        self.assertEqual((failed, warnings), ([], []))
        self.assertEqual(self.core.state.goals[gid]["kind"], "dream")
        self.assertEqual(self.core.state.goals[gid]["title"], "Японский N2 к лету")

    def test_mcp_tools_surface_doubts(self) -> None:
        server = Server(lambda: self.core)
        out = server.call_tool("profile", {"action": "goal", "title": "Стать лучше", "why": "надо"})["content"][0]["text"]
        self.assertIn("⚠️ Проверь", out)
        self.assertIn("не продолжай молча", out)
        clean = server.call_tool("profile", {"action": "goal", "title": "ОГЭ математика", "why": "профильный класс",
                                             "deadline": "2027-05-30", "metric": "оценка 5", "kind": "yearly"})["content"][0]["text"]
        self.assertNotIn("⚠️", clean)


class CriticalPromptTest(ArvixCase):
    def test_critical_thinking_is_in_normal_prompts_only(self) -> None:
        self.assertIn("<critical_thinking>", system_prompt(self.core))
        self.assertIn("<critical_thinking>", hook_context(self.core))
        self.core.sos(True)
        self.assertNotIn("<critical_thinking>", system_prompt(self.core))
        self.assertNotIn("<critical_thinking>", hook_context(self.core))

    def test_sleep_target_below_seven_hours_is_flagged(self) -> None:
        self.assertEqual(checks.sleep_target_issues(510), [])
        self.assertTrue(checks.sleep_target_issues(360))


if __name__ == "__main__":
    unittest.main()
