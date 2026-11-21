"""Следующий проект к цели (D44 → D56): Arvix предлагает ОДИН проект — или говорит, что проект не нужен.

Это совет (L2): один вызов головы в фоне, никто не ждёт ответа в чате (правило №2). Код раскладывает
ответ в журнал — только как **идею** с этапами (у каждого — критерий) и источниками, помеченную
«предложил Arvix». В работу проект берёт человек сам: лимит трёх активных и «зачем» никто не обходит.

Почему один, а не цепочка (D56): цепочка из 3–6 проектов на каждую цель превратила вкладку в склад —
девять «отложенных», половина из которых не проекты (привычка «21 день по 45 минут», число цели
«10 000 ₽ за месяц», этап соседнего проекта). Поэтому код: не спрашивает голову, пока у цели есть
неразобранный шаг или неначатых идей уже IDEAS_MAX; отбрасывает похожие на любой проект — и на те,
от которых человек отказался кнопкой «Не нужен».
"""

from __future__ import annotations

import logging
import re
from typing import Any

from arvix import projects
from arvix.context import build_context
from arvix.core import ArvixError

log = logging.getLogger("arvix.project_roadmap")

IDEAS_MAX = 3  # неначатых проектов на все цели: больше — склад, а не план (D56)

ROADMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "почему именно этот следующий шаг к цели, до 500 символов"},
        "not_project": {"type": "string", "description": "следующий шаг — не проект: что это (привычка, тема для учёбы, этап проекта) и что сделать; тогда projects пустой"},
        "projects": {
            "type": "array", "maxItems": 1, "description": "0 или 1 проект — следующий шаг к цели",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string", "description": "что именно этот проект даёт для цели"},
                    "kind": {"type": "string", "description": "тип: " + ", ".join(projects.KIND_PRESETS) + " или своё слово"},
                    "purposes": {"type": "array", "items": {"type": "string"}, "description": "из: " + ", ".join(projects.PURPOSES)},
                    "expectation": {"type": "string", "description": "проверяемый результат в конце"},
                    "weeks": {"type": "integer", "description": "реалистичная длительность в неделях при weekly_min, 2–6"},
                    "weekly_min": {"type": "integer"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "milestones": {"type": "array", "items": {"type": "object", "properties": {
                        "title": {"type": "string"}, "dod": {"type": "string", "description": "критерий готовности"}},
                        "required": ["title", "dod"]}},
                    "resources": {"type": "array", "items": {"type": "object", "properties": {
                        "title": {"type": "string"}, "url": {"type": "string", "description": "только настоящая ссылка; не уверен — пусто"},
                        "kind": {"type": "string", "enum": list(projects.RESOURCE_KINDS)}}, "required": ["title"]}},
                },
                "required": ["title", "why", "expectation", "milestones"],
            },
        },
    },
    "required": ["summary", "projects"],
}

TASK = """<task>Следующий проект к цели человека — ОДИН или ни одного.
Проект — то, что он делает руками и что остаётся результатом, который можно показать: код, сайт, ролики,
исследование, заявка, мероприятие, выступление. НЕ проект:
- привычка или режим («21 день по 45 минут», «2 поста в неделю») — это блок в распорядке;
- тема, которую надо выучить, — это «Что выучить»;
- этап или продолжение уже идущего проекта — это его этап;
- сама цель или её число («10 000 ₽ за месяц», «поступить») — это цель.
Если следующий шаг к цели не проект — верни пустой projects, а в not_project одной-двумя фразами: что это и что сделать.
- Проект на 2–6 недель при часах недели из контекста; первый видимый результат — в первую неделю.
- Ближайшие сроки важнее мечты: экзамены и поступление этого года — раньше портфолио на будущее.
- 3–5 этапов, у каждого — проверяемый критерий (ссылка, число, отзыв, оценка).
- Источники и инструменты — только настоящие; не уверен в ссылке — url пустой. Ничего не выдумывай.
- Учитывай возраст, учёбу, нагрузку и то, что человек уже умеет, — из контекста и памяти.
- Не повторяй и не перефразируй проекты из списков ниже — ни этой цели, ни других, ни тех, от которых он отказался.</task>"""


