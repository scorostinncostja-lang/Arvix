"""Ежедневный отчёт в Obsidian — по шаблону человека, без ИИ.

ensure() создаёт заметку дня из шаблона (папка и шаблон — из настроек Daily notes
в Obsidian): дата, номер дня и недели программы, задачи дня чекбоксами.
Переменные шаблона ({{date:DD.MM.YYYY}}, Templater tp.date.now) подставляются, как это
сделал бы Obsidian; оставшиеся сырыми в уже созданной заметке — чинятся при sync().
sync() дописывает факты: заполняет только пустые поля frontmatter (сон, подъём,
фокус, тренировка), ставит [x] у строк задач, которые Arvix сам вписал и которые
закрыты, и обновляет свой блок «Arvix» с итогами и разбором. Что человек
написал сам, не трогается никогда.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from arvix.context import STATUS_ICON, hm
from arvix.vault import PLACEHOLDER, parse_frontmatter, render_template, set_frontmatter

BLOCK = "день"
EMPTY_TASK = re.compile(r"^- \[ \][ \t]*$", re.MULTILINE)
CHECK_LINE = re.compile(r"^(\s*[-*+] )\[([ xX])\]( )(.*)$")
OPEN_LINE = re.compile(r"^(\s*[-*+] )\[ \]( )(.*)$", re.MULTILINE)


def program_day(core: Any, d: date) -> tuple[int, int]:
    """(день, неделя) программы — с даты старта профиля или первого отчёта."""
    start = core.state.profile.get("program_start")
    if not start:
        return 1, 1
    days = (d - date.fromisoformat(start)).days + 1
    return max(days, 1), max((days - 1) // 7 + 1, 1)


def task_prefix(task: Any) -> str:
    """Начало строки задачи после чекбокса — по нему код узнаёт свою строку в заметке."""
    return f"{task.start or '--:--'} {task.title} ({task.duration_min} мин)"


def _task_lines(core: Any, d: date) -> list[str]:
    lines = []
    for task in core.state.tasks_on(d):
        box = "x" if task.status == "done" else " "
        line = f"- [{box}] {task_prefix(task)}"
        if task.status == "done" and task.report:
            line += f" — {task.report}"
        elif task.status in ("failed", "debt") and task.reason:
            line += f" — не сделано: {task.reason}"
        lines.append(line)
    return lines


def ensure(core: Any, d: date) -> str | None:
    """Создаёт заметку дня, если её нет. Возвращает путь или None (хранилища нет)."""
    if not core.cfg.vault:
        return None
    vault = core.vault
    rel = vault.daily_path(d)
    if (vault.root / rel).is_file():
        return rel
    if not core.state.profile.get("program_start"):
        core.profile_set("program_start", d.isoformat(), source="l0")
    day_no, week_no = program_day(core, d)
    text = render_template(vault.daily_template(), _moment(core, d), rel.rsplit("/", 1)[-1].removesuffix(".md"))
    text = set_frontmatter(text, {"date": d.isoformat(), "day": day_no, "week": week_no, "type": "daily"})
    tasks = _task_lines(core, d)
    if tasks and EMPTY_TASK.search(text):
        text = EMPTY_TASK.sub("\n".join(tasks), text, count=1)
    return core.write_note(rel, text, source="l0")["path"]


def _moment(core: Any, d: date) -> datetime:
    return datetime.combine(d, core.now().time())


def task_at_line(core: Any, d: date, line: str) -> Any:
    """Задача Arvix, которой соответствует строка-чекбокс заметки дня, или None."""
    m = CHECK_LINE.match(line)
    if not m:
        return None
    rest = m.group(4)
    for task in core.state.tasks_on(d):
        if rest.startswith(task_prefix(task)):
            return task
    return None


def tick_done(core: Any, d: date, text: str) -> str:
    """[ ] → [x] у своих строк задач, которые уже закрыты. Обратно не снимает."""
    done = {task_prefix(t) for t in core.state.tasks_on(d) if t.status == "done"}
    if not done:
        return text

    def fix(m: re.Match[str]) -> str:
        return f"{m.group(1)}[x]{m.group(2)}{m.group(3)}" if any(m.group(3).startswith(p) for p in done) else m.group(0)

    return OPEN_LINE.sub(fix, text)


def repair(core: Any, d: date, rel: str) -> Any:
    """Сырые переменные шаблона (заметку создал не Obsidian) и галочки закрытых задач."""
    title = rel.rsplit("/", 1)[-1].removesuffix(".md")
    moment = _moment(core, d)

    def transform(text: str) -> str:
        if PLACEHOLDER.search(text):
            text = render_template(text, moment, title)
        return tick_done(core, d, text)

    return core.update_note(rel, transform, source="l0")


def _fields(core: Any, d: date) -> dict[str, Any]:
    st = core.state
    day = st.days.get(d)
    values: dict[str, Any] = {}
    if day and day.sleep_min:
        values["sleep"] = hm(day.sleep_min).replace("м", "")
        if day.bedtime:
            bed = datetime.combine(d - timedelta(days=1), datetime.strptime(day.bedtime, "%H:%M").time())
            if day.bedtime < "12:00":
                bed += timedelta(days=1)
            values["wake"] = (bed + timedelta(minutes=day.sleep_min)).strftime("%H:%M")
    if day and (day.deep_min or d < core.today() or day.debrief):
        # Днём 0 не пишется (only_empty заблокировал бы вечернее число); после разбора или задним числом — и 0.
        values["focus_min"] = day.deep_min
        values["focus_minutes"] = day.deep_min  # заполняется только то поле, что есть в шаблоне человека
    sport = [t for t in st.tasks_on(d) if t.sphere == "sport"]
    if sport:
        values["workout"] = "да" if any(t.status == "done" for t in sport) else "нет"
    return values


def summary(core: Any, d: date) -> str:
    """Итог дня для человека — словами и с причиной, а не таблица цифр и не копия переписки.
    Ответы разбора остаются в журнале (память Arvix), в заметку идёт только его вывод."""
    st = core.state
    day = st.days.get(d)
    tasks = st.tasks_on(d)
    lines = ["## Итог дня · Arvix"]
    gentle = core.effective_mode() == "red" and d == core.today()
    if gentle:
        lines.append("Мягкий день: без плана и без цифр. Сон, еда, движение — этого достаточно.")
    elif not tasks:
        why = ("распорядок ещё не сохранён — опиши Arvix свою неделю словами, он соберёт план"
               if not st.templates else "в распорядке на этот день нет блоков, и задач не добавлялось")
        lines.append(f"Плана не было: {why}.")
    else:
        done = [t for t in tasks if t.status == "done"]
        missed = [t for t in tasks if t.status in ("failed", "debt")]
        text = f"Сделано {len(done)} из {len(tasks)}"
        completion = st.completion(d)
        text += f" ({completion:.0f} %)." if completion is not None else "."
        if missed:
            text += " Не сделано: " + "; ".join(f"{t.title}" + (f" — {t.reason}" if t.reason else "") for t in missed) + "."
        lines.append(text)
    if not gentle:
        facts = []
        if day and day.deep_min:
            facts.append(f"глубокая работа {hm(day.deep_min)} из {hm(core.deep_target(d))}")
        if day and day.focus:
            facts.append(f"фокус: {len(day.focus)} сесс. ({', '.join(s.get('topic') or 'по задаче' for s in day.focus[:3])})")
        if day and day.sleep_min:
            target = core.sleep_target()
            gap = day.sleep_min - target
            facts.append(f"сон {hm(day.sleep_min)}" + ("" if abs(gap) < 30 else f" — на {hm(abs(gap))} {'больше' if gap > 0 else 'меньше'} нормы"))
        if facts:
            lines.append(facts[0][:1].upper() + facts[0][1:] + ("; " + "; ".join(facts[1:]) if facts[1:] else "") + ".")
        for task in tasks:
            if task.status == "done" and task.report:
                lines.append(f"- {STATUS_ICON.get(task.status, '?')} {task.title} — {task.report}")
    for ev in core.store.read(0):
        if ev.kind == "debrief_completed" and ev.payload.get("date") == d.isoformat() and ev.payload.get("conclusion"):
            lines += ["", f"**Вывод.** {ev.payload['conclusion'].strip()}"]
    return "\n".join(lines)


def sync(core: Any, d: date, *, create: bool | None = None) -> str | None:
    """Дописывает факты дня в его заметку. Создаёт заметку только для сегодня."""
    if not core.cfg.vault:
        return None
    vault = core.vault
    rel = vault.daily_path(d)
    if not (vault.root / rel).is_file():
        if not (create if create is not None else d == core.today()):
            return None
        rel = ensure(core, d) or rel
    repair(core, d, rel)
    values = _fields(core, d)
    if values:
        core.update_note(rel, lambda text: set_frontmatter(text, values, only_empty=True), source="l0")
    core.write_block(rel, BLOCK, summary(core, d), source="l0")
    return rel


def read_fields(core: Any, d: date) -> dict[str, str]:
    """Поля, которые человек заполнил сам (телефон, игры, срывы) — для разбора."""
    note = core.vault.daily_note(d) if core.cfg.vault else None
    return {k: v for k, v in (note or {}).get("fields", {}).items() if v} if note else {}


__all__ = ["ensure", "parse_frontmatter", "program_day", "read_fields", "repair", "summary", "sync", "task_at_line", "tick_done"]
