"""Данные приложения — чистые функции над Core (05-INTERFACES §7.4).

Чтение идёт из потоков HTTP-сервера через отдельный Core (только чтение, под замком).
Изменения — функции вида fn(bot) для главного потока (web/hub.py): те же операции L0,
что у кнопок Telegram, поэтому долг и режим решает тот же код.

В 🟥 и при выключенном менторе приложение, как и панель в Telegram, не показывает
цифры и список задач — только одну маленькую вещь (правило №5).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from arvix import rules
from arvix.context import DAY_TYPES_RU, QUOTA_RU, end_time
from arvix.core import ArvixError, Core
from arvix.telegram import templates as tpl

FOCUS = "focus"
LESSON = "lesson"
SPHERES_RU = {"learning": "учёба", "work": "работа", "sport": "спорт", "social": "люди", "health": "здоровье",
              "finance": "деньги", "project": "проект", "chore": "быт"}


def task_view(task: Any) -> dict[str, Any]:
    return {
        "id": task.id, "title": task.title, "sphere": task.sphere, "sphere_ru": SPHERES_RU.get(task.sphere, task.sphere),
        "date": task.local_date.isoformat(), "start": task.start, "end": end_time(task.start, task.duration_min) if task.start else None,
        "duration_min": task.duration_min, "importance": task.importance, "difficulty": task.difficulty,
        "deep_work": task.deep_work, "status": task.status, "done_pct": task.done_pct,
        "focus_min": task.focus_min, "report": task.report, "proof": task.proof, "open": task.is_open,
        "project": task.project, "photos": list(task.report_photos),
    }


def gentle(core: Any) -> bool:
    return core.effective_mode() == "red" or not core.state.mentor_enabled


def state_view(core: Any, *, thinking: str = "") -> dict[str, Any]:
    st = core.state
    now = core.now()
    today = now.date()
    focus = core.store.kv_get(FOCUS)
    lesson = core.store.kv_get(LESSON)
    base: dict[str, Any] = {
        "now": now.isoformat(), "date": today.isoformat(), "weekday": tpl.WEEKDAYS_FULL[today.weekday()],
        "name": st.profile.get("name") or "", "mode": core.effective_mode(), "mode_label": rules.MODE_LABELS[core.effective_mode()],
        "gentle": gentle(core), "thinking": thinking, "version": st.last_event_id,
        "focus": focus_view(core, focus), "focus_choices": list(tpl.FOCUS_CHOICES), "lesson": {"task_id": lesson.get("task_id"), "topic": lesson.get("topic"),
                                                    "started": lesson.get("started")} if lesson else None,
    }
    tasks = st.tasks_on(today)
    if base["gentle"]:
        open_tasks = [t for t in tasks if t.is_open]
        small = min(open_tasks, key=lambda t: (t.duration_min or 999, t.importance)) if open_tasks else None
        base.update({"tasks": [task_view(small)] if small else [], "tomorrow": [], "debts": [], "stats": None,
                     "note": "Сегодня без плана и без цифр. Сон, еда, движение — и одна маленькая вещь, если захочется."})
        return base
    status = core.status()
    day = st.days.get(today)
    done = sum(1 for t in tasks if t.status == "done")
    base.update({
        "tasks": [task_view(t) for t in tasks],
        "tomorrow": [task_view(t) for t in st.tasks_on(today + timedelta(days=1))],
        "yesterday": [task_view(t) for t in core.open_yesterday()],  # после полуночи, до 04:00 — ещё можно закрыть
        "debts": [task_view(t) for t in st.debts()],
        "sessions": sessions_view(core, today),
        "busy": [{"start": b["start"], "end": end_time(b["start"], b.get("duration", 60)), "title": b["title"]} for b in core.fixed_blocks(today)],
        "day_type": DAY_TYPES_RU.get(day.day_type) if day and getattr(day, "day_type", None) else None,
        "stats": {  # только факты дня (D41): ни очков, ни здоровья, ни уровня, ни серии
            "done": done, "total": len(tasks), "completion": status["completion"],
            "deep_min": day.deep_min if day else 0, "deep_target": core.deep_target(today),
            "sleep_min": day.sleep_min if day else None, "sleep_target": status["sleep_target"], "debts": status["debts"],
            "sleep_guess": None if day and day.sleep_min else core.sleep_guess(today),  # D48: карточка сна — одним касанием
        },
    })
    return base


def focus_view(core: Any, focus: dict[str, Any] | None) -> dict[str, Any] | None:
    if not focus:
        return None
    task = core.state.tasks.get(focus.get("task_id") or "")
    return {"until": focus["until"], "started": focus["started"], "minutes": int(focus["minutes"]),
            "task_id": focus.get("task_id"), "title": task.title if task else focus.get("topic"), "topic": focus.get("topic"),
            "paused_at": focus.get("paused_at"), "max_pause_min": tpl.FOCUS_MAX_PAUSE_MIN}


def sessions_view(core: Any, d: Any) -> list[dict[str, Any]]:
    """Фокус-сессии дня: сколько, над чем, что сделано."""
    day = core.state.days.get(d)
    out = []
    for s in (day.focus if day else []):
        task = core.state.tasks.get(s.get("task_id") or "")
        out.append({"event_id": s["event_id"], "at": s["at"], "minutes": s["minutes"],
                    "title": task.title if task else (s.get("topic") or "глубокая работа"), "note": s.get("note")})
    return out


def quote_view(core: Any, event: Any, near: dict[int, Any]) -> dict[str, Any] | None:
    """Цитата в пузыре, как в Telegram (D52): кто, начало текста, id — по нему лента прокручивает к оригиналу."""
    target_id = event.payload.get("reply_to")
    if not target_id:
        return None
    target = near.get(int(target_id)) or core.message(int(target_id))
    if target is None:
        return None
    text = " ".join(str(target.payload.get("text") or "").split())
    return {"id": target.id, "who": "me" if target.kind == "message_in" else "arvix", "text": text[:160]}


def live_buttons(core: Any, rows: list[Any]) -> list[Any]:
    """Кнопки задачи, которая уже закрыта (галочкой в приложении, словами, в Telegram), в ленте не нужны:
    нажатие дало бы только «уже выполнена». Остальные кнопки — как были."""
    def alive(button: Any) -> bool:
        data = str(button[1]) if isinstance(button, (list, tuple)) and len(button) > 1 else ""
        if not data.startswith("t:"):
            return True
        task = core.state.tasks.get(data.split(":")[1])
        return task is None or task.is_open or task.status == "debt"
    out = [[b for b in row if alive(b)] for row in rows if isinstance(row, list)]
    return [row for row in out if row]


def messages_view(core: Any, *, before: int | None = None, limit: int = 60) -> list[dict[str, Any]]:
    """Переписка из журнала — все каналы: Telegram, приложение, терминал."""
    start = max(0, (before or core.state.last_event_id + 1) - 3000)
    # Нити чатов проектов (D47) и учебных сессий (D56) живут в своих окнах — в общем чате их нет
    events = [e for e in core.store.read(start) if e.kind in ("message_in", "message_out") and (before is None or e.id < before)
              and not e.payload.get("project") and not e.payload.get("study")]
    out = []
    near = {e.id: e for e in events}
    for event in events[-limit:]:
        text = str(event.payload.get("text") or "")
        if event.kind == "message_in" and text.startswith("[кнопка "):
            continue  # нажатия кнопок в ленте не нужны
        out.append({
            "id": event.id, "at": event.at.astimezone(core.tz).isoformat(), "who": "me" if event.kind == "message_in" else "arvix",
            "text": text, "channel": event.payload.get("channel") or "telegram",
            "buttons": live_buttons(core, event.payload.get("buttons") or []), "reply_to": quote_view(core, event, near),
            "reaction": (core.state.reactions.get(event.id) or {}).get("emoji", ""),
        })
    return out


def history_view(core: Any, days: int = 30) -> dict[str, Any]:
    """Прогресс за N дней: выполнение, сон, глубокая работа по дням; цели; неделя."""
    st = core.state
    today = core.today()
    if gentle(core):
        return {"gentle": True, "days": [], "goals": [], "week": None}
    rows = []
    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)
        day = st.days.get(d)
        tasks = st.tasks_on(d)
        rows.append({
            "date": d.isoformat(), "done": sum(1 for t in tasks if t.status == "done"), "total": len(tasks),
            "completion": st.completion(d), "sleep_min": day.sleep_min if day else None,
            "deep_min": day.deep_min if day else 0,
        })
    week = st.week_stats(today)
    quotas = core.cfg.mech("quotas") or {}
    plan = core.budget()
    goals = [{"depth": depth, "id": g["id"], "title": g["title"], "kind": g.get("kind"), "status": g.get("status", "active"),
              "deadline": g.get("deadline"), "why": g.get("why"), "metric": g.get("metric")}
             for depth, g in core.goal_tree() if g.get("status") != "dropped"]
    return {
        "gentle": False, "days": rows, "goals": goals, "heat": heatmap_view(core),
        "week": {
            "productive_min": week["productive_min"], "budget_min": plan["week_min"], "deep_min": week["deep_min"],
            "deep_budget_min": plan["deep_min"],
            "quotas": [{"key": k, "label": QUOTA_RU.get(k, k), "done": week["quotas"].get(k, 0), "need": v} for k, v in quotas.items()],
            "spent": sum(week["expenses"].values()),
        },
        "lessons": st.lessons[-10:],
    }


def heat_level(completion: float | None, deep_min: int, done: int, deep_target: int) -> int:
    """Цвет квадрата 0–4 — только за сделанную работу (задачи, глубокие минуты), не за сообщения:
    иначе карту можно закрасить, ничего не сделав (П4). Это история, а не игра: серий и рекордов нет (D41)."""
    if completion is not None and completion >= 90 and deep_min >= max(deep_target, 1):
        return 4
    if (completion is not None and completion >= 70) or deep_min >= 90:
        return 3
    if (completion is not None and completion >= 40) or deep_min >= 45:
        return 2
    if done or deep_min >= 15:
        return 1
    return 0


def heatmap_view(core: Any, weeks: int = 53) -> dict[str, Any]:
    """Год квадратами, как вклад на GitHub: колонки — недели с понедельника, сегодня — справа.
    Дни отдыха (тихий день, восстановление) — отдельным цветом."""
    st = core.state
    today = core.today()
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    days, d = [], start
    active = 0
    while d <= today:
        day = st.days.get(d)
        tasks = st.tasks_on(d)
        done = sum(1 for t in tasks if t.status == "done")
        completion = st.completion(d)
        deep = day.deep_min if day else 0
        level = heat_level(completion, deep, done, core.deep_target(d))
        rest = bool(day and (day.silent or day.day_type in ("recovery", "silent")))
        tracked = st.first_date is not None and d >= st.first_date
        days.append({"date": d.isoformat(), "level": level if tracked else -1, "rest": rest and not level, "done": done,
                     "total": len(tasks), "deep_min": deep, "completion": completion, "focus": len(day.focus) if day else 0})
        active += 1 if level else 0
        d += timedelta(days=1)
    return {"days": days, "active": active, "start": start.isoformat()}


# --- проекты (D43, D44, D47): окна над папкой проекта в Obsidian и чатом проекта --------------------------

def _project_card(core: Any, p: dict[str, Any]) -> dict[str, Any]:
    from arvix import projects

    s = projects.stats(core, p)
    step = projects.next_step(core, p)
    goal = core.state.goals.get(p.get("goal_id") or "")
    return {
        "id": p["id"], "title": p["title"], "why": p.get("why", ""), "kind": p.get("kind"), "kind_ru": projects.kind_label(p.get("kind")),
        "purposes_ru": [projects.purpose_label(x) for x in projects.purposes_of(p)],
        "status": p["status"], "status_ru": projects.STATUSES[p["status"]], "group": projects.group(p["status"]),
        "expectation": p.get("expectation", ""), "deadline": p.get("deadline"), "weekly_min": s["weekly_target"],
        "week_min": s["week_min"], "minutes": s["minutes"], "milestones_done": s["milestones_done"],
        "milestones_total": s["milestones_total"], "idle_days": s["idle_days"], "last_move": s["last_move"],
        "pace": s["pace"], "forecast": s["forecast"], "learn_todo": s["learn_todo"],
        "next": {"id": step["id"], "title": step["title"], "dod": step["dod"]} if step else None,
        "issues": projects.issues(core, p, s), "skills": p.get("skills") or [], "link": p.get("link", ""),
        "started": p.get("started"), "goal_id": p.get("goal_id"), "goal_title": goal["title"] if goal else None,
        "weeks": p.get("weeks"), "by": p.get("by", ""), "folder": projects.folder(core, p), "main_note": projects.main_note(core, p),
    }


def obsidian_vault(core: Any) -> str:
    """Имя хранилища для ссылок obsidian://: на сервере папка называется иначе, чем у человека в Obsidian."""
    from pathlib import Path

    return str(core.cfg.section("obsidian").get("vault") or (Path(core.cfg.vault).name if core.cfg.vault else ""))


