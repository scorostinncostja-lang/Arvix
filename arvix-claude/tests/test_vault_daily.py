"""Ежедневный отчёт по шаблону, бюджет нагрузки, перегруз, сброс вопроса."""

import json
import unittest
from datetime import timedelta

from arvix import daily_note, load
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
        f = dict(load.START_FACTORS)
        ok = {"deep": {"planned": 300, "done": 290}, "sport": {"planned": 120, "done": 120}}
        base = {"days_with_data": 6, "red_days": 0, "yellow_days": 0, "sleep_avg": 460, "sleep_target": 450, "hp_drop": 0}
        first = load.review(f, channels=ok, streaks={}, **base)
        self.assertEqual(first["verdict"], "hold")  # рост только после двух недель
        self.assertEqual(first["streaks"]["deep"], 1)
        second = load.review(first["factors"], channels=ok, streaks=first["streaks"], **base)
        self.assertEqual(second["verdict"], "up")
        self.assertAlmostEqual(second["factors"]["deep"], 0.75)
        weak = load.review(f, channels={"learning": {"planned": 300, "done": 100}}, streaks={}, **base)
        self.assertLess(weak["factors"]["learning"], f["learning"])
        burnout = load.review(f, channels=ok, streaks={"deep": 3}, **base | {"red_days": 2, "sleep_avg": 360})
        self.assertEqual(burnout["verdict"], "down")
        self.assertAlmostEqual(burnout["factors"]["deep"], 0.55)
        self.assertAlmostEqual(burnout["factors"]["rest"], 1.2)
        self.assertEqual(burnout["streaks"]["deep"], 0)
        few = load.review(f, channels=ok, streaks={}, **base | {"days_with_data": 2})
        self.assertEqual(few["factors"], f)
        floor = load.review({**f, "deep": 0.5}, channels=ok, streaks={}, **base | {"red_days": 5})
        self.assertEqual(floor["factors"]["deep"], 0.5)

    def test_fixed_blocks_are_never_scaled(self) -> None:
        factors = {**load.START_FACTORS, "learning": 0.5}
        self.assertEqual(load.scaled_duration({"title": "Школа", "sphere": "learning", "duration": 400}, factors), 400)
        self.assertEqual(load.scaled_duration({"title": "Алгебра", "sphere": "learning", "duration": 90}, factors), 45)
        self.assertEqual(load.scaled_duration({"title": "Что угодно", "fixed": True, "duration": 30}, factors), 30)
        self.assertEqual(load.scaled_duration({"title": "Мелочь", "duration": 20}, {**factors, "other": 0.5}), load.MIN_BLOCK)

    def test_budget_starts_from_interview_without_templates(self) -> None:
        self.core.interview_answer("study_hours", "10 часов, максимум 12")
        self.assertEqual(self.core.budget()["week_min"], 600)
        self.assertFalse(self.core.budget()["auto"])

    def test_auto_load_scales_templates_and_reviews_weekly(self) -> None:
        self.at(moscow(2026, 11, 2, 6))
        blocks = [
            {"start": "08:30", "duration": 360, "title": "Школа", "sphere": "learning"},
            {"start": "17:00", "duration": 100, "title": "Математика ОГЭ", "sphere": "learning", "deep_work": True},
            {"start": "19:30", "duration": 60, "title": "Бег", "sphere": "sport"},
        ]
        self.core.set_template([0, 1, 2, 3, 4, 5, 6], "study", blocks)
        budget = self.core.budget()
        self.assertTrue(budget["auto"])
        self.assertEqual(budget["channels"]["deep"], 70 * 7)  # старт 0.7
        self.assertEqual(budget["channels"]["fixed"], 360 * 7)
        for offset in range(7):
            day = moscow(2026, 11, 2, 6) + timedelta(days=offset)
            self.at(day)
            self.core.refresh()
            tasks = {t.title: t for t in self.core.state.tasks_on(day.date())}
            self.assertEqual(tasks["Математика ОГЭ"].duration_min, 70)
            self.assertEqual(tasks["Школа"].duration_min, 360)
            for task in tasks.values():
                self.core.complete_task(task.id, report="сделал")
            self.core.log_sleep("7:45")
        self.at(moscow(2026, 11, 9, 6))
        self.core.refresh()
        first = self.core.budget()
        self.assertEqual(first["verdict"], "hold")
        self.assertEqual(first["since"], "2026-11-09")
        self.assertEqual(sum(1 for e in self.core.store.read(0) if e.kind == "budget_set"), 1)
        self.at(moscow(2026, 11, 10, 6))
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
