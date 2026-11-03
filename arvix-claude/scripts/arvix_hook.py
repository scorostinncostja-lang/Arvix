#!/usr/bin/env python3
"""Точка входа: кладёт корень плагина в sys.path, дальше — пакет arvix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arvix.hooks import run

if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "session-start"))
