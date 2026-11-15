"""Проверки ввода (L0): Арвикс не верит на слово (02-MECHANICS §13).

Человек может поставить ненужную или нереалистичную цель, задачу поверх школы, отметить
полуторачасовой блок через 20 минут после начала. Код ищет такие несостыковки
детерминированно, а модель их называет и исправляет (constitution/critical.md).

Каждая функция чистая: на входе данные, на выходе список строк для человека.
Пустой список — всё сходится. Ничего не запрещается: запись идёт, сомнение видно.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from arvix import rules

TOP_KINDS = ("main", "yearly")
MAX_TOP_GOALS = 3          # больше трёх целей года — распыление (02-MECHANICS §13)
MAX_GOAL_YEARS = 3         # дальше — это мечта, а не цель
MAX_BLOCK_MIN = 180        # дольше трёх часов без перерыва не работают
MIN_SLEEP_TARGET = 420     # целевой сон меньше 7 ч — план на недосып
SLEEP_PLAUSIBLE = (180, 13 * 60)


def _hm(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def _min(hhmm: str) -> int:
    hours, minutes = map(int, str(hhmm).split(":")[:2])
    return hours * 60 + minutes


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"\w{4,}", text.lower())}


def similar(a: str, b: str) -> bool:
    """Похожие формулировки: большая часть основ слов совпадает («Выучить английский
    до B1» и «Английский B1 к маю»)."""
    sa, sb = _stems(a), _stems(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= 0.6


def goal_issues(goal: dict[str, Any], goals: dict[str, dict[str, Any]], today: date) -> list[str]:
    """Цель без срока и метрики, с прошедшим сроком, дубль, вторая главная, четвёртая цель года."""
    if goal.get("status", "active") != "active" or goal.get("kind") == "dream":
        return []  # мечта — направление: срок и метрика не обязательны
    issues: list[str] = []
    kind = goal.get("kind")
    others = [g for g in goals.values() if g.get("id") != goal.get("id") and g.get("status", "active") == "active"]
    deadline = None
    if not goal.get("deadline"):
        issues.append("нет срока — цель без даты не попадает в план")
    else:
        try:
            deadline = date.fromisoformat(str(goal["deadline"])[:10])
        except ValueError:
            issues.append(f"срок «{goal['deadline']}» — не дата ГГГГ-ММ-ДД")
    if deadline:
        if deadline < today:
            issues.append(f"срок {deadline:%d.%m.%Y} уже прошёл — закрыть, перенести или снять")
        elif kind != "milestone" and (deadline - today).days > MAX_GOAL_YEARS * 365:
            issues.append(f"срок дальше {MAX_GOAL_YEARS} лет — это мечта, а не цель: нужна ступень ближе")
        parent = goals.get(goal.get("parent_id") or "")
        if parent and parent.get("deadline") and str(parent["deadline"])[:10] < deadline.isoformat():
            issues.append(f"этап кончается позже цели «{parent['title']}» ({parent['deadline']})")
    if not goal.get("metric"):
        issues.append("нет метрики — как проверить, что достигнуто? Число, оценка, результат")
    if kind in ("quarterly", "milestone") and not goal.get("parent_id"):
        issues.append("этап без родительской цели — к чему он ведёт?")
    for other in others:
        if similar(goal.get("title", ""), other.get("title", "")):
            issues.append(f"похожа на цель «{other['title']}» [{other['id']}] — дубль?")
            break
    if kind == "main":
        main = [g for g in others if g.get("kind") == "main" and not g.get("parent_id")]
        if main:
            issues.append(f"главная цель уже есть — «{main[0]['title']}» [{main[0]['id']}]; главная одна")
    if kind in TOP_KINDS and not goal.get("parent_id"):
        top = [g for g in others if g.get("kind") in TOP_KINDS and not g.get("parent_id")]
        if len(top) >= MAX_TOP_GOALS:
            issues.append(f"это {len(top) + 1}-я активная цель года — силы распылятся: одну на паузу (status=dropped)")
    return issues


def task_issues(task: Any, others: list[Any], busy: list[dict[str, Any]], bedtime: str | None, now_hhmm: str | None = None) -> list[str]:
    """Задача без времени, в прошлом, поверх другой задачи или школы, впритык к отбою, слишком длинная."""
    if not task.start:
        return ["нет времени начала — напоминания не будет"]
    start = _min(task.start)
    end = start + int(task.duration_min or 0)
    issues: list[str] = []
    if now_hhmm and task.status == "planned" and start < _min(now_hhmm) - 15:
        issues.append(f"{task.start} уже прошло")
    for other in others:
        if other.start and start < _min(other.start) + other.duration_min and _min(other.start) < end:
            issues.append(f"пересекается с «{other.title}» {other.start}–{_hm(_min(other.start) + other.duration_min)}")
    for block in busy:
        b_start = _min(block["start"])
        b_end = b_start + int(block.get("duration", 60))
        if start < b_end and b_start < end:
            issues.append(f"попадает на обязательное «{block['title']}» {block['start']}–{_hm(b_end)}")
    if bedtime:
        gap = rules.minutes_after(_hm(end), bedtime)
        if gap is not None and gap < 60:
            issues.append(f"заканчивается в {_hm(end)} — меньше часа до отбоя {bedtime}")
    if task.duration_min > MAX_BLOCK_MIN:
        issues.append(f"{task.duration_min} мин подряд — разбей на блоки по 60–120 мин")
    return issues


def report_issues(title: str, now: datetime, planned: datetime | None, started: datetime | None, duration_min: int, done_pct: int) -> list[str]:
    """Отчёт «сделано полностью», которому не верят цифры: задача ещё не наступила
    или с начала прошло меньше половины её длительности."""
    if done_pct < 100:
        return []
    issues: list[str] = []
    if planned and not started and planned - now > timedelta(minutes=30):
        issues.append(f"«{title}» стоит на {planned:%H:%M}, а отмечена в {now:%H:%M} — сделано заранее или не та задача?")
    if started and duration_min:
        elapsed = int((now - started).total_seconds() // 60)
        if 0 <= elapsed < duration_min * 0.5:
            issues.append(f"«{title}» начата в {started:%H:%M}, прошло {elapsed} мин из {duration_min} — точно полностью?")
    return issues


def sleep_issues(minutes: int) -> list[str]:
    if not SLEEP_PLAUSIBLE[0] <= minutes <= SLEEP_PLAUSIBLE[1]:
        return [f"сон {minutes // 60}ч{minutes % 60:02d}м — похоже на опечатку; если так и было, это повод для разговора"]
    return []


def sleep_target_issues(target_min: int) -> list[str]:
    if target_min < MIN_SLEEP_TARGET:
        return [f"целевой сон по распорядку {target_min // 60}ч{target_min % 60:02d}м — меньше 7 ч, план заложен на недосып"]
    return []
