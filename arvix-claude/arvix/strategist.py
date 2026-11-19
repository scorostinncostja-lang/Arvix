"""Стратег (D52; 04-AI-LAYER §7): Арвикс сам решает, что нужно цели, — привычка, проект, задача, учёба.

Это совет (L2): один вызов головы в фоне, никто не ждёт ответа в чате (правило №2). Когда звать —
решает код (strategy.auto_candidate: цель в фокусе без системы или стоит, не чаще раза в неделю),
плюс явная просьба («собери план к ОГЭ» → action plan_goal) и кнопка в приложении.

Голова видит цель, её этапы, нынешнюю систему с минутами, распорядок по дням, бюджет недели, другие цели
фокуса и прошлые отказы человека — и выбирает минимальную систему. Ответ код чистит и пишет одним событием
goal_plan_set; раскладывает его тоже код (strategy.accept_item) — после «да» человека. Время для привычки
подбирает код по шаблону дня, а не модель.

Заменяет «Роадмап проектов» (project_roadmap.py, D44), который на каждую цель предлагал только проекты:
цели нужны не только проекты, а кнопка «предложить» у каждой из 17 целей превращала вкладку в стену.
"""

from __future__ import annotations

import logging
from typing import Any

from arvix import projects, strategy
from arvix.context import build_context, end_time
from arvix.core import ArvixError

log = logging.getLogger("arvix.strategist")

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string", "description": "почему цель сейчас не двигается или что ей мешает — честно, с цифрами из данных, до 400 символов"},
        "summary": {"type": "string", "description": "логика плана для человека: почему именно эти пункты, до 600 символов"},
        "items": {
            "type": "array", "description": "1–5 пунктов — минимальная система, которая двигает цель",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(strategy.ITEM_TYPES)},
                    "title": {"type": "string", "description": "коротко, что делать: «ОГЭ информатика: 2 задачи №…», «Английский: 15 слов Anki»"},
                    "why": {"type": "string", "description": "что пункт даёт цели"},
                    "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "habit: дни 0=пн … 6=вс"},
                    "start": {"type": "string", "description": "habit/task: желаемое ЧЧ:ММ; занято — код найдёт окно сам"},
                    "duration": {"type": "integer", "description": "habit: 10–120 мин; task: 10–180 мин"},
                    "sphere": {"type": "string", "description": "learning, sport, health, work, project, social"},
                    "deep_work": {"type": "boolean"},
                    "date": {"type": "string", "description": "task: ГГГГ-ММ-ДД"},
                    "expectation": {"type": "string", "description": "project: проверяемый результат"},
                    "weekly_min": {"type": "integer", "description": "project: минут в неделю"},
                    "weeks": {"type": "integer"},
                    "kind": {"type": "string", "description": "project: тип словом"},
                    "milestones": {"type": "array", "items": {"type": "object", "properties": {
                        "title": {"type": "string"}, "dod": {"type": "string"}}, "required": ["title", "dod"]}},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "learn: учебник и глава, документация, курс — настоящие"},
                    "block": {"type": "string", "description": "link_block: точное название существующего блока распорядка"},
                    "deadline": {"type": "string", "description": "fix_goal: срок цели ГГГГ-ММ-ДД"},
                    "metric": {"type": "string", "description": "fix_goal: как проверить достижение — число, оценка, результат"},
                },
                "required": ["type", "title", "why"],
            },
        },
    },
    "required": ["diagnosis", "summary", "items"],
}

TASK = """<task>Ты стратег. Цели не нужен список — ей нужна система, которая работает без силы воли.
Выбери МИНИМАЛЬНУЮ систему (1–5 пунктов), которая реально сдвинет эту цель в ближайшие 2–4 недели:
- habit — то, что должно повторяться (ежедневно или по дням): короткий блок, который встанет в распорядок и сам
  станет задачей с напоминанием. Для навыка, языка, экзамена, тела, сна. 15–60 минут, а не «2 часа каждый день».
- project — то, что строится и остаётся результатом (код, ролики, портфолио, исследование), с этапами и критерием.
- task — разовое дело со сроком: регистрация, документ, письмо, пробник, найти расписание олимпиад.
- learn — тема, которую надо выучить (тогда «Учить сейчас» поставит урок).
- link_block — существующий блок распорядка УЖЕ работает на цель: привяжи его (block — точное название из РАСПОРЯДКА),
  а не создавай второй такой же.
- fix_goal — у цели нет срока или метрики: предложи их (срок — дата, метрика — число, оценка, результат).
Правила:
- Время есть только то, что в РАСПОРЯДКЕ и БЮДЖЕТЕ. Сначала свободное время, потом новое: если неделя забита — меньше
  пунктов и короче блоки, честно скажи это в diagnosis.
- Не дублируй то, что в СИСТЕМЕ уже есть, и не предлагай снова то, что человек ОТКЛОНИЛ.
- Учитывай возраст, учёбу, сон, режим и другие цели фокуса: одна цель не должна съесть остальные.
- Источники — только настоящие (учебник с параграфом, официальная документация, известный курс); не уверен — без ссылки.
- Арвикс не делает работу за человека: пункты — то, что он делает сам.
- diagnosis — что на самом деле мешает цели сейчас, по данным, без утешений и без стыда.</task>"""


