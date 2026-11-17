#!/usr/bin/env python3
"""Точка входа: кладёт корень плагина в sys.path, дальше — пакет arvix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Команды этой машины: меняют её конфиг и папки или сами решают, когда сходить на сервер.
LOCAL_COMMANDS = {"setup", "desktop-mcp", "init-home", "doctor", "statusline", "remote", "app-url", "--version", "-h", "--help"}

if __name__ == "__main__":
    # `arvix` без аргументов или `arvix app` — приложение в терминале: оно само ходит к серверу
    # через SSH-туннель, поэтому запускается здесь, а не пересылается на сервер.
    if sys.argv[1:] in ([], ["app"]):
        from arvix.tui import main as tui

        tui()
        sys.exit(0)
    if not (set(sys.argv[1:2]) & LOCAL_COMMANDS):
        from arvix.remote import exec_remote

        exec_remote("arvix_cli.py", sys.argv[1:])
    from arvix.cli import main

    main()
