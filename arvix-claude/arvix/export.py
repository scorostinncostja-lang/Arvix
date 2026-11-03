"""Полный экспорт в Obsidian (03-DATA-MODEL §4, 00-VISION П6): Markdown + JSONL.

Это и бэкап, и второй мозг, и гарантия, что данные не заперты в чужой базе.
Пишется только в Arvix/ внутри хранилища.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from arvix import interview
from arvix.context import STATUS_ICON, hm
from arvix.vault import Vault


def export_all(core: Any, days: int = 60) -> list[str]:
    if not core.cfg.vault:
        raise ValueError("Путь к хранилищу не задан: `arvix setup` или vault в config.toml")
    vault = Vault(core.cfg.vault, core.cfg.arvix_folder)
    st = core.state
    written = [vault.write("Profile.md", render_profile(core)), vault.write("Insights.md", render_insights(core))]
    today = core.today()
    for offset in range(days, -1, -1):
        d = today - timedelta(days=offset)
        if st.tasks_on(d) or (d in st.days and (st.days[d].closed or st.days[d].sleep_min)):
            written.append(vault.write(f"Daily/{d.isoformat()}.md", render_day(core, d)))
    lines = []
    for ev in core.store.read(0):
        lines.append(json.dumps({"id": ev.id, "at": ev.at.isoformat(), "date": ev.local_date.isoformat(), "kind": ev.kind,
                                 "entity_id": ev.entity_id, "payload": ev.payload, "source": ev.source}, ensure_ascii=False))
    written.append(vault.write("_raw/events.md", "```jsonl\n" + "\n".join(lines) + "\n```\n"))
    return written


def render_profile(core: Any) -> str:
    st = core.state
    out = ["---", "type: arvix-profile", f"updated: {core.today().isoformat()}", "---", "# Профиль", ""]
    for key, value in sorted(st.profile.items()):
        out.append(f"- **{key}**: {value}")
    if st.goals:
        out += ["", "## Цели"]
        for goal in st.goals.values():
            out.append(f"- [{goal.get('kind')}] {goal['title']} — зачем: {goal.get('why', '—')}" + (f" (до {goal['deadline']})" if goal.get("deadline") else ""))
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
    return "\n".join(out) + "\n"


def render_day(core: Any, d: date) -> str:
    st = core.state
    day = st.days.get(d)
    closed = (day.closed if day else None) or {}
    tasks = st.tasks_on(d)
    done = sum(1 for t in tasks if t.status == "done")
    front = {
        "date": d.isoformat(), "type": "arvix-daily", "done": done, "total": len(tasks),
        "completion": closed.get("completion", st.completion(d)), "deep_min": day.deep_min if day else 0,
        "sleep_min": day.sleep_min if day else None, "xp": day.xp if day else 0, "hp_end": closed.get("hp_end"),
    }
    out = ["---"] + [f"{k}: {'' if v is None else v}" for k, v in front.items()] + ["---", f"# {d:%d.%m.%Y}", ""]
    out.append(f"Сделано {done} из {len(tasks)} · глубокая {hm(front['deep_min'])} · сон {hm(front['sleep_min'])}")
    if tasks:
        out += ["", "## Задачи"]
        for t in tasks:
            line = f"- {STATUS_ICON.get(t.status, '?')} {t.start or '--:--'} {t.title} ({t.duration_min}м, imp{t.importance})"
            if t.report:
                line += f" — {t.report}"
            if t.reason and t.status in ("failed", "debt", "written_off"):
                line += f" — причина: {t.reason}"
            out.append(line)
    debriefs = [ev.payload for ev in core.store.read(0) if ev.kind == "debrief_completed" and ev.payload.get("date") == d.isoformat()]
    if debriefs:
        out += ["", "## Разбор"]
        for item in debriefs:
            out.append(item.get("answers", ""))
            if item.get("conclusion"):
                out += ["", f"**Вывод:** {item['conclusion']}"]
    return "\n".join(out) + "\n"


def render_insights(core: Any) -> str:
    st = core.state
    out = ["---", "type: arvix-insights", "---", "# Выводы Арвикса", ""]
    for item in reversed(st.insights):
        out.append(f"- {item['date']}: {item['text']} (события: {', '.join('#' + str(e) for e in item.get('evidence', []))})")
    if st.directives:
        out += ["", "## Директивы"]
        for item in sorted(st.directives.values(), key=lambda x: x.get("date", ""), reverse=True):
            out.append(f"- {item['date']} [{item['kind']}/p{item['priority']}] {item['text']} (до {item.get('valid_until')})")
    return "\n".join(out) + "\n"