def _templates_text(core: Any) -> str:
    st = core.state
    if not st.templates:
        return "распорядка нет — привычки ставить некуда; предлагай задачи, проекты и учёбу"
    lines = []
    for weekday in range(7):
        template = st.templates.get(weekday)
        if not template:
            continue
        blocks = sorted(template.get("blocks", []), key=lambda b: b.get("start") or "99")
        lines.append(f"{strategy.WEEKDAYS_RU[weekday]}: " + "; ".join(
            f"{b['start']}–{end_time(b['start'], b.get('duration', 60))} {b['title']}" + (" [цель]" if any(str(t).startswith("goal:") for t in b.get("tags") or []) else "")
            for b in blocks if b.get("start")))
    return "\n".join(lines)


def prompt(core: Any, goal: dict[str, Any]) -> str:
    st = core.state
    eng = strategy.engine(core, goal)
    stages = [g for g in st.goals.values() if g.get("parent_id") == goal["id"] and g.get("status", "active") != "dropped"]
    system = []
    for h in eng["habits"]:
        system.append(f"привычка: {h['title']} — {strategy.weekdays_ru(h['weekdays'])} {h['start']}, {h['duration']} мин")
    for p in eng["projects"]:
        step = projects.next_step(core, p)
        system.append(f"проект ({projects.STATUSES[p['status']]}): {p['title']}" + (f" → {step['title']}" if step else ""))
    for x in eng["learn"]:
        system.append(f"учиться: {x['topic']}")
    for t in eng["upcoming"][:5]:
        system.append(f"задача: {t.local_date:%d.%m} {t.start or ''} {t.title}")
    rejected = [i for p in st.goal_plans.values() if p["goal_id"] in eng["ids"] for i in p["items"] if i["status"] == "rejected"]
    others, _ = strategy.focus(core)
    other_lines = [f"- {g['title']}: {strategy.STATUS_RU[strategy.status(core, g)]}" for g in others if g["id"] != goal["id"]]
    budget = core.budget()
    head = (f"ЦЕЛЬ: [{goal['id']}] {goal['title']} — {strategy.KIND_RU.get(goal.get('kind'), 'цель')}"
            f"\nЗАЧЕМ: {goal.get('why') or '—'}\nСРОК: {goal.get('deadline') or 'нет'} · МЕТРИКА: {goal.get('metric') or 'нет'}")
    if stages:
        head += "\nЭТАПЫ: " + "; ".join(f"{g['title']} ({'пройден' if g.get('status') == 'done' else 'до ' + str(g.get('deadline') or '—')})" for g in stages)
    head += (f"\nДВИЖЕНИЕ: неделя {strategy.hm(eng['week_min'])}, 4 недели {strategy.hm(eng['month_min'])}, "
             f"последнее {eng['last_move'] or 'не было'}; нужно по системе {strategy.hm(eng['need_week'])}/нед")
    head += "\nСИСТЕМА СЕЙЧАС:\n" + ("\n".join(f"- {x}" for x in system) or "- ничего")
    if rejected:
        head += "\nОТКЛОНИЛ РАНЬШЕ: " + "; ".join(strategy.item_line(i) for i in rejected[-6:])
    head += f"\nДРУГИЕ ЦЕЛИ ФОКУСА:\n" + ("\n".join(other_lines) or "- нет")
    head += f"\nБЮДЖЕТ НЕДЕЛИ: {strategy.hm(budget['week_min'])} своего времени, глубокая работа {strategy.hm(budget['deep_min'])}"
    head += f"\nРАСПОРЯДОК:\n{_templates_text(core)}"
    return head + f"\n\nКонтекст:\n{build_context(core)}"


def generate(core: Any, brain: Any, goal_id: str, *, system: str) -> dict[str, Any]:
    """Один вызов головы → план-предложение в журнале. Голова недоступна — ArvixError: учёт идёт дальше."""
    goal = core.state.goals.get(strategy.canonical(core, goal_id) or "")
    if goal is None or goal.get("status", "active") != "active":
        raise ArvixError(f"Активной цели {goal_id} нет")
    cfg = core.cfg.section("brain")
    result = brain.ask(system=system + "\n\n" + TASK, prompt=prompt(core, goal), schema=PLAN_SCHEMA, role="analyst",
                       vault_tools=bool(cfg.get("vault_tools", True)), web=bool(cfg.get("web_tools", True)))
    if not result:
        raise ArvixError("Голова сейчас недоступна — план соберу позже")
    plan_id = strategy.record_plan(core, goal["id"], result)
    return {"goal": goal, "plan": core.state.goal_plans[plan_id]}


def message(core: Any, plan: dict[str, Any]) -> str:
    """План для Telegram: диагноз, пункты, что будет по кнопке."""
    goal = core.state.goals.get(plan["goal_id"]) or {"title": "цель"}
    lines = [f"🧭 **{goal['title']}**"]
    if plan.get("diagnosis"):
        lines += ["", plan["diagnosis"]]
    lines += ["", "Предлагаю:"] + [f"{n}. {strategy.item_line(i)}" for n, i in enumerate(plan["items"], 1)]
    if plan.get("summary"):
        lines += ["", plan["summary"]]
    lines += ["", "«Принять» — привычки встанут в распорядок (время подберу по свободным окнам), задачи — в план, "
                  "темы — в «Учиться». По одному пункту — в приложении, вкладка «Цели»."]
    return "\n".join(lines)
