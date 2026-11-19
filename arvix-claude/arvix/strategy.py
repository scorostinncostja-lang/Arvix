"""Стратегия целей (D52; 02-MECHANICS §15): как цель превращается в систему, которая работает каждый день.

Цель живёт не в списке, а в системе:
- **привычка** — блок распорядка, который повторяется (тег `goal:<id>` у блока шаблона дня);
- **проект** — то, что строится и остаётся результатом (projects.py, `goal_id` проекта);
- **задача** — разовое дело со сроком (тег `goal:<id>` у задачи);
- **учёба** — тема, которую надо выучить (learn_item_set с `goal_id`).

Всё здесь — код без ИИ (правило №1): дубли целей, фокус (≤ 3), система каждой цели, минуты на цель,
статус «движется / стоит / нет системы», следующий шаг, место для привычки в распорядке. Что именно
нужно цели, решает стратег (strategist.py, L2, в фоне); его план ложится сюда предложениями
(goal_plan_set), а принимает их человек одной кнопкой — и тогда код раскладывает их событиями
(правило №3). Арвикс решает, человек соглашается: П2 «автономия выше контроля» не нарушается.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from arvix.core import ArvixError, new_id, parse_hhmm

KIND_RANK = {"main": 0, "yearly": 1, "quarterly": 2, "milestone": 3}
KIND_RU = {"dream": "мечта", "main": "главная", "yearly": "цель года", "quarterly": "цель квартала", "milestone": "этап"}
STATUS_RU = {"moving": "движется", "start": "система есть — ждёт первого блока", "stalled": "стоит",
             "none": "нет системы", "overdue": "срок прошёл"}
ITEM_TYPES = {"habit": "привычка", "project": "проект", "task": "задача", "learn": "учиться", "link_block": "блок распорядка",
              "fix_goal": "уточнить цель"}
STALL_DAYS = 14        # система есть, а движения столько дней нет — «стоит»
START_DAYS = 7         # столько дней после принятия плана цель «запускается», а не «стоит»
PLAN_EVERY_DAYS = 7    # стратег сам приходит к цели без системы не чаще раза в неделю
DUP_THRESHOLD = 0.6    # доля общих основ слов, после которой цели — вероятные дубли
DAY_START, DAY_END = "07:00", "22:00"
WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

# Служебные слова не делают цели похожими: «Поступить в Stanford или MIT» и «Поступить в школу» —
# разные цели, хотя «поступить» общее.
STOP = frozenset("""для или при через без как что это все всё мой моя моё мои свой своя своё свои своего своей свою своим
хотя бы чтобы чем тем под над про после перед между уже ещё еще так также тоже очень можно нужно надо минимум
день дня дней год года лет раз два три""".split())


def max_focus(core: Any) -> int:
    return int(core.cfg.section("strategy").get("max_focus") or 3)


def goal_tag(goal_id: str) -> str:
    return f"goal:{goal_id}"


# --- дубли --------------------------------------------------------------------------------------

def stems(text: str) -> set[str]:
    """Основы слов: первые 4 буквы («информатика» и «информатике» — одно), аббревиатуры от 3 букв (ОГЭ, MIT)."""
    out = set()
    for word in re.findall(r"[\w]+", str(text or "").lower()):
        if len(word) < 3 or word in STOP or word.isdigit():
            continue
        out.add(word[:4])
    return out


def similarity(a: str, b: str) -> float:
    sa, sb = stems(a), stems(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def alive(core: Any) -> list[dict[str, Any]]:
    """Активные цели в порядке появления."""
    return [g for g in core.state.goals.values() if g.get("status", "active") == "active"]


def canonical(core: Any, goal_id: str | None) -> str | None:
    """Слитая цель указывает на ту, в которую её слили: старые теги и проекты продолжают работать."""
    goals, seen = core.state.goals, set()
    while goal_id and goal_id in goals and goals[goal_id].get("merged_into") and goal_id not in seen:
        seen.add(goal_id)
        goal_id = goals[goal_id]["merged_into"]
    return goal_id


def _weight(core: Any, goal: dict[str, Any]) -> tuple:
    """Какую из похожих целей оставить: ту, где больше сделано и записано."""
    gid = goal["id"]
    st = core.state
    linked = sum(1 for p in st.projects.values() if p.get("goal_id") == gid) + \
        sum(1 for g in st.goals.values() if g.get("parent_id") == gid and g.get("status", "active") == "active")
    filled = bool(goal.get("deadline")) + bool(goal.get("metric")) + (len(goal.get("why") or "") > 20)
    rank = 5 - KIND_RANK.get(goal.get("kind"), 4 if goal.get("kind") != "dream" else 5)
    return (bool(goal.get("focus")), linked, filled, rank, len(goal.get("title") or ""))


def duplicates(core: Any) -> list[dict[str, Any]]:
    """Группы похожих активных целей. Код находит и предлагает, какую оставить; сливает человек
    кнопкой или голова действием merge_goals — молча код ничего не сливает."""
    goals = [g for g in alive(core)]
    parent: dict[str, str] = {g["id"]: g["id"] for g in goals}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(goals):
        for b in goals[i + 1:]:
            if a.get("parent_id") == b["id"] or b.get("parent_id") == a["id"]:
                continue  # этап и его цель похожи по словам — это не дубль
            if (a.get("kind") == "dream") != (b.get("kind") == "dream"):
                continue  # мечта и цель на её пути — разные уровни
            if similarity(a["title"], b["title"]) >= DUP_THRESHOLD:
                parent[root(a["id"])] = root(b["id"])
    clusters: dict[str, list[dict[str, Any]]] = {}
    for g in goals:
        clusters.setdefault(root(g["id"]), []).append(g)
    out = []
    for group in clusters.values():
        if len(group) < 2:
            continue
        keeper = max(group, key=lambda g: _weight(core, g))
        out.append({"keeper": keeper, "others": [g for g in group if g["id"] != keeper["id"]]})
    return out


def merge(core: Any, keeper_id: str, other_ids: list[str], *, source: str = "web") -> dict[str, Any]:
    """Слить похожие цели в одну. Оставшаяся забирает недостающее (срок, метрику, «зачем»), этапы,
    проекты и темы учёбы; слитые закрываются событием со ссылкой merged_into — ничего не удаляется."""
    from arvix import projects

    st = core.state
    keeper = st.goals.get(keeper_id)
    if not keeper or keeper.get("status", "active") != "active":
        raise ArvixError(f"Цели {keeper_id} нет среди активных")
    others = [st.goals[o] for o in dict.fromkeys(other_ids) if o in st.goals and o != keeper_id]
    if not others:
        raise ArvixError("Нечего сливать: нужна хотя бы одна другая цель")
    fill: dict[str, Any] = {}
    for field in ("deadline", "metric"):
        if not keeper.get(field):
            fill[field] = next((o[field] for o in others if o.get(field)), None)
    why = keeper.get("why") or ""
    for o in others:
        extra = (o.get("why") or "").strip()
        if extra and extra.lower() not in why.lower() and len(why) + len(extra) < 480:
            why = f"{why}; {extra}" if why else extra
    with core.tx():
        core.set_goal(goal_id=keeper_id, why=why, deadline=fill.get("deadline"), metric=fill.get("metric"), source=source)
        moved = 0
        for o in others:
            for p in list(st.projects.values()):
                if p.get("goal_id") == o["id"]:
                    projects.set_project(core, project_id=p["id"], goal_id=keeper_id, source=source, sync=False)
                    moved += 1
            for child in list(st.goals.values()):
                if child.get("parent_id") == o["id"] and child["id"] != keeper_id:
                    core.set_goal(goal_id=child["id"], parent_id=keeper_id, source=source)
            for item in list(st.learn_items.values()):
                if item.get("goal_id") == o["id"]:
                    core.emit("learn_item_set", {**{k: v for k, v in item.items() if k not in ("date", "updated")}, "goal_id": keeper_id},
                              source=source, entity_id=item.get("project_id"))
            core.set_goal(goal_id=o["id"], status="dropped", merged_into=keeper_id, source=source)
    return {"keeper": st.goals[keeper_id], "merged": [o["title"] for o in others], "moved_projects": moved}


def set_focus(core: Any, goal_id: str, on: bool | None, *, source: str = "web") -> dict[str, Any]:
    """Человек решает сам: цель в фокус (True), в «потом» (False) или вернуть выбор коду (None)."""
    goal = core.state.goals.get(goal_id)
    if not goal or goal.get("status", "active") != "active":
        raise ArvixError(f"Цели {goal_id} нет среди активных")
    if on:
        pinned = [g for g in alive(core) if g.get("focus") is True and g["id"] != goal_id]
        if len(pinned) >= max_focus(core):
            raise ArvixError(f"В фокусе уже {len(pinned)}: " + ", ".join(f"«{g['title']}»" for g in pinned)
                             + " — сначала одну в «потом». Больше трёх целей сразу не двигаются.")
    payload = {k: v for k, v in goal.items()}
    payload.pop("focus", None)
    if on is not None:
        payload["focus"] = bool(on)
    with core.tx():
        core.emit("goal_set", payload, source=source, entity_id=goal_id)
    return core.state.goals[goal_id]


# --- дерево и фокус -----------------------------------------------------------------------------------

def tree_ids(core: Any, goal_id: str) -> set[str]:
    """Цель, её этапы на любую глубину и слитые в неё цели — всё, что работает на неё."""
    goals = core.state.goals
    ids = {goal_id}
    changed = True
    while changed:
        changed = False
        for g in goals.values():
            if g["id"] in ids:
                continue
            if g.get("parent_id") in ids or g.get("merged_into") in ids:
                ids.add(g["id"])
                changed = True
    return ids


def is_top(core: Any, goal: dict[str, Any]) -> bool:
    """Цель верхнего уровня (не этап другой живой цели). Этапы показываются внутри своей цели."""
    parent = core.state.goals.get(goal.get("parent_id") or "")
    return not parent or parent.get("status", "active") != "active" or parent.get("kind") == "dream"


def ranked(core: Any) -> list[dict[str, Any]]:
    """Кандидаты в фокус: живые цели верхнего уровня (кроме мечт и проигравших дублей) по важности.
    Порядок — код: закреплённые человеком, главная, цели года, ближе срок."""
    losers = {o["id"] for d in duplicates(core) for o in d["others"]}
    goals = [g for g in alive(core) if g.get("kind") != "dream" and is_top(core, g) and g["id"] not in losers]
    order = {g["id"]: n for n, g in enumerate(core.state.goals.values())}
    return sorted(goals, key=lambda g: (g.get("focus") is not True, g.get("focus") is False, KIND_RANK.get(g.get("kind"), 4),
                                        g.get("deadline") or "9999", order[g["id"]]))


def focus(core: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(в фокусе, потом). Не больше max_focus в фокусе: распыление — проблема №5 из 00-VISION."""
    goals = ranked(core)
    limit = max_focus(core)
    now = [g for g in goals if g.get("focus") is not False][:limit]
    ids = {g["id"] for g in now}
    return now, [g for g in goals if g["id"] not in ids]


