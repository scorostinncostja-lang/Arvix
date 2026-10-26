#!/usr/bin/env python3
"""Git операции для коммита AI-слоя."""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/dastan/Рабочий стол/Projects/Arvix")

def run_git(args: list[str]) -> tuple[bool, str]:
    """Выполнить git команду."""
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT)] + args,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout + result.stderr
        print(output)
        return result.returncode == 0, output
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False, str(e)

def main():
    """Выполнить git add, commit, push."""
    print("📊 Git status...")
    run_git(["status", "--short"])
    
    print("\n➕ Adding all changes...")
    success, _ = run_git(["add", "."])
    if not success:
        sys.exit(1)
    
    print("\n💾 Committing...")
    commit_msg = """feat(ai): integrate AI layer L1 (steps 0.8-0.9)

- Added core/ai/ with router, context builder, privacy filter
- Integrated debrief and freeform handlers (freeform LAST)
- Scheduler jobs for morning brief (07:30) and debrief (22:30)
- Deleted temp files (check_syntax.py, AI_LAYER_*.md)
- Added test scripts and documentation

Invariants enforced:
- RED mode + mentor_disabled exclude harsh tone blocks
- OpenAI-compatible universal client (AsyncOpenAI)
- Event sourcing through emit()
- L0/L1/L2 separation maintained"""
    
    success, _ = run_git(["commit", "-m", commit_msg])
    if not success:
        print("⚠️  Commit failed (maybe nothing to commit?)")
    
    print("\n🚀 Pushing to remote...")
    success, _ = run_git(["push"])
    if not success:
        sys.exit(1)
    
    print("\n✅ Done!")

if __name__ == "__main__":
    main()
