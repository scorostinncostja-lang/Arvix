"""Arvix пишет первым — по важному поводу, а не по расписанию (D59).

Повод находит код, детерминированно: блок прошёл и молчит, одна и та же задача снова и снова уезжает.
Что сказать и стоит ли вообще — решает голова: пустой ответ значит «не о чем», и сообщение не уходит.
Квоты на число сообщений нет — владелец так решил. Есть гигиена: не ночью, не во время фокуса,
не посреди разговора, не в 🟥 и в тихий день, не чаще раза в GAP_MIN минут — один сбой не зальёт чат.

Паттерны (patterns) — тоже код: они идут в контекст каждого ответа, чтобы голова видела их и в разговоре.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


MISSED_AFTER_MIN = 40      # блок кончился, отчёта нет столько минут — повод
MISSED_WINDOW_H = 5        # старше — уже не «только что», об этом скажет разбор
GAP_MIN = 40               # между двумя сообщениями-инициативами
TALKING_MIN = 15           # человек писал недавно — он и так в разговоре, голова ответит там
PATTERN_DAYS = 14
PATTERN_MISSES = 2         # столько несделанных за PATTERN_DAYS — паттерн
PATTERN_DEFERS = 3         # или столько переносов
PATTERN_REPEAT_DAYS = 7    # один и тот же паттерн — не чаще раза в неделю
TRIED = "initiative_tried"  # ключи поводов, по которым голову уже спрашивали (даже если она промолчала)
LAST = "initiative_last"    # время последней попытки
MISSED_STATUSES = ("failed", "debt", "written_off")


def topic(title: str) -> str:
    """«Физика: §12, закон Ома» и «Физика: §13» — одна тема «физика»."""
    head = title.split(":")[0].split("—")[0].strip().lower()
    return " ".join(head.split()[:3])


def patterns(core: Any, today: date | None = None) -> list[dict[str, Any]]:
    """Темы, которые за PATTERN_DAYS дней чаще проваливаются или уезжают. Сначала самые упорные."""
    today = today or core.today()
    since = today - timedelta(days=PATTERN_DAYS - 1)
    stats: dict[str, dict[str, Any]] = {}
    by_id: dict[str, str] = {}
    for task in core.state.tasks.values():
        if not (since <= task.local_date <= today) or task.status == "cancelled":
            continue
        key = topic(task.title)
        if not key:
            continue
        s = stats.setdefault(key, {"topic": task.title.split(":")[0].strip(), "total": 0, "missed": 0, "done": 0, "defers": 0})
        s["total"] += 1
        s["missed"] += task.status in MISSED_STATUSES
        s["done"] += task.status == "done"
        by_id[task.id] = key
    start = max(0, core.state.last_event_id - 6000)
    for ev in core.store.read(start):
        if ev.kind == "task_deferred" and ev.entity_id in by_id and ev.local_date >= since:
            stats[by_id[ev.entity_id]]["defers"] += 1
    found = [s for s in stats.values() if s["missed"] >= PATTERN_MISSES or s["defers"] >= PATTERN_DEFERS]
    return sorted(found, key=lambda s: -(2 * s["missed"] + s["defers"]))


def pattern_line(s: dict[str, Any]) -> str:
    parts = [f"{s['total']} блоков", f"сделано {s['done']}"]
    if s["missed"]:
        parts.append(f"не сделано {s['missed']}")
    if s["defers"]:
        parts.append(f"переносов {s['defers']}")
    return f"«{s['topic']}» за {PATTERN_DAYS} дней: " + ", ".join(parts)


def missed(core: Any, now: datetime) -> list[Any]:
    """Открытые блоки, которые кончились MISSED_AFTER_MIN+ минут назад, — человек молчит о них."""
    out = []
    for task in core.open_yesterday() + core.state.tasks_on(now.date()):
        if not task.is_open or not task.start:
            continue
        end = core.at(task.local_date, task.start) + timedelta(minutes=max(task.duration_min, 5))
        if end + timedelta(minutes=MISSED_AFTER_MIN) <= now < end + timedelta(hours=MISSED_WINDOW_H):
            out.append(task)
    return out


def quiet_hours(core: Any, now: datetime) -> bool:
    """Ночь человека: от отбоя по плану до подъёма (+30 мин). Без распорядка — 23:00–08:00 (подъём 07:30 + 30 мин)."""
    from arvix.core import parse_hhmm  # лениво: core тянет context, а context — этот модуль
    profile = core.state.profile
    bed = parse_hhmm(profile.get("bedtime_target")) or "23:00"
    wake = parse_hhmm(profile.get("wake_target")) or "07:30"
    t = f"{now:%H:%M}"
    wake_plus = (datetime.strptime(wake, "%H:%M") + timedelta(minutes=30)).strftime("%H:%M")
    if bed <= wake_plus:  # отбой после полуночи: 01:00–09:00
        return bed <= t < wake_plus
    return t >= bed or t < wake_plus


def blocked(core: Any, now: datetime) -> str:
    """Почему сейчас писать первым нельзя ('' — можно). Порядок — от дешёвых проверок к дорогим."""
    st = core.state
    day = st.days.get(now.date())
    if not st.mentor_enabled or core.effective_mode() == "red":
        return "мягкий режим"
    if day and day.silent:
        return "тихий день"
    if core.store.kv_get("focus"):
        return "фокус"
    if quiet_hours(core, now):
        return "ночь"
    last_in = core.store.kv_get("last_in_at")
    if last_in and now.timestamp() - float(last_in) < TALKING_MIN * 60:
        return "разговор"
    last = core.store.kv_get(LAST)
    if last and now.timestamp() - float(last) < GAP_MIN * 60:
        return "недавно писал"
    return ""


def reasons(core: Any, now: datetime) -> tuple[list[str], list[str]]:
    """Новые поводы: (ключи, строки для головы). Ключ, по которому голову уже спрашивали, не повторяется."""
    tried = set(core.store.kv_get(TRIED) or [])
    keys, lines = [], []
    gone = missed(core, now)
    fresh = [t for t in gone if f"missed:{t.id}" not in tried]
    if fresh:
        keys += [f"missed:{t.id}" for t in fresh]
        lines.append("БЛОК ПРОШЁЛ, ОТЧЁТА НЕТ: " + " · ".join(
            f"[{t.id}] {t.start} {t.title} ({t.duration_min} мин)" for t in fresh))
    for s in patterns(core, now.date())[:2]:
        key = f"pattern:{topic(s['topic'])}"
        last_day = core.store.kv_get(f"{TRIED}:{key}")
        if last_day and (now.date() - date.fromisoformat(last_day)).days < PATTERN_REPEAT_DAYS:
            continue
        # паттерн — повод сам по себе, только если по этой теме что-то происходит сегодня
        today_topic = any(topic(t.title) == topic(s["topic"]) for t in gone + core.state.tasks_on(now.date()))
        if fresh or today_topic:
            keys.append(key)
            lines.append("ПОВТОРЯЕТСЯ: " + pattern_line(s))
    return keys, lines


def remember(core: Any, now: datetime, keys: list[str]) -> None:
    """Голову спросили по этим поводам — второй раз не спрашивать, даже если она промолчала."""
    tried = list(core.store.kv_get(TRIED) or []) + [k for k in keys if not k.startswith("pattern:")]
    core.store.kv_set(TRIED, tried[-300:])
    for key in keys:
        if key.startswith("pattern:"):
            core.store.kv_set(f"{TRIED}:{key}", now.date().isoformat())
    core.store.kv_set(LAST, now.timestamp())


PROMPT = """<initiative>
Человек ничего не писал — ты пишешь первым, потому что код увидел повод:
{reasons}

Это не напоминание (их код уже прислал) и не отчёт. Это ты — наставник на его стороне, который заметил.
1. Назови наблюдение по данным без предположений о характере человека.
2. Если причина неясна — один вопрос. Иначе предложи один короткий следующий шаг.
   Это инициатива без согласия на изменения: actions пустой, не меняй расписание или задачи, не запускай таймер.
3. Если к месту — одна мысль, которая заставит задуматься (см. <depth>), привязанная к его ситуации.
2–4 предложения, каждое несёт факт, вывод или шаг. Главное — **жирным**.
Если повод мелкий и писать незачем (задача уже сделана по отчётам, человек явно занят другим важным) — reply пустой.
</initiative>"""
