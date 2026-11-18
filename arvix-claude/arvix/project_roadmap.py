"""Роадмап проектов под цель (D44): Арвикс предлагает цепочку проектов, которые ведут к цели.

Это совет (L2): один вызов головы в фоне, никто не ждёт ответа в чате (правило №2). Код раскладывает
ответ в журнал — только как **идеи** с этапами (у каждого — критерий) и источниками, помеченными
«предложил Арвикс». В работу проект берёт человек сам: лимит трёх активных и «зачем» никто не обходит.
Уже существующие проекты цели модель видит и не дублирует; дубль по названию код всё равно отбросит.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from arvix import projects
from arvix.context import build_context
from arvix.core import ArvixError

log = logging.getLogger("arvix.project_roadmap")

ROADMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "логика роадмапа для человека: почему эти проекты и в таком порядке, до 600 символов"},
        "projects": {
            "type": "array", "description": "3–6 проектов по порядку: от простого к сложному, каждый опирается на предыдущий",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string", "description": "что именно этот проект даёт для цели"},
                    "kind": {"type": "string", "description": "тип: " + ", ".join(projects.KIND_PRESETS) + " или своё слово"},
                    "purposes": {"type": "array", "items": {"type": "string"}, "description": "из: " + ", ".join(projects.PURPOSES)},
                    "expectation": {"type": "string", "description": "проверяемый результат в конце"},
                    "weeks": {"type": "integer", "description": "реалистичная длительность в неделях при weekly_min"},
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

TASK = """<task>Роадмап проектов к цели человека. Проект — то, что он делает руками и что остаётся результатом:
код, сайт, ролики, исследование, мероприятие, выступление. Не курс и не «почитать».
- 3–6 проектов по порядку: первый — маленький, на 1–3 недели, чтобы был результат быстро; дальше сложнее, каждый
  опирается на навыки и результат предыдущего; последний прямо закрывает цель или её этап.
- Часы в неделю — из бюджета недели и других активных проектов в контексте; не обещай больше, чем есть.
- У каждого проекта 3–5 этапов, у каждого этапа — проверяемый критерий (ссылка, число, отзыв, оценка).
- Источники и инструменты — только настоящие (официальная документация, известные курсы, инструменты); не
  уверен в ссылке — оставь url пустым, название всё равно полезно. Ничего не выдумывай.
- Учитывай возраст, учёбу, нагрузку и то, что человек уже умеет, — из контекста и памяти.
- Существующие проекты этой цели — уже часть роадмапа: не повторяй их, продолжай с того места.</task>"""


def prompt(core: Any, goal: dict[str, Any]) -> str:
    chain = projects.roadmap_chain(core, goal["id"])
    have = "\n".join(f"- {p['title']} ({projects.STATUSES[p['status']]}): {p.get('expectation') or p.get('why', '')}" for p in chain) or "- нет"
    skills = sorted({s for p in core.state.projects.values() for s in p.get("skills") or []})
    return (f"ЦЕЛЬ: {goal['title']} (зачем: {goal.get('why') or '—'})" + (f", срок {goal['deadline']}" if goal.get("deadline") else "")
            + (f", метрика: {goal['metric']}" if goal.get("metric") else "")
            + f"\nУЖЕ ЕСТЬ В РОАДМАПЕ ЭТОЙ ЦЕЛИ:\n{have}"
            + (f"\nНАВЫКИ ИЗ ПРОШЛЫХ ПРОЕКТОВ: {', '.join(skills)}" if skills else "")
            + f"\n\nКонтекст:\n{build_context(core)}")


def apply(core: Any, goal: dict[str, Any], result: dict[str, Any], *, source: str = "l2") -> list[str]:
    """Ответ модели → проекты-идеи в журнал. Возвращает названия созданных."""
    existing = {p["title"].strip().lower() for p in core.state.projects.values() if p.get("goal_id") == goal["id"]}
    created: list[str] = []
    for item in (result.get("projects") or [])[:6]:
        title = str(item.get("title") or "").strip()
        if not title or title.lower() in existing:
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
        existing.add(title.lower())
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
    web = bool(core.cfg.section("brain").get("web_tools", True))
    result = brain.ask(system=system + "\n\n" + TASK, prompt=prompt(core, goal), schema=ROADMAP_SCHEMA, role="analyst",
                       vault_tools=bool(core.cfg.section("brain").get("vault_tools", True)), web=web)
    if not result:
        raise ArvixError("Голова сейчас недоступна — роадмап соберу позже. Проекты можно добавить и самому.")
    created = apply(core, goal, result)
    path = None
    if core.cfg.vault:
        try:
            folder = str(core.cfg.vault_paths.get("roadmaps") or "03_Resources/Роадмапы").strip("/")
            name = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", goal["title"][:60]).strip() or goal["id"]
            path = core.write_block(f"{folder}/Проекты — {name}.md", "проекты",
                                    note_md(core, goal, str(result.get("summary") or "")),
                                    create_with=f"# Проекты — {goal['title']}\n\n", source="l2")["path"]
        except ArvixError as exc:
            log.warning("заметка роадмапа не записана: %s", exc)
    return {"goal": goal, "summary": str(result.get("summary") or "")[:900], "created": created, "path": path}