def projects_view(core: Any) -> dict[str, Any]:
    """Список проектов по целям (это и есть роадмап), отложенные и завершённые. В 🟥 — без цифр (правило №5).
    Цели без проектов — отдельным списком: пятнадцать пустых групп с «предложить» прятали сами проекты (D56)."""
    from arvix import project_roadmap, projects

    if gentle(core):
        return {"gentle": True, "groups": [], "note": "Проекты подождут. Сегодня — восстановление; если тянет к проекту, "
                                                      "сделай самое приятное в нём, без плана и цифр."}
    cards = {p["id"]: _project_card(core, p) for p in core.state.projects.values()}
    groups, idle = [], []
    for block in projects.roadmap(core):
        # в работе — сверху, неначатые — под ними: порядок роадмапа внутри каждой части сохраняется
        items = sorted((cards[p["id"]] for p in block["projects"] if cards[p["id"]]["group"] != "closed"),
                       key=lambda c: c["status"] != "active")
        goal = block["goal"]
        if items:
            groups.append({"goal": {k: goal.get(k) for k in ("id", "title", "kind", "deadline")} if goal else None, "projects": items})
        elif goal:  # цель без проектов — одной строкой внизу, а не пустой группой с кнопкой (D56)
            idle.append({k: goal.get(k) for k in ("id", "title", "kind", "deadline")})
    closed = sorted((c for c in cards.values() if c["group"] == "closed"), key=lambda c: c["title"])
    active = [c for c in cards.values() if c["status"] == "active"]
    return {
        "gentle": False, "groups": groups, "idle_goals": idle, "closed": closed, "count": len(cards), "max_active": projects.max_active(core),
        "ideas": sum(1 for c in cards.values() if c["status"] == "idea"), "ideas_max": project_roadmap.IDEAS_MAX,
        "active": len(active), "load_issue": projects.load_issue(core), "vault": obsidian_vault(core),
        "goals": [{"id": g["id"], "title": g["title"]} for g in core.state.goals.values() if g.get("status", "active") == "active"],
        "log_kinds": projects.LOG_KINDS, "resource_kinds": projects.RESOURCE_KINDS, "kinds": projects.KIND_PRESETS,
    }


