"""Правило №5 CLAUDE.md: в 🟥 и при mentor_enabled = false жёсткие тон-блоки,
жёсткие примеры и «отказ с цифрой» физически не попадают в промпт."""

import json
import re
import subprocess
import sys
import unittest

from arvix import prompt
from arvix.prompt import HARSH_TONES, hook_context, read_block, render_output_style, system_prompt

from tests.helpers import ROOT, ArvixCase

HARSH_EXAMPLES = [e["arvix"] for e in json.loads((ROOT / "arvix" / "constitution" / "fewshot.json").read_text(encoding="utf-8")) if e["harsh"]]


class PromptSafetyTest(ArvixCase):
    def assert_gentle(self, text: str) -> None:
        for name in HARSH_TONES:
            self.assertNotIn(read_block(name), text, name)
        for example in HARSH_EXAMPLES:
            self.assertNotIn(example, text)
        self.assertNotIn("<decision_rule>", text)
        self.assertIn(read_block("tone_red"), text)
        self.assertNotIn("HP ", text.split("<context>")[-1])  # мягкий контекст — без метрик

    def force_mode(self, mode: str) -> None:
        self.core.emit("mode_changed", {"from": self.core.state.mode, "to": mode, "trigger": "тест"}, source="test")

    def test_red_mode_prompt(self) -> None:
        self.core.add_task("Алгоритмы", importance=4, start="18:00")
        self.force_mode("red")
        self.assert_gentle(system_prompt(self.core, message="всё плохо"))
        self.assert_gentle(hook_context(self.core))

    def test_mentor_off_beats_pressure(self) -> None:
        self.force_mode("pressure")
        self.core.safety_flag("high", "тест")
        self.assert_gentle(system_prompt(self.core))
        self.assert_gentle(hook_context(self.core))

    def test_sos_switches_prompt_to_red(self) -> None:
        self.core.sos(True)
        self.assert_gentle(system_prompt(self.core))

    def test_normal_mode_has_its_tone_and_harsh_examples(self) -> None:
        text = system_prompt(self.core)
        self.assertIn(read_block("tone_norm"), text)
        self.assertNotIn(read_block("tone_red"), text)
        self.assertIn(HARSH_EXAMPLES[0], text)
        self.assertIn("<decision_rule>", text)

    def test_pressure_mode_tone(self) -> None:
        self.force_mode("pressure")
        self.assertIn(read_block("tone_pressure"), hook_context(self.core))

    def test_static_output_style_has_no_tone_or_harsh_content(self) -> None:
        style = render_output_style()
        for name in (*HARSH_TONES, "tone_red"):
            self.assertNotIn(read_block(name), style)
        for example in HARSH_EXAMPLES:
            self.assertNotIn(example, style)
        self.assertNotIn("<decision_rule>", style)


class AssetsTest(unittest.TestCase):
    def test_generated_assets_are_fresh(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_assets.py"), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frontmatter_is_valid_flat_yaml(self) -> None:
        """«ключ: значение» без лишнего «: » внутри значения — иначе YAML не разберётся
        и Claude Code молча потеряет name/description."""
        files = list((ROOT / "skills").glob("*/SKILL.md")) + [ROOT / "output-styles" / "arvix.md"]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), path)
            front = text[4 : text.index("\n---", 4)]
            for line in front.splitlines():
                key, sep, value = line.partition(": ")
                self.assertTrue(sep and re.fullmatch(r"[a-z-]+", key), f"{path}: {line}")
                if not value.startswith('"'):
                    self.assertNotIn(": ", value, f"{path}: {line}")

    def test_name_is_not_hardcoded_in_constitution(self) -> None:
        for path in (ROOT / "arvix" / "constitution").glob("*.md"):
            self.assertNotIn("Aktan", path.read_text(encoding="utf-8"), path)

    def test_no_model_names_in_code(self) -> None:
        """Правило №4: имена моделей — только в конфиге ролей."""
        pattern = re.compile(r"\b(sonnet|opus|haiku|fable|claude-[a-z]+-\d)", re.IGNORECASE)
        for path in (ROOT / "arvix").rglob("*.py"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), path)
        self.assertEqual(prompt.EMERGENCY, "112")


if __name__ == "__main__":
    unittest.main()
