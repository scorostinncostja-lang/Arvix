"""«Как сделать» у задачи (D62): что сделать и чем — 2–5 шагов «действие → инструмент → минуты»,
«готово, когда» и «куда записать».

Arvix не повторяет инструменты (тест, колоду, плеер, задачник, конспект) — он говорит, ЧТО сделать и ЧЕМ:
«Решу ОГЭ → каталог → №15: 6 задач», «учебник §… — правило и пример», «Anki: карточки из ошибок», «заметка своими
словами в Obsidian». Результат живёт в инструменте, отчёт о нём — одной фразой, как у любой задачи.

Шаги пишет голова — это суждение: какой шаг первым и какой инструмент под него (правило №1). Всё остальное — код:
проверка ответа модели, минуты в рамках блока, событие task_guide, текст для Telegram и приложения, блок
«Как · Arvix» в заметке дня, каркас заметки «своими словами» по шаблону человека.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from arvix.vault import render_template

MAX_STEPS = 6
NOTE_BLOCK = "как"  # блок в заметке дня: %% arvix:как %% … %% /arvix:как %%

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "description": "2–5 шагов по порядку; первый — такой, чтобы начать за 2 минуты",
            "items": {
                "type": "object",
                "properties": {
                    "do": {"type": "string", "description": "что сделать руками, одной фразой, с адресом внутри инструмента: "
                                                           "«каталог → №15: 6 задач, перед каждой назови теорему»"},
                    "tool": {"type": "string", "description": "инструмент из его списка: Решу ОГЭ, учебник §…, Anki, Obsidian…; "
                                                             "нового нет в списке — «новый: название»"},
                    "min": {"type": "integer", "description": "минут на шаг"},
                },
                "required": ["do", "tool", "min"],
            },
        },
        "done": {"type": "string", "description": "готово, когда — проверяемо, по результату: «5 из 6 верно», "
                                                 "«объяснил без подглядывания», «коммит в репозитории»"},
        "save": {"type": "string", "description": "куда записать результат: путь заметки, журнал ошибок, Anki; пусто — некуда"},
        "note": {"type": "string", "description": "название заметки «своими словами» (2–5 слов), если шаг её просит; иначе пусто"},
    },
    "required": ["steps", "done"],
}

RULES = """<guide>
Ты — навигатор по инструментам человека, а не их замена. Задача: «{title}», {minutes} мин, сфера {sphere}, сегодня {date}.
Сначала коротко посмотри в хранилище (Read, Grep, Glob; 2–3 файла, не больше): роадмап и заметки по теме, журнал ошибок,
заметки о его методе ({methods}). Потом дай план блока — что сделать и чем:
- steps: 2–5 шагов. Шаг — действие в одном инструменте с адресом внутри него: «Решу ОГЭ → каталог → №15: 6 задач,
  перед каждой назови теорему», «Атанасян, §… — правило и разобранный пример», «Anki: карточки из сегодняшних ошибок».
  Первый шаг — такой, чтобы начать за 2 минуты. Минуты в сумме — не больше {minutes}.