# --- система цели -------------------------------------------------------------------------------------

def _tagged(tags: Any, ids: set[str]) -> bool:
    return any(str(t).startswith("goal:") and str(t)[5:] in ids for t in tags or ())


def habits(core: Any, ids: set[str]) -> list[dict[str, Any]]:
    """Привычки цели — блоки шаблонов дней с её тегом, сгруппированные по (название, время, длительность)."""
    out: dict[tuple, dict[str, Any]] = {}
    for weekday, template in sorted(core.state.templates.items()):
        for block in template.get("blocks", []):
            if not _tagged(block.get("tags"), ids):
                continue
            key = (block["title"], block.get("start"), int(block.get("duration", 60)))
            item = out.setdefault(key, {"title": block["title"], "start": block.get("start"), "duration": int(block.get("duration", 60)),
                                        "weekdays": []})
            item["weekdays"].append(int(weekday))
    return list(out.values())


def weekdays_ru(days: list[int]) -> str:
    days = sorted(set(days))
    if days == list(range(7)):
        return "каждый день"
    if days == list(range(5)):
        return "по будням"
    return ", ".join(WEEKDAYS_RU[d] for d in days)


def _task_minutes(task: Any) -> int:
    from arvix import projects

    return projects.task_minutes(task)


def goal_tasks(core: Any, ids: set[str]) -> list[Any]:
    """Задачи, работающие на цель: с её тегом или из её проектов."""
    project_ids = {p["id"] for p in core.state.projects.values() if canonical(core, p.get("goal_id")) in ids or p.get("goal_id") in ids}
    return [t for t in core.state.tasks.values() if t.status != "cancelled" and (_tagged(t.tags, ids) or (t.project and t.project in project_ids))]