def _words(title: str) -> set[str]:
    """Слова названия без окончаний: «Портфолио EECS: сайт» и «Сайт-портфолио для EECS» — одно и то же."""
    return {w[:5] for w in re.findall(r"[a-zа-яё0-9]+", title.lower().replace("ё", "е")) if len(w) > 2}


def similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def blocker(core: Any, goal_id: str) -> str | None:
    """Почему не спрашивать голову: у цели уже есть неразобранный шаг или идей и так много. None — можно."""
    waiting = [p for p in projects.roadmap_chain(core, goal_id) if p["status"] in ("active", "paused", "idea")]
    if waiting:
        p = waiting[0]
        return (f"У цели уже есть шаг — «{p['title']}» ({projects.STATUSES[p['status']]}). "
                + ("Сначала доведи его." if p["status"] == "active" else "Сначала реши, нужен ли он: «В работу» или «Не нужен». Потом предложу следующий."))
    ideas = [p for p in core.state.projects.values() if p["status"] == "idea"]
    if len(ideas) >= IDEAS_MAX:
        return (f"Неначатых проектов уже {len(ideas)}. Новые не добавляю, пока не разберёшь эти: "
                "что не нужно — «Не нужен», что нужно — «В работу».")
    return None


def prompt(core: Any, goal: dict[str, Any]) -> str:
    chain = projects.roadmap_chain(core, goal["id"])
    have = "\n".join(f"- {p['title']} ({projects.STATUSES[p['status']]}): {p.get('expectation') or p.get('why', '')}" for p in chain) or "- нет"
    others = [p for p in core.state.projects.values() if p.get("goal_id") != goal["id"] and p["status"] != "dropped"]
    refused = [p for p in core.state.projects.values() if p["status"] == "dropped"]
    skills = sorted({s for p in core.state.projects.values() for s in p.get("skills") or []})
    return (f"ЦЕЛЬ: {goal['title']} (зачем: {goal.get('why') or '—'})" + (f", срок {goal['deadline']}" if goal.get("deadline") else "")
            + (f", метрика: {goal['metric']}" if goal.get("metric") else "")
            + f"\nУЖЕ ЕСТЬ У ЭТОЙ ЦЕЛИ:\n{have}"
            + ("\nПРОЕКТЫ ДРУГИХ ЦЕЛЕЙ:\n" + "\n".join(f"- {p['title']} ({projects.STATUSES[p['status']]})" for p in others) if others else "")
            + ("\nОТКАЗАЛСЯ ИЛИ ЗАКРЫЛ — не предлагай снова:\n" + "\n".join(f"- {p['title']}" for p in refused) if refused else "")
            + (f"\nНАВЫКИ ИЗ ПРОШЛЫХ ПРОЕКТОВ: {', '.join(skills)}" if skills else "")
            + f"\n\nКонтекст:\n{build_context(core)}")


