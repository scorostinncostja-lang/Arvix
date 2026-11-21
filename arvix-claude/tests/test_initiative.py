"""Arvix пишет первым по важному поводу (D59) и думает вслух: паттерны в контексте, мнение о пропусках.

Повод и гигиену проверяет код (arvix/initiative.py), слова и «стоит ли» — голова."""

from __future__ import annotations

import json

from arvix import initiative
from arvix.context import build_context
from arvix.prompt import read_block, system_prompt

from tests.helpers import ROOT, moscow
from tests.test_telegram import BotCase


class InitiativeTest(BotCase):
    start = moscow(2026, 11, 2, 10, 0)  # понедельник

    def setUp(self) -> None:
        super().setUp()
        self.math = self.core.add_task("Математика ОГЭ: задания 20–25", start="10:00", duration_min=30, importance=4)

    def tick(self, hh: int, mm: int) -> None:
        self.at(moscow(2026, 11, 2, hh, mm))
        self.scheduler.initiative(self.core.now())

    def calls(self) -> list[dict]:
        return [c for c in self.brain.calls if "<initiative>" in c["raw_prompt"]]

    def test_silent_block_makes_arvix_write_first_with_an_action(self) -> None:
        self.brain.answers.append({"reply": "Математика с 10:00 — тишина. **Ставлю на 13:00, 30 минут.**",
                                   "actions": [{"type": "defer_task", "task": self.math.id, "start": "13:00"}]})
        self.tick(10, 50)  # кончилась в 10:30, прошло 20 минут — ещё рано
        self.assertEqual(self.calls(), [])
        self.tick(11, 15)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("БЛОК ПРОШЁЛ, ОТЧЁТА НЕТ", self.calls()[0]["raw_prompt"])
        self.assertIn("Ставлю на 13:00", self.api.last)
        self.assertEqual(self.core.state.tasks[self.math.id].start, "13:00")  # решил и сделал, а не спросил

    def test_same_reason_is_not_asked_twice_even_if_head_was_silent(self) -> None:
        self.brain.answers.append({"reply": "", "actions": []})  # голова решила: писать незачем
        self.tick(11, 15)
        sent = len(self.api.sent)
        self.tick(12, 30)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(len(self.api.sent), sent)

    def test_no_daily_quota_only_a_gap(self) -> None:
        eng = self.core.add_task("Английский: карточки", start="10:20", duration_min=20)  # молчит с 11:20
        self.brain.answers += [{"reply": "Про математику.", "actions": []}, {"reply": "Про английский.", "actions": []}]
        self.tick(11, 15)  # только математика: английский молчит лишь с 11:20
        self.tick(11, 30)  # английский уже повод, но с прошлого раза меньше GAP_MIN
        self.assertEqual(len(self.calls()), 1)
        self.tick(11, 56)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn(eng.id, self.calls()[1]["raw_prompt"])

    def test_red_mode_focus_and_conversation_keep_quiet(self) -> None:
        self.core.store.kv_set("focus", {"until": "x"})
        self.tick(11, 15)
        self.core.store.kv_del("focus")
        self.core.store.kv_set("last_in_at", moscow(2026, 11, 2, 11, 20).timestamp())
        self.tick(11, 25)
        self.core.store.kv_del("last_in_at")
        self.core.sos(True)
        self.tick(11, 50)
        self.assertEqual(self.calls(), [])

    def test_night_is_quiet(self) -> None:
        self.core.add_task("Чтение", start="22:30", duration_min=30)
        self.tick(23, 45)
        self.assertEqual(self.calls(), [])


class PatternTest(BotCase):
    start = moscow(2026, 11, 9, 10, 0)

    def test_recurring_misses_reach_context(self) -> None:
        for day in (2, 4, 6):
            task = self.core.add_task(f"Физика: §1{day}", start="18:00", duration_min=40, day=f"2026-11-0{day}")
            self.core.fail_task(task.id, reason="устал")
        found = initiative.patterns(self.core)
        self.assertEqual(found[0]["topic"], "Физика")
        self.assertEqual(found[0]["missed"], 3)
        self.assertIn("ПАТТЕРНЫ", build_context(self.core))
        self.assertIn("«Физика» за 14 дней: 3 блоков, сделано 0, не сделано 3", build_context(self.core))

    def test_one_miss_is_not_a_pattern(self) -> None:
        task = self.core.add_task("Химия", start="18:00", duration_min=40, day="2026-11-05")
        self.core.fail_task(task.id)
        self.assertEqual(initiative.patterns(self.core), [])


class MindPromptTest(BotCase):
    def test_opinion_block_is_in_normal_prompt_and_absent_in_red(self) -> None:
        self.assertIn(read_block("mentor_mind"), system_prompt(self.core, message="не сделал"))
        self.assertIn(read_block("depth"), system_prompt(self.core, message="не сделал"))
        self.core.sos(True)
        red = system_prompt(self.core, message="не сделал")
        self.assertNotIn(read_block("mentor_mind"), red)  # правило №5: о пропусках в 🟥 не говорим
        self.assertIn(read_block("depth"), red)

    def test_examples_have_no_mug_slogans(self) -> None:
        examples = json.loads((ROOT / "arvix" / "constitution" / "fewshot.json").read_text(encoding="utf-8"))
        for e in examples:
            for cliche in ("победив себя", "терпение и труд", "зоны комфорта", "верь в себя", "ты сможешь"):
                self.assertNotIn(cliche, e["arvix"].lower(), e["situation"])