def project_messages(core: Any, project_id: str, limit: int = 80, *, key: str = "project") -> list[dict[str, Any]]:
    """Нить чата из общей переписки: проекта — payload.project (D47), учебной сессии — payload.study (D56)."""
    start = max(0, core.state.last_event_id - 6000)
    out = []
    thread = [e for e in core.store.read(start) if e.kind in ("message_in", "message_out") and e.payload.get(key) == project_id]
    near = {e.id: e for e in thread}
    for event in thread[-limit:]:
        out.append({"id": event.id, "at": event.at.astimezone(core.tz).isoformat(), "who": "me" if event.kind == "message_in" else "arvix",
                    "text": str(event.payload.get("text") or ""), "reply_to": quote_view(core, event, near),
                    "reaction": (core.state.reactions.get(event.id) or {}).get("emoji", "")})
    return out


def project_view(core: Any, project_id: str) -> dict[str, Any]:
    from arvix import projects

    if gentle(core):
        return {"gentle": True}
    p = projects.resolve(core, project_id)
    st = core.state
    tasks = sorted((t for t in st.tasks.values() if t.project == p["id"] and t.status != "cancelled"),
                   key=lambda t: (t.local_date, t.start or "99"), reverse=True)
    log = [x for x in st.project_log if x["project_id"] == p["id"]]
    return {
        **_project_card(core, p), "gentle": False,
        "milestones": [{k: m.get(k) for k in ("id", "title", "dod", "due", "status", "done_date")} for m in projects.milestones(core, p["id"])],
        "learn": projects.learn_items(core, p["id"]), "files": projects.note_files(core, p),
        "tasks": [task_view(t) for t in tasks[:30]], "log": list(reversed(log[-40:])),
        "resources": projects.resources(core, p["id"]), "messages": project_messages(core, p["id"]),
        "task_min": projects.stats(core, p)["task_min"],
    }


KICKOFF = """<new_project>Человек только что начал этот проект одной фразой (она — его сообщение). Карточка — черновик кода.
Заполни проект сам, не устраивая анкету: set_project (project=id) — короткое название, kind словом, purposes, why, expectation
(проверяемо), deadline и weekly_min по его нагрузке, goal_id, если проект ведёт к цели из контекста; 3–6 этапов set_milestone
с dod; 2–5 тем learn_add — что придётся выучить; project_note «План» — коротко: результат, этапы, первый шаг, риски; источники
project_resource — только настоящие ссылки. Чего не знаешь — реши сам по данным и скажи, как поправить. В ответе: что
создал и один первый шаг; если стоит — предложи блок в план. Один вопрос — только если без ответа нельзя.</new_project>"""


def project_new(text: str, goal_id: str | None) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        from arvix import projects

        pid = projects.start(bot.core, text, goal_id=goal_id or None, source="web")
        return {"project": _project_card(bot.core, bot.core.state.projects[pid])}
    return run


def project_chat(project_id: str, text: str, *, kickoff: bool = False) -> Any:
    """Сообщение в чат проекта: тот же путь, что у обычного (safety, голова, actions), но в нити проекта
    и с блоком <project> в запросе. Ожидаемые ответы (сон, отчёт) здесь не перехватываются — это разговор о проекте."""
    def run(bot: Any) -> None:
        from arvix import safety

        bot.core.refresh()
        with bot.via("web", SINK), bot.in_project(project_id), bot.incoming():
            bot.log_in(text)
            if safety.detect(text):
                bot.safety_protocol(text)
                return
            bot.converse(text, extra=KICKOFF if kickoff else "")
    return run


