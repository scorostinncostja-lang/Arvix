"""Хуки Claude Code: молчат вне дома Арвикса, в доме — состояние и тон по режиму."""

import json
import os
import subprocess
import sys
import unittest

from arvix.prompt import read_block

from tests.helpers import ROOT, ArvixCase


class HookTest(ArvixCase):
    def run_hook(self, event: str, cwd: str, session: str = "s1") -> str:
        env = {**os.environ, "ARVIX_DATA_DIR": str(self.tmp / "data"), "ARVIX_CONFIG_DIR": str(self.tmp / "cfg")}
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "arvix_hook.py"), event],
            input=json.dumps({"cwd": cwd, "session_id": session}), capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_silent_outside_home(self) -> None:
        self.assertEqual(self.run_hook("session-start", str(self.tmp)), "")
        self.assertEqual(self.run_hook("prompt", str(self.tmp)), "")

    def test_context_inside_home_and_mode_switch(self) -> None:
        home = self.tmp / "home"
        (home / "sub").mkdir(parents=True)
        (home / ".arvix-home").touch()
        out = json.loads(self.run_hook("session-start", str(home / "sub")))
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn(read_block("tone_norm"), context)
        # режим сменился посреди сессии → в следующий промпт уходит новый тон-блок
        from arvix.core import Core
        from arvix.store import Store

        self.at(None)  # хук — отдельный процесс с настоящими часами
        other = Core(self.core.cfg, Store(self.tmp / "data" / "arvix.db"))
        other.sos(True)
        line = json.loads(self.run_hook("prompt", str(home)))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("КРАСНЫЙ", line)
        self.assertIn(read_block("tone_red"), line)
        self.assertNotIn("HP", line)

    def test_brain_env_disables_hooks(self) -> None:
        home = self.tmp / "home"
        home.mkdir()
        (home / ".arvix-home").touch()
        os.environ["ARVIX_BRAIN"] = "1"
        try:
            self.assertEqual(self.run_hook("session-start", str(home)), "")
        finally:
            os.environ.pop("ARVIX_BRAIN")


if __name__ == "__main__":
    unittest.main()
