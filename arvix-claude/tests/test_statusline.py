"""Строка состояния Claude Code: цифры в норме, без цифр в 🟥, CLI не падает."""

import json
import os
import subprocess
import sys
import unittest

from arvix.statusline import render

from tests.helpers import ROOT, ArvixCase


class StatuslineTest(ArvixCase):
    def test_normal_line_has_mode_hp_day_and_next_block(self) -> None:
        core = self.core
        core.add_task("Алгоритмы: графы", start="16:00", duration_min=90, importance=4, deep_work=True)
        done = core.add_task("Английский", start="09:00", duration_min=30, importance=2)
        core.complete_task(done.id)
        line = render(core, {"context_window": {"used_percentage": 12.4}})
        self.assertIn("🟩 НОРМА", line)
        self.assertIn("ур.1", line)
        self.assertIn("HP 100", line)
        self.assertIn("сегодня 1/2", line)
        self.assertIn("→ 16:00 Алгоритмы: графы", line)
        self.assertIn("ctx 12%", line)

    def test_active_task_and_debt(self) -> None:
        core = self.core
        task = core.add_task("Физика", start="11:00", duration_min=60, importance=5)
        core.start_task(task.id)
        debt = core.add_task("Долг по матану", start="08:00", duration_min=60, importance=4)
        core.fail_task(debt.id, reason="проспал")
        line = render(core)
        self.assertIn("▶ Физика", line)
        self.assertIn("долг 1", line)

    def test_red_mode_hides_numbers(self) -> None:
        self.core.add_task("Задача", start="18:00")
        self.core.sos(True)
        line = render(self.core)
        self.assertIn("КРАСНЫЙ", line)
        self.assertNotIn("HP", line)
        self.assertNotIn("сегодня", line)
        self.assertNotIn("Задача", line)

    def test_cli_prints_a_line(self) -> None:
        env = {**os.environ, "ARVIX_DATA_DIR": str(self.tmp / "data"), "ARVIX_CONFIG_DIR": str(self.tmp / "cfg"), "ARVIX_LOCAL": "1"}
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "arvix_cli.py"), "statusline"],
            input=json.dumps({"context_window": {"used_percentage": 3}}), capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("НОРМА", result.stdout)
        self.assertIn("ctx 3%", result.stdout)


if __name__ == "__main__":
    unittest.main()