def project_upload(project_id: str, data: bytes, name: str, mime: str, caption: str) -> Any:
    """Файл в чат проекта — в папку проекта «Файлы» (код, скриншот, PDF): Arvix читает и отвечает."""
    def run(bot: Any) -> None:
        bot.core.refresh()
        with bot.via("web", SINK), bot.in_project(project_id), bot.incoming():
            bot.on_file({"file_name": name, "mime_type": mime}, caption=caption, data=data)
    return run


def project_roadmap(goal_id: str) -> Any:
    """«Arvix, предложи проекты к цели» — фоновая задача: ответ придёт сообщением, проекты — отложенными."""
    def run(bot: Any) -> None:
        with bot.via("web", SINK):
            bot.build_project_roadmap(goal_id)
    return run


def project_op(project_id: str, op: str, body: dict[str, Any]) -> Any:
    """save · milestone · log · block · status · move · learn · learn_start · resource — кнопки вкладки «Проекты»."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import projects

        core = bot.core
        pid = projects.resolve(core, project_id)["id"]
        out: dict[str, Any] = {}
        if op == "save":
            projects.set_project(core, str(body.get("title") or ""), project_id=pid, expectation=str(body.get("expectation") or ""),
                                 deadline=body.get("deadline") or None, weekly_min=body.get("weekly_min"),
                                 goal_id=body.get("goal_id") if "goal_id" in body else None, kind=str(body.get("kind") or "") or None,
                                 why=str(body.get("why") or ""), source="web")
        elif op == "milestone":
            projects.set_milestone(core, pid, str(body.get("title") or ""), milestone_id=body.get("milestone") or None,
                                   due=body.get("due") or None, dod=str(body.get("dod") or ""), status=body.get("status") or None,
                                   source="web")
        elif op == "log":
            projects.log_entry(core, pid, str(body.get("text") or ""), kind=str(body.get("kind") or "update"),
                               minutes=body.get("minutes") or 0, source="web")
        elif op == "block":
            task = projects.plan_block(core, pid, minutes=int(body.get("minutes") or 60), day=body.get("date") or None,
                                       start=body.get("start") or None, source="web")
            out = {"task": task_view(task), "warnings": core.task_warnings(task)}
            bot.refresh_panel()
        elif op == "status":
            projects.set_project(core, project_id=pid, status=str(body.get("status") or ""), reason=str(body.get("reason") or ""),
                                 source="web")
        elif op == "move":
            projects.move(core, pid, int(body.get("step") or 1), source="web")
        elif op == "learn":
            projects.set_learn(core, str(body.get("topic") or ""), item_id=body.get("item") or None, project_ref=pid,
                               status=body.get("status") or None, kind=body.get("kind") or None, source="web")
        elif op == "learn_start":
            task = projects.learn_start(core, str(body.get("item") or ""), minutes=int(body.get("minutes") or 45))
            out = {"task": task_view(task)}
            bot.refresh_panel()
        elif op == "resource":
            projects.set_resource(core, pid, resource_id=body.get("resource") or None, status=body.get("status") or None, source="web")
        else:
            raise ArvixError(f"Неизвестное действие проекта: {op}")
        return {**out, "project": project_view(core, pid)}
    return run


# --- Обучение (D55): учебная сессия = урок §8 + окна; очередь тем — общая с проектами -------------------

AWAIT = "tg_await"  # чего бот ждёт (Bot.await_set): проверка урока — ответом из окна сессии
STUDY_ASK = {  # подсказки чата — под этап: что обычно спрашивают именно здесь
    "diag": ["Не понимаю условие задачи", "С чего начать эту тему?"],
    "learn": ["Объясни с начала, по шагам", "Покажи ещё пример", "Нарисуй чертёж", "Схема темы", "Найди другое видео", "Проверь мою заметку"],
    "practice": ["Дай подсказку к задаче, не решение", "Проверь моё решение по фото", "Ещё 3 задачи посложнее"],
    "fix": ["Почему мой ответ неверный?", "Дай ещё похожую задачу", "Где я обычно ошибаюсь?"],
    "check": ["Что повторить перед проверкой?"],
}


def _lesson_row(core: Any, task_id: str) -> dict[str, Any] | None:
    return next((x for x in reversed(core.state.lessons) if x.get("task_id") == task_id), None)


def session_view(core: Any, task_id: str) -> dict[str, Any]:
    """Рабочий стол сессии по этапам (D60): этапы с минутами и шагом, уровень по диагностике, окна этапов,
    ошибки для работы над ними, таймер, чат урока. Эталоны теста и проверки сюда не уходят."""
    from arvix import lesson as lesson_mod
    from arvix import review, study

    task = core.resolve_task(task_id)
    if task.sphere != "learning":
        raise ArvixError("Это не учебный блок")
    lesson = core.store.kv_get(LESSON) or {}
    live = lesson.get("task_id") == task.id
    row = _lesson_row(core, task.id) or {}
    data = study.session_of(core, task.id)
    panels = [{**study.public_panel(p, data["answers"].get(p["id"])), "stage": study.panel_stage(p, data)} for p in study.visible(data)]
    plan = study.stage_plan(lesson.get("plan") or [], task.duration_min) if live else {}
    stage = study.current_stage(data)
    errs = study.public_errors(data)
    stages = []
    for key in study.STAGES:
        span = plan.get(key) or {}
        mine = [p for p in panels if p["stage"] == key]
        done = {"diag": bool(mine) and all(p.get("done") for p in mine if p["type"] == "quiz") and any(p["type"] == "quiz" for p in mine),
                "practice": any(p["type"] == "quiz" and p.get("done") for p in mine),
                "fix": bool(errs) and all(e["closed"] for e in errs), "check": bool(row.get("checked"))}.get(key, False)
        stages.append({"id": key, "name": study.STAGE_RU[key], "short": study.STAGE_SHORT[key], "goal": study.STAGE_GOAL[key],
                       "from": span.get("from"), "to": span.get("to"),
                       "steps": span.get("steps") or [], "done": done, "panels": len(mine),
                       "errors": sum(1 for e in errs if not e["closed"]) if key == "fix" else None})
    rev = next((r for r in core.state.reviews.values() if task.id in (r.get("tasks") or [])), None)
    waiting = core.store.kv_get(AWAIT) or {}
    check = [c["q"] for c in lesson.get("check") or []] if live and waiting.get("kind") == "lesson_check" else []
    focus = core.store.kv_get(FOCUS) or {}
    # Своя нить сессии (D56): раньше чат урока был общим чатом с начала урока — туда попадали вечерний
    # разбор и «ложись», если урок не закрыли. Теперь — только то, что написано в окне сессии.
    messages = project_messages(core, task.id, limit=60, key="study")
    item = study.learn_item_of(core, task)
    project = core.state.projects.get(task.project or "")
    return {
        "task": task_view(task), "live": live, "prepared": bool(row), "topic": (lesson.get("topic") if live else row.get("topic")) or task.title,
        "plan": (lesson.get("plan") or []) if live else [], "sources": (lesson.get("sources") or []) if live else [],
        "note": (lesson.get("note") if live else row.get("note")) or None, "started": lesson.get("started") if live else None,
        "focus": focus_view(core, focus) if focus.get("task_id") == task.id else None,
        "check": check, "result": {k: row.get(k) for k in ("score", "gaps", "next_step")} if row.get("checked") else None,
        "roadmap_node": row.get("roadmap_node", ""), "fallback": row.get("fallback", False),
        "panels": panels, "messages": messages, "asks": STUDY_ASK.get(stage, STUDY_ASK["learn"]),
        "item": {"id": item["id"], "topic": item["topic"], "kind": item.get("kind") or "theory"} if item else None,
        "project": {"id": project["id"], "title": project["title"]} if project else None,
        "stage": stage, "stages": stages, "route": study.route(data), "errors": errs, "error_kinds": study.ERROR_KINDS,
        "check_asked": bool(check), "subject": lesson_mod.subject_of(task.title),
        "note_own": study.note_own(core, (lesson.get("note") if live else row.get("note")) or None),
        "review": {"due": rev.get("due"), "step": rev.get("step"), "status": rev.get("status")} if rev else None,
    }


def study_view(core: Any, task_id: str | None = None) -> dict[str, Any]:
    """Раздел «Обучение»: сессия (идёт или открыта), учебные блоки дня, очередь тем (общая с проектами),
    пройденное с оценками и пробелами. В 🟥 — без цифр и без очереди (правило №5)."""
    from arvix import projects, study

    if gentle(core):
        return {"gentle": True, "note": "Учёба подождёт. Если тянет — почитай что-нибудь по теме без плана, теста и таймера."}
    st = core.state
    lesson = core.store.kv_get(LESSON) or {}
    current = task_id or lesson.get("task_id")
    session = None
    if current and current in st.tasks:
        try:
            session = session_view(core, current)
        except ArvixError:
            session = None
    today = core.today()
    day_tasks = [t for t in [*core.open_yesterday(), *st.tasks_on(today)] if t.sphere == "learning" and t.status != "cancelled"]
    blocks = []
    for t in day_tasks:
        row = _lesson_row(core, t.id) or {}
        blocks.append({**task_view(t), "lesson": bool(row), "score": row.get("score") if row.get("checked") else None,
                       "live": lesson.get("task_id") == t.id})
    titles = {pid: p["title"] for pid, p in st.projects.items()}
    queue = [{**x, "kind_ru": study.LEARN_KINDS.get(x["kind"], x["kind"]), "project": titles.get(x.get("project_id") or ""),
              "goal": (st.goals.get(x.get("goal_id") or "") or {}).get("title")}
             for x in projects.learn_items(core) if x["status"] != "dropped"]
    history = []
    for x in reversed(st.lessons[-30:]):
        task = st.tasks.get(x.get("task_id") or "")
        history.append({"task_id": x.get("task_id"), "date": x["date"], "subject": x.get("subject", ""), "topic": x.get("topic", ""),
                        "score": x.get("score"), "checked": bool(x.get("checked")), "gaps": x.get("gaps") or [],
                        "next_step": x.get("next_step", ""), "status": task.status if task else None,
                        "panels": len([p for p in (st.study.get(x.get("task_id") or "") or {}).get("panels", []) if not p.get("hidden")])})
    subjects: dict[str, dict[str, Any]] = {}
    for x in st.lessons:  # по предметам — только факты: сколько блоков и средняя оценка проверок
        s = subjects.setdefault(x.get("subject") or "—", {"subject": x.get("subject") or "—", "lessons": 0, "scores": []})
        s["lessons"] += 1
        if x.get("score") is not None:
            s["scores"].append(x["score"])
    from arvix import review

    return {
        "gentle": False, "session": session, "blocks": blocks, "queue": queue, "history": history, "review": review.public(core),
        "subjects": [{"subject": s["subject"], "lessons": s["lessons"], "avg": round(sum(s["scores"]) / len(s["scores"])) if s["scores"] else None}
                     for s in sorted(subjects.values(), key=lambda s: -s["lessons"])],
        "projects": [{"id": p["id"], "title": p["title"]} for p in st.projects.values() if p["status"] == "active"],
        "kinds": study.LEARN_KINDS, "panel_types": study.PANEL_RU, "vault": obsidian_vault(core),
    }


def study_open(task_id: str | None = None, item_id: str | None = None, minutes: int = 45) -> Any:
    """«Открыть сессию»: тема из очереди → учебный блок в свободное окно (projects.learn_start); у блока
    готовится план с окнами (голова). Таймер не стартует — ▶ на рабочем столе. Идёт урок по другой
    задаче — не трогаем: у бота один урок за раз, его проверку нельзя потерять."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import projects

        core = bot.core
        task = projects.learn_start(core, item_id, minutes=minutes, source="web") if item_id else core.resolve_task(task_id)
        if task.sphere != "learning":
            raise ArvixError("Сессия бывает только у учебного блока")
        lesson = core.store.kv_get(LESSON) or {}
        if lesson.get("task_id") and lesson["task_id"] != task.id and (lesson.get("started") or (core.store.kv_get(AWAIT) or {}).get("kind") == "lesson_check"):
            other = core.state.tasks.get(lesson["task_id"])
            raise ArvixError(f"Сейчас идёт урок «{other.title if other else lesson.get('topic')}» — сначала закончи его")
        if not task.is_open and not (lesson.get("task_id") == task.id):
            return {"task_id": task.id, "queued": False}  # прошлая сессия — только посмотреть
        bot.refresh_panel()
        return {"task_id": task.id, "queued": not bot.lesson_pending(task.id)}
    return run


