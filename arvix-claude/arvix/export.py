"""Полный экспорт в Obsidian (03-DATA-MODEL §4, 00-VISION П6).

Пишет в структуру хранилища по [vault_paths], только в свои блоки
<!-- arvix:… -->: профиль, выводы, журнал событий и итоги дней в ежедневных
отчётах. Всё, что человек допишет вне блоков, переживёт любой повторный экспорт.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from arvix import daily_note, interview


def export_all(core: Any, days: int = 60) -> list[str]:
    vault = core.vault
    written = [
        core.write_block(vault.place("profile"), "profile", render_profile(core),
                         create_with="# Профиль Арвикса\n\nСвои заметки пиши вне блока — Арвикс их не трогает.\n")["path"],
        core.write_block(vault.place("system", "Выводы"), "insights", render_insights(core), create_with="# Выводы Арвикса\n")["path"],
    ]
    today = core.today()
    for offset in range(days, -1, -1):
        d = today - timedelta(days=offset)
        if vault.daily_note(d) and (rel := daily_note.sync(core, d, create=False)):
            written.append(rel)
    lines = [json.dumps({"id": ev.id, "at": ev.at.isoformat(), "date": ev.local_date.isoformat(), "kind": ev.kind,
                         "entity_id": ev.entity_id, "payload": ev.payload, "source": ev.source}, ensure_ascii=False)
             for ev in core.store.read(0)]
    written.append(core.write_block(vault.place("system", "Журнал событий"), "events", "```jsonl\n" + "\n".join(lines) + "\n```",
                                    create_with="# Журнал событий Арвикса\n\nПолная история, по строке на событие.\n")["path"])
    return written


def render_profile(core: Any) -> str:
    st = core.state
    out = [f"Обновлено: {core.today():%d.%m.%Y}", ""]
    for key, value in sorted(st.profile.items()):
        out.append(f"- **{key}**: {value}")
    tree = core.goal_tree()
    if tree:
        out += ["", "## Цели"]
        for depth, goal in tree:
            mark = {"done": "x", "dropped": "-"}.get(goal.get("status", ""), " ")
            out.append("  " * depth + f"- [{mark}] {goal['title']}" + (f" — зачем: {goal['why']}" if goal.get("why") and not depth else "")
                       + (f" (до {goal['deadline']})" if goal.get("deadline") else ""))
    if st.traits:
        out += ["", "## Черты, привычки, страхи"]
        for trait in st.traits.values():
            out.append(f"- [{trait['kind']}] {trait['title']}" + (f" → {trait['counter_strategy']}" if trait.get("counter_strategy") else ""))
    if st.facts:
        out += ["", "## Память"]
        out += [f"- ({f['topic']}) {f['fact']}" for f in st.facts.values()]
    if st.interview:
        out += ["", "## Интервью"]
        for block, title in interview.BLOCKS:
            answered = [q for q in interview.QUESTIONS if q["block"] == block and q["id"] in st.interview]
            if answered:
                out += ["", f"### {title}"]
                for q in answered:
                    out += [f"**{q['text']}**", st.interview[q["id"]], ""]
    return "\n".join(out)


def render_insights(core: Any) -> str:
    st = core.state
    out = []
    for item in reversed(st.insights):
        out.append(f"- {item['date']}: {item['text']} (события: {', '.join('#' + str(e) for e in item.get('evidence', []))})")
    if st.directives:
        out += ["", "## Директивы"]
        for item in sorted(st.directives.values(), key=lambda x: x.get("date", ""), reverse=True):
            out.append(f"- {item['date']} [{item['kind']}/p{item['priority']}] {item['text']} (до {item.get('valid_until')})")
    return "\n".join(out) or "Пока пусто."