def minutes_between(core: Any, ids: set[str], start: date, end: date, tasks: list[Any] | None = None) -> int:
    tasks = goal_tasks(core, ids) if tasks is None else tasks
    total = sum(_task_minutes(t) for t in tasks if start <= t.local_date <= end)
    project_ids = {p["id"] for p in core.state.projects.values() if p.get("goal_id") in ids}
    total += sum(int(x.get("minutes") or 0) for x in core.state.project_log
                 if x["project_id"] in project_ids and start.isoformat() <= x["date"] <= end.isoformat())
    return total


def engine(core: Any, goal: dict[str, Any]) -> dict[str, Any]:
    """Всё, что двигает цель, и цифры: минуты за 7 и 28 дней, по неделям, последнее движение, нужное в неделю."""
    from arvix import projects

    st = core.state
    today = core.today()
    ids = tree_ids(core, goal["id"])
    tasks = goal_tasks(core, ids)
    habit_list = habits(core, ids)
    project_list = [p for p in st.projects.values() if p.get("goal_id") in ids and p["status"] in ("active", "paused", "idea")]
    learn = [x for x in projects.learn_items(core) if x.get("goal_id") in ids and x["status"] == "todo"]
    upcoming = sorted((t for t in tasks if t.is_open and t.local_date >= today), key=lambda t: (t.local_date, t.start or "99"))
    weeks = []
    for n in range(3, -1, -1):  # 4 недели, текущая последней
        start = st.week_start(today) - timedelta(days=7 * n)
        weeks.append(minutes_between(core, ids, start, min(start + timedelta(days=6), today), tasks))
    moves = [t.local_date for t in tasks if t.status == "done" or t.focus_min]
    project_ids = {p["id"] for p in project_list}
    moves += [date.fromisoformat(x["date"]) for x in st.project_log if x["project_id"] in project_ids]
    last = max(moves) if moves else None
    need = sum(h["duration"] * len(h["weekdays"]) for h in habit_list) + \
        sum(int(p.get("weekly_min") or 0) for p in project_list if p["status"] == "active")
    since = [date.fromisoformat(p["started"]) for p in project_list if p.get("started") and p["status"] == "active"]
    since += [date.fromisoformat(x["date"]) for x in learn if x.get("date")]
    for plan in st.goal_plans.values():
        if plan["goal_id"] in ids:
            since += [date.fromisoformat(i["decided"]) for i in plan["items"] if i.get("status") == "accepted" and i.get("decided")]
    return {
        "ids": ids, "habits": habit_list, "projects": project_list, "learn": learn, "upcoming": upcoming,
        "week_min": minutes_between(core, ids, today - timedelta(days=6), today, tasks),
        "month_min": minutes_between(core, ids, today - timedelta(days=27), today, tasks),
        "weeks": weeks, "last_move": last, "need_week": need, "since": max(since) if since else None,
        "active_projects": [p for p in project_list if p["status"] == "active"],
    }


