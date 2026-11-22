"""Инструменты человека (D62): Arvix — навигатор по ним, а не их замена.

Список живёт в хранилище заметкой (по умолчанию `05_System/Инструменты.md`, место — `[vault_paths] tools`):
таблица «Инструмент | Для чего | Как», которую человек правит в Obsidian. Код читает её без ИИ и кладёт строкой
ИНСТРУМЕНТЫ в контекст головы: шаги «Как сделать» и советы в чате называют его инструменты с адресом внутри них,
а не общее «используй Anki». Нет заметки — её создаёт код из стартового списка (`ensure`); заметку, которую
человек правил, код не трогает никогда (правила записи vault.py).
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_PATH = "05_System/Инструменты.md"
CONTEXT_LIMIT = 900  # символов на строку ИНСТРУМЕНТЫ: каждый ответ головы её читает

# Стартовый список — из метода владельца («Гайд на обучение», «Универсальный метод», 03_Resources/Обучение):
# бумага → учебник → NotebookLM → Obsidian → задачи → Gemini как строгий профессор; Anki — факты; Решу ОГЭ и ФИПИ — экзамен.
STARTER = [
    ("Бумага и тетрадь", "вспомнить с пустого листа, решать задачи, черновик",
     "закрыть всё и писать по памяти; задачи — только руками, с ходом решения"),
    ("Учебник", "первоисточник теории", "параграф: правило и разобранный пример → закрыть → пересказать своими словами"),
    ("Решу ОГЭ", "практика по номерам заданий ОГЭ с проверкой ответа",
     "каталог → номер задания → 5–10 задач подряд; вариант целиком на время — по выходным"),
    ("ФИПИ", "демоверсия, кодификатор, открытый банк заданий", "что именно проверяет номер и в каком виде ответ"),
    ("NotebookLM", "выжимка главы из PDF без выдумок", "загрузить главу; «извлеки правила и формулы», «5 вопросов на понимание»"),
    ("Obsidian", "заметки своими словами, журнал ошибок, планы", "одна идея — одна заметка; ошибку — строкой в журнал ошибок"),
    ("Anki", "факты, формулы, слова — интервальное повторение", "карточку делать самому из своей ошибки; 15–20 минут утром"),
    ("Gemini", "сократовский профессор при затыке", "«не решай — укажи строку с ошибкой» или «спрашивай, пока не пойму»"),
    ("YouTube", "видео-объяснение темы; английский на слух", "один ролик по теме после учебника, не вместо него"),
    ("Таймер Arvix", "блок без отвлечений", "таймер на задачу, телефон — в другой комнате"),
    ("GitHub", "код проектов и чужие примеры", "коммит — доказательство работы; чужой репозиторий — прочитать и сломать"),
]

HEADER = ("Чем я работаю. Arvix называет шаги только этими инструментами — правь таблицу под себя:\n"
          "добавь своё, убери лишнее. Колонки: что, для чего, как пользоваться.\n\n")


def path(core: Any) -> str:
    return core.cfg.vault_paths.get("tools") or DEFAULT_PATH


def starter_text() -> str:
    rows = "\n".join(f"| {name} | {use} | {how} |" for name, use, how in STARTER)
    return HEADER + "| Инструмент | Для чего | Как |\n|---|---|---|\n" + rows + "\n"


def _clean_cell(cell: str) -> str:
    cell = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", cell)  # [[путь|текст]] → текст
    cell = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cell)
    cell = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)  # [текст](ссылка) → текст
    return re.sub(r"\s+", " ", cell.replace("**", "").replace("__", "")).strip()


def parse(text: str) -> list[dict[str, str]]:
    """Строки таблицы «Инструмент | Для чего | Как» или списка «- Инструмент — для чего».
    Шапка и разделитель таблицы пропускаются; лишние колонки — тоже."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|"):
            cells = [_clean_cell(c) for c in line.strip("|").split("|")]
            if not cells or not cells[0] or set("".join(cells)) <= set("-: "):
                continue
            if cells[0].lower() in ("инструмент", "инструменты", "tool", "что"):
                continue
            row = {"name": cells[0], "use": cells[1] if len(cells) > 1 else "", "how": cells[2] if len(cells) > 2 else ""}
        elif m := re.match(r"^[-*+] (?!\[[ xX]\])(.+?)\s+[—–-]\s+(.+)$", line):
            row = {"name": _clean_cell(m.group(1)), "use": _clean_cell(m.group(2)), "how": ""}
        else:
            continue
        key = row["name"].lower()
        if row["name"] and key not in seen:
            seen.add(key)
            out.append(row)
    return out


def load(core: Any) -> list[dict[str, str]]:
    """Инструменты из заметки человека; заметки нет (или в ней пусто) — стартовый список. Ничего не пишет."""
    if core.cfg.vault:
        try:
            rows = parse(core.vault.read(path(core)))
            if rows:
                return rows
        except Exception:  # noqa: BLE001 — нет хранилища или заметки: работаем по стартовому списку
            pass
    return parse(starter_text())


def ensure(core: Any) -> str | None:
    """Заметка-список в хранилище — создаётся один раз из стартового списка. Есть — не трогается."""
    if not core.cfg.vault:
        return None
    rel = path(core)
    try:
        if (core.vault.root / rel).is_file():
            return rel
        return core.write_note(rel, starter_text(), source="l0")["path"]
    except Exception:  # noqa: BLE001 — хранилище недоступно: Arvix работает по стартовому списку
        return None


def context_line(core: Any) -> str:
    """ИНСТРУМЕНТЫ для каждого ответа головы — коротко: имя и для чего. «Как» — в заметке и в промпте шагов."""
    rows = load(core)
    body = " · ".join(f"{r['name']} — {r['use']}" if r["use"] else r["name"] for r in rows)
    if len(body) > CONTEXT_LIMIT:
        body = body[:CONTEXT_LIMIT].rsplit(" · ", 1)[0] + " · …"
    return f"ИНСТРУМЕНТЫ (его список — {path(core)}; шаги называй ими): {body}"


def projects_dir(core: Any) -> str | None:
    """Папка проектов в хранилище ([vault_paths] projects, по умолчанию 01_Projects), если она есть.
    Вкладки «Проекты» нет (D62): знание о проекте живёт в его заметках, голова читает их перед советом."""
    rel = core.cfg.vault_paths.get("projects") or "01_Projects"
    try:
        return rel if core.cfg.vault and (core.vault.root / rel).is_dir() else None
    except Exception:  # noqa: BLE001 — хранилище недоступно
        return None


def table(core: Any) -> str:
    """Полный список для промпта шагов: имя — для чего — как."""
    return "\n".join(f"- {r['name']}" + (f" — {r['use']}" if r["use"] else "") + (f" ({r['how']})" if r["how"] else "")
                     for r in load(core))
