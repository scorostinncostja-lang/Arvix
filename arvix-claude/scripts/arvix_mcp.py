#!/usr/bin/env python3
"""Точка входа: кладёт корень плагина в sys.path, дальше — пакет arvix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from arvix.remote import exec_remote

    exec_remote("arvix_mcp.py", sys.argv[1:])  # [remote] в конфиге — база на сервере
    from arvix.mcp_server import serve

    serve()
