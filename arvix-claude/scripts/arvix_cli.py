#!/usr/bin/env python3
"""Точка входа: кладёт корень плагина в sys.path, дальше — пакет arvix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Команды этой машины: меняют её конфиг и папки или сами решают, когда сходить на сервер.
LOCAL_COMMANDS = {"setup", "desktop-mcp", "init-home", "doctor", "statusline", "remote", "--version", "-h", "--help"}

if __name__ == "__main__":
    if not (set(sys.argv[1:2]) & LOCAL_COMMANDS):
        from arvix.remote import exec_remote

        exec_remote("arvix_cli.py", sys.argv[1:])
    from arvix.cli import main

    main()
