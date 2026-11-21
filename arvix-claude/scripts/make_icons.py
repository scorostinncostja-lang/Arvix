#!/usr/bin/env python3
"""PNG-иконки приложения (192, 512, maskable 512) и аватар бота (640) из icon.svg — один источник правды.

Инструмент разработчика, а не часть продукта: нужен rsvg-convert (пакет librsvg, есть в Arch/CachyOS).
PNG лежат в git — на сервере скрипт не запускается.

Аватар для Telegram — квадрат без скруглений: Telegram сам режет его кругом.
Поставить: @BotFather → /setuserpic → прислать deploy/avatar.png.

Запуск: python3 scripts/make_icons.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "arvix" / "web" / "static"
SVG = STATIC / "icon.svg"


def render(svg: str, size: int, out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8") as tmp:
        tmp.write(svg)
    try:
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), tmp.name, "-o", str(out)], check=True)
    finally:
        Path(tmp.name).unlink()
    print(out.relative_to(ROOT), file=sys.stderr)


def main() -> int:
    if not shutil.which("rsvg-convert"):
        print("нужен rsvg-convert: sudo pacman -S librsvg", file=sys.stderr)
        return 1
    svg = SVG.read_text(encoding="utf-8")
    for size in (192, 512):
        render(svg, size, STATIC / f"icon-{size}.png")
    square = svg.replace(' rx="114"', "")  # во всю площадь: маску (круг, «капля») накладывает система
    render(square, 512, STATIC / "icon-maskable-512.png")
    render(square, 640, ROOT / "deploy" / "avatar.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
