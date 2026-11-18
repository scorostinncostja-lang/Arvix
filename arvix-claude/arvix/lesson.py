"""Учебный блок (06-LEARNING §8): задача сферы learning → урок по роадмапу и методу человека.

Голова зовётся дважды за блок: в начале — план по минутам с инструментами, источниками
и вопросами проверки (LESSON_SCHEMA); в конце — оценка ответов (CHECK_SCHEMA). Между ними
модель не нужна: таймер, кнопки, каркас заметки и запись результата — код. Объяснение
«у доски» — обычный вызов L1 с блоком <lesson> в промпте, когда человек спрашивает.

Здесь — чистые функции: схемы, тексты правил, рендер, каркас заметки, запасной план.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from arvix.vault import render_template

LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "тема блока — конкретная, как узел роадмапа"},
        "why": {"type": "string", "description": "одной строкой: что даёт для цели (номер задания, баллы, этап)"},
        "roadmap_node": {"type": "string", "description": "узел роадмапа и его положение, например «Постоянный ток (3/12)»; пусто — роадмапа нет"},
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_min": {"type": "integer"}, "to_min": {"type": "integer"},
                    "step": {"type": "string", "description": "конкретное действие"},
                    "tool": {"type": "string", "description": "инструмент: учебник §, NotebookLM, Решу ОГЭ №, Obsidian, Anki…"},
                },
                "required": ["from_min", "to_min", "step"],
            },
        },
        "sources": {"type": "array", "items": {"type": "string"}, "description": "первоисточник первым; видео и заметки человека — после"},
        "check": {
            "type": "array",
            "items": {"type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string", "description": "короткий эталон для оценки"}}, "required": ["q", "a"]},
        },
        "note_title": {"type": "string", "description": "название заметки-конспекта для каркаса, 2–5 слов"},
    },
    "required": ["topic", "why", "plan", "sources", "check"],
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "score_pct": {"type": "integer", "description": "доля верного 0–100"},
        "feedback": {"type": "string", "description": "для человека: что верно, что нет и почему, что дочитать; абзацы через пустую строку"},
        "gaps": {"type": "array", "items": {"type": "string"}, "description": "пробелы — по одному, формулировкой для карточки"},
        "next_step": {"type": "string", "description": "одно действие на следующий блок"},
    },
    "required": ["score_pct", "feedback", "gaps"],
}

LESSON_RULES = """<lesson_plan>
Ты готовишь учебный блок на {minutes} минут: задача «{title}», сфера {sphere}, сегодня {date}.
Сначала посмотри в хранилище (Read, Grep, Glob): роадмап предмета ({roadmaps}; файлы со словом «Роадмап»
в названии, папка 02_Areas), журнал ошибок, заметки человека о методе обучения ({methods}), его конспекты по теме.
Прошлые уроки по этому предмету: {history}.
Тема — следующий незакрытый узел роадмапа по этому предмету после прошлых уроков; роадмапа нет — ближайшая тема
по цели (для ОГЭ — кодификатор и демоверсия ФИПИ) и скажи в why, что роадмапа нет.
План — по минутам на весь блок, 4–6 шагов, по методу человека из его заметок (желательная трудность, вспоминание
с пустого листа, Фейнман, интерливинг). Каждый шаг — одно конкретное действие и инструмент: учебник с параграфом,
NotebookLM (выжимка главы, 5 вопросов на понимание), видео (канал или курс по названию; ссылка только настоящая),
Решу ОГЭ или открытый банк ФИПИ с номером задания и числом задач, Gemini — только сократовский вопрос при затыке,
Obsidian — заметка своими словами, Anki — карточки из ошибок. Инструменты — те, что человек назвал в заметках
и профиле{tools}; новых не навязывай.
Первый шаг — вспомнить с пустого листа, последний — проверка: {questions} вопроса от тебя.
sources — первоисточник первым (учебник и параграф, документ ФИПИ, документация), затем видео и заметки человека
(путь в хранилище). Выдуманный адрес хуже отсутствия ссылки.
check — ровно {questions} вопроса на понимание и применение, не «перескажи параграф»; один из них — задача по теме;
у каждого короткий эталон a — по нему будет оценка.
Сам ничего не объясняй: объяснение будет, когда человек спросит внутри блока. Названия точные, всё по-русски.
</lesson_plan>"""

CHECK_RULES = """<lesson_check>
Человек прошёл учебный блок по теме «{topic}» и ответил на вопросы проверки одним сообщением.
Вопросы и эталоны:
{pairs}
Оцени каждый ответ по сути, а не по словам: верно / частично / неверно. score_pct — доля верного, 0–100.
feedback — для человека, 2–3 коротких абзаца через пустую строку: что верно; что нет и почему, с правильной
мыслью в одну-две фразы, не целым конспектом; что дочитать — источник и раздел, минут на десять.
gaps — пробелы по одному, формулировкой для карточки Anki и журнала ошибок. next_step — одно действие на следующий блок.
Не льсти. Пустой ответ или «не знаю» — 0 за вопрос. В feedback нет оценок в процентах — их допишет код.
</lesson_check>"""

LESSON_CONTEXT = """<lesson>
Идёт учебный блок: «{topic}» ({title}, {minutes} мин, прошло {elapsed}).
План блока: {plan}
Вопрос по теме блока — объясняй у доски: по шагам, с одним примером, в конце один вопрос на понимание.
Это обучение, а не подсказка: подробно, но без воды, и не целым параграфом сразу — порцией на 2–3 минуты чтения.
Задачу за него не решай: один шаг и вопрос «что дальше?». Первоисточник называй.
Вопрос не по теме — одной строкой и вернуть к блоку. Отчёт о блоке сам не принимай: в конце будет проверка.
</lesson>"""

DEFAULT_QUESTIONS = 3
DEFAULT_MINUTES = 45


def fallback_plan(minutes: int) -> list[dict[str, Any]]:
    """План без головы: те же фазы по методу человека, пропорционально длине блока."""
    m = max(minutes, 15)
    cuts = [0, round(m * 0.1), round(m * 0.4), round(m * 0.75), round(m * 0.9), m]
    steps = [
        ("Вспомни с пустого листа всё, что знаешь по теме", "лист бумаги"),
        ("Первоисточник: учебник, параграф по теме; выпиши формулы и определения", "учебник / NotebookLM"),
        ("Практика: задачи по теме, не подглядывая в решение", "Решу ОГЭ / банк ФИПИ"),
        ("Запиши суть своими словами", "Obsidian"),
        ("Проверка: ответь на вопросы, которые пришлёт Арвикс", "Telegram"),
    ]
    return [{"from_min": a, "to_min": b, "step": s, "tool": t} for (a, b), (s, t) in zip(zip(cuts, cuts[1:]), steps)]


def render(lesson: dict[str, Any], task: Any, note_path: str | None = None) -> str:
    """Сообщение урока — код, не модель: план по минутам, источники, что будет в конце."""
    lines = [f"📚 {task.title} · {task.duration_min} мин", lesson.get("topic", "").strip()]
    if lesson.get("why"):
        lines.append(f"Зачем: {lesson['why'].strip()}")
    if lesson.get("roadmap_node"):
        lines.append(f"Роадмап: {lesson['roadmap_node'].strip()}")
    lines += ["", "План:"]
    for step in lesson.get("plan") or []:
        span = f"{int(step.get('from_min', 0))}–{int(step.get('to_min', 0))}"
        tool = f" · {step['tool']}" if step.get("tool") else ""
        lines.append(f"{span:>5}  {step.get('step', '').strip()}{tool}")
    if lesson.get("sources"):
        lines += ["", "Источники: " + " · ".join(s.strip() for s in lesson["sources"] if s.strip())]
    if note_path:
        lines.append(f"📝 Каркас заметки: {note_path}")
    n = len(lesson.get("check") or [])
    if n:
        lines.append(f"В конце — {n} вопроса, ответ одним сообщением (можно голосом). Это и будет отчёт.")
    else:
        lines.append("В конце — «Сделано?»: одной фразой, что именно сделано.")
    return "\n".join(line for line in lines if line is not None)


def render_check(lesson: dict[str, Any]) -> str:
    questions = [c["q"] for c in lesson.get("check") or []]
    head = f"Время вышло. Проверка по теме «{lesson.get('topic', '')}» — {len(questions)} вопроса, ответь одним сообщением, можно голосом:"
    return head + "\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))


def check_pairs(lesson: dict[str, Any]) -> str:
    return "\n".join(f"{i}. {c['q']}\n   эталон: {c['a']}" for i, c in enumerate(lesson.get("check") or [], 1))


def skeleton(template: str | None, title: str, subject: str, today: date, questions: list[str], sources: list[str]) -> str:
    """Каркас заметки по шаблону человека (Templates/Concept.md): заполняются только
    название, предмет, дата и вопросы самопроверки; остальное он пишет сам."""
    if template:
        # Те же переменные, что подставил бы Obsidian: {{title}}, {{ date:YYYY-MM-DD }} с пробелами, Templater.
        text = render_template(template, datetime.combine(today, datetime.min.time()), title)
        text = re.sub(r"^(subject:\s*)$", rf"\g<1>{subject}", text, count=1, flags=re.MULTILINE)
        checks = "\n".join(f"- [ ] {q}" for q in questions)
        text, n = re.subn(r"(## Самопроверка\n)(?:- \[ \][^\n]*\n?)*", rf"\g<1>{checks}\n", text, count=1)
        if not n:
            text = text.rstrip("\n") + "\n\n## Самопроверка\n" + checks + "\n"
        if sources:
            text = text.rstrip("\n") + "\n\n## Источники\n" + "\n".join(f"- {s}" for s in sources) + "\n"
        return text
    body = [f"# {title}", "", f"Предмет: {subject} · {today.isoformat()}", "",
            "> Суть одним предложением, своими словами:", ">", "", "## Объяснение по Фейнману", "", "## Пример", "",
            "## Типичные ошибки", "", "## Самопроверка"]
    body += [f"- [ ] {q}" for q in questions]
    if sources:
        body += ["", "## Источники"] + [f"- {s}" for s in sources]
    return "\n".join(body) + "\n"


def subject_of(title: str) -> str:
    """«Физика: §44 постоянный ток» → «Физика»; «Математика ОГЭ» → «Математика ОГЭ»."""
    head = re.split(r"[:—–-]", title, maxsplit=1)[0].strip()
    return head or title


def safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip()[:80]
