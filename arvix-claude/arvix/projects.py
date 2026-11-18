"""Проекты (D43, 02-MECHANICS §14): то, что человек строит сам, — с ожиданием, сроком, этапами
с критерием готовности, временем в неделю, журналом, деньгами и каналами привлечения.

Всё, что здесь считается, — L0: время, темп, прогноз, застой, деньги, цена клиента. Модель эти
числа только читает (правило №1). Состояние меняется только событиями (правило №3):
project_set · milestone_set · project_logged · project_money · channel_set; задачи проекта —
обычные task_created с полем project.

Арвикс не делает проект за человека (00-VISION §7): режет на этапы, ставит блоки, разбирает,
проверяет результат. Деньги — учёт фактов из журнала, без инвестиционных советов.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from arvix.core import ArvixError, new_id, parse_hhmm

KINDS = {"learning": "обучение", "portfolio": "портфолио", "income": "доход", "community": "люди и единомышленники"}
STATUSES = {"idea": "идея", "active": "в работе", "paused": "пауза", "done": "готов", "dropped": "закрыт"}
MILESTONE_STATUSES = ("open", "done", "dropped")
LOG_KINDS = {"update": "сделано", "decision": "решение", "lesson": "урок", "blocker": "стопор", "release": "релиз",
             "feedback": "отзыв"}
CHANNEL_TYPES = {"free": "бесплатный", "barter": "условно бесплатный", "paid": "платный"}
CHANNEL_STATUSES = {"test": "тест", "works": "работает", "dropped": "не работает"}

STALL_DAYS = 7        # без движения столько дней — застой: Арвикс пишет сам
DECIDE_DAYS = 21      # столько — прямой вопрос «продолжаем, пауза или закрываем?»: проект не умирает молча
BEHIND_MARGIN = 0.15  # отставание этапов от времени больше 15 п.п. — «отстаёт»
DAY_START = "09:00"   # раньше блок проекта код сам не ставит


def _min(hhmm: str) -> int:
    hours, minutes = map(int, str(hhmm).split(":"))
    return hours * 60 + minutes


def max_active(core: Any) -> int:
    """Лимит проектов в работе: распыление — проблема №5 из 00-VISION. Четвёртый проект
    начинается только паузой или закрытием одного из трёх."""
    return int(core.cfg.section("projects").get("max_active") or 3)


# --- поиск --------------------------------------------------------------------------------------

def resolve(core: Any, ref: Any) -> dict[str, Any]:
    key = str(ref or "").strip().strip("#[]")
    projects = core.state.projects
    if key in projects:
        return projects[key]
    found = [p for p in projects.values() if len(key) >= 3 and p["id"].startswith(key)]
    if not found and key:
        low = key.lower()
        found = [p for p in projects.values() if low in p["title"].lower()]
        alive = [p for p in found if p["status"] in ("active", "idea", "paused")]
        found = alive if len(alive) == 1 else found
    if len(found) == 1:
        return found[0]
    names = "; ".join(p["title"] for p in projects.values() if p["status"] != "dropped") or "проектов нет"
    if not found:
        raise ArvixError(f"Проект «{ref}» не найден. Есть: {names}")
    raise ArvixError(f"Под «{ref}» подходит несколько проектов: {'; '.join(p['title'] for p in found[:5])}")


def _date(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ArvixError(f"{field}: дата «{value}» не похожа на ГГГГ-ММ-ДД") from exc


def _money(value: Any, field: str = "Сумма") -> float:
    try:
        number = round(float(str(value).replace(",", ".").replace(" ", "").replace("₽", "")), 2)
    except ValueError as exc:
        raise ArvixError(f"{field} «{value}» не число") from exc
    if number < 0:
        raise ArvixError(f"{field} не может быть отрицательной")
    return number


# --- операции (каждая — событие) ------------------------------------------------------------------

def set_project(
    core: Any, title: str = "", *, project_id: str | None = None, why: str = "", kind: str | None = None,
    expectation: str = "", deadline: Any = None, weekly_min: Any = None, goal_id: str | None = None,
    status: str | None = None, skills: list[str] | None = None, link: str = "", reason: str = "", source: str = "claude",
) -> str:
    """Новый проект или правка. С project_id непереданные поля остаются прежними."""
    st = core.state
    old = resolve(core, project_id) if project_id else {}
    if status and status not in STATUSES:
        raise ArvixError(f"Статус проекта: {', '.join(STATUSES)}")
    if goal_id and goal_id not in st.goals:
        raise ArvixError(f"Цели {goal_id} нет")
    payload = {
        "id": old.get("id") or new_id(),
        "title": (str(title).strip() or old.get("title", ""))[:120],
        "why": (str(why).strip() or old.get("why", ""))[:500],
        "kind": kind if kind in KINDS else old.get("kind", "learning"),
        "expectation": (str(expectation).strip() or old.get("expectation", ""))[:500],
        "deadline": _date(deadline, "Срок") or old.get("deadline"),
        "weekly_min": max(0, min(int(weekly_min), 40 * 60)) if weekly_min not in (None, "") else int(old.get("weekly_min") or 0),
        "goal_id": goal_id or old.get("goal_id"),
        "status": status or old.get("status") or "active",
        "skills": [str(s).strip()[:40] for s in (skills if skills is not None else old.get("skills") or []) if str(s).strip()][:12],
        "link": (str(link).strip() or old.get("link", ""))[:300],
    }
    if not payload["title"]:
        raise ArvixError("У проекта нет названия")
    if not payload["why"]:
        raise ArvixError("У проекта обязательно «зачем»: навык, портфолио, доход, люди — что именно ты хочешь получить")
    if payload["status"] in ("done", "dropped") and old.get("status") != payload["status"] and len(reason.strip()) < 10:
        raise ArvixError("Закрыть проект можно только с итогом: что получилось и почему так — хотя бы одной фразой")
    if payload["status"] == "active" and old.get("status") != "active":
        others = [p for p in st.projects.values() if p["status"] == "active" and p["id"] != payload["id"]]
        if len(others) >= max_active(core):
            names = ", ".join(p["title"] for p in others)
            raise ArvixError(f"В работе уже {len(others)} проекта ({names}) — это лимит. Поставь один на паузу или закрой, "
                             "иначе ни один не доедет до конца. Новый пока сохраню идеей, если скажешь.")
    if reason.strip():
        payload["reason"] = reason.strip()[:1000]
    with core.tx():
        core.emit("project_set", payload, source=source, entity_id=payload["id"])
    return payload["id"]


def set_milestone(
    core: Any, project_ref: Any, title: str = "", *, milestone_id: str | None = None, due: Any = None, dod: str = "",
    status: str | None = None, source: str = "claude",
) -> str:
    """Этап проекта. Новый этап — только с критерием готовности (DoD): «лендинг онлайн и 3 человека
    оставили контакт», а не «поработать над лендингом» (П4)."""
    project = resolve(core, project_ref)
    old = core.state.milestones.get(milestone_id or "", {})
    if milestone_id and not old:
        raise ArvixError(f"Этапа {milestone_id} нет")
    if status and status not in MILESTONE_STATUSES:
        raise ArvixError(f"Статус этапа: {', '.join(MILESTONE_STATUSES)}")
    order = old.get("order")
    if order is None:
        order = 1 + max((m.get("order", 0) for m in core.state.milestones.values() if m["project_id"] == project["id"]), default=0)
    payload = {
        "id": old.get("id") or new_id(),
        "project_id": project["id"],
        "title": (str(title).strip() or old.get("title", ""))[:200],
        "dod": (str(dod).strip() or old.get("dod", ""))[:500],
        "due": _date(due, "Срок этапа") or old.get("due"),
        "status": status or old.get("status") or "open",
        "order": int(order),
    }
    if not payload["title"]:
        raise ArvixError("У этапа нет названия")
    if not payload["dod"]:
        raise ArvixError("У этапа нужен критерий готовности: как проверить, что он сделан — число, ссылка, результат")
    with core.tx():
        core.emit("milestone_set", payload, source=source, entity_id=project["id"])
    return payload["id"]


def log_entry(core: Any, project_ref: Any, text: str, *, kind: str = "update", minutes: Any = 0, source: str = "claude") -> dict[str, Any]:
    """Запись в журнал проекта: что сделано, решение, урок, стопор, релиз, отзыв. Минуты — со слов,
    поэтому в статистике они отдельно от минут задач и таймера."""
    project = resolve(core, project_ref)
    text = str(text).strip()
    if not text:
        raise ArvixError("Пустая запись в журнал проекта")
    kind = kind if kind in LOG_KINDS else "update"
    payload = {"project_id": project["id"], "kind": kind, "text": text[:2000],
               "minutes": max(0, min(int(minutes or 0), 12 * 60))}
    with core.tx():
        core.emit("project_logged", payload, source=source, entity_id=project["id"])
    return payload


def log_money(core: Any, project_ref: Any, amount: Any, *, direction: str = "out", category: str = "", note: str = "",
              channel_id: str | None = None, source: str = "claude") -> dict[str, Any]:
    """Доход (in) или расход (out) проекта. Трата проекта — не личная трата недели: в квоты и
    импульсивные траты она не идёт, у неё свой учёт."""
    project = resolve(core, project_ref)
    value = _money(amount)
    if value <= 0:
        raise ArvixError("Сумма должна быть больше нуля")
    if direction not in ("in", "out"):
        raise ArvixError("direction: in — доход, out — расход")
    if channel_id and channel_id not in core.state.channels:
        raise ArvixError(f"Канала {channel_id} нет")
    payload = {"project_id": project["id"], "amount": value, "direction": direction,
               "currency": core.state.profile.get("currency", "RUB"),
               "category": (category or ("продажи" if direction == "in" else "прочее")).strip().lower()[:40],
               "note": str(note).strip()[:300], "channel_id": channel_id}
    with core.tx():
        core.emit("project_money", payload, source=source, entity_id=project["id"])
    return payload


def set_channel(
    core: Any, project_ref: Any, name: str = "", *, channel_id: str | None = None, type: str | None = None,
    hypothesis: str = "", cost: Any = None, leads: Any = None, clients: Any = None, revenue: Any = None,
    status: str | None = None, note: str = "", source: str = "claude",
) -> str:
    """Канал привлечения как эксперимент: гипотеза → цена → заявки → клиенты → вывод.
    Числа — накопленным итогом (сколько всего), а не приростом: так их не задвоить."""
    project = resolve(core, project_ref)
    old = core.state.channels.get(channel_id or "", {})
    if channel_id and not old:
        raise ArvixError(f"Канала {channel_id} нет")
    if status and status not in CHANNEL_STATUSES:
        raise ArvixError(f"Статус канала: {', '.join(CHANNEL_STATUSES)}")

    def num(value: Any, key: str, field: str) -> float:
        return _money(value, field) if value not in (None, "") else float(old.get(key) or 0)

    payload = {
        "id": old.get("id") or new_id(),
        "project_id": project["id"],
        "name": (str(name).strip() or old.get("name", ""))[:80],
        "type": type if type in CHANNEL_TYPES else old.get("type", "free"),
        "hypothesis": (str(hypothesis).strip() or old.get("hypothesis", ""))[:500],
        "cost": num(cost, "cost", "Затраты"),
        "leads": int(num(leads, "leads", "Заявки")),
        "clients": int(num(clients, "clients", "Клиенты")),
        "revenue": num(revenue, "revenue", "Выручка"),
        "status": status or old.get("status") or "test",
        "note": (str(note).strip() or old.get("note", ""))[:500],
    }
    if not payload["name"]:
        raise ArvixError("У канала нет названия: Reels, Telegram-канал, Авито, сарафан…")
    if not payload["hypothesis"]:
        raise ArvixError("Канал без гипотезы — не эксперимент. Что ждёшь: «5 роликов → 20 заявок за 2 недели»?")
    if payload["clients"] > payload["leads"]:
        payload["leads"] = payload["clients"]  # клиент — тоже заявка; иначе конверсия больше 100 %
    with core.tx():
        core.emit("channel_set", payload, source=source, entity_id=project["id"])
    return payload["id"]


def next_step(core: Any, project: dict[str, Any]) -> dict[str, Any] | None:
    open_ms = [m for m in milestones(core, project["id"]) if m["status"] == "open"]
    return open_ms[0] if open_ms else None


def free_slot(core: Any, d: date, minutes: int) -> str | None:
    """Первое свободное окно на дату: не раньше DAY_START и текущего времени, не позже чем за час до
    отбоя, мимо задач и обязательных блоков. Код ищет, модель не угадывает."""
    busy: list[tuple[int, int]] = []
    for task in core.state.tasks_on(d):
        if task.start and task.status not in ("cancelled", "failed", "written_off"):
            start = _min(task.start)
            busy.append((start, start + max(task.duration_min, 15)))
    for block in core.fixed_blocks(d):
        start = _min(block["start"])
        busy.append((start, start + int(block.get("duration", 60))))
    begin = _min(DAY_START)
    if d == core.today():
        now = core.now()
        begin = max(begin, -(-(now.hour * 60 + now.minute + 10) // 15) * 15)
    bed = core.state.profile.get("bedtime_target")
    end = _min(bed) - 60 if bed and _min(bed) > 12 * 60 else 22 * 60
    cursor = begin
    for start, stop in sorted(busy):
        if start - cursor >= minutes:
            break
        cursor = max(cursor, stop)
    if cursor + minutes > end:
        return None
    return f"{cursor // 60:02d}:{cursor % 60:02d}"


def plan_block(core: Any, project_ref: Any, *, minutes: int = 60, day: Any = None, start: Any = None, title: str = "",
               source: str = "claude") -> Any:
    """Блок проекта в план: задача сферы project, глубокая работа, привязана к проекту. Время — первое
    свободное окно, если не задано. Название — следующий этап, чтобы блок работал на результат."""
    project = resolve(core, project_ref)
    if project["status"] in ("done", "dropped"):
        raise ArvixError(f"Проект «{project['title']}» {STATUSES[project['status']]} — блоки в него не ставятся")
    minutes = max(15, min(int(minutes or 60), 240))
    target = core.parse_day(day)
    when = parse_hhmm(start) or free_slot(core, target, minutes)
    if when is None:
        raise ArvixError(f"На {target:%d.%m} свободного окна на {minutes} мин нет. Скажи время сам или возьми завтра.")
    step = next_step(core, project)
    name = title.strip() or (f"{project['title']}: {step['title']}" if step else f"{project['title']}: следующий шаг")
    return core.add_task(name, sphere="project", importance=3, difficulty=3, start=when, duration_min=minutes,
                         deep_work=True, day=target.isoformat(), project=project["id"], source=source)


# --- свёртка в цифры (L0) -------------------------------------------------------------------------

def milestones(core: Any, project_id: str) -> list[dict[str, Any]]:
    items = [m for m in core.state.milestones.values() if m["project_id"] == project_id and m["status"] != "dropped"]
    return sorted(items, key=lambda m: (m["status"] != "open", m.get("order", 0)))


def task_minutes(task: Any) -> int:
    """Минуты задачи в проект: сделанная — её длительность по проценту или таймер, если больше;
    несделанная — только то, что засёк таймер."""
    if task.status == "done":
        return max(task.duration_min * task.done_pct // 100, task.focus_min)
    return task.focus_min


def stats(core: Any, project: dict[str, Any]) -> dict[str, Any]:
    st = core.state
    today = core.today()
    pid = project["id"]
    tasks = [t for t in st.tasks.values() if t.project == pid and t.status != "cancelled"]
    log = [x for x in st.project_log if x["project_id"] == pid]
    money = [x for x in st.project_money if x["project_id"] == pid]
    channels = [c for c in st.channels.values() if c["project_id"] == pid]
    ms = milestones(core, pid)
    week_start = st.week_start(today)

    task_min = sum(task_minutes(t) for t in tasks)
    said_min = sum(int(x.get("minutes") or 0) for x in log)
    week_min = sum(task_minutes(t) for t in tasks if t.local_date >= week_start) + \
        sum(int(x.get("minutes") or 0) for x in log if x["date"] >= week_start.isoformat())

    # Движение — только сделанное: закрытая задача, таймер, запись журнала, пройденный этап, деньги.
    # План или правка карточки движением не считается (П4).
    moves = [t.local_date.isoformat() for t in tasks if t.status == "done" or t.focus_min]
    moves += [x["date"] for x in log] + [x["date"] for x in money]
    moves += [m["done_date"] for m in st.milestones.values() if m["project_id"] == pid and m.get("done_date")]
    last = max(moves) if moves else None
    since = date.fromisoformat(last if last else project.get("started") or today.isoformat())
    idle = (today - since).days

    done_ms = sum(1 for m in ms if m["status"] == "done")
    started = date.fromisoformat(project.get("started") or today.isoformat())
    pace = None
    if project.get("deadline") and ms:
        deadline = date.fromisoformat(project["deadline"])
        span = max((deadline - started).days, 1)
        elapsed = min(max((today - started).days / span, 0.0), 1.0)
        share = done_ms / len(ms)
        pace = {"time_share": round(elapsed, 2), "done_share": round(share, 2),
                "behind": share + BEHIND_MARGIN < elapsed, "days_left": (deadline - today).days}
    forecast = None
    weeks = max((today - started).days / 7, 1.0)
    left = len(ms) - done_ms
    if done_ms and left:
        forecast = (today + timedelta(days=round(left / (done_ms / weeks) * 7))).isoformat()

    income = round(sum(x["amount"] for x in money if x["direction"] == "in"), 2)
    expense = round(sum(x["amount"] for x in money if x["direction"] == "out"), 2)
    month = today.isoformat()[:7]
    hours = (task_min + said_min) / 60
    chan = []
    for c in channels:
        chan.append({**c, "cpl": round(c["cost"] / c["leads"], 2) if c["leads"] and c["cost"] else None,
                     "cpc": round(c["cost"] / c["clients"], 2) if c["clients"] and c["cost"] else None,
                     "conversion": round(100 * c["clients"] / c["leads"], 1) if c["leads"] else None,
                     "roi": round(100 * (c["revenue"] - c["cost"]) / c["cost"], 1) if c["cost"] else None})
    return {
        "minutes": task_min + said_min, "task_min": task_min, "said_min": said_min, "week_min": week_min,
        "weekly_target": int(project.get("weekly_min") or 0),
        "tasks_done": sum(1 for t in tasks if t.status == "done"), "tasks_open": [t for t in tasks if t.is_open],
        "milestones_done": done_ms, "milestones_total": len(ms), "last_move": last, "idle_days": idle,
        "pace": pace, "forecast": forecast,
        "income": income, "expense": expense, "net": round(income - expense, 2),
        "month_income": round(sum(x["amount"] for x in money if x["direction"] == "in" and x["date"][:7] == month), 2),
        "month_expense": round(sum(x["amount"] for x in money if x["direction"] == "out" and x["date"][:7] == month), 2),
        "per_hour": round((income - expense) / hours) if hours >= 1 and income else None,
        "channels": chan,
    }


def issues(core: Any, project: dict[str, Any], s: dict[str, Any] | None = None) -> list[str]:
    """Несостыковки проекта — как checks.py для целей и задач: код находит, модель поднимает сама."""
    if project["status"] not in ("active",):
        return []
    s = s or stats(core, project)
    today = core.today()
    out = []
    if s["idle_days"] >= DECIDE_DAYS:
        out.append(f"{s['idle_days']} дн без движения — реши честно: продолжаем, пауза или закрываем с итогом")
    elif s["idle_days"] >= STALL_DAYS:
        out.append(f"{s['idle_days']} дн без движения")
    if not project.get("expectation"):
        out.append("нет ожидания: что должно быть в конце — результат, который можно проверить")
    if not project.get("deadline"):
        out.append("нет срока")
    elif project["deadline"] < today.isoformat():
        out.append(f"срок {project['deadline']} прошёл — сдвинь честно или закрой")
    if not s["milestones_total"]:
        out.append("нет этапов — проект не разложен на шаги")
    elif s["milestones_done"] == s["milestones_total"]:
        out.append("все этапы пройдены — закрыть проект с итогом или добавить следующий этап")
    if s["pace"] and s["pace"]["behind"]:
        out.append(f"отстаёт: этапов {round(100 * s['pace']['done_share'])}% при {round(100 * s['pace']['time_share'])}% времени")
    if not s["tasks_open"] and s["milestones_total"] > s["milestones_done"]:
        out.append("в плане нет ни одного блока проекта")
    if s["weekly_target"] and today.weekday() >= 3 and s["week_min"] * 2 < s["weekly_target"]:
        out.append(f"за неделю {s['week_min']} мин из {s['weekly_target']}")
    if project.get("kind") == "income" and s["expense"] > s["income"] and s["expense"]:
        out.append(f"расходы {s['expense']:.0f} больше доходов {s['income']:.0f}")
    return out


def active(core: Any) -> list[dict[str, Any]]:
    return sorted((p for p in core.state.projects.values() if p["status"] == "active"),
                  key=lambda p: (p.get("deadline") or "9999", p["title"]))


def load_issue(core: Any) -> str | None:
    """Часы проектов в неделю против бюджета недели: план, который не влезает, — самообман."""
    total = sum(int(p.get("weekly_min") or 0) for p in active(core))
    budget = core.budget()["week_min"]
    if total and budget and total > budget * 0.6:
        return f"проекты просят {total // 60} ч в неделю — это больше 60 % бюджета недели ({budget // 60} ч)"
    return None


# --- текст для головы, брифинга и Obsidian ------------------------------------------------------------

def hm(minutes: int) -> str:
    h, m = divmod(int(minutes or 0), 60)
    return f"{h}ч{m:02d}м" if h else f"{m}м"


def context_lines(core: Any) -> list[str]:
    """Блок ПРОЕКТЫ контекста головы: цифры кода и несостыковки, которые надо поднять."""
    lines = []
    for p in active(core):
        s = stats(core, p)
        step = next_step(core, p)
        parts = [f"[{p['id']}] {p['title']} ({KINDS.get(p['kind'], p['kind'])}; зачем: {p['why']})"]
        if p.get("expectation"):
            parts.append(f"ожидание: {p['expectation']}")
        if p.get("deadline"):
            parts.append(f"срок {p['deadline']}")
        parts.append(f"этапы {s['milestones_done']}/{s['milestones_total']}")
        week = f"неделя {hm(s['week_min'])}" + (f"/{hm(s['weekly_target'])}" if s["weekly_target"] else "")
        parts.append(week)
        parts.append(f"всего {hm(s['minutes'])}")
        if s["income"] or s["expense"]:
            parts.append(f"доход {s['income']:.0f} · расход {s['expense']:.0f} · итог {s['net']:.0f}")
        if step:
            parts.append(f"следующий этап: [{step['id']}] {step['title']} — готово, когда {step['dod']}")
        line = "  " + " · ".join(parts)
        if found := issues(core, p, s):
            line += "\n    ⚠️ " + "; ".join(found)
        lines.append(line)
    rest = [p for p in core.state.projects.values() if p["status"] in ("paused", "idea")]
    if rest:
        lines.append("  на паузе и идеи: " + " · ".join(f"[{p['id']}] {p['title']} ({STATUSES[p['status']]})" for p in rest[:6]))
    if issue := load_issue(core):
        lines.append(f"  ⚠️ {issue}")
    return lines


def brief_line(core: Any) -> str | None:
    items = []
    for p in active(core)[:3]:
        s = stats(core, p)
        step = next_step(core, p)
        if s["idle_days"] >= STALL_DAYS:
            items.append(f"«{p['title']}» — {s['idle_days']} дн без движения")
        elif step:
            items.append(f"«{p['title']}» → {step['title']}")
        else:
            items.append(f"«{p['title']}»: этапов нет — разложим?")
    return "Проекты: " + " · ".join(items) if items else None


def stalled(core: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    out = []
    for p in active(core):
        s = stats(core, p)
        if s["idle_days"] >= STALL_DAYS:
            out.append((p, s))
    return out


def portfolio_md(core: Any, project: dict[str, Any]) -> str:
    """Карточка проекта для портфолио — только факты журнала: что построено, этапы, часы, навыки,
    решения и уроки, деньги. Пишется блоком Арвикса, текст человека в заметке не трогается."""
    s = stats(core, project)
    log = [x for x in core.state.project_log if x["project_id"] == project["id"]]
    lines = [f"**{project['title']}** · {KINDS.get(project['kind'], project['kind'])} · {STATUSES[project['status']]}",
             f"Зачем: {project['why']}"]
    if project.get("expectation"):
        lines.append(f"Ожидание: {project['expectation']}")
    if project.get("link"):
        lines.append(f"Ссылка: {project['link']}")
    meta = [f"начат {project.get('started')}"]
    if project.get("deadline"):
        meta.append(f"срок {project['deadline']}")
    meta.append(f"вложено {hm(s['minutes'])}" + (f" (со слов {hm(s['said_min'])})" if s["said_min"] else ""))
    lines.append(" · ".join(meta))
    if project.get("skills"):
        lines.append("Навыки: " + ", ".join(project["skills"]))
    ms = milestones(core, project["id"])
    if ms:
        lines += ["", "Этапы:"] + [f"- [{'x' if m['status'] == 'done' else ' '}] {m['title']} — {m['dod']}" for m in ms]
    for kind, label in (("release", "Релизы"), ("decision", "Решения"), ("lesson", "Уроки"), ("feedback", "Отзывы")):
        items = [x for x in log if x["kind"] == kind]
        if items:
            lines += ["", f"{label}:"] + [f"- {x['date']}: {x['text']}" for x in items[-8:]]
    if s["income"] or s["expense"]:
        lines += ["", f"Деньги: доход {s['income']:.0f}, расход {s['expense']:.0f}, итог {s['net']:.0f}"
                  + (f", {s['per_hour']} за час" if s["per_hour"] is not None else "")]
    if s["channels"]:
        lines += ["", "Каналы:"] + [f"- {c['name']} ({CHANNEL_TYPES.get(c['type'], c['type'])}): заявок {c['leads']}, клиентов "
                                     f"{c['clients']}" + (f", клиент за {c['cpc']:.0f}" if c["cpc"] else "")
                                     + f" — {CHANNEL_STATUSES.get(c['status'], c['status'])}" for c in s["channels"]]
    return "\n".join(lines)


def note_path(core: Any, project: dict[str, Any]) -> str:
    folder = str(core.cfg.vault_paths.get("projects") or "01_Projects").strip("/")
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", project["title"]).strip() or project["id"]
    return f"{folder}/{name}.md"


def export_note(core: Any, project_ref: Any, *, source: str = "claude") -> str:
    project = resolve(core, project_ref)
    rel = note_path(core, project)
    core.write_block(rel, "проект", portfolio_md(core, project), create_with=f"# {project['title']}\n\n", source=source)
    return rel