def has_system(eng: dict[str, Any]) -> bool:
    return bool(eng["habits"] or eng["active_projects"] or eng["learn"] or eng["upcoming"])


def status(core: Any, goal: dict[str, Any], eng: dict[str, Any] | None = None) -> str:
    eng = eng or engine(core, goal)
    today = core.today()
    if goal.get("deadline") and str(goal["deadline"])[:10] < today.isoformat():
        return "overdue"
    if not has_system(eng):
        return "none"
    if eng["week_min"] > 0:
        return "moving"
    if eng["since"] and (today - eng["since"]).days < START_DAYS:
        return "start"
    if eng["last_move"] and (today - eng["last_move"]).days < STALL_DAYS:
        return "moving"
    return "stalled"


def idle_days(core: Any, eng: dict[str, Any]) -> int | None:
    return (core.today() - eng["last_move"]).days if eng["last_move"] else None


def next_action(core: Any, goal: dict[str, Any], eng: dict[str, Any]) -> str | None:
    """Один следующий шаг — по данным: ближайший блок, этап проекта, тема учёбы, ближайшая привычка."""
    from arvix import projects

    today = core.today()
    if eng["upcoming"]:
        t = eng["upcoming"][0]
        day = "сегодня" if t.local_date == today else "завтра" if t.local_date == today + timedelta(days=1) else f"{t.local_date:%d.%m}"
        return f"{day} {t.start or ''} · {t.title}".replace("  ", " ")
    for p in eng["active_projects"]:
        if step := projects.next_step(core, p):
            return f"{p['title']} → {step['title']}"
    if eng["learn"]:
        return f"выучить: {eng['learn'][0]['topic']}"
    if eng["habits"]:
        h = eng["habits"][0]
        return f"{h['title']} · {weekdays_ru(h['weekdays'])} {h['start']}"
    return None


def issues(core: Any, goal: dict[str, Any], eng: dict[str, Any], code: str) -> list[str]:
    """Несостыковки цели — код находит, голова называет и чинит (critical.md)."""
    from arvix import checks

    out = list(checks.goal_issues(goal, core.state.goals, core.today()))
    # Дубли — отдельным блоком с кнопкой «объединить»; «N-я цель года» — это и есть фокус: лишние уходят в «потом»
    out = [x for x in out if "дубль" not in x and "активная цель года" not in x]
    if code == "none":
        out.insert(0, "нет системы: ни привычки, ни проекта, ни учёбы, ни задачи — цель не двигается сама")
    elif code == "stalled":
        days = idle_days(core, eng)
        out.insert(0, f"система есть, а движения {days} дн" if days is not None else "система есть, а движения ещё не было")
    if eng["need_week"] and eng["week_min"] * 2 < eng["need_week"] and core.today().weekday() >= 3:
        out.append(f"за неделю {hm(eng['week_min'])} из {hm(eng['need_week'])} по системе")
    return out


def hm(minutes: int) -> str:
    h, m = divmod(int(minutes or 0), 60)
    return f"{h}ч{m:02d}м" if h else f"{m}м"


