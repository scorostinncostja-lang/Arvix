"""Навыки головы (D33): библиотека через --plugin-dir, в 🟥 — только мягкие."""

from __future__ import annotations

import re

from arvix.brain import HEAD_SKILLS, Brain, gentle_violation

from tests.test_telegram import BotCase


def plugin_dirs(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == "--plugin-dir"]


class HeadSkillsTest(BotCase):
    def test_full_library_in_normal_mode(self) -> None:
        cmd = Brain(self.core.cfg).command(system="s", prompt="p", schema={}, role="voice", vault_tools=True, web=True, skills="full")
        self.assertEqual(plugin_dirs(cmd), [str(HEAD_SKILLS / "gentle"), str(HEAD_SKILLS / "full")])
        self.assertIn("Skill", cmd[cmd.index("--tools") + 1].split(","))
        self.assertNotIn("--disable-slash-commands", cmd)  # навыки — тоже слеш-команды, иначе не загрузятся

    def test_without_skills_slash_commands_stay_disabled(self) -> None:
        cmd = Brain(self.core.cfg).command(system="s", prompt="p", schema={}, role="analyst", vault_tools=False)
        self.assertEqual(plugin_dirs(cmd), [])
        self.assertIn("--disable-slash-commands", cmd)

    def test_owner_skill_dirs_only_in_full_and_only_if_present(self) -> None:
        extra = self.tmp / "study-desk"
        extra.mkdir()
        self.core.cfg.raw.setdefault("brain", {})["skill_dirs"] = [str(extra), str(self.tmp / "missing")]
        brain = Brain(self.core.cfg)
        self.assertIn(str(extra), brain.skill_plugins("full"))
        self.assertNotIn(str(self.tmp / "missing"), brain.skill_plugins("full"))
        self.assertNotIn(str(extra), brain.skill_plugins("gentle"))

    def test_red_mode_gets_only_gentle_skills(self) -> None:
        self.brain.answers.append({"reply": "Слышу тебя.", "actions": []})
        self.text("давай просто поговорим")
        self.assertEqual(self.brain.calls[-1]["skills"], "full")
        self.core.sos(True, note="тяжело")
        self.brain.answers.append({"reply": "Я рядом.", "actions": []})
        self.text("мне тревожно")
        self.assertEqual(self.brain.calls[-1]["skills"], "gentle")

    def test_library_is_well_formed_and_gentle_part_has_no_pressure(self) -> None:
        skills = sorted(HEAD_SKILLS.glob("*/skills/*/SKILL.md"))
        self.assertGreaterEqual(len(skills), 6)
        for path in skills:
            text = path.read_text(encoding="utf-8")
            fm = re.match(r"---\nname: ([\w-]+)\ndescription: (.+?)\n---\n", text, re.S)
            self.assertIsNotNone(fm, path)
            self.assertEqual(fm.group(1), path.parent.name)
            self.assertLessEqual(len(fm.group(2)), 1024)
        for path in HEAD_SKILLS.glob("gentle/skills/*/SKILL.md"):
            body = path.read_text(encoding="utf-8").split("## Тон")[0]  # в «Тоне» эти слова стоят под запретом
            self.assertFalse(gentle_violation(body), path)

    def test_gentle_check_matches_word_starts_only(self) -> None:
        """«Одна маленькая вещь» — совет самого 🟥; раньше «лень» внутри слова отправляло ответ на перегенерацию."""
        self.assertFalse(gentle_violation("Сделай одну маленькую вещь и отдыхай."))
        self.assertTrue(gentle_violation("Это лень, а не усталость."))
        self.assertTrue(gentle_violation("Сегодня +20 XP"))
        self.assertTrue(gentle_violation("Дисциплина важнее"))
