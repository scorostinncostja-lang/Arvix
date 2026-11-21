"""Повторения тем по интервалам (06-LEARNING §5, D60).

Карточки фактов (формулы, слова, даты) — по-прежнему Anki с FSRS: свою колоду Arvix не строит. Но навык
«решить №20» в карточку не ложится: ответ на карточке запоминается, а метод — нет. Поэтому Arvix повторяет
темы: через 1, 3, 7, 16 и 35 дней после сессии тема возвращается двумя короткими задачами с новыми числами,
вперемешку с другими темами (интерливинг). Это эффект тестирования и распределённого повторения — самые
надёжные результаты когнитивной психологии — в той форме, которая подходит задачам.

Расписание считает код (правило №1): ≥ 80 % — интервал растёт, 50–79 % — тот же, < 50 % — завтра снова.
Пять пройденных интервалов — тема закреплена. Задачи пишет голова (новые числа, один вопрос — на пробел),
голова молчит — задачи берутся из банка сессии (похожие задачи, которых человек не видел). Проверяет код.
Просрочка не копится в долг и не считается (D41, фильтр №4): ждущие темы просто стоят первыми.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from arvix import study
from arvix.core import ArvixError, new_id

INTERVALS = (1, 3, 7, 16, 35)  # дней до следующего повторения на шаге 0…4
PER_QUIZ = 3   # тем в одном повторении: 5–8 минут, а не час
PER_TOPIC = 2  # задач на тему

_ITEM = {**study.QUESTION_SCHEMA["properties"], "review": {"type": "string", "description": "id темы из списка"}}
_ITEM.pop("twin")
_ITEM.pop("a")
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": _ITEM, "required": ["review", "q"]}}},
    "required": ["items"],
}

REVIEW_RULES = """<review>
Повторение по интервалам: человек вспоминает темы, которые уже учил. Темы (id, предмет, пробелы, прошлые результаты):
{topics}
Дай по {per} задачи на каждую тему — в поле review её id. Формат экзамена: short (число или слово, другие записи —
в accept) или options + answer. Открытых вопросов нет: проверяет код. Числа и условия новые, не как в уроке: он
должен вспомнить метод, а не ответ. Если у темы есть пробел — одна из задач на него. why — решение в 1–2 строки.
Проверь каждый ответ сам: ошибка эталона станет ложной ошибкой человека. Всё по-русски.
</review>"""


def _review_of(core: Any, task: Any, subject: str, topic: str) -> dict[str, Any] | None:
    from arvix.project_roadmap import similar

    learn_id = next((t[6:] for t in getattr(task, "tags", ()) or () if t.startswith("learn:")), None)
    for r in core.state.reviews.values():
        if r.get("status") != "active":
            continue
        if (learn_id and r.get("learn_id") == learn_id) or task.id in (r.get("tasks") or []):
            return r
        if r.get("subject", "").lower() == subject.lower() and similar(r.get("topic", ""), topic):
            return r
    return None


def after_lesson(core: Any, task: Any, *, topic: str, subject: str, score: int | None, gaps: list[str],
                 source: str = "telegram") -> dict[str, Any]:
    """Сессия закрыта проверкой — тема встаёт в повторения: завтра, а если тема уже повторялась и проверка
    сдана на ≥ 80 % — по своему интервалу. Та же тема второй раз — та же строка, пробелы копятся."""
    item = study.learn_item_of(core, task)
    topic = (item["topic"] if item else topic or task.title)[:160]
    old = _review_of(core, task, subject, topic)
    step = int(old.get("step") or 0) if old and score is not None and score >= 80 else 0
    today = core.today()
    review = {
        "id": old["id"] if old else new_id(), "topic": old["topic"] if old else topic, "subject": subject[:80],
        "learn_id": (old or {}).get("learn_id") or (item["id"] if item else None),
        "tasks": [*[t for t in (old or {}).get("tasks") or [] if t != task.id], task.id][-6:],
        "gaps": list(dict.fromkeys([*gaps, *((old or {}).get("gaps") or [])]))[:8],
        "step": step, "due": (today + timedelta(days=INTERVALS[step])).isoformat(), "status": "active",
        "history": [*((old or {}).get("history") or []), {"date": today.isoformat(), "pct": score, "kind": "session"}][-12:],
    }
    with core.tx():
        core.emit("review_set", review, source=source, entity_id=review["id"])
    return review


def schedule(review: dict[str, Any], pct: int, today: date) -> dict[str, Any]:
    """≥ 80 % — следующий интервал; 50–79 — тот же ещё раз; < 50 — с начала, завтра. После последнего — закреплено."""
    step = int(review.get("step") or 0)
    if pct >= 80:
        step += 1
    elif pct < 50:
        step = 0
    out = {**review, "step": min(step, len(INTERVALS)),
           "history": [*(review.get("history") or []), {"date": today.isoformat(), "pct": pct, "kind": "review"}][-12:]}
    if step >= len(INTERVALS):
        out.update(status="done", due=None)
    else:
        out.update(status="active", due=(today + timedelta(days=INTERVALS[step])).isoformat())
    return out


def due(core: Any, day: date | None = None) -> list[dict[str, Any]]:
    """Темы, которым пора: срок сегодня или раньше; самые давние — первыми."""
    day = day or core.today()
    rows = [r for r in core.state.reviews.values() if r.get("status") == "active" and r.get("due") and r["due"] <= day.isoformat()]
    return sorted(rows, key=lambda r: (r["due"], r.get("topic", "")))


def upcoming(core: Any, limit: int = 8) -> list[dict[str, Any]]:
    today = core.today().isoformat()
    rows = [r for r in core.state.reviews.values() if r.get("status") == "active" and r.get("due") and r["due"] > today]
    return sorted(rows, key=lambda r: r["due"])[:limit]


def drop(core: Any, review_id: str, *, source: str = "web") -> dict[str, Any]:
    review = core.state.reviews.get(review_id)
    if review is None:
        raise ArvixError("Такой темы в повторениях нет")
    with core.tx():
        core.emit("review_set", {**review, "status": "dropped"}, source=source, entity_id=review_id)
    return core.state.reviews[review_id]


# --- задачи повторения -----------------------------------------------------------------------------

def bank(core: Any, review: dict[str, Any], n: int = PER_TOPIC) -> list[dict[str, Any]]:
    """Задачи из сессий темы, когда голова молчит: сначала похожие, которых человек не видел, потом
    нерешённые, потом те, где ошибся. Открытых нет — повторение проверяет код."""
    ranked: list[tuple[int, dict[str, Any]]] = []
    for task_id in review.get("tasks") or []:
        session = study.session_of(core, task_id)
        for p in study.visible(session):
            if p["type"] != "quiz":
                continue
            ans = (session.get("answers") or {}).get(p["id"])
            for i, q in enumerate(p["questions"]):
                ok = ans["results"][i] if ans and i < len(ans["results"]) else None
                fix = (session.get("fixes") or {}).get(f"{p['id']}:{i}") or {}
                if (twin := q.get("twin")) and fix.get("twin_given") is None:
                    ranked.append((0, {**twin, "skill": q.get("skill")}))
                if "a" in q:
                    continue
                ranked.append((1 if ans is None else 2 if ok is False else 3, {k: v for k, v in q.items() if k != "twin"}))
    ranked.sort(key=lambda x: x[0])
    out, seen = [], set()
    for _, q in ranked:
        if q["q"] not in seen:
            seen.add(q["q"])
            out.append(q)
        if len(out) >= n:
            break
    return out


def topics_block(core: Any, reviews: list[dict[str, Any]]) -> str:
    rows = []
    for r in reviews:
        past = ", ".join(f"{h['date'][8:10]}.{h['date'][5:7]} {h['pct']}%" for h in (r.get("history") or [])[-3:] if h.get("pct") is not None)
        rows.append(f"[{r['id']}] {r['topic']} ({r.get('subject') or '—'})" + (f" · пробелы: {'; '.join(r['gaps'][:4])}" if r.get("gaps") else "")
                    + (f" · было: {past}" if past else ""))
    return "\n".join(rows)


def build(core: Any, reviews: list[dict[str, Any]], head_items: list[Any] | None, *, source: str = "web") -> dict[str, Any]:
    """Тест повторения: задачи головы по темам (кривые — отброшены), недостающее — из банка сессии;
    темы вперемешку (интерливинг). Пусто — ArvixError: не из чего собрать."""
    per: dict[str, list[dict[str, Any]]] = {r["id"]: [] for r in reviews}
    for raw in head_items or []:
        rid = str((raw or {}).get("review") or "") if isinstance(raw, dict) else ""
        if rid in per and len(per[rid]) < PER_TOPIC and (q := study._question(raw)) and "a" not in q:
            q.pop("twin", None)
            per[rid].append(q)
    by_head = sum(len(v) for v in per.values())
    for r in reviews:
        if len(per[r["id"]]) < PER_TOPIC:
            have = {q["q"] for q in per[r["id"]]}
            per[r["id"]] += [q for q in bank(core, r, PER_TOPIC + 2) if q["q"] not in have][:PER_TOPIC - len(per[r["id"]])]
    items = []
    for i in range(PER_TOPIC):  # по кругу: тема А, тема Б, тема В, снова А…
        for r in reviews:
            if i < len(per[r["id"]]):
                items.append({**per[r["id"]][i], "review": r["id"]})
    if not items:
        raise ArvixError("Не из чего собрать повторение: голова недоступна, а в сессиях темы нет задач")
    quiz = {"id": new_id(), "reviews": [r["id"] for r in reviews], "items": items, "by": "head" if by_head else "bank"}
    with core.tx():
        core.emit("review_quiz", quiz, source=source)
    return quiz


def current(core: Any) -> dict[str, Any] | None:
    """Сегодняшний тест повторения без ответа — его и показываем, второй раз голову не зовём."""
    quiz = core.state.review_quiz
    if quiz and quiz.get("date") == core.today().isoformat():
        return quiz
    return None


def answer(core: Any, answers: list[Any], *, source: str = "web") -> dict[str, Any]:
    quiz = current(core)
    if quiz is None:
        raise ArvixError("Повторения сейчас нет — начни его заново")
    if quiz.get("answer"):
        raise ArvixError("На это повторение уже ответил")
    clean, results = [], []
    for i, q in enumerate(quiz["items"]):
        given = answers[i] if i < len(answers) else None
        if given == study.UNKNOWN:
            clean.append(study.UNKNOWN)
            results.append(False)
        elif "options" in q:
            ok = isinstance(given, int) and not isinstance(given, bool) and 0 <= given < len(q["options"])
            clean.append(given if ok else None)
            results.append(ok and given == q["answer"])
        else:
            clean.append(str(given or "").strip()[:120])
            results.append(study.match_short(clean[-1], q))
    by_review: dict[str, int] = {}
    for rid in quiz["reviews"]:
        mine = [ok for q, ok in zip(quiz["items"], results) if q["review"] == rid]
        if mine:
            by_review[rid] = round(100 * sum(mine) / len(mine))
    today = core.today()
    with core.tx():
        core.emit("review_answer", {"quiz_id": quiz["id"], "answers": clean, "results": results, "by_review": by_review}, source=source)
        for rid, pct in by_review.items():
            if (review := core.state.reviews.get(rid)) and review.get("status") == "active":
                core.emit("review_set", schedule(review, pct, today), source=source, entity_id=rid)
    return {"results": results, "by_review": by_review}


def public(core: Any) -> dict[str, Any]:
    """Повторения для приложения: что ждёт сегодня, что дальше, сегодняшний тест (эталоны — после ответа)."""
    quiz = current(core)
    out: dict[str, Any] = {"due": [_row(r) for r in due(core)], "upcoming": [_row(r) for r in upcoming(core)],
                           "done": sum(1 for r in core.state.reviews.values() if r.get("status") == "done"),
                           "per_quiz": PER_QUIZ, "quiz": None}
    if quiz:
        ans = quiz.get("answer")
        items = []
        for i, q in enumerate(quiz["items"]):
            item = {"q": q["q"], "options": q.get("options"), "short": "short" in q, "review": q["review"],
                    "topic": (core.state.reviews.get(q["review"]) or {}).get("topic", "")}
            if ans:
                given = ans["answers"][i] if i < len(ans["answers"]) else None
                item.update(ok=ans["results"][i], given_text=study._given_text(q, given), right=study.right_text(q), why=q.get("why", ""),
                            answer=q.get("answer"), given=given)
            items.append(item)
        out["quiz"] = {"id": quiz["id"], "items": items, "done": bool(ans),
                       "by_review": [{**_row(core.state.reviews[rid]), "pct": pct} for rid, pct in ((ans or {}).get("by_review") or {}).items()
                                     if rid in core.state.reviews]}
    return out


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "topic": r.get("topic", ""), "subject": r.get("subject", ""), "due": r.get("due"), "step": int(r.get("step") or 0),
            "steps": len(INTERVALS), "status": r.get("status"), "gaps": (r.get("gaps") or [])[:4]}


def minutes(n_topics: int) -> int:
    return max(3, round(n_topics * PER_TOPIC * 1.5))


def brief_line(core: Any) -> str:
    rows = due(core)
    if not rows:
        return ""
    names = " · ".join(r["topic"][:40] for r in rows[:PER_QUIZ])
    more = f" и ещё {len(rows) - PER_QUIZ}" if len(rows) > PER_QUIZ else ""
    return f"🔁 Повторить: {names}{more} — ≈{minutes(min(len(rows), PER_QUIZ))} мин в «Обучении»."


def context_line(core: Any) -> str:
    rows = due(core)
    nxt = upcoming(core, 3)
    if not rows and not nxt:
        return ""
    parts = []
    if rows:
        parts.append("пора сегодня: " + "; ".join(f"{r['topic'][:60]} (шаг {int(r.get('step') or 0) + 1}/{len(INTERVALS)})" for r in rows[:4]))
    if nxt:
        parts.append("дальше: " + "; ".join(f"{r['topic'][:40]} {r['due'][8:10]}.{r['due'][5:7]}" for r in nxt))
    return "ПОВТОРЕНИЯ ТЕМ: " + " · ".join(parts) + " — в разделе «Обучение», 5–8 мин."
