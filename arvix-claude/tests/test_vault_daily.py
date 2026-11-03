"""Ежедневный отчёт по шаблону, бюджет нагрузки, перегруз, сброс вопроса."""

import json
import unittest
from datetime import timedelta

from arvix import daily_note, rules
from arvix.vault import parse_frontmatter

from tests.helpers import ArvixCase, moscow

TEMPLATE = """---
date:
  "{ date }":
day:
week:
type: daily
wake:
sleep:
phone_h:
focus_min:
workout:
---
# День {{date}}

## Задачи
- [ ] 

## Отчёт
- Один вывод на завтра:
"""


class DailyNoteTest(ArvixCase):
    def setUp(self) -> None:
        super().setUp()
        (self.vault / ".obsidian" / "daily-notes.json").write_text(
            json.dumps({"folder": "08_Daily Report", "format": "YYYY-MM-DD", "template": "05_System/Шаблоны/Шаблон отчёта"}), encoding="utf-8")
        (self.vault / "05_System" / "Шаблоны").mkdir(parents=True)
        (self.vault / "05_System" / "Шаблоны" / "Шаблон отчёта.md").write_text(TEMPLATE, encoding="utf-8")

    def test_ensure_creates_from_human_template(self) -> None:
        self.core.add_task("Математика ОГЭ", start="16:00", duration_min=60, importance=4)
        rel = daily_note.ensure(self.core, self.core.today())
        self.assertEqual(rel, "08_Daily Report/2026-11-02.md")
        text = (self.vault / rel).read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        self.assertEqual((fields["date"], fields["day"], fields["week"]), ("2026-11-02", "1", "1"))
        self.assertNotIn("{ date }", text)
        self.assertIn("- [ ] 16:00 Математика ОГЭ (60 мин)", text)
        self.assertIn("# День 2026-11-02", text)

    def test_sync_fills_only_empty_fields_and_keeps_human_text(self) -> None:
        task = self.core.add_task("Зал", start="11:00", sphere="sport", importance=2)
        self.core.complete_task(task.id, report="жим 3×8", proof_kind="photo")
        self.core.log_sleep("7:30", bedtime="23:30")
        rel = daily_note.ensure(self.core, self.core.today())
        path = self.vault / rel
        path.write_text(path.read_text(encoding="utf-8").replace("phone_h:", "phone_h: 3").replace("- Один вывод на завтра:", "- Один вывод на завтра: лечь раньше"), encoding="utf-8")
        self.core.complete_debrief("день норм", conclusion="Завтра зал в 11:00 снова.")
        daily_note.sync(self.core, self.core.today())
        daily_note.sync(self.core, self.core.today())
        text = path.read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        self.assertEqual((fields["sleep"], fields["wake"], fields["workout"], fields["phone_h"]), ("7ч30", "07:00", "да", "3"))
        self.assertIn("лечь раньше", text)
        self.assertEqual(text.count("<!-- arvix:день -->"), 1)
        self.assertIn("Завтра зал в 11:00 снова.", text)

    def test_past_days_are_not_created(self) -> None:
        self.assertIsNone(daily_note.sync(self.core, self.core.today() - timedelta(days=3)))


class BudgetTest(ArvixCase):
    def test_review_rules(self) -> None:
        up = rules.review_budget(week_min=600, deep_min=210, completion_avg=82, sleep_avg=450, red_days=0, yellow_days=1, days_with_data=20)
        self.assertEqual(up[:3], (720, 270, "up"))
        down = rules.review_budget(week_min=600, deep_min=210, completion_avg=90, sleep_avg=450, red_days=3, yellow_days=0, days_with_data=20)
        self.assertEqual(down[2], "down")
        self.assertLess(down[0], 600)
        hold = rules.review_budget(week_min=600, deep_min=210, completion_avg=60, sleep_avg=450, red_days=0, yellow_days=0, days_with_data=20)
        self.assertEqual(hold[:3], (600, 210, "hold"))
        few = rules.review_budget(week_min=600, deep_min=210, completion_avg=95, sleep_avg=450, red_days=0, yellow_days=0, days_with_data=4)
        self.assertEqual(few[2], "hold")

    def test_budget_starts_from_interview_and_is_reviewed_after_four_weeks(self) -> None:
        self.core.interview_answer("study_hours", "10 часов, максимум 12")
        self.assertEqual(self.core.budget()["week_min"], 600)
        for offset in range(27):
            day = moscow(2026, 11, 2, 9) + timedelta(days=offset)
            self.at(day)
            task = self.core.add_task(f"Учёба {offset}", start="18:00", duration_min=60, importance=2, sphere="work")
            self.core.complete_task(task.id)
            self.core.log_sleep("7:45")
        self.at(moscow(2026, 11, 30, 9))
        self.core.refresh()
        budget = self.core.budget()
        self.assertEqual(budget["verdict"], "up")
        self.assertEqual(budget["week_min"], 720)
        self.at(moscow(2026, 12, 1, 9))
        self.core.refresh()
        self.assertEqual(sum(1 for e in self.core.store.read(0) if e.kind == "budget_set"), 1)

    def test_load_warnings(self) -> None:
        self.core.profile_set("bedtime_target", "23:00")
        self.core.profile_set("week_budget_min", "240")
        self.core.add_task("Марафон", start="12:00", duration_min=280, deep_work=True)
        self.core.add_task("Поздно", start="22:30", duration_min=30)
        warnings = " | ".join(self.core.load_check())
        self.assertIn("неделя перегружена", warnings)
        self.assertIn("день перегружен", warnings)
        self.assertIn("больше 4 ч", warnings)
        self.assertIn("меньше часа до отбоя", warnings)

    def test_interview_reset_asks_again(self) -> None:
        self.core.interview_answer("learning_style", "дубль")
        self.core.interview_reset("learning_style", reason="дубль после обрыва сети")
        self.assertNotIn("learning_style", self.core.state.interview)


if __name__ == "__main__":
    unittest.main()
