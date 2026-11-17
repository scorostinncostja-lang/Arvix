#!/usr/bin/env python3
"""PNG-иконки приложения (192 и 512) из той же фигуры, что icon.svg, — без Pillow.

Растеризация полигонов с 4× сглаживанием. Запуск: python3 scripts/make_icons.py
"""

import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "arvix" / "web" / "static"
OUTER = [(256, 104), (392, 408), (330, 408), (302, 342), (210, 342), (182, 408), (120, 408)]
HOLE = [(256, 196), (226, 290), (286, 290)]
A, B = (0x4F, 0x6B, 0xFF), (0x19, 0xB3, 0x94)


def inside(poly: list[tuple[float, float]], x: float, y: float) -> bool:
    hit = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def in_rounded(x: float, y: float, r: float = 112, size: float = 512) -> bool:
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size: int) -> bytes:
    scale = 512 / size
    sub = ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))
    rows = bytearray()
    for py in range(size):
        rows.append(0)
        for px in range(size):
            bg = glyph = 0
            for dx, dy in sub:
                x, y = (px + dx) * scale, (py + dy) * scale
                if in_rounded(x, y):
                    bg += 1
                    if inside(OUTER, x, y) and not inside(HOLE, x, y):
                        glyph += 1
            t = (px + py) / (2 * size)
            base = [round(a + (b - a) * t) for a, b in zip(A, B)]
            mix = glyph / 4
            color = [round(c + (255 - c) * mix) for c in base]
            rows += bytes(color) + bytes([round(255 * bg / 4)])
    return bytes(rows)


def png(size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(render(size), 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    for size in (192, 512):
        (OUT / f"icon-{size}.png").write_bytes(png(size))
        print(f"icon-{size}.png", file=sys.stderr)