# --- планы стратега (предложения) ------------------------------------------------------------------------

def pending_plan(core: Any, goal_id: str) -> dict[str, Any] | None:
    """Свежий план цели, в котором есть нерешённые пункты."""
    plans = [p for p in core.state.goal_plans.values() if p["goal_id"] == goal_id and any(i["status"] == "proposed" for i in p["items"])]
    return max(plans, key=lambda p: p["event_id"]) if plans else None


def last_plan_date(core: Any, goal_id: str) -> date | None:
    dates = [date.fromisoformat(p["date"]) for p in core.state.goal_plans.values() if p["goal_id"] == goal_id]
    return max(dates) if dates else None


def auto_candidate(core: Any) -> dict[str, Any] | None:
    """Цель, к которой стратег придёт сам (L0 решает, когда звать L2): в фокусе, без системы или стоит,
    без нерешённого плана и без плана за последнюю неделю. Одна за раз."""
    now, _ = focus(core)
    today = core.today()
    for goal in now:
        code = status(core, goal)
        if code not in ("none", "stalled"):
            continue
        if pending_plan(core, goal["id"]):
            continue
        last = last_plan_date(core, goal["id"])
        if last and (today - last).days < PLAN_EVERY_DAYS:
            continue
        return goal
    return None


def record_plan(core: Any, goal_id: str, result: dict[str, Any], *, source: str = "l2") -> str:
    """Ответ стратега → одно событие goal_plan_set. Пункты чистит код: только известные типы, у привычки —
    дни и длительность, у проекта — этапы с критерием; остальное отбрасывается, а не чинится молча."""
    goal = core.state.goals.get(goal_id)
    if not goal:
        raise ArvixError(f"Цели {goal_id} нет")
    items = []
    for raw in (result.get("items") or [])[:6]:
        kind = raw.get("type")
        title = str(raw.get("title") or "").strip()[:160]
        if kind not in ITEM_TYPES or (not title and kind != "fix_goal"):
            continue
        item: dict[str, Any] = {"idx": len(items), "type": kind, "title": title, "why": str(raw.get("why") or "")[:300]}
        if kind == "habit":
            days = sorted({int(d) for d in raw.get("weekdays") or [] if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6})
            item.update(weekdays=days or list(range(5)), start=parse_hhmm(raw.get("start")) if raw.get("start") else None,
                        duration=max(10, min(int(raw.get("duration") or 30), 120)),
                        sphere=str(raw.get("sphere") or "learning")[:20], deep_work=bool(raw.get("deep_work")))
        elif kind == "project":
            ms = [{"title": str(m.get("title") or "")[:200], "dod": str(m.get("dod") or "")[:300]}
                  for m in raw.get("milestones") or [] if m.get("title") and m.get("dod")][:6]
            item.update(expectation=str(raw.get("expectation") or "")[:400], weekly_min=int(raw.get("weekly_min") or 0) or None,
                        weeks=int(raw.get("weeks") or 0) or None, milestones=ms, kind=str(raw.get("kind") or "")[:40])
        elif kind == "task":
            item.update(date=str(raw.get("date") or "")[:10] or None, start=parse_hhmm(raw.get("start")) if raw.get("start") else None,
                        duration=max(10, min(int(raw.get("duration") or 45), 180)), sphere=str(raw.get("sphere") or "project")[:20])
        elif kind == "learn":
            item.update(sources=[str(s)[:300] for s in raw.get("sources") or []][:5])
        elif kind == "link_block":
            item.update(block=str(raw.get("block") or title)[:200])
        elif kind == "fix_goal":
            item.update(deadline=str(raw.get("deadline") or "")[:10] or None, metric=str(raw.get("metric") or "")[:200] or None)
            if not (item["deadline"] or item["metric"]):
                continue
            item["title"] = title or "Срок и метрика цели"
        items.append(item)
    if not items:
        raise ArvixError("В плане не оказалось ни одного пригодного пункта")
    plan_id = new_id()
    payload = {"id": plan_id, "goal_id": goal_id, "diagnosis": str(result.get("diagnosis") or "")[:600],
               "summary": str(result.get("summary") or "")[:900], "items": items}
    with core.tx():
        core.emit("goal_plan_set", payload, source=source, entity_id=goal_id)
    return plan_id


