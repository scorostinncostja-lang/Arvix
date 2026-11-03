#!/usr/bin/env python3
"""Точка входа: кладёт корень плагина в sys.path, дальше — пакет arvix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arvix.mcp_server import serve

if __name__ == "__main__":
    serve()
