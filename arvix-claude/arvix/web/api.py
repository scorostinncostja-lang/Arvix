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

from arvix import learning_focus, rules, tools
from arvix.context import DAY_TYPES_RU, QUOTA_RU, end_time
from arvix.core import ArvixError, Core
from arvix.telegram import templates as tpl

FOCUS = "focus"
SPHERES_RU = {"learning": "учёба", "work": "работа", "sport": "спорт", "social": "люди", "health": "здоровье",
              "finance": "деньги", "project": "проект", "chore": "быт"}


def task_view(task: Any) -> dict[str, Any]:
    return {
        "id": task.id, "title": task.title, "sphere": task.sphere, "sphere_ru": SPHERES_RU.get(task.sphere, task.sphere),
        "date": task.local_date.isoformat(), "start": task.start, "end": end_time(task.start, task.duration_min) if task.start else None,
        "duration_min": task.duration_min, "importance": task.importance, "difficulty": task.difficulty,
        "deep_work": task.deep_work, "status": task.status, "done_pct": task.done_pct,
        "focus_min": task.focus_min, "report": task.report, "proof": task.proof, "open": task.is_open,
        "photos": list(task.report_photos), "guide": guide_view(task.guide),
    }


def guide_view(g: dict[str, Any] | None) -> dict[str, Any] | None:
    """«Как сделать» (D62) для экрана: шаги, «готово, когда», куда записать, заметка своими словами."""
    if not g:
        return None
    return {"steps": list(g.get("steps") or []), "done": g.get("done") or "", "save": g.get("save") or "",
            "note_path": g.get("note_path") or None}


def gentle(core: Any) -> bool:
    return core.effective_mode() == "red" or not core.state.mentor_enabled


def state_view(core: Any, *, thinking: str = "") -> dict[str, Any]:
    st = core.state
    now = core.now()
    today = now.date()
    focus = core.store.kv_get(FOCUS)
    base: dict[str, Any] = {
        "now": now.isoformat(), "date": today.isoformat(), "weekday": tpl.WEEKDAYS_FULL[today.weekday()],
        "name": st.profile.get("name") or "", "mode": core.effective_mode(), "mode_label": rules.MODE_LABELS[core.effective_mode()],
        "gentle": gentle(core), "thinking": thinking, "version": st.last_event_id,
        "focus": focus_view(core, focus), "focus_choices": list(tpl.FOCUS_CHOICES),
        "tools_note": tools.path(core),  # список инструментов в Obsidian (D62): «Мои инструменты» открывает его
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
            "study": bool(task and task.sphere == "learning" and task.is_open),
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
    # Нити чатов проектов (D47) и учебных сессий (D56) до D62 жили в своих окнах — в общем чате их нет и теперь
    events = [e for e in core.store.read(start) if e.kind in ("message_in", "message_out") and (before is None or e.id < before)
              and not Core.side_thread(e)]
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
            if task.sphere == "learning" and task.status in ("planned", "active"):
                bot.release_stale_focus()
                focus = core.store.kv_get(FOCUS)
                if focus and focus.get("task_id") != task.id:
                    raise ArvixError("Сначала закончи текущий фокус")
                with bot.via("web", SINK):
                    bot.start_focus(task.duration_min or 25, task.id, source="web")
                result["study"] = True
            else:
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
            bot.start_focus(minutes, task_id or None, topic=(topic or "").strip() or None, source="web")
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


def task_study(task_id: str, body: dict[str, Any]) -> Any:
    def run(bot: Any) -> dict[str, Any]:
        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK):
            return learning_focus.run(bot, task, body)
    return run


def task_guide(task_id: str) -> Any:
    """«Как сделать» из приложения (D62): голова пишет шаги по его инструментам, код проверяет и пишет в журнал.
    В чат не уходит — шаги видны у задачи, в заметке дня и в контексте головы."""
    def run(bot: Any) -> dict[str, Any]:
        task = bot.core.resolve_task(task_id)
        with bot.via("web", SINK):
            task = bot.prepare_guide(task, source="web")
        bot.refresh_panel()
        return {"task": task_view(task)}
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
