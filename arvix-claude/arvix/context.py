"""Контекст-пакет для L1 (04-AI-LAYER §4) — собирается кодом, не моделью.

Формат — компактный текст, не JSON (JSON ест токены). Пустые поля не выводятся.
Числа — полные, без округлений в пользу человека. В мягком режиме (🟥 или
выключенный ментор) метрики, долг и директивы не показываются вовсе.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from arvix import rules
from arvix.load import CHANNEL_LABELS

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
DAY_TYPES_RU = {"study": "Учебный", "work": "Рабочий", "deep": "Глубокий", "recovery": "Восстановительный", "silent": "Тихий"}
STATUS_ICON = {"planned": "⏳", "active": "▶️", "done": "✅", "failed": "❌", "debt": "🔴", "written_off": "✖️"}
QUOTA_RU = {"sport": "спорт", "social": "социум", "novelty": "новое", "offscreen": "отдых без экрана"}
TOP_TOPICS = ("goal", "fear", "weakness", "trigger")


LOAD_LABELS = {**CHANNEL_LABELS, "fixed": "обязательное"}


def hm(minutes: int | None) -> str:
    if minutes is None:
        return "—"
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}ч{mins:02d}м" if hours else f"{mins}м"


def end_time(start: str, duration: Any) -> str:
    """«08:30» + 360 → «14:30» (через полночь — по кругу)."""
    hours, minutes = map(int, start.split(":")[:2])
    end = hours * 60 + minutes + int(duration or 0)
    return f"{end // 60 % 24:02d}:{end % 60:02d}"


def autonomy_line(data: dict[str, Any]) -> str:
    """«Автономность: тихие дни 0.9 (3 дн) · вопросы без /answer 4/5» — пусто, пока нет данных."""
    parts = []
    if data.get("silent_ratio") is not None:
        parts.append(f"тихие дни {data['silent_ratio']:.2f} ({data['silent_days']} дн)")
    if data.get("hint_share") is not None:
        parts.append(f"вопросы без /answer {data['hints']}/{data['questions']}")
    return "Автономность: " + " · ".join(parts) if parts else ""


def task_line(task: Any, with_id: bool = True) -> str:
    """Строка задачи для модели (с id — она ссылается на задачи только по ним) или для
    человека (with_id=False: id в чате не нужен, /done принимает часть названия)."""
    bits = [task.start or "--:--", STATUS_ICON.get(task.status, "?"), task.title]
    if with_id:
        bits.insert(0, f"[{task.id}]")
    meta = [f"{task.duration_min}м", f"imp{task.importance}", f"diff{task.difficulty}"]
    if task.deep_work:
        meta.append("deep")
    if task.proof != "confirm":
        meta.append(f"отчёт:{task.proof}")
    if task.status == "done" and task.done_pct < 100:
        meta.append(f"{task.done_pct}%")
    return " ".join(bits) + " · " + " ".join(meta)


def _facts(state: Any, message: str, today: date | None = None, limit: int = 8) -> list[str]:
    """Топ важных фактов всегда + совпадения по словам сообщения (вместо векторов).
    Факт с истёкшим valid_until («сессия до пятницы») в контекст больше не попадает."""
    alive = today.isoformat() if today else ""
    facts = [f for f in state.facts.values() if not (alive and f.get("valid_until") and f["valid_until"] < alive)]
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
    elif gentle:
        mode_label += " — день восстановления"  # причина с цифрами (%, часы) в мягкий контекст не идёт — правило №5
    elif st.mode_trigger:
        mode_label += f" ({st.mode_trigger})"
    day_type = DAY_TYPES_RU.get(day.day_type) if day and day.day_type else None
    head = f"СЕЙЧАС: {WEEKDAYS[today.weekday()]} {today:%d.%m.%Y}, {now:%H:%M} ({core.tz.key}). Режим: {mode_label}."
    if day_type:
        head += f" Тип дня: {day_type}."
    if day and day.silent:
        head += " ТИХИЙ ДЕНЬ: проактивных сообщений нет, долга за сегодня нет."
    lines.append(head)

    profile = st.profile
    who = [profile.get("name")]
    if profile.get("bedtime_target") and profile.get("wake_target"):
        who.append(f"сон по плану {profile['bedtime_target']}–{profile['wake_target']} (норма {hm(core.sleep_target())})")
    if any(who):
        lines.append("ЧЕЛОВЕК: " + " · ".join(x for x in who if x))

    sleep = f" · сон {hm(day.sleep_min)}" if day and day.sleep_min else ""
    tasks = st.tasks_on(today)
    if gentle:
        if sleep:
            lines.append("СЕГОДНЯ:" + sleep.lstrip(" ·"))
        else:
            lines.append("СОН СЕГОДНЯ: не записан. Спроси между делом, во сколько лёг и встал, и запиши: log_sleep с bedtime и wake.")
        open_tasks = [t for t in tasks if t.is_open]
        if open_tasks:
            small = min(open_tasks, key=lambda t: (t.duration_min or 999, t.importance))
            lines.append(f"ОДНА МАЛЕНЬКАЯ ВЕЩЬ НА ВЫБОР: {small.title} ({small.duration_min} мин) [{small.id}]")
        if st.mentor_enabled and st.mode == "red":
            lines.append(f"ВЫХОД ИЗ 🟥 (считает код): {core.red_exit()}. Готов вернуться — action offer_return, решает он кнопкой.")
        return "\n".join(lines)

    status = core.status()
    done = sum(1 for t in tasks if t.status == "done")
    completion = st.completion(today)
    deep_target = core.deep_target(today)
    if tasks or sleep:
        pct = f" ({completion:.0f}%)" if completion is not None else ""
        lines.append(f"СЕГОДНЯ: {done}/{len(tasks)} задач{pct} · глубокая {hm(day.deep_min if day else 0)} из {hm(deep_target)}{sleep}")
    if tasks:
        lines.append("ЗАДАЧИ:\n" + "\n".join("  " + task_line(t) for t in tasks))
    if busy := core.fixed_blocks(today):
        lines.append("ЗАНЯТО: " + " · ".join(f"{b['start']}–{end_time(b['start'], b.get('duration', 60))} {b['title']}" for b in busy))
    debts = st.debts()
    if debts:
        lines.append("ДОЛГ: " + " · ".join(f"[{t.id}] {t.title} ({(today - t.debt_since).days} дн)" for t in debts if t.debt_since))
    tomorrow = st.tasks_on(today + timedelta(days=1))
    if tomorrow:
        lines.append("ЗАВТРА: " + " · ".join(f"{t.start or '--:--'} {t.title}" for t in tomorrow[:5]))

    week = st.week_stats(today)
    quotas = core.cfg.mech("quotas") or {}
    quota_text = " · ".join(f"{QUOTA_RU.get(k, k)} {week['quotas'].get(k, 0)}/{v}" for k, v in quotas.items())
    plan = core.budget()
    budget, deep_budget = plan["week_min"], plan["deep_min"]
    spent = sum(week["expenses"].values())
    week_line = f"НЕДЕЛЯ: сделано {hm(week['productive_min'])}/{hm(budget)} · глубокая {hm(week['deep_min'])}/{hm(deep_budget)}"
    if quota_text:
        week_line += f" · квоты: {quota_text}"
    if spent:
        week_line += f" · траты {spent:.0f}" + (f" (импульсивные {week['impulse']:.0f})" if week["impulse"] else "")
    lines.append(week_line)
    planned = core.planned_minutes(st.week_start(today), st.week_start(today) + timedelta(days=6))
    load = f"НАГРУЗКА: бюджет {hm(budget)}/нед (глубокая {hm(deep_budget)}) · запланировано {hm(planned)} · пересмотр {plan['next_review']:%d.%m}"
    if plan["auto"]:
        load += " · авто: " + ", ".join(f"{LOAD_LABELS[ch]} {hm(m)}" for ch, m in plan["channels"].items() if m)
    if plan.get("reason"):
        load += f" · последний пересмотр: {plan['reason']}"
    warnings = core.load_check(today)
    if warnings:
        load += "\n  ⚠️ " + "\n  ⚠️ ".join(warnings)
    lines.append(load)
    if not st.templates:
        lines.append("РАСПОРЯДОК: шаблонов дней нет — задачи и напоминания не создаются. Предложи собрать распорядок.")

    if autonomy := autonomy_line(status["autonomy"]):
        lines.append("АВТОНОМНОСТЬ:" + autonomy.split(":", 1)[1])
    if st.lessons:
        recent = st.lessons[-4:]
        lines.append("УРОКИ: " + " · ".join(
            f"{x['date'][8:10]}.{x['date'][5:7]} {x['subject']}: {x['topic']}" + (f" {x['score']}%" if x.get("score") is not None else "") for x in recent))

    directives = st.active_directives(today)[:5]
    if directives:
        lines.append("ДИРЕКТИВЫ:\n" + "\n".join(f"  [{d['kind']}/p{d['priority']}] {d['text']}" + (f" — {d['voice_hint']}" if d.get("voice_hint") else "") for d in directives))

    goals = [g for g in st.goals.values() if g.get("status", "active") == "active"]
    main = [g for g in goals if g.get("kind") == "main"] or goals
    if main:
        goal = main[0]
        lines.append(f"ГЛАВНАЯ ЦЕЛЬ: [{goal['id']}] {goal['title']} (зачем: {goal.get('why', '—')})" + (f" · до {goal['deadline']}" if goal.get("deadline") else ""))
        stages = [g for g in goals if g.get("parent_id") == goal["id"]]
        if stages:
            done = sum(1 for g in st.goals.values() if g.get("parent_id") == goal["id"] and g.get("status") == "done")
            nxt = min(stages, key=lambda g: g.get("deadline") or "9999")
            lines.append(f"ЭТАПЫ: {done}/{done + len(stages)} пройдено · следующий: [{nxt['id']}] {nxt['title']}" + (f" до {nxt['deadline']}" if nxt.get("deadline") else ""))
    traits = sorted(st.traits.values(), key=lambda t: -int(t.get("severity", 3)))[:4]
    if traits:
        lines.append("ЧЕРТЫ: " + " · ".join(f"{t['kind']}: {t['title']}" + (f" → {t['counter_strategy']}" if t.get("counter_strategy") else "") for t in traits))
    facts = _facts(st, message, today)
    if facts:
        lines.append("ПАМЯТЬ: " + " · ".join(facts))

    issues = core.audit()
    if issues:  # код нашёл несостыковку — модель обязана её поднять (constitution/critical.md)
        lines.append("ПРОВЕРИТЬ:\n" + "\n".join(f"  ⚠️ {i}" for i in issues))

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
