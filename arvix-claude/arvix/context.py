"""Контекст-пакет для L1 (04-AI-LAYER §3) — собирается кодом, не моделью.

Формат — компактный текст, не JSON (JSON ест токены). Пустые поля не выводятся.
Числа — полные, без округлений в пользу человека. В мягком режиме (🟥 или
выключенный ментор) метрики, долг и директивы не показываются вовсе.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from arvix import rules

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
DAY_TYPES_RU = {"study": "Учебный", "work": "Рабочий", "deep": "Глубокий", "recovery": "Восстановительный", "silent": "Тихий"}
STATUS_ICON = {"planned": "⏳", "active": "▶️", "done": "✅", "failed": "❌", "debt": "🔴", "written_off": "✖️"}
QUOTA_RU = {"sport": "спорт", "social": "социум", "novelty": "новое", "offscreen": "отдых без экрана"}
TOP_TOPICS = ("goal", "fear", "weakness", "trigger")


def hm(minutes: int | None) -> str:
    if minutes is None:
        return "—"
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}ч{mins:02d}м" if hours else f"{mins}м"


def task_line(task: Any) -> str:
    bits = [f"[{task.id}]", task.start or "--:--", STATUS_ICON.get(task.status, "?"), task.title]
    meta = [f"{task.duration_min}м", f"imp{task.importance}", f"diff{task.difficulty}"]
    if task.deep_work:
        meta.append("deep")
    if task.proof != "confirm":
        meta.append(f"отчёт:{task.proof}")
    if task.status == "done" and task.done_pct < 100:
        meta.append(f"{task.done_pct}%")
    return " ".join(bits) + " · " + " ".join(meta)


def _facts(state: Any, message: str, limit: int = 8) -> list[str]:
    """Топ важных фактов всегда + совпадения по словам сообщения (вместо векторов)."""
    facts = list(state.facts.values())
    top = [f for f in facts if f.get("topic") in TOP_TOPICS][:3]
    words = {w[:5] for w in re.findall(r"\w{4,}", message.lower())}
    scored = []
    for fact in facts:
        if fact in top:
            continue
        text = fact["fact"].lower()
        score = sum(1 for w in words if w in text) * 10 + int(fact.get("confidence", 3))
        scored.append((score, fact.get("event_id", 0), fact))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picked = top + [f for _, _, f in scored[: limit - len(top)]]
    return [f["fact"] for f in picked]


def build_context(core: Any, *, message: str = "", gentle: bool | None = None) -> str:
    st = core.state
    now = core.now()
    today = now.date()
    if gentle is None:
        gentle = core.effective_mode() == "red"
    day = st.days.get(today)
    lines = []

    mode_label = rules.MODE_LABELS[core.effective_mode()]
    if not st.mentor_enabled:
        mode_label += " (ментор выключен safety-контуром)"
    elif st.mode_trigger:
        mode_label += f" ({st.mode_trigger})"
    day_type = DAY_TYPES_RU.get(day.day_type) if day and day.day_type else None
    head = f"СЕЙЧАС: {WEEKDAYS[today.weekday()]} {today:%d.%m.%Y}, {now:%H:%M} ({core.tz.key}). Режим: {mode_label}."
    if day_type:
        head += f" Тип дня: {day_type}."
    if day and day.silent:
        head += " ТИХИЙ ДЕНЬ: проактивных сообщений нет, разбор без штрафов."
    lines.append(head)

    profile = st.profile
    who = [profile.get("name")]
    if profile.get("bedtime_target") and profile.get("wake_target"):
        who.append(f"сон по плану {profile['bedtime_target']}–{profile['wake_target']}")
    if any(who):
        lines.append("ЧЕЛОВЕК: " + " · ".join(x for x in who if x))

    sleep = f" · сон {hm(day.sleep_min)}" if day and day.sleep_min else ""
    tasks = st.tasks_on(today)
    if gentle:
        if sleep:
            lines.append("СЕГОДНЯ:" + sleep.lstrip(" ·"))
        open_tasks = [t for t in tasks if t.is_open]
        if open_tasks:
            lines.append(f"ОДНА МАЛЕНЬКАЯ ВЕЩЬ НА ВЫБОР: {open_tasks[0].title}")
        return "\n".join(lines)

    status = core.status()
    season = status["season"]
    lines.append(
        f"СОСТОЯНИЕ: ур.{status['level']} ({status['xp_into']}/{status['xp_need']} XP) · HP {st.hp}"
        f" · стрик {status['streak']} дн · сезон S{season['number']} нед.{season['week']} {season['rank']} (SP {season['sp_avg']})"
        + (" · ПРОТОКОЛ НОЛЬ" if status["protocol_zero"] else "")
    )
    done = sum(1 for t in tasks if t.status == "done")
    completion = st.completion(today)
    deep_target = int(core.cfg.mech("deep_target_min", 120))
    if tasks or sleep:
        pct = f" ({completion:.0f}%)" if completion is not None else ""
        lines.append(f"СЕГОДНЯ: {done}/{len(tasks)} задач{pct} · глубокая {hm(day.deep_min if day else 0)} из {hm(deep_target)}{sleep}")
    if tasks:
        lines.append("ЗАДАЧИ:\n" + "\n".join("  " + task_line(t) for t in tasks))
    debts = st.debts()
    if debts:
        lines.append("ДОЛГ: " + " · ".join(f"[{t.id}] {t.title} ({(today - t.debt_since).days} дн)" for t in debts if t.debt_since))
    tomorrow = st.tasks_on(today + timedelta(days=1))
    if tomorrow:
        lines.append("ЗАВТРА: " + " · ".join(f"{t.start or '--:--'} {t.title}" for t in tomorrow[:5]))

    week = st.week_stats(today)
    quotas = core.cfg.mech("quotas") or {}
    quota_text = " · ".join(f"{QUOTA_RU.get(k, k)} {week['quotas'].get(k, 0)}/{v}" for k, v in quotas.items())
    budget = int(core.cfg.mech("week_budget_min", 1560))
    deep_budget = int(core.cfg.mech("week_deep_budget_min", 480))
    spent = sum(week["expenses"].values())
    week_line = f"НЕДЕЛЯ: бюджет {hm(week['productive_min'])}/{hm(budget)} · глубокая {hm(week['deep_min'])}/{hm(deep_budget)}"
    if quota_text:
        week_line += f" · квоты: {quota_text}"
    if spent:
        week_line += f" · траты {spent:.0f}" + (f" (импульсивные {week['impulse']:.0f})" if week["impulse"] else "")
    lines.append(week_line)

    directives = st.active_directives(today)[:5]
    if directives:
        lines.append("ДИРЕКТИВЫ:\n" + "\n".join(f"  [{d['kind']}/p{d['priority']}] {d['text']}" + (f" — {d['voice_hint']}" if d.get("voice_hint") else "") for d in directives))

    goals = [g for g in st.goals.values() if g.get("status", "active") == "active"]
    main = [g for g in goals if g.get("kind") == "main"] or goals
    if main:
        goal = main[0]
        lines.append(f"ГЛАВНАЯ ЦЕЛЬ: {goal['title']} (зачем: {goal.get('why', '—')})" + (f" · до {goal['deadline']}" if goal.get("deadline") else ""))
    traits = sorted(st.traits.values(), key=lambda t: -int(t.get("severity", 3)))[:4]
    if traits:
        lines.append("ЧЕРТЫ: " + " · ".join(f"{t['kind']}: {t['title']}" + (f" → {t['counter_strategy']}" if t.get("counter_strategy") else "") for t in traits))
    facts = _facts(st, message)
    if facts:
        lines.append("ПАМЯТЬ: " + " · ".join(facts))

    recent = []
    for offset, label in ((1, "вчера"), (2, "позавчера")):
        closed = st.days.get(today - timedelta(days=offset))
        if closed and closed.closed and closed.closed.get("total"):
            recent.append(f"{label} {closed.closed['done']}/{closed.closed['total']}")
    yesterday = st.days.get(today - timedelta(days=1))
    if yesterday and yesterday.closed:
        recent.append("разбор вчера: " + ("пройден" if yesterday.debrief else "пропущен"))
    if recent:
        lines.append("ПОСЛЕДНЕЕ: " + " · ".join(recent))

    interview = core.interview_status()
    if interview["answered"] < interview["total"] and interview["next"]:
        block = next(b for b in interview["blocks"] if b["block"] == interview["next"]["block"])
        lines.append(f"ЗНАКОМСТВО: отвечено {interview['answered']}/{interview['total']} — следующий блок «{block['title']}»")
    return "\n".join(lines)
