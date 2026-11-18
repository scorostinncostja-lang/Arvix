"""Состояние — свёртка журнала событий (03-DATA-MODEL §1).

State.apply(event) — инкремент, State.rebuild(events) — полный пересчёт.
Инвариант «rebuild() == накопленный apply()» проверяется тестом. Поля State
снаружи не меняются: только новым событием через Core.emit().

Игры нет (D41): XP, уровней, HP, щитов, Протокола Ноль, сезонов и серии больше не
считаем. Их старые события (xp_awarded, hp_changed, shield_used, protocol_zero)
остаются в журнале — он только дополняется, — но в свёртку не входят.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from arvix import rules
from arvix.store import Event

# Источники, которые означают «человек что-то сделал сам» (для протокола игнора).
USER_SOURCES = frozenset({"telegram", "claude", "cli", "user"})


@dataclass
class Task:
    id: str
    title: str
    sphere: str
    importance: int
    difficulty: int
    local_date: date
    start: str | None  # "HH:MM" по местному времени
    duration_min: int
    deep_work: bool
    proof: str
    source: str
    tags: tuple[str, ...] = ()
    status: str = "planned"  # planned | active | done | failed | debt | cancelled | written_off
    actual_start: str | None = None
    done_pct: int = 0
    report: str | None = None
    debt_since: date | None = None
    reason: str | None = None
    focus_min: int = 0  # фокус-сессии по этой задаче (таймер): при закрытии — глубокие минуты и подтверждение «таймер»

    @property
    def is_open(self) -> bool:
        return self.status in ("planned", "active")


@dataclass
class Day:
    date: date
    sleep_min: int | None = None
    bedtime: str | None = None
    deep_min: int = 0
    debrief: bool = False
    user_actions: int = 0
    msgs_out: int = 0
    out_keys: set[str] = field(default_factory=set)
    silent: bool = False
    reason: str | None = None
    materialized: bool = False
    day_type: str | None = None
    social: int = 0
    expenses: float = 0.0
    closed: dict[str, Any] | None = None
    focus: list[dict[str, Any]] = field(default_factory=list)  # сессии таймера: минуты, задача или тема, заметка


@dataclass
class State:
    profile: dict[str, Any] = field(default_factory=dict)
    goals: dict[str, dict[str, Any]] = field(default_factory=dict)
    traits: dict[str, dict[str, Any]] = field(default_factory=dict)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    directives: dict[str, dict[str, Any]] = field(default_factory=dict)
    insights: list[dict[str, Any]] = field(default_factory=list)
    templates: dict[int, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    days: dict[date, Day] = field(default_factory=dict)
    interview: dict[str, str] = field(default_factory=dict)
    interview_skipped: set[str] = field(default_factory=set)
    mode: str = "normal"
    mode_trigger: str = ""
    mentor_enabled: bool = True
    sos_until: str | None = None
    recovery_until: str | None = None  # «Вернуться к плану» после 🟥: до этого момента режим не выше 🟨 (D38)
    expenses: list[dict[str, Any]] = field(default_factory=list)
    learning: list[dict[str, Any]] = field(default_factory=list)
    lessons: list[dict[str, Any]] = field(default_factory=list)  # учебные блоки: тема, задача, оценка проверки
    safety: list[dict[str, Any]] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # заметки Арвикса: путь → хэш последней записи
    budget: dict[str, Any] = field(default_factory=dict)
    last_user_at: str | None = None
    last_event_id: int = 0
    first_date: date | None = None

    # --- свёртка ---------------------------------------------------------

    @classmethod
    def rebuild(cls, events: list[Event]) -> State:
        state = cls()
        for event in events:
            state.apply(event)
        return state

    def day(self, d: date) -> Day:
        if d not in self.days:
            self.days[d] = Day(d)
        return self.days[d]

    def apply(self, ev: Event) -> None:
        self.last_event_id = ev.id
        if self.first_date is None or ev.local_date < self.first_date:
            self.first_date = ev.local_date
        day = self.day(ev.local_date)
        if ev.source in USER_SOURCES:
            day.user_actions += 1
            self.last_user_at = ev.at.isoformat()
        handler = getattr(self, f"_on_{ev.kind}", None)
        if handler is not None:
            handler(ev, ev.payload, day)

    def _task(self, p: dict[str, Any]) -> Task | None:
        return self.tasks.get(p.get("id", ""))

    def _on_profile_set(self, ev: Event, p: dict, day: Day) -> None:
        self.profile[p["key"]] = p["value"]

    def _on_interview_answer(self, ev: Event, p: dict, day: Day) -> None:
        self.interview[p["qid"]] = p["answer"]
        self.interview_skipped.discard(p["qid"])

    def _on_interview_reset(self, ev: Event, p: dict, day: Day) -> None:
        self.interview.pop(p["qid"], None)
        self.interview_skipped.discard(p["qid"])

    def _on_interview_skipped(self, ev: Event, p: dict, day: Day) -> None:
        self.interview_skipped.add(p["qid"])

    def _on_goal_set(self, ev: Event, p: dict, day: Day) -> None:
        self.goals[p["id"]] = dict(p)

    def _on_trait_set(self, ev: Event, p: dict, day: Day) -> None:
        self.traits[p["id"]] = dict(p)

    def _on_fact_remembered(self, ev: Event, p: dict, day: Day) -> None:
        self.facts[p["id"]] = {**p, "event_id": ev.id, "date": ev.local_date.isoformat()}

    def _on_fact_retracted(self, ev: Event, p: dict, day: Day) -> None:
        self.facts.pop(p["id"], None)

    def _on_template_set(self, ev: Event, p: dict, day: Day) -> None:
        for weekday in p["weekdays"]:
            self.templates[int(weekday)] = {"day_type": p["day_type"], "blocks": list(p["blocks"])}

    def _on_day_materialized(self, ev: Event, p: dict, day: Day) -> None:
        target = self.day(date.fromisoformat(p["date"]))
        target.materialized = True
        target.day_type = p.get("day_type")

    def _on_task_created(self, ev: Event, p: dict, day: Day) -> None:
        self.tasks[p["id"]] = Task(
            id=p["id"],
            title=p["title"],
            sphere=p["sphere"],
            importance=int(p["importance"]),
            difficulty=int(p["difficulty"]),
            local_date=date.fromisoformat(p["date"]),
            start=p.get("start"),
            duration_min=int(p.get("duration_min") or 0),
            deep_work=bool(p.get("deep_work")),
            proof=p["proof"],
            source=p.get("source") or ev.source,
            tags=tuple(p.get("tags") or ()),
        )

    def _on_task_started(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.status = "active"
            task.actual_start = p.get("at") or ev.at.isoformat()

    def _on_task_completed(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.status = "done"
            task.done_pct = int(p.get("done_pct", 100))
            task.report = p.get("report")
            self.day(task.local_date).deep_min += int(p.get("deep_min", 0))

    def _on_task_failed(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.reason = p.get("reason")
            if p.get("debt"):
                task.status = "debt"
                task.debt_since = ev.local_date
            else:
                task.status = "failed"

    def _on_task_reason(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.reason = p.get("reason")

    def _on_task_deferred(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.start = p.get("to")
            if p.get("date"):
                task.local_date = date.fromisoformat(p["date"])

    def _on_task_cancelled(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.status = "cancelled"
            task.reason = p.get("reason")

    def _on_debt_written_off(self, ev: Event, p: dict, day: Day) -> None:
        if task := self._task(p):
            task.status = "written_off"
            task.reason = p.get("justification")

    def _on_reason_declared(self, ev: Event, p: dict, day: Day) -> None:
        day.reason = p["reason"]

    def _on_mode_changed(self, ev: Event, p: dict, day: Day) -> None:
        self.mode = p["to"]
        self.mode_trigger = p.get("trigger", "")

    def _on_sleep_recorded(self, ev: Event, p: dict, day: Day) -> None:
        target = self.day(date.fromisoformat(p["date"])) if p.get("date") else day
        target.sleep_min = int(p["duration_min"])
        target.bedtime = p.get("bedtime") or target.bedtime

    def _on_focus_session(self, ev: Event, p: dict, day: Day) -> None:
        # Сессия по задаче копится в самой задаче (глубокая работа придёт с её закрытием);
        # сессия без задачи — сразу глубокая работа дня.
        task = self.tasks.get(p.get("task_id") or "")
        if task is not None:
            task.focus_min += int(p.get("duration_min", 0))
        else:
            day.deep_min += int(p.get("duration_min", 0))
        day.focus.append({"event_id": ev.id, "at": ev.at.isoformat(), "minutes": int(p.get("duration_min", 0)),
                          "task_id": task.id if task else None, "topic": p.get("topic"), "note": None})

    def _on_focus_noted(self, ev: Event, p: dict, day: Day) -> None:
        # Заметка «что сделал» приходит после сессии отдельным событием: журнал не правится.
        for d in (day, self.days.get(date.fromisoformat(p["date"])) if p.get("date") else None):
            for session in (d.focus if d else []):
                if session["event_id"] == p.get("focus_event_id"):
                    session["note"] = p.get("note")
                    return

    def _on_expense_logged(self, ev: Event, p: dict, day: Day) -> None:
        self.expenses.append({**p, "date": ev.local_date.isoformat(), "event_id": ev.id})
        day.expenses += float(p["amount"])

    def _on_social_contact(self, ev: Event, p: dict, day: Day) -> None:
        day.social += 1

    def _on_directive_created(self, ev: Event, p: dict, day: Day) -> None:
        self.directives[p["id"]] = {**p, "date": ev.local_date.isoformat()}

    def _on_insight(self, ev: Event, p: dict, day: Day) -> None:
        self.insights.append({**p, "date": ev.local_date.isoformat(), "event_id": ev.id})

    def _on_debrief_completed(self, ev: Event, p: dict, day: Day) -> None:
        self.day(date.fromisoformat(p["date"]) if p.get("date") else ev.local_date).debrief = True

    def _on_silent_day(self, ev: Event, p: dict, day: Day) -> None:
        self.day(date.fromisoformat(p["date"])).silent = True

    def _on_message_out(self, ev: Event, p: dict, day: Day) -> None:
        day.msgs_out += 1
        if p.get("key"):
            day.out_keys.add(p["key"])

    def _on_learning_question(self, ev: Event, p: dict, day: Day) -> None:
        self.learning.append({**p, "date": ev.local_date.isoformat()})

    def _on_lesson_started(self, ev: Event, p: dict, day: Day) -> None:
        self.lessons.append({"task_id": p.get("task_id"), "topic": p.get("topic", ""), "subject": p.get("subject", ""),
                             "date": ev.local_date.isoformat(), "score": None})

    def _on_lesson_checked(self, ev: Event, p: dict, day: Day) -> None:
        for lesson in reversed(self.lessons):
            if lesson["task_id"] == p.get("task_id") and lesson["score"] is None:
                lesson["score"] = p.get("score_pct")
                lesson["gaps"] = list(p.get("gaps") or [])
                break

    def _on_safety_flag(self, ev: Event, p: dict, day: Day) -> None:
        if p.get("level") not in rules.SAFETY_ALARM_LEVELS:
            return  # старые флаги «info» до разделения уровней — не беда
        self.mentor_enabled = False
        self.safety.append({**p, "date": ev.local_date.isoformat()})

    def _on_mentor_toggled(self, ev: Event, p: dict, day: Day) -> None:
        self.mentor_enabled = bool(p["enabled"])

    def _on_sos(self, ev: Event, p: dict, day: Day) -> None:
        self.sos_until = p.get("until") if p.get("on") else None
        if p.get("on"):
            self.recovery_until = None  # новый SOS отменяет возвращение: человек снова просит отдых

    def _on_recovery_started(self, ev: Event, p: dict, day: Day) -> None:
        self.recovery_until = p.get("until")

    def _on_note_written(self, ev: Event, p: dict, day: Day) -> None:
        if p.get("owned"):
            self.notes[p["path"]] = p["sha"]
        else:
            self.notes.pop(p["path"], None)

    def _on_budget_set(self, ev: Event, p: dict, day: Day) -> None:
        self.budget = {**p, "since": ev.local_date.isoformat()}

    def _on_day_closed(self, ev: Event, p: dict, day: Day) -> None:
        self.day(date.fromisoformat(p["date"])).closed = dict(p)

    # --- производные величины ---------------------------------------------

    def tasks_on(self, d: date) -> list[Task]:
        tasks = [t for t in self.tasks.values() if t.local_date == d and t.status != "cancelled"]
        return sorted(tasks, key=lambda t: (t.start or "99:99", t.title))

    def debts(self) -> list[Task]:
        return sorted((t for t in self.tasks.values() if t.status == "debt"), key=lambda t: t.debt_since or date.max)

    def completion(self, d: date) -> float | None:
        """% выполнения дня: частичное выполнение засчитывается долей."""
        tasks = self.tasks_on(d)
        if not tasks:
            return None
        done = sum(t.done_pct / 100 for t in tasks if t.status == "done")
        return round(done / len(tasks) * 100, 1)

    def series(self, until: date, n: int, attr: str) -> list[Any]:
        out = []
        for i in range(n - 1, -1, -1):
            d = until - timedelta(days=i)
            if attr == "completion":
                closed = self.days.get(d) and self.days[d].closed
                out.append(closed.get("completion") if closed else self.completion(d))
            else:
                out.append(getattr(self.days.get(d), attr, None) if d in self.days else None)
        return out

    def ignore_streak(self, until: date) -> int:
        """Сколько дней (до until включительно) бот писал, а человек молчал.

        Серию рвёт только действие человека. Дни, когда бот ничего не отправлял
        (ноутбук спал, недельная пауза протокола игнора), её не рвут и не удлиняют:
        иначе после восьми дней тишины протокол начинался бы заново с «обычного дня»."""
        if self.first_date is None:
            return 0
        count, d = 0, until
        while d >= self.first_date:
            day = self.days.get(d)
            if day and day.user_actions:
                break
            if day and day.msgs_out:
                count += 1
            d -= timedelta(days=1)
        return count

    def autonomy(self, today: date, days: int = 28) -> dict[str, Any]:
        """Автономность (00-VISION §5): насколько человек держит день без бота.

        silent_ratio — выполнение в тихие дни к выполнению в обычные (≤ 1.0);
        hint_share — доля учебных вопросов, разобранных без готового ответа (/answer).
        Считается по закрытым дням и вопросам за последние `days` дней; нет данных — None.
        """
        since = today - timedelta(days=days)
        silent: list[float] = []
        normal: list[float] = []
        for d, day in self.days.items():
            closed = day.closed
            if not (since <= d < today) or not closed or not closed.get("total") or closed.get("completion") is None:
                continue
            (silent if day.silent else normal).append(float(closed["completion"]))
        ratio = None
        if silent and normal and sum(normal):
            ratio = round(min(1.0, (sum(silent) / len(silent)) / (sum(normal) / len(normal))), 2)
        questions = [q for q in self.learning if q.get("date", "") >= since.isoformat()]
        hints = sum(1 for q in questions if q.get("mode") == "hint")
        return {
            "silent_ratio": ratio, "silent_days": len(silent),
            "hint_share": round(hints / len(questions), 2) if questions else None, "hints": hints, "questions": len(questions),
        }

    def active_directives(self, today: date) -> list[dict[str, Any]]:
        alive = [x for x in self.directives.values() if not x.get("valid_until") or x["valid_until"] >= today.isoformat()]
        return sorted(alive, key=lambda x: (int(x.get("priority", 3)), x.get("date", "")))

    def week_start(self, d: date) -> date:
        return d - timedelta(days=d.weekday())

    def week_stats(self, d: date) -> dict[str, Any]:
        start = self.week_start(d)
        days = [start + timedelta(days=i) for i in range(7)]
        tasks = [t for t in self.tasks.values() if start <= t.local_date <= days[-1] and t.status == "done"]
        quotas = {
            "sport": sum(1 for t in tasks if t.sphere == "sport"),
            "social": sum(self.days[x].social for x in days if x in self.days) + sum(1 for t in tasks if t.sphere == "social"),
            "novelty": sum(1 for t in tasks if "novelty" in t.tags),
            "offscreen": sum(1 for t in tasks if "offscreen" in t.tags),
        }
        spent = [e for e in self.expenses if start.isoformat() <= e["date"] <= days[-1].isoformat()]
        by_category: dict[str, float] = {}
        for e in spent:
            by_category[e["category"]] = by_category.get(e["category"], 0.0) + float(e["amount"])
        return {
            "start": start,
            "productive_min": sum(t.duration_min * t.done_pct // 100 for t in tasks),
            "deep_min": sum(self.days[x].deep_min for x in days if x in self.days),
            "quotas": quotas,
            "expenses": by_category,
            "impulse": sum(float(e["amount"]) for e in spent if e.get("impulse")),
        }
