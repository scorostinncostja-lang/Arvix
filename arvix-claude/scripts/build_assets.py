#!/usr/bin/env python3
"""Генерирует файлы, собранные из конституции, — один источник правды:

  output-styles/arvix.md                     стиль Arvix для Claude Code
  deploy/claude-ai/PROJECT_INSTRUCTIONS.md   инструкции проекта на claude.ai
  deploy/claude-ai/arvix-skill/SKILL.md      скилл для загрузки в claude.ai (zip)

Запуск: python3 scripts/build_assets.py [--check]
--check — только проверить, что файлы актуальны (для тестов и CI).
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arvix.prompt import render_claude_ai_instructions, render_output_style

SKILL_HEADER = """---
name: arvix-mentor
description: Арвикс — личный ментор без доступа к журналу - голос, сократовский режим, разбор дня и интервью-знакомство. Используй, когда человек обращается к Арвиксу, просит разбор дня, план или задаёт учебный вопрос.
---

"""


def targets() -> dict[Path, str]:
    return {
        ROOT / "output-styles" / "arvix.md": render_output_style(),
        ROOT / "deploy" / "claude-ai" / "PROJECT_INSTRUCTIONS.md": render_claude_ai_instructions(),
        ROOT / "deploy" / "claude-ai" / "arvix-skill" / "SKILL.md": SKILL_HEADER + render_claude_ai_instructions(),
    }


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, content in targets().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if check:
            stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"записан {path.relative_to(ROOT)}")
    if check:
        if stale:
            print("Устарели (запусти scripts/build_assets.py):", ", ".join(stale))
            return 1
        return 0
    skill_dir = ROOT / "deploy" / "claude-ai" / "arvix-skill"
    archive = ROOT / "deploy" / "claude-ai" / "arvix-skill.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(skill_dir / "SKILL.md", "arvix-skill/SKILL.md")
    print(f"записан {archive.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