def study_chat(task_id: str, text: str) -> Any:
    """Сообщение из окна учебной сессии: ответ Arvix — в её нить, не в общий чат (D56)."""
    def run(bot: Any) -> None:
        bot.core.refresh()
        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK), bot.in_study(task.id), bot.incoming():
            bot.on_text(text)
    return run


def study_prepare(task_id: str) -> Any:
    """Фоном (голова думает): план урока с окнами, без таймера."""
    def run(bot: Any) -> None:
        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK), bot.in_study(task.id):  # план — в нить сессии: на столе он уже есть, общий чат не засоряем
            if task.is_open and not bot.lesson_pending(task.id):
                bot.prepare_lesson(task)
    return run


def study_op(task_id: str, op: str, body: dict[str, Any]) -> Any:
    """answer · stage · fix · panel · hide — этапы и окна сессии. Ответ на тест и похожую задачу проверяет код сразу."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import study

        core = bot.core
        out: dict[str, Any] = {}
        if op == "answer":
            answers = body.get("answers")
            if not isinstance(answers, list):
                raise ArvixError("Нет ответов")
            out = study.answer_quiz(core, str(body.get("panel") or ""), answers, task_ref=task_id, source="web")
            task = core.resolve_task(task_id)
            lesson = core.store.kv_get(LESSON) or {}
            if lesson.get("task_id") == task.id and not lesson.get("started") and task.is_open:
                with bot.via("web", SINK), bot.in_study(task.id):
                    bot.begin_lesson(task)  # ответил на задачи — значит, начал: таймер блока идёт сам, без ▶
        elif op == "stage":
            out = {"stage": study.set_stage(core, str(body.get("stage") or ""), task_ref=task_id, source="web")}
        elif op == "fix":
            twin = body.get("twin") if "twin" in body else None
            key = str(body.get("key") or "")
            study.fix_error(core, key, task_ref=task_id, kind=body.get("kind") or None, twin=twin, done=bool(body.get("done")), source="web")
            # наружу — публичный вид: ответ похожей задачи виден только после попытки
            out = {"fixed": next(e for e in study.public_errors(study.session_of(core, core.resolve_task(task_id).id)) if e["key"] == key)}
        elif op == "panel":
            raw = body.get("panel")
            if not isinstance(raw, dict) or raw.get("type") not in ("video", "note", "sources"):
                raise ArvixError("Сам можно добавить видео, заметку или источники; тест и доску попроси у Arvix")
            out = {"panel": study.add_panel(core, raw, task_ref=task_id, by="me", source="web")}
        elif op == "hide":
            out = {"panel": study.hide_panel(core, str(body.get("panel") or ""), task_ref=task_id, source="web")}
        else:
            raise ArvixError(f"Неизвестное действие сессии: {op}")
        return {**out, "session": session_view(core, task_id)}
    return run


def study_check(task_id: str) -> Any:
    """«К проверке»: таймер этого блока останавливается (прошедшие минуты — в журнал), вопросы — в нить сессии."""
    def run(bot: Any) -> dict[str, Any]:
        core = bot.core
        task = core.resolve_task(task_id)
        lesson = core.store.kv_get(LESSON) or {}
        if lesson.get("task_id") != task.id:
            raise ArvixError("Проверка бывает только у идущей сессии")
        with bot.via("web", SINK), bot.in_study(task.id):
            if (core.store.kv_get(FOCUS) or {}).get("task_id") == task.id:
                bot.stop_focus()
            if (core.store.kv_get(AWAIT) or {}).get("kind") != "lesson_check":
                bot.send_lesson_check(early=True)
        return {"session": session_view(core, task.id)}
    return run


def study_upload(task_id: str, data: bytes, name: str, mime: str, caption: str) -> Any:
    """Файл в чат сессии — фото решения из тетради, скриншот, PDF: Arvix смотрит его с блоком <study>."""
    def run(bot: Any) -> None:
        bot.core.refresh()
        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK), bot.in_study(task.id), bot.incoming():
            bot.on_file({"file_name": name, "mime_type": mime}, caption=caption, data=data)
    return run


def study_voice(task_id: str, audio: bytes, filename: str) -> Any:
    """Голосовое в чат сессии: распознать и ответить в нити урока (как вопрос текстом)."""
    def run(bot: Any) -> None:
        from arvix.stt import STTError

        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK), bot.in_study(task.id), bot.incoming():
            if not bot.stt.enabled:
                bot.log_in("[голосовое — распознавание не настроено]")
                bot.send(tpl.VOICE_OFF)
                return
            try:
                text = bot.stt.transcribe(audio, filename=filename, browser=True)
            except STTError as exc:
                bot.log_in("[голосовое — не распознано]")
                bot.send(f"Голосовое не распознал: {exc}. Напиши текстом.")
                return
            if text.strip():
                bot.core.refresh()
                bot.on_text(text, voice=True)
    return run


def review_start() -> Any:
    """«Начать повторение»: задачи по темам, которым пора (голова; молчит — банк сессий). Ждём ответа здесь же."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import review

        if gentle(bot.core):
            raise ArvixError("Сейчас без учёбы")
        with bot.via("web", SINK):
            bot.prepare_review()
        return {"review": review.public(bot.core)}
    return run


