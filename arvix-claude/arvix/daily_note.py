"""Ежедневный отчёт в Obsidian — по шаблону человека, без ИИ.

ensure() создаёт заметку дня из шаблона (папка и шаблон — из настроек Daily notes
в Obsidian): дата, номер дня и недели программы, задачи дня чекбоксами.
sync() дописывает факты: заполняет только пустые поля frontmatter (сон, подъём,
фокус, тренировка) и обновляет свой блок «Арвикс» с итогами и разбором. Что человек
написал сам, не трогается никогда.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from arvix.context import STATUS_ICON, hm
from arvix.vault import parse_frontmatter, set_frontmatter

BLOCK = "день"
EMPTY_TASK = re.compile(r"^- \[ \]\s*$", re.MULTILINE)


def program_day(core: Any, d: date) -> tuple[int, int]:
    """(день, неделя) программы — с даты старта профиля или первого отчёта."""
    start = core.state.profile.get("program_start")
    if not start:
        return 1, 1
    days = (d - date.fromisoformat(start)).days + 1
    return max(days, 1), max((days - 1) // 7 + 1, 1)


def _task_lines(core: Any, d: date) -> list[str]:
    lines = []
    for task in core.state.tasks_on(d):
        box = "x" if task.status == "done" else " "
        line = f"- [{box}] {task.start or '--:--'} {task.title} ({task.duration_min} мин)"
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
    text = vault.daily_template()
    for token, value in (("{{date}}", d.isoformat()), ("{{title}}", d.isoformat()), ("{{time}}", core.now().strftime("%H:%M"))):
        text = text.replace(token, value)
    text = set_frontmatter(text, {"date": d.isoformat(), "day": day_no, "week": week_no, "type": "daily"})
    tasks = _task_lines(core, d)
    if tasks and EMPTY_TASK.search(text):
        text = EMPTY_TASK.sub("\n".join(tasks), text, count=1)
    return core.write_note(rel, text, source="l0")["path"]


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
    if day and day.deep_min:
        values["focus_min"] = day.deep_min
        values["focus_minutes"] = day.deep_min  # заполняется только то поле, что есть в шаблоне человека
    sport = [t for t in st.tasks_on(d) if t.sphere == "sport"]
    if sport:
        values["workout"] = "да" if any(t.status == "done" for t in sport) else "нет"
    return values


def summary(core: Any, d: date) -> str:
    st = core.state
    day = st.days.get(d)
    tasks = st.tasks_on(d)
    done = sum(1 for t in tasks if t.status == "done")
    completion = st.completion(d)
    head = f"Сделано {done}/{len(tasks)}" + (f" ({completion:.0f}%)" if completion is not None else "")
    head += f" · глубокая {hm(day.deep_min if day else 0)}"
    if day and day.sleep_min:
        head += f" · сон {hm(day.sleep_min)}"
    if day and day.xp:
        head += f" · +{day.xp} XP"
    if day and day.hp_end is not None:
        head += f" · HP {day.hp_end}"
    lines = ["## Арвикс", head]
    for task in tasks:
        note = f" — {task.report}" if task.report else (f" — {task.reason}" if task.reason and task.status != "done" else "")
        lines.append(f"- {STATUS_ICON.get(task.status, '?')} {task.start or '--:--'} {task.title}{note}")
    for ev in core.store.read(0):
        if ev.kind == "debrief_completed" and ev.payload.get("date") == d.isoformat():
            lines += ["", f"**Разбор.** {ev.payload.get('answers', '').strip()}"]
            if ev.payload.get("conclusion"):
                lines.append(f"**Вывод Арвикса.** {ev.payload['conclusion'].strip()}")
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
    values = _fields(core, d)
    if values:
        core.update_note(rel, lambda text: set_frontmatter(text, values, only_empty=True), source="l0")
    core.write_block(rel, BLOCK, summary(core, d), source="l0")
    return rel


def read_fields(core: Any, d: date) -> dict[str, str]:
    """Поля, которые человек заполнил сам (телефон, игры, срывы) — для разбора."""
    note = core.vault.daily_note(d) if core.cfg.vault else None
    return {k: v for k, v in (note or {}).get("fields", {}).items() if v} if note else {}


__all__ = ["ensure", "parse_frontmatter", "program_day", "read_fields", "summary", "sync"]
