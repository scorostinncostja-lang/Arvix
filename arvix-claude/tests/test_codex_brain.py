import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from arvix.brain import Brain
from arvix.config import Config


class CodexBrainTest(unittest.TestCase):
    def test_learning_routes_to_codex_with_schema_and_without_shell(self):
        brain = Brain(Config({"roles": {"learning": {"provider": "codex", "codex_model": "fixture"}}}))
        schema = {"type": "object", "required": ["instruction"]}

        def answer(command, **kwargs):
            self.assertIn("shell_tool", command)
            self.assertIn("fixture", command)
            self.assertEqual(command[command.index("--image") + 1], "/fixture.jpg")
            self.assertNotIn("текст задачи", command)
            self.assertIn("текст задачи", kwargs["input"])
            Path(command[command.index("--output-last-message") + 1]).write_text(
                json.dumps({"instruction": "Первый шаг"}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with patch("arvix.codex_brain.subprocess.run", side_effect=answer):
            reply = brain.ask(system="объясни", prompt="текст задачи", schema=schema, role="learning", image=Path("/fixture.jpg"))
        self.assertEqual(reply, {"instruction": "Первый шаг"})

    def test_codex_failure_does_not_trigger_a_second_model(self):
        brain = Brain(Config({"roles": {"learning": {"provider": "codex"}}}))
        with patch("arvix.codex_brain.subprocess.run", side_effect=FileNotFoundError), patch.object(brain, "_ask") as claude:
            self.assertIsNone(brain.ask(system="", prompt="", schema={}, role="learning"))
            claude.assert_not_called()

    def test_default_learning_uses_voice_profile(self):
        brain = Brain(Config({}))
        with patch.object(brain, "_ask", return_value={}) as claude:
            brain.ask(system="", prompt="", schema={}, role="learning")
        self.assertEqual(claude.call_args.kwargs["role"], "voice")