def review_op(op: str, body: dict[str, Any]) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        from arvix import review

        core = bot.core
        if op == "answer":
            answers = body.get("answers")
            if not isinstance(answers, list):
                raise ArvixError("Нет ответов")
            review.answer(core, answers, source="web")
        elif op == "drop":
            review.drop(core, str(body.get("review") or ""), source="web")
        else:
            raise ArvixError(f"Неизвестное действие повторения: {op}")
        return {"review": review.public(core)}
    return run


def study_learn(body: dict[str, Any]) -> Any:
    """Тема в общую очередь «учиться» из раздела «Обучение»: та же, что из проекта (projects.set_learn)."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import projects

        item = projects.set_learn(bot.core, str(body.get("topic") or ""), item_id=body.get("item") or None,
                                  project_ref=body.get("project") or None, why=str(body.get("why") or ""),
                                  status=body.get("status") or None, kind=body.get("kind") or None, source="web")
        return {"item": item, "study": study_view(bot.core)}
    return run


# --- изменения: выполняются в главном потоке (fn(bot)) ------------------------------------

def add_task(fields: dict[str, Any]) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        title = str(fields.get("title") or "").strip()
        if not title:
            raise ArvixError("Название задачи пустое")
        day = fields.get("date") or None
        task = bot.core.add_task(
            title, sphere=fields.get("sphere") or "project", importance=int(fields.get("importance") or 3),
            difficulty=int(fields.get("difficulty") or 3), start=fields.get("start") or None,
            duration_min=int(fields.get("duration_min") or 60), deep_work=bool(fields.get("deep_work")), day=day, source="web",
        )
        bot.refresh_panel()
        return {"task": task_view(task), "warnings": bot.core.task_warnings(task)}
    return run


def task_op(task_id: str, op: str, body: dict[str, Any]) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        core = bot.core
        task = core.resolve_task(task_id)
        result: dict[str, Any] = {}
        if op == "start":
            core.start_task(task.id, source="web")
        elif op == "done":
            pct = rules.clamp(int(body.get("pct") or 100), 1, 100)
            photos = [str(x) for x in (body.get("photos") or []) if x]
            done = core.complete_task(task.id, done_pct=pct, report=(body.get("report") or None), photos=photos, source="web")
            result = {"warnings": done["warnings"], "debt_closed": done["debt_closed"]}
        elif op == "fail":
            failed = core.fail_task(task.id, reason=str(body.get("reason") or "отмечено в приложении"), source="web")
            result = {"debt": failed["debt"]}
        elif op == "defer":
            moved = core.defer_task(task.id, int(body.get("minutes") or 30), source="web")
            result = {"start": moved.start}
        elif op == "cancel":
            core.cancel_task(task.id, reason=str(body.get("reason") or "отменено в приложении"), source="web")
        else:
            raise ArvixError(f"Неизвестное действие: {op}")
        bot.refresh_panel()
        result["task"] = task_view(core.state.tasks[task.id])
        return result
    return run


def task_photo(task_id: str, data: bytes, name: str, mime: str) -> Any:
    """Фото к отчёту (D49): сначала файл в хранилище, потом «Сделано» с его путём — голову не зовёт."""
    def run(bot: Any) -> dict[str, Any]:
        bot.core.resolve_task(task_id)
        return {"path": bot.core.receive_report_photo(data, name, mime, source="web")}
    return run


def focus_start(minutes: int, task_id: str | None, topic: str | None = None) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        with bot.via("web", SINK):
            # Человек сам выбрал минуты — это таймер, а не урок (урок — кнопкой ▶ у учебной задачи).
            bot.start_focus(minutes, task_id or None, lesson=True, topic=(topic or "").strip() or None)
        return {"focus": focus_view(bot.core, bot.core.store.kv_get(FOCUS))}
    return run


def focus_op(op: str) -> Any:
    """pause · resume · cancel · stop. stop возвращает сессию — к ней приложение спросит заметку."""
    if op not in ("pause", "resume", "cancel", "stop"):
        raise ArvixError(f"Неизвестное действие таймера: {op}")

    def run(bot: Any) -> dict[str, Any]:
        with bot.via("web", SINK):
            result = getattr(bot, f"{op}_focus")()
        out: dict[str, Any] = {"focus": focus_view(bot.core, bot.core.store.kv_get(FOCUS))}
        if op == "stop" and result:
            bot.await_clear()  # заметку спросит само приложение, а не следующее сообщение в чате
            session = next((s for s in sessions_view(bot.core, bot.core.today()) if s["event_id"] == result), None)
            out["session"] = session
        return out
    return run


def focus_stop() -> Any:
    return focus_op("stop")


def focus_note(event_id: int, note: str) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        result = bot.core.note_focus(event_id, note, source="web")
        waiting = bot.await_get()
        if waiting and waiting.get("kind") == "focus_note" and int(waiting.get("event") or 0) == int(event_id):
            bot.await_clear()
        return result
    return run


def chat(text: str, *, voice: bool = False, reply_to: int | None = None) -> Any:
    """reply_to — id сообщения, на которое человек ответил в приложении (свайп или «Ответить», D52)."""
    def run(bot: Any) -> None:
        bot.core.refresh()
        with bot.via("web", SINK), bot.incoming(reply_to=reply_to):
            bot.on_text(text, voice=voice)
    return run


def react(message_id: int, emoji: str) -> Any:
    """Реакция из приложения (D52): набор Core.REACTIONS или пусто — снять. ❓ — Arvix объяснит проще."""
    if emoji and emoji not in Core.REACTIONS:
        raise ArvixError("Такой реакции нет")

    def run(bot: Any) -> None:
        bot.core.refresh()
        with bot.via("web", SINK):
            bot.on_reaction(message_id, emoji, channel="web")
    return run


def seen(upto: int | None) -> Any:
    """Пульс приложения на экране (в сети) и, если лента дочитана, — до какого сообщения прочитано."""
    def run(bot: Any) -> None:
        bot.core.presence_ping()
        if upto:
            bot.core.mark_read(upto, channel="web")
    return run


def button(data: str) -> Any:
    def run(bot: Any) -> None:
        with bot.via("web", SINK):
            bot.on_callback({"id": "web", "from": {"id": bot.owner}, "data": data, "message": {}})
    return run


def voice(audio: bytes, filename: str, *, reply_to: int | None = None) -> Any:
    def run(bot: Any) -> None:
        from arvix.stt import STTError

        with bot.via("web", SINK), bot.incoming(reply_to=reply_to):
            if not bot.stt.enabled:
                bot.log_in("[голосовое — распознавание не настроено]")
                bot.send(tpl.VOICE_OFF)
                return
            try:
                text = bot.stt.transcribe(audio, filename=filename, browser=True)
            except STTError as exc:
                bot.log_in("[голосовое — не распознано]")
                bot.send(f"Голосовое не распознал: {exc}. Напиши текстом.")
                return
            if text.strip():
                bot.core.refresh()
                bot.on_text(text, voice=True)
    return run


def upload(data: bytes, name: str, mime: str, caption: str, *, reply_to: int | None = None) -> Any:
    """Файл из приложения — тот же путь, что из Telegram: хранилище, журнал, голова."""
    def run(bot: Any) -> None:
        bot.core.refresh()
        with bot.via("web", SINK), bot.incoming(reply_to=reply_to):
            bot.on_file({"file_name": name, "mime_type": mime}, caption=caption, data=data)
    return run


def pair_link() -> Any:
    """Ссылка установки на телефон с одноразовым кодом (web/auth.py::pair_code)."""
    def run(bot: Any) -> dict[str, Any]:
        return {"url": bot.install_link()}
    return run


def claim_pair(code: str) -> Any:
    def run(bot: Any) -> str | None:
        from arvix.web.auth import claim_pair as claim

        return claim(bot.core, code)
    return run


def lesson(task_id: str) -> Any:
    """Учебный блок из приложения: план урока (вызов головы), задача запущена, таймер."""
    def run(bot: Any) -> None:
        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK), bot.in_study(task.id):
            bot.begin_lesson(task)
    return run


# --- заметки: чтение в потоке HTTP, запись — в главном потоке ---------------------------------

def daily_date(core: Any, path: str) -> Any:
    """Дата, если заметка — отчёт дня (по настройкам Daily notes), иначе None."""
    if not core.cfg.vault:
        return None
    today = core.today()
    for offset in range(-1, 31):
        d = today - timedelta(days=offset)
        if core.vault.daily_path(d) == path:
            return d
    return None


def note_view(core: Any, path: str) -> dict[str, Any]:
    """Заметка для экрана: текст, хэш для защиты от затирания, и какие строки-чекбоксы —
    задачи Arvix (их галочка закрывает задачу, а не просто меняет текст)."""
    from arvix import daily_note
    from arvix.vault import sha

    vault = core.vault
    path = vault.rel(vault.resolve(path, must_exist=True))
    text = vault.read(path)
    d = daily_date(core, path)
    tasks: dict[str, Any] = {}
    if d is not None:
        for i, line in enumerate(text.split("\n")):
            if task := daily_note.task_at_line(core, d, line):
                tasks[str(i)] = task_view(task)
    return {"path": path, "text": text, "sha": sha(text), "daily": d.isoformat() if d else None, "tasks": tasks}


def note_save(path: str, text: str, base_sha: str | None) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        bot.core.save_note(path, text, base_sha=base_sha, source="web")
        return note_view(bot.core, path if path.endswith(".md") else path + ".md")
    return run


def note_create(folder: str, name: str) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        import re

        clean = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", name).strip()
        if not clean:
            raise ArvixError("Название заметки пустое")
        path = f"{folder.strip('/')}/{clean}.md" if folder.strip("/") else f"{clean}.md"
        if (bot.core.vault.root / path).exists():
            raise ArvixError(f"Заметка «{clean}» уже есть в этой папке")
        bot.core.save_note(path, f"# {clean}\n\n", base_sha=None, source="web")
        return note_view(bot.core, path)
    return run


def note_toggle(path: str, line: int, base_sha: str) -> Any:
    """Галочка в заметке. Строка задачи Arvix → не текст, а задача: ответ {"task"}, и
    приложение проводит её через ✓ (с отчётом, если он нужен); [x] поставит код после закрытия."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import daily_note
        from arvix.core import NoteConflict
        from arvix.vault import sha

        core = bot.core
        view = note_view(core, path)
        if view["sha"] != base_sha:
            raise NoteConflict("Заметка изменилась — открыл свежую версию.", view["path"], view["text"])
        lines = view["text"].split("\n")
        if not 0 <= line < len(lines) or not (m := daily_note.CHECK_LINE.match(lines[line])):
            raise ArvixError("В этой строке нет чекбокса")
        checked = m.group(2) != " "
        if (task := view["tasks"].get(str(line))) is not None:
            if task["open"] and not checked:
                return {"task": task}
            if task["status"] == "done":
                raise ArvixError("Задача уже закрыта. Журнал не переписывается — если ошибся, скажи Arvix.")
            raise ArvixError("Задача закрыта как несделанная — галочка ей не поставится.")
        lines[line] = f"{m.group(1)}[{' ' if checked else 'x'}]{m.group(3)}{m.group(4)}"
        text = "\n".join(lines)
        core.save_note(view["path"], text, base_sha=sha(view["text"]), source="web")
        return note_view(core, view["path"])
    return run


