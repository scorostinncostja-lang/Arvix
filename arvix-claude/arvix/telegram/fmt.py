"""Вёрстка ответов для Telegram (05-INTERFACES §2.5) — кодом, а не обещанием модели.

1. Каждое предложение — с новой строки. Так читается как переписка, а не как абзац учебника:
   новая мысль не начинается в хвосте строки предыдущей.
2. Разметка — HTML-режим Telegram: модель пишет **жирный** для одного-двух ключевых слов,
   код переводит в <b>. Всё остальное экранируется: «<» в тексте не сломает сообщение.
3. Список — строки с «— » (модель пишет «- », «* » или «• » — код выравнивает).
"""

from __future__ import annotations

import html
import re

# Конец предложения: . ! ? … (и их сочетания), потом пробел и заглавная буква, цифра, кавычка или тире.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[«\"(—–\-]?\s?[A-ZА-ЯЁ0-9])")
# Не резать после инициалов и сокращений: «А. С. Пушкин», «т. е. Москва», «г. Москва», «стр. 5».
_NO_BREAK = re.compile(r"(?:^|\s)(?:[A-ZА-ЯЁ]|т\.\s?е|т\.\s?к|и\s?т\.\s?д|и\s?т\.\s?п|г|гг|стр|с|рис|см|др|пр|ул|д|им|напр|т|№)\.$", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_HEADER = re.compile(r"^\s*#{1,6}\s*")


def split_sentences(line: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(line):
        head = line[start : match.start()]
        if _NO_BREAK.search(head):
            continue
        parts.append(head.strip())
        start = match.end()
    parts.append(line[start:].strip())
    return [p for p in parts if p]


def sentence_lines(text: str) -> str:
    """Предложения — по строкам; пункты списка и пустые строки (границы абзацев) не трогаются."""
    out: list[str] = []
    for line in text.strip().splitlines():
        if not line.strip():
            out.append("")
            continue
        line = _MD_HEADER.sub("", line)
        if (bullet := _BULLET.match(line)) is not None:
            marker = "— " if not re.match(r"\s*\d", bullet.group(0)) else bullet.group(0).strip() + " "
            out.append(marker + line[bullet.end():].strip())
            continue
        out.extend(split_sentences(line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def to_html(text: str) -> str:
    """Готовый к parse_mode=HTML текст: экранирование + **жирный** → <b>."""
    escaped = html.escape(text, quote=False)
    return _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", escaped)


def strip_markup(text: str) -> str:
    """Запасной путь, если Telegram не принял разметку: тот же текст без звёздочек."""
    return _BOLD.sub(lambda m: m.group(1), text)


def render(text: str) -> str:
    return to_html(sentence_lines(text))
