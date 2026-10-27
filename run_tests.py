#!/usr/bin/env python3
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd="/home/dastan/Рабочий стол/Projects/Arvix"
)
sys.exit(result.returncode)
