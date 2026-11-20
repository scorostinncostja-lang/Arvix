"""Проекты обратно в журнал из хранилища, когда журнал потерян (D54).

Сервер может пропасть вместе с журналом, а хранилище Obsidian живёт и на ноутбуке. Арвикс зеркалит туда
проекты двумя блоками — их и читаем:

1. карточка `%% arvix:проект %%` в главной заметке папки проекта (`projects.card_md`): вид, статус, «зачем»,
   цель, результат, дата начала, срок, часы в неделю, навыки, этапы со сроками, «Учиться», источники;
2. роадмап цели `%% arvix:проекты %%` (`project_roadmap.note_md`): порядок проектов, «~N нед» и проекты-идеи,
   у которых папки нет.

Каждый проект, которого в журнале нет (по названию), создаётся обычными событиями `project_set` /
`milestone_set` / `resource_set` / `learn_item_set` с источником `restore` — правило №3: состояние только
через события, а источник честно говорит, откуда они. Уже существующие проекты не трогаются: повторный
запуск ничего не дублирует. Без `apply` — только план.

Что из хранилища не восстановить: журнал работы проекта, его чат, вложенные минуты — их в блоках нет.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arvix import projects as P
from arvix.core import ArvixError

CARD = re.compile(r"%% arvix:проект %%\n(.*?)\n%% /arvix:проект %%", re.S)
ROADMAP = re.compile(r"%% arvix:проекты %%\n(.*?)\n%% /arvix:проекты %%", re.S)
HEAD = re.compile(r"^\*\*(?P<title>.+?)\*\* · (?P<kind>.+?) · (?P<status>.+?)\s*$")
ITEM = re.compile(r"^\s*- \[(?P<mark>[ xX/])\] (?P<title>.+?)(?: — (?P<rest>.*))?$")
DUE = re.compile(r"\s*\(до (\d{4}-\d{2}-\d{2})\)\s*$")
LINK = re.compile(r"^\[(?P<title>[^\]]+)\]\((?P<url>[^)\s]+)\)(?: — (?P<note>.*))?$")
WIKI = re.compile(r"^\[\[(?P<path>[^|\]]+)(?:\|(?P<title>[^\]]+))?\]\](?: — (?P<note>.*))?$")
STEP = re.compile(r"^(?P<n>\d+)\. \[[ xX/]\] \*\*(?P<title>.+?)\*\* — (?P<status>[^,]+?)(?:, ~(?P<weeks>\d+) нед)?\s*$")

# Подписи → значения. «отложен» — и idea, и paused; идея честнее: она не начата, пока её не взяли в работу.
STATUS_BY_LABEL = {"в работе": "active", "отложен": "idea", "идея": "idea", "завершён": "done", "закрыт": "dropped"}
KIND_BY_LABEL = {label: key for key, label in {**P.LEGACY_KINDS, **P.KIND_PRESETS}.items()}
PURPOSE_BY_LABEL = {label: key for key, label in P.PURPOSES.items()}
REASON = "Восстановлен из хранилища Obsidian после потери журнала на сервере"


def _minutes(text: str) -> int:
    m = re.fullmatch(r"(?:(\d+)ч)?(\d+)м", text.strip())
    return int(m.group(1) or 0) * 60 + int(m.group(2)) if m else 0


def _resource(text: str) -> dict[str, str]:
    text = text.strip().removeprefix("📎").strip()
    if m := LINK.match(text):
        return {"title": m["title"], "url": m["url"], "note": m["note"] or ""}
    if m := WIKI.match(text):
        return {"title": m["title"] or m["path"], "url": m["path"] + ".md", "note": m["note"] or ""}
    title, _, note = text.partition(" — ")
    return {"title": title.strip(), "url": "", "note": note.strip()}


def parse_card(text: str) -> dict[str, Any] | None:
    """Карточка проекта из заметки → поля для set_project и списки этапов, тем и источников."""
    found = CARD.search(text)
    if not found:
        return None
    lines = found.group(1).splitlines()
    head = HEAD.match(lines[0].strip()) if lines else None
    if not head:
        return None
    kind_label = head["kind"].strip()
    card: dict[str, Any] = {
        "title": head["title"].strip(), "kind": KIND_BY_LABEL.get(kind_label, kind_label),
        "status": STATUS_BY_LABEL.get(head["status"].strip(), "idea"), "purposes": [], "why": "", "goal": "",
        "expectation": "", "started": None, "deadline": None, "weekly_min": 0, "skills": [], "link": "",
        "milestones": [], "learn": [], "resources": [],
    }
    section = ""
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        bare = line.removeprefix("- ").strip()
        heading = line.strip("*").rstrip(":").strip()
        if heading in ("Этапы", "Учиться", "Источники и инструменты") and (line.startswith("**") or line.endswith(":")):
            section = heading
            continue
        if section == "Этапы" and (item := ITEM.match(raw)):
            due = DUE.search(item["rest"] or "")
            dod = DUE.sub("", item["rest"] or "").strip()
            card["milestones"].append({"title": item["title"].strip(), "dod": dod, "due": due.group(1) if due else None,
                                       "status": "done" if item["mark"] in "xX" else "open"})
        elif section == "Учиться" and (item := ITEM.match(raw)):
            card["learn"].append({"topic": item["title"].strip(), "why": (item["rest"] or "").strip(),
                                  "status": "done" if item["mark"] in "xX" else "todo"})
        elif section == "Источники и инструменты" and line.startswith("- "):
            card["resources"].append(_resource(bare))
        elif bare.startswith("Зачем:"):
            labels, sep, why = bare.removeprefix("Зачем:").strip().partition("; ")
            keys = [PURPOSE_BY_LABEL.get(x.strip()) for x in labels.split(",")]
            if sep and all(keys):
                card["purposes"], card["why"] = keys, why.strip()
            elif all(keys) and labels.strip():
                card["purposes"] = keys
            else:
                card["why"] = bare.removeprefix("Зачем:").strip()
        elif bare.startswith("Цель:"):
            card["goal"] = bare.removeprefix("Цель:").strip()
        elif bare.startswith(("Результат:", "Ожидание:")):
            card["expectation"] = bare.split(":", 1)[1].strip()
        elif bare.startswith("Навыки:"):
            card["skills"] = [x.strip() for x in bare.removeprefix("Навыки:").split(",") if x.strip()]
        elif bare.startswith("Ссылка:"):
            card["link"] = bare.removeprefix("Ссылка:").strip()
        elif bare.startswith("начат "):
            for part in bare.split(" · "):
                part = part.strip()
                if part.startswith("начат "):
                    card["started"] = part.removeprefix("начат ").strip()
                elif part.startswith("срок "):
                    card["deadline"] = part.removeprefix("срок ").strip()
                elif part.endswith(" в неделю"):
                    card["weekly_min"] = _minutes(part.removesuffix(" в неделю"))
    return card


def parse_roadmap(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Роадмап цели → (название цели, проекты по порядку с этапами и источниками)."""
    found = ROADMAP.search(text)
    if not found:
        return "", []
    goal, steps = "", []
    for raw in found.group(1).splitlines():
        line = raw.strip()
        if line.startswith("**Роадмап проектов:"):
            goal = line.removeprefix("**Роадмап проектов:").removesuffix("**").strip()
        elif step := STEP.match(line):
            steps.append({"order": int(step["n"]), "title": step["title"].strip(), "weeks": int(step["weeks"]) if step["weeks"] else None,
                          "status": STATUS_BY_LABEL.get(step["status"].strip(), "idea"), "expectation": "", "milestones": [], "resources": []})
        elif steps and line.startswith("Результат:"):
            steps[-1]["expectation"] = line.removeprefix("Результат:").strip()
        elif steps and line.startswith("- 📎"):
            steps[-1]["resources"].append(_resource(line.removeprefix("- ")))
        elif steps and (item := ITEM.match(raw)):
            steps[-1]["milestones"].append({"title": item["title"].strip(), "dod": (item["rest"] or "").strip(), "due": None,
                                            "status": "done" if item["mark"] in "xX" else "open"})
    return goal, steps


