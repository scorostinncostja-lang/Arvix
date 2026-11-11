"""Настройка без вопросов: автоопределение папок хранилища, конфиг, дом Арвикса."""

import json
import os
import subprocess
import sys
import tomllib
import unittest

from arvix.cli import merge_home_settings
from arvix.vault import detect_paths

from tests.helpers import ROOT, ArvixCase


class DetectPathsTest(ArvixCase):
    def make_vault(self) -> None:
        v = self.vault
        (v / "02_Areas" / "Роадмапы").mkdir(parents=True)
        (v / "00_Inbox").mkdir()
        (v / "00_Inbox" / "Входящие.md").write_text("# Inbox\n", encoding="utf-8")
        (v / "05_System" / "Templates").mkdir(parents=True)
        (v / "05_System" / "Templates" / "Daily Report.md").write_text("---\ndate:\n---\n", encoding="utf-8")
        (v / ".obsidian" / "daily-notes.json").write_text(
            json.dumps({"folder": "08_Daily Report", "template": "05_System/Шаблоны/Шаблон отчёта"}), encoding="utf-8"
        )
        (v / ".obsidian" / "templates.json").write_text(json.dumps({"folder": "05_System/Templates"}), encoding="utf-8")

    def test_finds_roadmaps_inbox_and_template(self) -> None:
        self.make_vault()
        found = detect_paths(self.vault)
        self.assertEqual(found["roadmaps"], "02_Areas/Роадмапы")
        self.assertEqual(found["inbox"], "00_Inbox/Входящие.md")
        # настройка Obsidian указывает на несуществующий шаблон → берём файл из папки шаблонов
        self.assertEqual(found["daily_template"], "05_System/Templates/Daily Report.md")
        self.assertNotIn("goals", found)

    def test_existing_obsidian_template_wins(self) -> None:
        self.make_vault()
        (self.vault / "05_System" / "Шаблоны").mkdir()
        (self.vault / "05_System" / "Шаблоны" / "Шаблон отчёта.md").write_text("---\n---\n", encoding="utf-8")
        self.assertNotIn("daily_template", detect_paths(self.vault))

    def test_empty_vault(self) -> None:
        self.assertEqual(detect_paths(self.vault), {})

    def test_setup_without_questions(self) -> None:
        self.make_vault()
        home = self.tmp / "home"
        env = {**os.environ, "ARVIX_DATA_DIR": str(self.tmp / "data"), "ARVIX_CONFIG_DIR": str(self.tmp / "cfg"), "ARVIX_LOCAL": "1"}
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "arvix_cli.py"), "setup", "--vault", str(self.vault), "--tz", "Europe/Moscow",
             "--home", str(home), "--no-telegram", "--yes"],
            capture_output=True, text=True, env=env, check=False, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        cfg = tomllib.loads((self.tmp / "cfg" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg["vault"], str(self.vault))
        self.assertEqual(cfg["timezone"], "Europe/Moscow")
        self.assertEqual(cfg["vault_paths"]["roadmaps"], "02_Areas/Роадмапы")
        self.assertNotIn("telegram", cfg)
        self.assertTrue((home / ".arvix-home").exists())
        settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["outputStyle"], "arvix:Arvix")
        self.assertIn("statusline", settings["statusLine"]["command"])
        self.assertIn(str(self.vault), settings["permissions"]["additionalDirectories"])

    def test_merge_keeps_user_changes(self) -> None:
        current = {"outputStyle": "Explanatory", "permissions": {"allow": ["Bash(ls *)"]}}
        wanted = {"outputStyle": "arvix:Arvix", "statusLine": {"type": "command", "command": "x"},
                  "permissions": {"allow": ["mcp__plugin_arvix_arvix"], "additionalDirectories": ["/v"]}}
        merged, changed = merge_home_settings(current, wanted)
        self.assertTrue(changed)
        self.assertEqual(merged["outputStyle"], "Explanatory")
        self.assertEqual(merged["statusLine"]["command"], "x")
        self.assertEqual(merged["permissions"]["allow"], ["Bash(ls *)", "mcp__plugin_arvix_arvix"])
        self.assertEqual(merged["permissions"]["additionalDirectories"], ["/v"])
        again, changed = merge_home_settings(merged, wanted)
        self.assertFalse(changed)
        self.assertEqual(again, merged)


if __name__ == "__main__":
    unittest.main()