def graph_link(a: str, b: str) -> Any:
    """«Связать» из подсказки графа: в конец заметки a — строка «Связи: [[b]]». Правка человека
    (он нажал), поэтому через save_note со сверкой версии."""
    def run(bot: Any) -> dict[str, Any]:
        from arvix import graph
        from arvix.vault import sha

        vault = bot.core.vault
        a_rel = vault.rel(vault.resolve(a, must_exist=True))
        b_path = vault.resolve(b, must_exist=True)
        text = vault.read(a_rel)
        b_rel = vault.rel(b_path)
        if a_rel == b_rel:
            raise ArvixError("Заметку не связать саму с собой")
        new = graph.link_line(text, graph.link_target(vault, b_rel))
        if new != text:
            bot.core.save_note(a_rel, new, base_sha=sha(text), source="web")
        return {"linked": True, "a": a_rel, "b": b_rel}
    return run


def capture(text: str) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        path = bot.core.capture_note(text, source="web")
        return {"path": path}
    return run


class SinkAPI:
    """Telegram-подобный API для ответов в приложение: всё уже в журнале (message_out)."""

    app_url = ""

    def send(self, chat_id: int, text: str, buttons: Any = None, keyboard: Any = None, *, html: str | None = None,
             reply_to: int | None = None) -> None:
        return None

    def edit(self, *a: Any, **k: Any) -> None:
        return None

    pin = unpin = typing = answer_callback = drop_buttons = edit

    def download(self, file_id: str) -> bytes:
        raise ArvixError("В приложении файлы приходят напрямую")


SINK = SinkAPI()