def collect(core: Any) -> list[dict[str, Any]]:
    """Все проекты из хранилища: карточки папок плюс роадмапы целей, слитые по названию. Карточка точнее
    (вид, «зачем», навыки, часы, дата начала), роадмап добавляет порядок, недели и идеи без папок."""
    if not core.cfg.vault:
        return []
    root: Path = core.vault.root
    base = root / str(core.cfg.vault_paths.get("projects") or "01_Projects").strip("/")
    found: dict[str, dict[str, Any]] = {}
    for note in sorted(base.glob("*/*.md")) if base.is_dir() else []:
        if note.stem != note.parent.name:
            continue  # главная заметка папки — одноимённая (projects.main_note)
        card = parse_card(note.read_text(encoding="utf-8", errors="replace"))
        if card:
            card["note"] = core.vault.rel(note)
            found[card["title"].casefold()] = card
    roadmaps = root / str(core.cfg.vault_paths.get("roadmaps") or "03_Resources/Роадмапы").strip("/")
    for note in sorted(roadmaps.glob("Проекты — *.md")) if roadmaps.is_dir() else []:
        goal, steps = parse_roadmap(note.read_text(encoding="utf-8", errors="replace"))
        for step in steps:
            card = found.get(step["title"].casefold())
            if card is None:
                found[step["title"].casefold()] = {
                    **step, "kind": "", "purposes": [], "why": f"Шаг роадмапа к цели «{goal}»", "goal": goal, "started": None,
                    "deadline": None, "weekly_min": 0, "skills": [], "link": "", "learn": [], "note": core.vault.rel(note)}
            else:
                card.setdefault("order", step["order"])
                card["weeks"] = card.get("weeks") or step["weeks"]
                card["goal"] = card["goal"] or goal
    return list(found.values())


