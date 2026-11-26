"""Codex CLI adapter for structured model calls without agent tools."""

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


class CodexBrain:
    def __init__(self, config):
        self.bin = str(Path(config.get("codex_bin") or "codex").expanduser())
        self.model = config.get("codex_model")

    def available(self):
        return bool(shutil.which(self.bin))

    def ask(self, system, prompt, schema, timeout, *, image=None):
        with tempfile.TemporaryDirectory(prefix="arvix-codex-") as workdir:
            root = Path(workdir)
            schema_file, answer = root / "schema.json", root / "answer.json"
            schema_file.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            cmd = [
                self.bin, "--ask-for-approval", "never", "exec",
                "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                "--sandbox", "read-only", "--disable", "shell_tool", "-c", 'web_search="disabled"',
                "--output-schema", str(schema_file), "--output-last-message", str(answer),
            ]
            if self.model:
                cmd.extend(["--model", self.model])
            if image:
                cmd.extend(["--image", str(image)])
            try:
                proc = subprocess.run(
                    [*cmd, "-"], input=system + "\n\n" + prompt, cwd=root,
                    capture_output=True, text=True, timeout=timeout, check=False,
                )
                if proc.returncode != 0:
                    log.warning("Codex CLI завершился с кодом %s", proc.returncode)
                    return None
                payload = json.loads(answer.read_text(encoding="utf-8"))
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                log.warning("Codex CLI не вернул ответ (%s)", type(exc).__name__)
                return None
        required = schema.get("required", ())
        if not isinstance(payload, dict) or any(key not in payload for key in required):
            return None
        return payload
