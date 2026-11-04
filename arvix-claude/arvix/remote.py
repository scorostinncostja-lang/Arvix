"""Удалённый режим: журнал живёт на сервере, ноутбук ходит к нему по SSH.

Если в ~/.config/arvix/config.toml есть
    [remote]
    host = "arvix@89.22.232.51"
то MCP-сервер, хук и CLI на ноутбуке не открывают локальную базу, а запускают тот же
скрипт на сервере через `ssh` — stdin/stdout идут насквозь. Одна база, одна история,
никаких копий SQLite туда-обратно. ARVIX_LOCAL=1 отключает пересылку (так её и вызывает
сервер, чтобы не зациклиться).

Модуль нарочно не импортирует ядро: решение «локально или на сервер» принимается
до открытия базы.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tomllib

from arvix.config import config_file

DEFAULT_APP = "~/.local/share/arvix/app"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=30", "-T")


def target() -> tuple[str, str] | None:
    """(host, app) из [remote] конфига или None — работаем локально."""
    if os.environ.get("ARVIX_LOCAL"):
        return None
    path = config_file()
    try:
        remote = tomllib.loads(path.read_text(encoding="utf-8")).get("remote") or {}
    except (OSError, tomllib.TOMLDecodeError):
        return None
    host = str(remote.get("host") or "").strip()
    return (host, str(remote.get("app") or DEFAULT_APP)) if host else None


def _command(host: str, app: str, script: str, args: list[str]) -> list[str]:
    app_path = app if not app.startswith("~/") else "$HOME/" + app[2:]
    remote = f"ARVIX_LOCAL=1 exec python3 {app_path}/scripts/{script} " + " ".join(shlex.quote(a) for a in args)
    return ["ssh", *SSH_OPTS, host, remote]


def exec_remote(script: str, args: list[str]) -> None:
    """Заменяет текущий процесс на ssh — для MCP и CLI (stdin/stdout насквозь)."""
    found = target()
    if not found:
        return
    command = _command(*found, script, args)
    sys.stdout.flush()
    os.execvp(command[0], command)


def run_remote(script: str, args: list[str], stdin: str, timeout: float) -> str | None:
    """Для хука: вывод серверного скрипта или None, если сервер недоступен."""
    found = target()
    if not found:
        return None
    try:
        done = subprocess.run(_command(*found, script, args), input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None