def template_slot(core: Any, weekday: int, minutes: int, prefer: str | None) -> str | None:
    """Место для привычки в шаблоне дня: желаемое время, если свободно, иначе первое окно между
    DAY_START и часом до отбоя. Время подбирает код, а не модель (как projects.free_slot)."""
    template = core.state.templates.get(weekday)
    if not template:
        return None
    busy = []
    for block in template.get("blocks", []):
        if block.get("start"):
            h, m = map(int, block["start"].split(":"))
            busy.append((h * 60 + m, h * 60 + m + int(block.get("duration", 60))))
    bed = core.state.profile.get("bedtime_target")
    end = _min(DAY_END)
    if bed and _min(bed) > 12 * 60:
        end = min(end, _min(bed) - 60)

    def free(start: int) -> bool:
        return start >= _min(DAY_START) and start + minutes <= end and all(start >= e or start + minutes <= s for s, e in busy)

    if prefer and free(_min(prefer)):
        return prefer
    cursor = _min(DAY_START)
    for s, e in sorted(busy) + [(end, end)]:
        if s - cursor >= minutes and free(cursor):
            return f"{cursor // 60:02d}:{cursor % 60:02d}"
        cursor = max(cursor, e)
        cursor = -(-cursor // 15) * 15
    return None


def _min(hhmm: str) -> int:
    h, m = map(int, str(hhmm).split(":")[:2])
    return h * 60 + m


def place_habit(core: Any, goal_id: str, item: dict[str, Any], *, source: str = "web") -> dict[str, Any]:
    """Привычка → блок в шаблоны выбранных дней с тегом цели. Со следующего утра она становится задачей
    с напоминанием (daily.materialize). День без шаблона или без окна пропускается — и это видно."""
    from arvix import rules

    if not core.state.templates:
        raise ArvixError("Распорядка ещё нет — привычке некуда встать. Сначала соберём распорядок: «составь мне распорядок»")
    placed, skipped = [], []
    with core.tx():
        for weekday in item.get("weekdays") or list(range(5)):
            template = core.state.templates.get(weekday)
            when = template_slot(core, weekday, int(item["duration"]), item.get("start"))
            if not template or not when:
                skipped.append(WEEKDAYS_RU[weekday])
                continue
            block = {"start": when, "duration": int(item["duration"]), "title": item["title"],
                     "sphere": item.get("sphere") if item.get("sphere") in rules.SPHERES else "learning",
                     "importance": 3, "difficulty": 2, "deep_work": bool(item.get("deep_work")),
                     "tags": [goal_tag(goal_id), "habit"]}
            core.set_template([weekday], template["day_type"], list(template["blocks"]) + [block], source=source)
            placed.append(f"{WEEKDAYS_RU[weekday]} {when}")
    if not placed:
        raise ArvixError("Ни в одном дне нет свободного окна на " + f"{item['duration']} мин — привычка не встала")
    return {"placed": placed, "skipped": skipped}


def link_block(core: Any, goal_id: str, title: str, *, source: str = "web") -> list[str]:
    """Существующий блок распорядка начинает работать на цель: тег цели во всех днях с таким названием."""
    low = title.strip().lower()
    hit = []
    with core.tx():
        for weekday, template in sorted(core.state.templates.items()):
            blocks, changed = [], False
            for block in template.get("blocks", []):
                if block["title"].strip().lower() == low and goal_tag(goal_id) not in (block.get("tags") or []):
                    block = {**block, "tags": list(block.get("tags") or []) + [goal_tag(goal_id)]}
                    changed = True
                blocks.append(block)
            if changed:
                core.set_template([weekday], template["day_type"], blocks, source=source)
                hit.append(WEEKDAYS_RU[weekday])
    if not hit:
        raise ArvixError(f"Блока «{title}» в распорядке нет")
    return hit


def accept_item(core: Any, plan_id: str, idx: int, *, source: str = "web") -> str:
    """Принять пункт плана: код раскладывает его событиями и отвечает строкой квитанции."""
    from arvix import projects

    plan = core.state.goal_plans.get(plan_id)
    if not plan:
        raise ArvixError(f"Плана {plan_id} нет")
    item = next((i for i in plan["items"] if i["idx"] == int(idx)), None)
    if not item:
        raise ArvixError("Такого пункта в плане нет")
    if item["status"] != "proposed":
        raise ArvixError(f"Пункт «{item['title']}» уже решён")
    gid = canonical(core, plan["goal_id"]) or plan["goal_id"]
    kind = item["type"]
    ref = None
    with core.tx():
        if kind == "habit":
            out = place_habit(core, gid, item, source=source)
            text = f"привычка «{item['title']}»: {', '.join(out['placed'])}" + (f" (нет окна: {', '.join(out['skipped'])})" if out["skipped"] else "")
        elif kind == "project":
            busy = len(projects.active(core)) >= projects.max_active(core)
            ref = projects.set_project(core, item["title"], why=item.get("why") or item["title"], kind=item.get("kind") or None,
                                       expectation=item.get("expectation") or "", weekly_min=item.get("weekly_min"), weeks=item.get("weeks"),
                                       goal_id=gid, status="paused" if busy else "active", by="arvix", source=source)
            for ms in item.get("milestones") or []:
                try:
                    projects.set_milestone(core, ref, ms["title"], dod=ms["dod"], source=source)
                except ArvixError:
                    pass
            text = f"проект «{item['title']}»" + (" — отложен: в работе уже лимит проектов" if busy else " — в работе")
        elif kind == "task":
            day = core.parse_day(item.get("date")) if item.get("date") else core.today()
            if day < core.today():
                day = core.today()
            start = item.get("start") or projects.free_slot(core, day, int(item["duration"]))
            if start is None and day == core.today():
                day = day + timedelta(days=1)
                start = projects.free_slot(core, day, int(item["duration"]))
            task = core.add_task(item["title"], sphere=item.get("sphere") or "project", start=start, duration_min=int(item["duration"]),
                                 day=day.isoformat(), tags=[goal_tag(gid)], source=source)
            ref = task.id
            text = f"задача «{task.title}» · {task.local_date:%d.%m} {task.start or ''}".rstrip()
        elif kind == "learn":
            ref = projects.set_learn(core, item["title"], goal_id=gid, why=item.get("why", ""), sources=item.get("sources"), source=source)
            text = f"учиться: {item['title']}"
        elif kind == "link_block":
            days = link_block(core, gid, item.get("block") or item["title"], source=source)
            text = f"блок «{item.get('block') or item['title']}» теперь работает на цель ({', '.join(days)})"
        else:  # fix_goal
            core.set_goal(goal_id=gid, deadline=item.get("deadline"), metric=item.get("metric"), source=source)
            text = "цель уточнена: " + " · ".join(x for x in (f"срок {item['deadline']}" if item.get("deadline") else "",
                                                              f"метрика: {item['metric']}" if item.get("metric") else "") if x)
        core.emit("goal_plan_item", {"plan_id": plan_id, "idx": item["idx"], "status": "accepted", "ref": ref, "note": text[:300]},
                  source=source, entity_id=gid)
    return text


def reject_item(core: Any, plan_id: str, idx: int | None = None, *, source: str = "web") -> int:
    """Отклонить пункт (или все нерешённые, idx=None). Отказ — тоже данные: стратег видит его в следующий раз."""
    plan = core.state.goal_plans.get(plan_id)
    if not plan:
        raise ArvixError(f"Плана {plan_id} нет")
    items = [i for i in plan["items"] if i["status"] == "proposed" and (idx is None or i["idx"] == int(idx))]
    with core.tx():
        for item in items:
            core.emit("goal_plan_item", {"plan_id": plan_id, "idx": item["idx"], "status": "rejected"}, source=source, entity_id=plan["goal_id"])
    return len(items)


def accept_all(core: Any, plan_id: str, *, source: str = "web") -> tuple[list[str], list[str]]:
    """Принять весь план. Пункт, который не встал (нет окна, лимит), не роняет остальные — отказ виден."""
    plan = core.state.goal_plans.get(plan_id)
    if not plan:
        raise ArvixError(f"Плана {plan_id} нет")
    done, failed = [], []
    for item in [i for i in plan["items"] if i["status"] == "proposed"]:
        try:
            done.append(accept_item(core, plan_id, item["idx"], source=source))
        except ArvixError as exc:
            failed.append(f"«{item['title']}»: {exc}")
    return done, failed


def item_line(item: dict[str, Any]) -> str:
    """Пункт плана одной строкой — для Telegram и для головы."""
    kind = item["type"]
    if kind == "habit":
        tail = f"{weekdays_ru(item['weekdays'])}" + (f" ~{item['start']}" if item.get("start") else "") + f", {item['duration']} мин"
    elif kind == "project":
        tail = (item.get("expectation") or "") + (f" · {len(item.get('milestones') or [])} этапа" if item.get("milestones") else "")
    elif kind == "task":
        tail = (f"{item['date']} " if item.get("date") else "") + f"{item['duration']} мин"
    elif kind == "fix_goal":
        tail = " · ".join(x for x in (item.get("deadline") or "", item.get("metric") or "") if x)
    else:
        tail = item.get("why") or ""
    return f"{ITEM_TYPES[kind]}: {item['title']}" + (f" — {tail}" if tail else "")


# --- карточка и контекст ---------------------------------------------------------------------------------

def card(core: Any, goal: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """Цель для приложения и головы: что это, как идёт и что её двигает. Цифры — только из журнала."""
    from arvix import projects

    eng = engine(core, goal)
    code = status(core, goal, eng)
    st = core.state
    stages = [g for g in st.goals.values() if g.get("parent_id") == goal["id"] and g.get("status", "active") != "dropped"]
    plan = pending_plan(core, goal["id"])
    out = {
        "id": goal["id"], "title": goal["title"], "kind": goal.get("kind"), "kind_ru": KIND_RU.get(goal.get("kind"), "цель"),
        "why": goal.get("why", ""), "deadline": goal.get("deadline"), "metric": goal.get("metric"), "focus": goal.get("focus"),
        "status": code, "status_ru": STATUS_RU[code], "week_min": eng["week_min"], "month_min": eng["month_min"],
        "weeks": eng["weeks"], "need_week": eng["need_week"], "idle_days": idle_days(core, eng),
        "next": next_action(core, goal, eng),
        "system": {"habits": len(eng["habits"]), "projects": len(eng["active_projects"]), "learn": len(eng["learn"]),
                   "tasks": len(eng["upcoming"])},
        "plan_pending": sum(1 for i in plan["items"] if i["status"] == "proposed") if plan else 0,
        "stages": [{"id": g["id"], "title": g["title"], "status": g.get("status", "active"), "deadline": g.get("deadline")}
                   for g in sorted(stages, key=lambda g: (g.get("status") == "done", g.get("deadline") or "9999"))],
    }
    if full:
        out["issues"] = issues(core, goal, eng, code)
        out["habits"] = [{**h, "days_ru": weekdays_ru(h["weekdays"])} for h in eng["habits"]]
        out["projects"] = [{"id": p["id"], "title": p["title"], "status": p["status"], "status_ru": projects.STATUSES[p["status"]],
                            "by": p.get("by", ""), "next": (projects.next_step(core, p) or {}).get("title")} for p in eng["projects"]]
        out["learn"] = [{"id": x["id"], "topic": x["topic"], "why": x.get("why", ""), "task_status": x.get("task_status")} for x in eng["learn"]]
        out["tasks"] = [{"id": t.id, "title": t.title, "date": t.local_date.isoformat(), "start": t.start, "duration_min": t.duration_min}
                        for t in eng["upcoming"][:8]]
        out["plan"] = plan_view(plan) if plan else None
        history = sorted((p for p in st.goal_plans.values() if p["goal_id"] == goal["id"]), key=lambda p: -p["event_id"])
        out["plans_done"] = len(history) - (1 if plan else 0)
    return out


def plan_view(plan: dict[str, Any]) -> dict[str, Any]:
    return {"id": plan["id"], "date": plan["date"], "diagnosis": plan.get("diagnosis", ""), "summary": plan.get("summary", ""),
            "items": [{**i, "line": item_line(i), "type_ru": ITEM_TYPES[i["type"]]} for i in plan["items"]]}


def dreams(core: Any) -> list[dict[str, Any]]:
    losers = {o["id"] for d in duplicates(core) for o in d["others"]}
    return [g for g in alive(core) if g.get("kind") == "dream" and g["id"] not in losers]


def context_lines(core: Any) -> list[str]:
    """Блок СТРАТЕГИЯ контекста головы: фокус с системой и цифрами, «потом» одной строкой, дубли, планы."""
    if not alive(core):
        return []
    now, later = focus(core)
    lines = []
    for goal in now:
        c = card(core, goal)
        sys = c["system"]
        parts = [f"[{goal['id']}] {goal['title']} ({c['kind_ru']}" + (f", до {goal['deadline']}" if goal.get("deadline") else "") + ")",
                 c["status_ru"], f"неделя {hm(c['week_min'])}" + (f"/{hm(c['need_week'])}" if c["need_week"] else ""),
                 f"система: привычек {sys['habits']}, проектов {sys['projects']}, тем {sys['learn']}, задач впереди {sys['tasks']}"]
        if c["next"]:
            parts.append(f"следующее: {c['next']}")
        line = "  " + " · ".join(parts)
        found = issues(core, goal, engine(core, goal), c["status"])
        if found:
            line += "\n    ⚠️ " + "; ".join(found[:3])
        if c["plan_pending"]:
            line += f"\n    ждёт ответа план Арвикса: {c['plan_pending']} пункт(а) — приложение, вкладка «Цели»"
        lines.append(line)
    if later:
        lines.append("  потом (не в фокусе): " + " · ".join(f"[{g['id']}] {g['title'][:60]}" for g in later[:8])
                     + (f" … ещё {len(later) - 8}" if len(later) > 8 else ""))
    for d in dreams(core)[:2]:
        lines.append(f"  мечта: {d['title']}")
    for dup in duplicates(core)[:3]:
        lines.append(f"  ⚠️ дубли: оставить [{dup['keeper']['id']}] «{dup['keeper']['title'][:50]}», слить "
                     + ", ".join(f"[{o['id']}] «{o['title'][:40]}»" for o in dup["others"]) + " — merge_goals")
    return lines