- Инструменты — только из списка ниже. Если ни один не подходит — один новый, tool = «новый: название».
- Результат живёт в инструменте (баллы, карточки, заметка, коммит), а не в чате: тест, колоду и конспект ты не пишешь.
- done — проверяемо, по результату, а не «позанимался 45 минут».
- save — куда записать: путь заметки, журнал ошибок, Anki. note — название, если шаг просит заметку своими словами.
Задачу за него не решай и ответов не давай: это план работы, а не урок. Всё по-русски, названия точные.
Инструменты человека ({path}):
{tools}
</guide>"""


def _int(value: Any) -> int:
    try:
        return max(0, min(int(value), 600))
    except (TypeError, ValueError):
        return 0


def clean(raw: dict[str, Any] | None, duration_min: int) -> dict[str, Any]:
    """Ответ модели → шаги, которым можно верить: пустые выброшены, строки обрезаны, не больше MAX_STEPS,
    минуты в сумме не выходят за блок (лишнее срезается пропорционально — арифметика кода, а не модели).
    Шагов нет — ValueError: пустое «как» хуже никакого."""
    raw = raw if isinstance(raw, dict) else {}
    steps = []
    for item in raw.get("steps") or []:
        if not isinstance(item, dict):
            continue
        do = re.sub(r"\s+", " ", str(item.get("do") or "")).strip()
        if not do:
            continue
        steps.append({"do": do[:240], "tool": re.sub(r"\s+", " ", str(item.get("tool") or "")).strip()[:60],
                      "min": _int(item.get("min"))})
        if len(steps) == MAX_STEPS:
            break
    if not steps:
        raise ValueError("в шагах пусто — не понял, что делать; скажи словами, что за задача")
    total = sum(s["min"] for s in steps)
    if duration_min > 0 and total > duration_min:
        for s in steps:
            s["min"] = max(1, s["min"] * duration_min // total) if s["min"] else 0
    return {"steps": steps, "done": str(raw.get("done") or "").strip()[:240], "save": str(raw.get("save") or "").strip()[:200],
            "note": re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", str(raw.get("note") or "")).strip()[:80]}


def step_line(step: dict[str, Any]) -> str:
    tool = f" — *{step['tool']}*" if step.get("tool") else ""
    minutes = f" · {step['min']} мин" if step.get("min") else ""
    return f"{step['do']}{tool}{minutes}"


def render_steps(guide: dict[str, Any]) -> str:
    """Шаги и критерий — для сообщения: нумерованный список (разметка D57), «готово» и «куда» строками."""
    lines = [f"{i}. {step_line(s)}" for i, s in enumerate(guide.get("steps") or [], 1)]
    if guide.get("done"):
        lines.append(f"**Готово, когда:** {guide['done']}")
    if guide.get("save"):
        lines.append(f"Записать: {guide['save']}")
    if guide.get("note_path"):
        lines.append(f"📝 Заметка своими словами: {guide['note_path']}")
    return "\n".join(lines)


def render(guide: dict[str, Any], task: Any, lead: str = "") -> str:
    """Сообщение «Как» — код, а не модель: заголовок, шаги, критерий."""
    head = lead or f"🧭 **Как: {task.title}** · {task.duration_min} мин"
    return head + "\n\n" + render_steps(guide)


def context_lines(tasks: list[Any], limit: int = 3) -> list[str]:
    """Шаги открытых задач для головы: в чате он спрашивает про «второй шаг» — она знает, что это."""
    out = []
    for task in [t for t in tasks if t.is_open and t.guide][:limit]:
        steps = " ".join(f"{i}) {s['do']}" + (f" [{s['tool']}]" if s.get("tool") else "") + (f" {s['min']}м" if s.get("min") else "")
                         for i, s in enumerate(task.guide["steps"], 1))
        done = f" · готово: {task.guide['done']}" if task.guide.get("done") else ""
        out.append(f"  [{task.id}] {task.title}: {steps}{done}"[:600])
    return out


def note_block(tasks: list[Any]) -> str:
    """Блок «Как · Arvix» в заметке дня: шаги задач дня, у которых они есть. Пусто — блока нет."""
    parts = []
    for task in tasks:
        if not task.guide:
            continue
        lines = [f"**{task.start or '--:--'} {task.title}**"]
        lines += [f"{i}. {step_line(s)}" for i, s in enumerate(task.guide.get("steps") or [], 1)]
        if task.guide.get("done"):
            lines.append(f"- Готово, когда: {task.guide['done']}")
        if task.guide.get("save"):
            lines.append(f"- Записать: {task.guide['save']}")
        if task.guide.get("note_path"):
            lines.append(f"- Заметка: [[{task.guide['note_path'].removesuffix('.md')}]]")
        parts.append("\n".join(lines))
    return ("## Как · Arvix\n" + "\n\n".join(parts)) if parts else ""


# --- заметка «своими словами» ------------------------------------------------------------------

def subject_of(title: str) -> str:
    """«Физика: §44 постоянный ток» → «Физика»; «Математика ОГЭ» → «Математика ОГЭ»."""
    head = re.split(r"[:—–-]", title, maxsplit=1)[0].strip()
    return head or title


def safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip()[:80]


def skeleton(template: str | None, title: str, subject: str, today: date, questions: list[str], sources: list[str]) -> str:
    """Каркас заметки по шаблону человека (Templates/Concept.md): заполняются только название, предмет, дата и
    вопросы самопроверки; остальное он пишет сам — формулировка своими словами и есть работа понимания."""
    if template:
        # Те же переменные, что подставил бы Obsidian: {{title}}, {{ date:YYYY-MM-DD }} с пробелами, Templater.
        text = render_template(template, datetime.combine(today, datetime.min.time()), title)
        text = re.sub(r"^(subject:\s*)$", rf"\g<1>{subject}", text, count=1, flags=re.MULTILINE)
        if questions:
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