def apply(core: Any, goal: dict[str, Any], result: dict[str, Any], *, source: str = "l2") -> list[str]:
    """Ответ модели → проект-идея в журнал (не больше одного). Возвращает названия созданных.
    Похожий на любой проект — на идущий, завершённый или отвергнутый «Не нужен» — отбрасывается кодом."""
    existing = [p["title"] for p in core.state.projects.values()]
    created: list[str] = []
    for item in (result.get("projects") or [])[:1]:
        title = str(item.get("title") or "").strip()
        if not title or any(similar(title, t) for t in existing):
            log.info("проект роадмапа отброшен как повтор: %s", title)
            continue
        purposes = [x for x in (item.get("purposes") or []) if x in projects.PURPOSES] or ["skill"]
        try:
            pid = projects.set_project(
                core, title, why=str(item.get("why") or ""), kind=str(item.get("kind") or "")[:40] or None, purposes=purposes,
                expectation=str(item.get("expectation") or ""), weekly_min=item.get("weekly_min") or None, goal_id=goal["id"],
                status="idea", skills=item.get("skills") or [], weeks=item.get("weeks") or None, by="arvix", source=source,
            )
            for ms in (item.get("milestones") or [])[:6]:
                try:
                    projects.set_milestone(core, pid, str(ms.get("title") or ""), dod=str(ms.get("dod") or ""), source=source)
                except ArvixError as exc:
                    log.info("этап отброшен: %s", exc)
            for res in (item.get("resources") or [])[:6]:
                try:
                    projects.set_resource(core, pid, str(res.get("title") or ""), url=str(res.get("url") or ""),
                                          kind=res.get("kind"), by="arvix", source=source)
                except ArvixError as exc:
                    log.info("источник отброшен: %s", exc)
        except ArvixError as exc:
            log.info("проект роадмапа отброшен: %s", exc)
            continue
        existing.append(title)
        created.append(title)
    return created


def note_md(core: Any, goal: dict[str, Any], summary: str) -> str:
    lines = [f"**Роадмап проектов: {goal['title']}**", "", summary.strip(), ""]
    for n, p in enumerate(projects.roadmap_chain(core, goal["id"]), 1):
        mark = {"done": "x", "active": "/"}.get(p["status"], " ")
        lines.append(f"{n}. [{mark}] **{p['title']}** — {projects.STATUSES[p['status']]}" + (f", ~{p['weeks']} нед" if p.get("weeks") else ""))
        if p.get("expectation"):
            lines.append(f"    Результат: {p['expectation']}")
        for m in projects.milestones(core, p["id"]):
            lines.append(f"    - [{'x' if m['status'] == 'done' else ' '}] {m['title']} — {m['dod']}")
        for r in projects.resources(core, p["id"])[:5]:
            lines.append(f"    - 📎 [{r['title']}]({r['url']})" if r["url"].startswith("http") else f"    - 📎 {r['title']}")
    return "\n".join(lines)


def generate(core: Any, brain: Any, goal_id: str, *, system: str) -> dict[str, Any]:
    """Один вызов головы. Голова недоступна — ArvixError: учёт и планирование работают дальше без неё."""
    goal = core.state.goals.get(goal_id)
    if goal is None:
        raise ArvixError(f"Цели {goal_id} нет")
    if why_not := blocker(core, goal_id):
        raise ArvixError(why_not)  # голову не спрашиваем: решение за человеком, а не ещё одна идея
    web = bool(core.cfg.section("brain").get("web_tools", True))
    result = brain.ask(system=system + "\n\n" + TASK, prompt=prompt(core, goal), schema=ROADMAP_SCHEMA, role="analyst",
                       vault_tools=bool(core.cfg.section("brain").get("vault_tools", True)), web=web)
    if not result:
        raise ArvixError("Голова сейчас недоступна — роадмап соберу позже. Проекты можно добавить и самому.")
    created = apply(core, goal, result)
    path = None
    if created and core.cfg.vault:
        try:
            folder = str(core.cfg.vault_paths.get("roadmaps") or "03_Resources/Роадмапы").strip("/")
            name = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", goal["title"][:60]).strip() or goal["id"]
            path = core.write_block(f"{folder}/Проекты — {name}.md", "проекты",
                                    note_md(core, goal, str(result.get("summary") or "")),
                                    create_with=f"# Проекты — {goal['title']}\n\n", source="l2")["path"]
        except ArvixError as exc:
            log.warning("заметка роадмапа не записана: %s", exc)
    return {"goal": goal, "summary": str(result.get("summary") or "")[:900], "created": created, "path": path,
            "not_project": str(result.get("not_project") or "").strip()[:600]}