def _goal_id(core: Any, title: str) -> str | None:
    want = title.strip().casefold()
    hits = [g["id"] for g in core.state.goals.values() if g["title"].strip().casefold() == want]
    return hits[0] if len(hits) == 1 else None


def restore(core: Any, *, apply: bool = False, source: str = "restore") -> list[str]:
    """План (apply=False) или восстановление. Возвращает строки отчёта — по одной на проект."""
    have = {p["title"].strip().casefold() for p in core.state.projects.values()}
    report: list[str] = []
    cards = sorted(collect(core), key=lambda c: (c["status"] != "active", c.get("goal") or "", c.get("order") or 99, c["title"]))
    for card in cards:
        if card["title"].casefold() in have:
            report.append(f"есть   {card['title']}")
            continue
        goal_id = _goal_id(core, card["goal"]) if card.get("goal") else None
        note = f" · цель «{card['goal']}» не найдена в журнале — без цели" if card.get("goal") and not goal_id else ""
        parts = f"{len(card['milestones'])} этапов, {len(card['resources'])} источников" + (f", {len(card['learn'])} тем" if card["learn"] else "")
        report.append(f"{'создан' if apply else 'будет '} {card['title']} — {P.STATUSES[card['status']]}, {parts}{note}")
        if not apply:
            continue
        try:
            with core.tx():  # проект целиком или ничего: полпроекта в журнале хуже, чем его отсутствие
                pid = P.set_project(
                    core, card["title"], why=card["why"], kind=card["kind"] or None, purposes=card["purposes"],
                    expectation=card["expectation"], deadline=card["deadline"], weekly_min=card["weekly_min"] or None,
                    goal_id=goal_id, status=card["status"], skills=card["skills"], link=card["link"], order=card.get("order"),
                    weeks=card.get("weeks"), started=card["started"], reason=REASON if card["status"] in ("done", "dropped") else "",
                    source=source, sync=False,
                )
                for m in card["milestones"]:
                    if m["dod"]:
                        P.set_milestone(core, pid, m["title"], dod=m["dod"], due=m["due"], status=m["status"], source=source, sync=False)
                for r in card["resources"]:
                    if r["title"] or r["url"]:
                        P.set_resource(core, pid, r["title"], url=r["url"], note=r["note"], source=source, sync=False)
                for item in card["learn"]:
                    P.set_learn(core, item["topic"], project_ref=pid, why=item["why"], status=item["status"], source=source, sync=False)
        except ArvixError as exc:
            report[-1] = f"НЕ создан {card['title']}: {exc}"
            continue
        P.sync_notes(core, pid)
        have.add(card["title"].casefold())
    return report
