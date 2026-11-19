"""Проекты (D43–D45; 02-MECHANICS §14): то, что человек строит сам, вместе с Арвиксом.

Человек говорит словами, Арвикс заполняет (D45): название, зачем, результат, этапы с критерием, что
выучить, источники, заметки. Всё содержательное живёт в Obsidian — папка проекта `01_Projects/<проект>/`:
главная заметка с блоком Арвикса, «Журнал», заметки самого человека и Арвикса, присланные файлы.
Приложение — окна над этой папкой: чат проекта, заметки, план, «учиться».

Считает код (правило №1): время, темп, прогноз, застой, следующий шаг, свободное окно. Состояние —
только событиями (правило №3): project_set · milestone_set · project_logged · resource_set ·
learn_item_set; задачи проекта — обычные task_created с полем project.

Убрано по опыту (D44, D45): деньги, каналы, GitHub-синхронизация. Старые события в журнале остаются.
Арвикс не делает проект за человека (00-VISION §7): разбирает, режет, ставит время, ревьюит.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from arvix.core import ArvixError, new_id, parse_hhmm

# Что это за проект. Подсказка, а не клетка: Арвикс и человек пишут любое слово.
KIND_PRESETS = {
    "code": "программирование", "app": "сайт или приложение", "bot": "бот и автоматизация", "game": "игра",
    "content": "контент и блог", "video": "видео и монтаж", "design": "дизайн", "music": "музыка",
    "writing": "текст и книга", "study": "учёба и исследование", "exam": "экзамен и олимпиада",
    "language": "язык", "business": "бизнес и продукт", "service": "услуги на заказ", "hardware": "железо и электроника",
    "opensource": "open source", "community": "сообщество", "event": "событие и мероприятие", "sport": "спорт и тело",
    "creative": "творчество", "hobby": "хобби", "personal": "личное",
}
LEGACY_KINDS = {"learning": "учёба и исследование", "portfolio": "портфолио", "income": "заработок"}
PURPOSES = {
    "skill": "навык", "portfolio": "портфолио", "experience": "опыт", "people": "единомышленники", "career": "карьера",
    "admission": "поступление", "earn": "заработок", "brand": "личный бренд", "help": "польза людям",
    "idea": "проверить идею", "fun": "удовольствие", "health": "здоровье",
}
LEGACY_PURPOSES = {"learning": ["skill"], "portfolio": ["portfolio"], "income": ["earn"], "community": ["people"]}

# Внутри — пять статусов (журнал 0.7 их уже содержит); человеку — три группы (D45).
STATUSES = {"idea": "отложен", "active": "в работе", "paused": "отложен", "done": "завершён", "dropped": "закрыт"}
GROUPS = {"active": "В работе", "later": "Отложены", "closed": "Завершены"}
MILESTONE_STATUSES = ("open", "done", "dropped")
LOG_KINDS = {"update": "сделано", "decision": "решение", "lesson": "урок", "blocker": "стопор", "release": "релиз",
             "feedback": "отзыв", "idea": "мысль"}
RESOURCE_KINDS = {"source": "источник", "doc": "документация", "course": "курс", "video": "видео", "tool": "инструмент",
                  "example": "пример (репозиторий, работа)", "repo": "репозиторий", "design": "макет", "note": "заметка",
                  "chat": "чат и люди", "other": "другое"}

STALL_DAYS = 7        # без движения столько дней — застой: Арвикс пишет сам
DECIDE_DAYS = 21      # столько — прямой вопрос «продолжаем, откладываем или завершаем?»
BEHIND_MARGIN = 0.15  # отставание этапов от времени больше 15 п.п. — «отстаёт»
DAY_START = "09:00"   # раньше блок проекта код сам не ставит
MAIN_BLOCK = "проект"
LOG_NOTE = "Журнал"


def _min(hhmm: str) -> int:
    hours, minutes = map(int, str(hhmm).split(":"))
    return hours * 60 + minutes


def max_active(core: Any) -> int:
    """Лимит проектов в работе: распыление — проблема №5 из 00-VISION."""
    return int(core.cfg.section("projects").get("max_active") or 3)


def group(status: str) -> str:
    return "active" if status == "active" else "closed" if status in ("done", "dropped") else "later"


def kind_label(kind: str | None) -> str:
    kind = kind or ""
    return KIND_PRESETS.get(kind) or LEGACY_KINDS.get(kind) or kind or "проект"


def purposes_of(project: dict[str, Any]) -> list[str]:
    return list(project.get("purposes") or LEGACY_PURPOSES.get(project.get("kind") or "", []))


def purpose_label(value: str) -> str:
    return PURPOSES.get(value, value)


def _clean_list(values: Any, limit: int, size: int = 40) -> list[str]:
    if isinstance(values, str):
        values = values.split(",")
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()[:size]
        if text and text not in out:
            out.append(text)
    return out[:limit]


def safe_name(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|#^\[\]]', " ", title)).strip()[:80]


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
        alive = [p for p in found if p["status"] not in ("done", "dropped")]
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


# --- Obsidian: папка проекта -------------------------------------------------------------------------

def folder(core: Any, project: dict[str, Any]) -> str:
    """Папка проекта в хранилище. Имя фиксируется при создании (`folder` в событии): переименование
    проекта папку не двигает — ссылки и заметки человека не ломаются."""
    if project.get("folder"):
        return project["folder"]
    base = str(core.cfg.vault_paths.get("projects") or "01_Projects").strip("/")
    return f"{base}/{safe_name(project['title']) or project['id']}"


def main_note(core: Any, project: dict[str, Any]) -> str:
    return f"{folder(core, project)}/{folder(core, project).rsplit('/', 1)[-1]}.md"


def note_files(core: Any, project: dict[str, Any]) -> list[dict[str, Any]]:
    """Заметки и файлы папки проекта: главная первой, потом по времени правки."""
    if not core.cfg.vault:
        return []
    root = core.vault.root / folder(core, project)
    if not root.is_dir():
        return []
    main = main_note(core, project)
    out = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = core.vault.rel(path)
        out.append({"path": rel, "name": path.stem if path.suffix == ".md" else path.name, "note": path.suffix == ".md",
                    "main": rel == main, "modified": int(path.stat().st_mtime),
                    "sub": str(path.parent.relative_to(root)) if path.parent != root else ""})
    return sorted(out, key=lambda x: (not x["main"], not x["note"], -x["modified"]))


def _sync_block(core: Any, rel: str, name: str, content: str, header: str) -> None:
    """Блок Арвикса в заметке — только если он изменился: журнал не растёт от пустых перезаписей."""
    from arvix.vault import replace_block

    path = core.vault.root / rel
    current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else header
    if replace_block(current, name, content) != current:
        core.write_block(rel, name, content, create_with=header, source="l0")


def sync_notes(core: Any, project_ref: Any) -> str | None:
    """Главная заметка и «Журнал» проекта — из журнала событий. Зовётся после каждой операции:
    что видно в приложении, то и в Obsidian. Нет хранилища — не беда, учёт идёт дальше."""
    if not core.cfg.vault:
        return None
    project = resolve(core, project_ref)
    if not project.get("folder") and project.get("folder") is not None:
        return None  # черновик из одной фразы: папки нет, пока Арвикс не дал проекту имя
    try:
        rel = main_note(core, project)
        _sync_block(core, rel, MAIN_BLOCK, card_md(core, project), f"# {project['title']}\n\n")
        log = [x for x in core.state.project_log if x["project_id"] == project["id"]]
        if log:
            _sync_block(core, f"{folder(core, project)}/{LOG_NOTE}.md", "журнал", journal_md(log),
                        f"# Журнал — {project['title']}\n\n")
        return rel
    except ArvixError:
        return None


def write_note(core: Any, project_ref: Any, name: str, content: str, *, append: bool = False, source: str = "claude") -> str:
    """Заметка в папке проекта — руки Арвикса в Obsidian (D45). Свою нетронутую он перезаписывает,
    чужую (правленную человеком) — только дописывает: правила vault.write. За пределы папки — нельзя."""
    project = resolve(core, project_ref)
    name = safe_name(str(name or "").removesuffix(".md"))
    if not name:
        raise ArvixError("У заметки нет названия")
    if not str(content or "").strip():
        raise ArvixError("Пустая заметка")
    rel = f"{folder(core, project)}/{name}.md"
    if rel == main_note(core, project):
        append = True  # в главной заметке своё место у Арвикса — блок; остальное только дописывается
    try:
        core.write_note(rel, str(content).strip() + "\n", append=append, source=source)
    except ArvixError:
        if append:
            raise
        # Человек правил эту заметку — его текст не трогаем, новое дописываем в конец (vault.write)
        core.write_note(rel, "\n" + str(content).strip() + "\n", append=True, source=source)
    return rel


# --- операции (каждая — событие) ------------------------------------------------------------------

def set_project(
    core: Any, title: str = "", *, project_id: str | None = None, why: str = "", kind: str | None = None,
    purposes: Any = None, expectation: str = "", deadline: Any = None, weekly_min: Any = None, goal_id: str | None = None,
    status: str | None = None, skills: Any = None, link: str = "", order: Any = None, weeks: Any = None,
    reason: str = "", by: str = "", source: str = "claude", sync: bool = True, draft: bool = False,
) -> str:
    """Новый проект или правка. С project_id непереданные поля остаются прежними."""
    st = core.state
    old = resolve(core, project_id) if project_id else {}
    if status and status not in STATUSES:
        raise ArvixError(f"Статус проекта: {', '.join(STATUSES)}")
    if goal_id and goal_id not in st.goals:
        raise ArvixError(f"Цели {goal_id} нет")
    kind_text = str(kind or "").strip()[:40]
    payload = {
        "id": old.get("id") or new_id(),
        "title": (str(title).strip() or old.get("title", ""))[:120],
        "why": (str(why).strip() or old.get("why", ""))[:800],
        "kind": kind_text or old.get("kind") or "personal",
        "purposes": _clean_list(purposes, 8) if purposes is not None else purposes_of(old),
        "expectation": (str(expectation).strip() or old.get("expectation", ""))[:500],
        "deadline": _date(deadline, "Срок") or old.get("deadline"),
        "weekly_min": max(0, min(int(weekly_min), 40 * 60)) if weekly_min not in (None, "") else int(old.get("weekly_min") or 0),
        "goal_id": (goal_id if goal_id is not None else old.get("goal_id")) or None,
        "status": status or old.get("status") or "active",
        "skills": _clean_list(skills, 12) if skills is not None else list(old.get("skills") or []),
        "link": (str(link).strip() or old.get("link", ""))[:300],
        "order": int(order) if order not in (None, "") else old.get("order"),
        "weeks": max(0, min(int(weeks), 104)) if weeks not in (None, "") else old.get("weeks"),
        "by": by or old.get("by") or "",
    }
    if not payload["title"]:
        raise ArvixError("У проекта нет названия")
    # Папка фиксируется первым настоящим названием: черновик из фразы (draft) её ещё не получает —
    # иначе папка навсегда звалась бы «Хочу снять серию роликов…».
    payload["folder"] = "" if draft else (old.get("folder") or folder(core, payload))
    if not payload["why"] and not payload["purposes"]:
        raise ArvixError("У проекта обязательно «зачем»: что хочешь получить — навык, результат, людей")
    if payload["status"] in ("done", "dropped") and old.get("status") != payload["status"] and len(reason.strip()) < 10:
        raise ArvixError("Завершить проект можно только с итогом: что получилось и почему так — хотя бы одной фразой")
    if payload["status"] == "active" and old.get("status") != "active":
        others = [p for p in st.projects.values() if p["status"] == "active" and p["id"] != payload["id"]]
        if len(others) >= max_active(core):
            names = ", ".join(p["title"] for p in others)
            raise ArvixError(f"В работе уже {len(others)} проекта ({names}) — это лимит. Отложи один или заверши, "
                             "иначе ни один не доедет до конца.")
    if payload["order"] is None and payload["goal_id"]:
        same = [p.get("order") or 0 for p in st.projects.values() if p.get("goal_id") == payload["goal_id"] and p["id"] != payload["id"]]
        payload["order"] = max(same, default=0) + 1
    if reason.strip():
        payload["reason"] = reason.strip()[:1000]
    with core.tx():
        core.emit("project_set", payload, source=source, entity_id=payload["id"])
    if sync and payload["folder"]:
        sync_notes(core, payload["id"])
    return payload["id"]


def start(core: Any, text: str, *, goal_id: str | None = None, source: str = "web") -> str:
    """Новый проект из одной фразы (D45): код сразу создаёт карточку-черновик, чтобы человеку было куда
    смотреть, а Арвикс следующим ходом заполняет её в чате проекта. Лимит занят — проект «отложен»."""
    text = str(text or "").strip()
    if len(text) < 3:
        raise ArvixError("Напиши, что хочешь сделать, — хотя бы пару слов")
    first = re.split(r"[.\n!?]", text, maxsplit=1)[0].strip()
    title = first[:60].rstrip(" ,;:—-") or text[:60]
    busy = sum(1 for p in core.state.projects.values() if p["status"] == "active") >= max_active(core)
    return set_project(core, title[0].upper() + title[1:], why=text, goal_id=goal_id or None,
                       status="idea" if busy else "active", source=source, draft=True)


def move(core: Any, project_ref: Any, step: int, *, source: str = "web") -> None:
    """Сдвинуть проект в роадмапе своей цели на шаг вверх (−1) или вниз (+1)."""
    project = resolve(core, project_ref)
    ids = [p["id"] for p in roadmap_chain(core, project.get("goal_id"))]
    i = ids.index(project["id"])
    j = i + (1 if step > 0 else -1)
    if not 0 <= j < len(ids):
        return
    ids[i], ids[j] = ids[j], ids[i]
    with core.tx():
        for n, pid in enumerate(ids, 1):
            if core.state.projects[pid].get("order") != n:
                set_project(core, project_id=pid, order=n, source=source, sync=False)


def set_milestone(
    core: Any, project_ref: Any, title: str = "", *, milestone_id: str | None = None, due: Any = None, dod: str = "",
    status: str | None = None, source: str = "claude",
) -> str:
    """Этап проекта. Новый этап — только с критерием готовности (П4)."""
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
        "id": old.get("id") or new_id(), "project_id": project["id"],
        "title": (str(title).strip() or old.get("title", ""))[:200],
        "dod": (str(dod).strip() or old.get("dod", ""))[:500],
        "due": _date(due, "Срок этапа") or old.get("due"),
        "status": status or old.get("status") or "open", "order": int(order),
    }
    if not payload["title"]:
        raise ArvixError("У этапа нет названия")
    if not payload["dod"]:
        raise ArvixError("У этапа нужен критерий готовности: как проверить, что он сделан — число, ссылка, результат")
    with core.tx():
        core.emit("milestone_set", payload, source=source, entity_id=project["id"])
    sync_notes(core, project["id"])
    return payload["id"]


def log_entry(core: Any, project_ref: Any, text: str, *, kind: str = "update", minutes: Any = 0, source: str = "claude",
              task_id: str | None = None) -> dict[str, Any]:
    """Запись в журнал проекта (и в заметку «Журнал»). Минуты — со слов, считаются отдельно."""
    project = resolve(core, project_ref)
    text = str(text).strip()
    if not text:
        raise ArvixError("Пустая запись в журнал проекта")
    payload = {"project_id": project["id"], "kind": kind if kind in LOG_KINDS else "update", "text": text[:2000],
               "minutes": max(0, min(int(minutes or 0), 12 * 60))}
    if task_id:
        payload["task_id"] = task_id
    with core.tx():
        core.emit("project_logged", payload, source=source, entity_id=project["id"])
    sync_notes(core, project["id"])
    return payload


def set_resource(
    core: Any, project_ref: Any, title: str = "", *, resource_id: str | None = None, url: str = "", kind: str | None = None,
    note: str = "", status: str | None = None, by: str = "", source: str = "claude",
) -> str:
    """Источник, инструмент или пример (чужой репозиторий, работа) — заполняет Арвикс по разговору.
    by="arvix" — проверь ссылку сам: модель может ошибиться."""
    project = resolve(core, project_ref)
    old = core.state.resources.get(resource_id or "", {})
    if resource_id and not old:
        raise ArvixError(f"Источника {resource_id} нет")
    url = str(url or "").strip() or old.get("url", "")
    if url and not re.match(r"^(https?://|obsidian://)", url) and not url.endswith(".md"):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url):
            url = "https://" + url
        else:
            raise ArvixError("Ссылка — с http(s):// или путь к заметке .md")
    payload = {
        "id": old.get("id") or new_id(), "project_id": project["id"],
        "title": (str(title).strip() or old.get("title", "") or url)[:120], "url": url[:500],
        "kind": kind if kind in RESOURCE_KINDS else old.get("kind", "source"),
        "note": (str(note).strip() or old.get("note", ""))[:500],
        "status": status if status in ("active", "removed") else old.get("status", "active"),
        "by": by or old.get("by") or "",
    }
    if not payload["title"]:
        raise ArvixError("У источника нет названия и ссылки")
    with core.tx():
        core.emit("resource_set", payload, source=source, entity_id=project["id"])
    sync_notes(core, project["id"])
    return payload["id"]


# --- «Учиться»: общая очередь для проектов и будущей вкладки «Обучение» (D45) ----------------------------

def set_learn(
    core: Any, topic: str = "", *, item_id: str | None = None, project_ref: Any = None, goal_id: str | None = None,
    why: str = "", sources: Any = None, status: str | None = None, source: str = "claude",
) -> str:
    """Тема, которую надо выучить. Привязка к проекту или цели — откуда она взялась; очередь общая:
    вкладка «Обучение» будет читать те же события learn_item_set."""
    old = core.state.learn_items.get(item_id or "", {})
    if item_id and not old:
        raise ArvixError(f"Темы {item_id} нет")
    project = resolve(core, project_ref) if project_ref else None
    if status and status not in ("todo", "done", "dropped"):
        raise ArvixError("Статус темы: todo, done, dropped")
    payload = {
        "id": old.get("id") or new_id(),
        "topic": (str(topic).strip() or old.get("topic", ""))[:160],
        "why": (str(why).strip() or old.get("why", ""))[:400],
        "project_id": project["id"] if project else old.get("project_id"),
        "goal_id": goal_id or old.get("goal_id") or (project.get("goal_id") if project else None),
        "sources": _clean_list(sources, 6, 300) if sources is not None else list(old.get("sources") or []),
        "status": status or old.get("status") or "todo",
        "task_id": old.get("task_id"),
    }
    if not payload["topic"]:
        raise ArvixError("Пустая тема")
    with core.tx():
        core.emit("learn_item_set", payload, source=source, entity_id=payload["project_id"])
    if payload["project_id"]:
        sync_notes(core, payload["project_id"])
    return payload["id"]


def learn_items(core: Any, project_id: str | None = None) -> list[dict[str, Any]]:
    """Темы с вычисленным статусом: тема, по которой учебный блок закрыт, — пройдена (L0, без отметки)."""
    out = []
    for item in core.state.learn_items.values():
        if project_id and item.get("project_id") != project_id:
            continue
        task = core.state.tasks.get(item.get("task_id") or "")
        status = item["status"]
        if status == "todo" and task and task.status == "done":
            status = "done"
        out.append({**item, "status": status, "task_status": task.status if task else None,
                    "task_date": task.local_date.isoformat() if task else None})
    rank = {"todo": 0, "done": 1, "dropped": 2}
    return sorted(out, key=lambda x: (rank[x["status"]], x["topic"]))


def learn_start(core: Any, item_id: str, *, minutes: int = 45, source: str = "web") -> Any:
    """«Учить сейчас»: учебный блок сферы learning в первое свободное окно сегодня. Дальше работает
    уже существующий урок (06-LEARNING §8): план по минутам, таймер, проверка."""
    item = core.state.learn_items.get(item_id)
    if not item:
        raise ArvixError(f"Темы {item_id} нет")
    day, when = core.today(), free_slot(core, core.today(), minutes)
    if when is None:
        day, when = core.today() + timedelta(days=1), free_slot(core, core.today() + timedelta(days=1), minutes)
    if when is None:
        raise ArvixError("Свободного окна сегодня и завтра нет — скажи время сам")
    task = core.add_task(f"Учить: {item['topic']}", sphere="learning", importance=3, start=when, duration_min=minutes,
                         deep_work=True, day=day.isoformat(), project=item.get("project_id"), tags=[f"learn:{item_id}"], source=source)
    with core.tx():
        core.emit("learn_item_set", {**item, "task_id": task.id}, source=source, entity_id=item.get("project_id"))
    return task


# --- план: свободное окно, блок, этапы ---------------------------------------------------------------

def next_step(core: Any, project: dict[str, Any]) -> dict[str, Any] | None:
    open_ms = [m for m in milestones(core, project["id"]) if m["status"] == "open"]
    return open_ms[0] if open_ms else None


def free_slot(core: Any, d: date, minutes: int) -> str | None:
    """Первое свободное окно на дату: не раньше DAY_START и текущего времени, не позже чем за час до
    отбоя, мимо задач и обязательных блоков. Код ищет, модель не угадывает."""
    busy: list[tuple[int, int]] = []
    for task in core.state.tasks_on(d):
        if task.start and task.status not in ("cancelled", "failed", "written_off"):
            begin_ = _min(task.start)
            busy.append((begin_, begin_ + max(task.duration_min, 15)))
    for block in core.fixed_blocks(d):
        begin_ = _min(block["start"])
        busy.append((begin_, begin_ + int(block.get("duration", 60))))
    begin = _min(DAY_START)
    if d == core.today():
        now = core.now()
        begin = max(begin, -(-(now.hour * 60 + now.minute + 10) // 15) * 15)
    bed = core.state.profile.get("bedtime_target")
    end = _min(bed) - 60 if bed and _min(bed) > 12 * 60 else 22 * 60
    cursor = begin
    for s, e in sorted(busy):
        if s - cursor >= minutes:
            break
        cursor = max(cursor, e)
    if cursor + minutes > end:
        return None
    return f"{cursor // 60:02d}:{cursor % 60:02d}"


def plan_block(core: Any, project_ref: Any, *, minutes: int = 60, day: Any = None, start: Any = None, title: str = "",
               source: str = "claude") -> Any:
    """Блок проекта в план: глубокая работа, привязана к проекту, название — следующий этап."""
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


def resources(core: Any, project_id: str) -> list[dict[str, Any]]:
    return [r for r in core.state.resources.values() if r["project_id"] == project_id and r["status"] == "active"]


def task_minutes(task: Any) -> int:
    if task.status == "done":
        return max(task.duration_min * task.done_pct // 100, task.focus_min)
    return task.focus_min


def stats(core: Any, project: dict[str, Any]) -> dict[str, Any]:
    st = core.state
    today = core.today()
    pid = project["id"]
    tasks = [t for t in st.tasks.values() if t.project == pid and t.status != "cancelled"]
    log = [x for x in st.project_log if x["project_id"] == pid]
    ms = milestones(core, pid)
    week_start = st.week_start(today).isoformat()
    task_min = sum(task_minutes(t) for t in tasks)
    said_min = sum(int(x.get("minutes") or 0) for x in log)
    week_min = sum(task_minutes(t) for t in tasks if t.local_date.isoformat() >= week_start) + \
        sum(int(x.get("minutes") or 0) for x in log if x["date"] >= week_start)
    # Движение — только сделанное: задача, таймер, запись журнала, пройденный этап. Разговор о проекте,
    # план и правка карточки — не движение (П4): обсуждать можно бесконечно, ничего не делая.
    moves = [t.local_date.isoformat() for t in tasks if t.status == "done" or t.focus_min]
    moves += [x["date"] for x in log]
    moves += [m["done_date"] for m in st.milestones.values() if m["project_id"] == pid and m.get("done_date")]
    last = max(moves) if moves else None
    since = date.fromisoformat(last if last else project.get("started") or today.isoformat())
    idle = max((today - since).days, 0)
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
    return {
        "minutes": task_min + said_min, "task_min": task_min, "said_min": said_min, "week_min": week_min,
        "weekly_target": int(project.get("weekly_min") or 0),
        "tasks_done": sum(1 for t in tasks if t.status == "done"), "tasks_open": [t for t in tasks if t.is_open],
        "milestones_done": done_ms, "milestones_total": len(ms), "last_move": last, "idle_days": idle,
        "pace": pace, "forecast": forecast,
        "learn_todo": sum(1 for x in learn_items(core, pid) if x["status"] == "todo"),
    }


def issues(core: Any, project: dict[str, Any], s: dict[str, Any] | None = None) -> list[str]:
    """Несостыковки проекта — код находит, модель поднимает сама (как checks.py)."""
    if project["status"] != "active":
        return []
    s = s or stats(core, project)
    today = core.today()
    out = []
    if s["idle_days"] >= DECIDE_DAYS:
        out.append(f"{s['idle_days']} дн без движения — реши честно: продолжаем, откладываем или завершаем с итогом")
    elif s["idle_days"] >= STALL_DAYS:
        out.append(f"{s['idle_days']} дн без движения")
    if not project.get("expectation"):
        out.append("нет результата: что должно быть в конце — проверяемо")
    if not project.get("deadline"):
        out.append("нет срока")
    elif project["deadline"] < today.isoformat():
        out.append(f"срок {project['deadline']} прошёл — сдвинь честно или заверши")
    if not s["milestones_total"]:
        out.append("нет этапов — проект не разложен на шаги")
    elif s["milestones_done"] == s["milestones_total"]:
        out.append("все этапы пройдены — завершить с итогом или добавить следующий этап")
    if s["pace"] and s["pace"]["behind"]:
        out.append(f"отстаёт: этапов {round(100 * s['pace']['done_share'])}% при {round(100 * s['pace']['time_share'])}% времени")
    if not s["tasks_open"] and s["milestones_total"] > s["milestones_done"]:
        out.append("в плане нет ни одного блока проекта")
    if s["weekly_target"] and today.weekday() >= 3 and s["week_min"] * 2 < s["weekly_target"]:
        out.append(f"за неделю {s['week_min']} мин из {s['weekly_target']}")
    return out


def active(core: Any) -> list[dict[str, Any]]:
    return sorted((p for p in core.state.projects.values() if p["status"] == "active"),
                  key=lambda p: (p.get("deadline") or "9999", p["title"]))


def load_issue(core: Any) -> str | None:
    total = sum(int(p.get("weekly_min") or 0) for p in active(core))
    budget = core.budget()["week_min"]
    if total and budget and total > budget * 0.6:
        return f"проекты просят {total // 60} ч в неделю — это больше 60 % бюджета недели ({budget // 60} ч)"
    return None


# --- роадмап: проекты по целям ----------------------------------------------------------------------

STATUS_RANK = {"done": 0, "active": 1, "paused": 2, "idea": 3, "dropped": 4}


def roadmap_chain(core: Any, goal_id: str | None) -> list[dict[str, Any]]:
    items = [p for p in core.state.projects.values() if (p.get("goal_id") or None) == (goal_id or None) and p["status"] != "dropped"]
    return sorted(items, key=lambda p: (p.get("order") or 999, STATUS_RANK[p["status"]], p.get("deadline") or "9999", p["title"]))


def roadmap(core: Any) -> list[dict[str, Any]]:
    goals = [g for g in core.state.goals.values() if g.get("status", "active") == "active"]
    kind_rank = {"dream": 0, "main": 1, "yearly": 2, "quarterly": 3, "milestone": 4}
    goals.sort(key=lambda g: (kind_rank.get(g.get("kind"), 5), g.get("deadline") or "9999", g["title"]))
    out = [{"goal": goal, "projects": roadmap_chain(core, goal["id"])} for goal in goals]
    loose = roadmap_chain(core, None)
    if loose:
        out.append({"goal": None, "projects": loose})
    return out


def roadmap_text(core: Any) -> str:
    lines = []
    for block in roadmap(core):
        goal = block["goal"]
        lines.append(f"{goal['title']} [{goal['id']}]" + (f" · до {goal['deadline']}" if goal.get("deadline") else "") if goal else "Вне целей")
        if not block["projects"]:
            lines.append("  проектов нет")
        for n, p in enumerate(block["projects"], 1):
            lines.append(f"  {n}. [{p['id']}] {p['title']} — {STATUSES[p['status']]}" + (f" · {p['weeks']} нед" if p.get("weeks") else ""))
    return "\n".join(lines) or "Целей и проектов нет."


# --- текст для головы, брифинга и Obsidian ------------------------------------------------------------

def hm(minutes: int) -> str:
    h, m = divmod(int(minutes or 0), 60)
    return f"{h}ч{m:02d}м" if h else f"{m}м"


def context_lines(core: Any) -> list[str]:
    """Блок ПРОЕКТЫ общего контекста головы: коротко по каждому активному + несостыковки."""
    lines = []
    goals = core.state.goals
    for p in active(core):
        s = stats(core, p)
        step = next_step(core, p)
        parts = [f"[{p['id']}] {p['title']} ({kind_label(p.get('kind'))})"]
        if p.get("goal_id") in goals:
            parts.append(f"цель: {goals[p['goal_id']]['title']}")
        if p.get("deadline"):
            parts.append(f"срок {p['deadline']}")
        parts.append(f"этапы {s['milestones_done']}/{s['milestones_total']}")
        parts.append(f"неделя {hm(s['week_min'])}" + (f"/{hm(s['weekly_target'])}" if s["weekly_target"] else ""))
        if step:
            parts.append(f"следующий этап: {step['title']}")
        line = "  " + " · ".join(parts)
        if found := issues(core, p, s):
            line += "\n    ⚠️ " + "; ".join(found)
        lines.append(line)
    rest = [p for p in core.state.projects.values() if p["status"] in ("paused", "idea")]
    if rest:
        lines.append("  отложены: " + " · ".join(f"[{p['id']}] {p['title']}" for p in rest[:8]))
    if issue := load_issue(core):
        lines.append(f"  ⚠️ {issue}")
    return lines


def chat_block(core: Any, project_ref: Any) -> str:
    """Всё о проекте — для разговора в окне проекта (D45). Голова видит карточку, этапы, «учиться»,
    журнал, заметки папки (пути — она читает их сама Read'ом) и знает, что может менять."""
    p = resolve(core, project_ref)
    s = stats(core, p)
    goal = core.state.goals.get(p.get("goal_id") or "")
    lines = [f"<project id=\"{p['id']}\">", f"ПРОЕКТ: {p['title']} — {STATUSES[p['status']]} · тип: {kind_label(p.get('kind'))}"]
    why = ", ".join(purpose_label(x) for x in purposes_of(p))
    lines.append("ЗАЧЕМ: " + "; ".join(x for x in (why, p.get("why", "")) if x))
    for label, value in (("ЦЕЛЬ", goal["title"] if goal else ""), ("РЕЗУЛЬТАТ", p.get("expectation")), ("СРОК", p.get("deadline")),
                         ("НАВЫКИ", ", ".join(p.get("skills") or []))):
        if value:
            lines.append(f"{label}: {value}")
    lines.append(f"ВРЕМЯ: неделя {hm(s['week_min'])}" + (f" из {hm(s['weekly_target'])}" if s["weekly_target"] else " (нормы нет)")
                 + f", всего {hm(s['minutes'])}; последнее движение {s['last_move'] or '—'}")
    ms = milestones(core, p["id"])
    lines.append("ЭТАПЫ:" + ("".join(f"\n  [{m['id']}] {'✓' if m['status'] == 'done' else '·'} {m['title']} — готово, когда {m['dod']}"
                                      + (f" (до {m['due']})" if m.get("due") else "") for m in ms) or " нет — разложи"))
    learn = learn_items(core, p["id"])
    if learn:
        lines.append("УЧИТЬСЯ:" + "".join(f"\n  [{x['id']}] {'✓' if x['status'] == 'done' else '·'} {x['topic']}" for x in learn))
    open_tasks = s["tasks_open"]
    if open_tasks:
        lines.append("БЛОКИ: " + " · ".join(f"{t.local_date:%d.%m} {t.start or ''} {t.title}" for t in open_tasks[:5]))
    log = [x for x in core.state.project_log if x["project_id"] == p["id"]][-8:]
    if log:
        lines.append("ЖУРНАЛ:" + "".join(f"\n  {x['date']} {LOG_KINDS.get(x['kind'], x['kind'])}: {x['text'][:200]}" for x in log))
    res = resources(core, p["id"])
    if res:
        lines.append("ИСТОЧНИКИ: " + " · ".join(f"{r['title']}" + (f" ({r['url']})" if r["url"] else "") for r in res[:10]))
    files = note_files(core, p)
    lines.append(f"ПАПКА В OBSIDIAN: {folder(core, p)}" + ("".join(f"\n  {f['path']}" for f in files[:25]) if files else " (пока пусто)"))
    if found := issues(core, p, s):
        lines.append("⚠️ " + "; ".join(found))
    lines.append("""Ты в окне этого проекта. Ты ведёшь его вместе с человеком и заполняешь сам, не спрашивая лишнего:
- карточка: set_project (project=id) — название, kind любым словом, purposes, why, expectation, deadline, weekly_min, goal_id;
- этапы: set_milestone с dod; отметить пройденный — status=done (только если критерий выполнен по словам или файлам);
- что выучить для проекта: learn_add (topic, why, sources) — это очередь для учёбы;
- заметки в папке проекта: project_note (name, content в Markdown, append) — план, архитектура, идеи, разбор кода, конспект;
- источники, инструменты, примеры чужих работ и репозиториев: project_resource — только настоящие ссылки;
- журнал: project_log — решения, уроки, стопоры, релизы; блок в план: plan_project.
Код, тексты и дизайн делает человек. Присланный код и файлы читай по путям из папки, ревьюй, задавай вопрос про
прогресс, предлагай один следующий шаг. Отвечай коротко: что сделал в проекте и что дальше.
</project>""")
    return "\n".join(lines)


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
    return [(p, s) for p in active(core) if (s := stats(core, p))["idle_days"] >= STALL_DAYS]


def card_md(core: Any, project: dict[str, Any]) -> str:
    """Блок Арвикса в главной заметке проекта — только факты журнала. Текст человека вокруг не трогается."""
    s = stats(core, project)
    why = ", ".join(purpose_label(x) for x in purposes_of(project))
    goal = core.state.goals.get(project.get("goal_id") or "")
    lines = [f"**{project['title']}** · {kind_label(project.get('kind'))} · {STATUSES[project['status']]}", ""]
    lines.append("- Зачем: " + "; ".join(x for x in (why, project.get("why", "")) if x))
    if goal:
        lines.append(f"- Цель: {goal['title']}")
    if project.get("expectation"):
        lines.append(f"- Результат: {project['expectation']}")
    meta = [f"начат {project.get('started')}"]
    if project.get("deadline"):
        meta.append(f"срок {project['deadline']}")
    if s["weekly_target"]:
        meta.append(f"{hm(s['weekly_target'])} в неделю")
    meta.append(f"вложено {hm(s['minutes'])}")
    lines.append("- " + " · ".join(meta))
    if project.get("skills"):
        lines.append("- Навыки: " + ", ".join(project["skills"]))
    if project.get("link"):
        lines.append(f"- Ссылка: {project['link']}")
    ms = milestones(core, project["id"])
    if ms:
        lines += ["", "**Этапы**"] + [f"- [{'x' if m['status'] == 'done' else ' '}] {m['title']} — {m['dod']}" + (f" (до {m['due']})" if m.get("due") else "")
                                      for m in ms]
    learn = learn_items(core, project["id"])
    if learn:
        lines += ["", "**Учиться**"] + [f"- [{'x' if x['status'] == 'done' else ' '}] {x['topic']}" + (f" — {x['why']}" if x.get("why") else "")
                                        for x in learn if x["status"] != "dropped"]
    res = resources(core, project["id"])
    if res:
        lines += ["", "**Источники и инструменты**"] + [
            (f"- [{r['title']}]({r['url']})" if r["url"].startswith("http") else f"- [[{r['url'].removesuffix('.md')}|{r['title']}]]" if r["url"] else f"- {r['title']}")
            + (f" — {r['note']}" if r.get("note") else "") for r in res[:20]]
    lines += ["", f"Журнал: [[{LOG_NOTE}]]"]
    return "\n".join(lines)


def journal_md(log: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {x['date']} · {LOG_KINDS.get(x['kind'], x['kind'])}: {x['text']}" + (f" ({hm(x['minutes'])})" if x.get("minutes") else "")
                     for x in reversed(log))
