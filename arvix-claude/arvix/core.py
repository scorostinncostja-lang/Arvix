"""Core — фасад L0. Каждая операция: проверка → формула → событие в журнал.

Им пользуются все лица Арвикса: MCP-сервер (Claude Code / Desktop), Telegram-бот
и CLI. Модель сюда напрямую не пишет — она только вызывает операции, а числа
(XP, HP, долг, режим) считает код (00-VISION П3, правило №1 CLAUDE.md).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from arvix import clock, interview, rules
from arvix.config import Config, load_config
from arvix.state import State, Task
from arvix.store import Event, Store

STATUS_RU = {
    "planned": "запланирована", "active": "в работе", "done": "выполнена", "failed": "провалена",
    "debt": "в долге", "cancelled": "отменена", "written_off": "списана",
}
DIRECTIVE_KINDS = ("focus", "warning", "schedule_change", "insight", "quota_push")
TRAIT_KINDS = ("fear", "weakness", "bad_habit", "good_habit", "trigger")
GOAL_KINDS = ("dream", "main", "yearly", "quarterly", "milestone")
GOAL_STATUSES = ("active", "done", "dropped")
DAY_TYPES = ("study", "work", "deep", "recovery", "silent")
SOS_HOURS = 24
ZERO_HOURS = 48


class ArvixError(ValueError):
    """Отказ L0 с объяснением для человека: долг, неизвестная задача и т.п."""


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def parse_hhmm(value: Any) -> str | None:
    if value in (None, ""):
        return None
    match = re.fullmatch(r"\s*([01]?\d|2[0-3])[:.]?([0-5]\d)?\s*", str(value))
    if not match:
        raise ArvixError(f"Время «{value}» не похоже на ЧЧ:ММ")
    return f"{int(match.group(1)):02d}:{match.group(2) or '00'}"


def parse_duration(value: Any) -> int:
    """7:30 / 7ч30м / 7.5 / 450 → минуты. Число ≤ 24 считается часами."""
    text = str(value).strip().lower().replace(",", ".")
    if match := re.fullmatch(r"(\d{1,2})[:ч\s]+(\d{1,2})\s*м?", text):
        return int(match.group(1)) * 60 + int(match.group(2))
    if match := re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ч|h)?", text):
        number = float(match.group(1))
        return int(number * 60) if number <= 24 or match.group(2) else int(number)
    if match := re.fullmatch(r"(\d+)\s*(м|мин|m|min)", text):
        return int(match.group(1))
    raise ArvixError(f"Длительность «{value}» не распознана. Примеры: 7:30, 7.5, 450м")


class Core:
    def __init__(self, cfg: Config | None = None, store: Store | None = None):
        self.cfg = cfg or load_config()
        self.store = store or Store(self.cfg.db_path)
        self.state = State()
        self._tx_depth = 0
        self.refresh(catch_up=False)

    # --- время ------------------------------------------------------------

    @property
    def tz(self) -> ZoneInfo:
        name = self.state.profile.get("timezone")
        if name:
            try:
                return ZoneInfo(name)
            except ZoneInfoNotFoundError:
                pass
        return self.cfg.tz

    def now(self) -> datetime:
        return clock.now().astimezone(self.tz)

    def today(self) -> date:
        return self.now().date()

    def at(self, d: date, hhmm: str) -> datetime:
        hours, minutes = map(int, hhmm.split(":"))
        return datetime.combine(d, time(hours, minutes), tzinfo=self.tz)

    def parse_day(self, value: Any) -> date:
        if value in (None, "", "today", "сегодня"):
            return self.today()
        if value in ("tomorrow", "завтра"):
            return self.today() + timedelta(days=1)
        if value in ("yesterday", "вчера"):
            return self.today() - timedelta(days=1)
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise ArvixError(f"Дата «{value}» не похожа на ГГГГ-ММ-ДД") from exc

    # --- журнал -------------------------------------------------------------

    def refresh(self, catch_up: bool = True) -> State:
        """Подтягивает события, записанные другими процессами (бот, MCP, CLI)."""
        for event in self.store.read(self.state.last_event_id):
            self.state.apply(event)
        if catch_up:
            from arvix import daily

            daily.catch_up(self)
        return self.state

    @contextmanager
    def tx(self) -> Iterator[None]:
        """Транзакция записи. При ошибке память откатывается вслед за базой —
        иначе State разъехался бы с журналом."""
        if self._tx_depth:
            self._tx_depth += 1
            try:
                yield
            finally:
                self._tx_depth -= 1
            return
        self._tx_depth = 1
        try:
            with self.store.transaction():
                self.refresh(catch_up=False)
                yield
        except BaseException:
            self.state = State.rebuild(self.store.read())
            raise
        finally:
            self._tx_depth = 0

    def emit(self, kind: str, payload: dict[str, Any], *, source: str, entity_id: str | None = None) -> Event:
        """Единственный способ изменить состояние (правило №3)."""
        now = self.now()
        event = self.store.append(kind, payload, at=now, local_date=now.date(), source=source, entity_id=entity_id)
        self.state.apply(event)
        return event

    # --- режим --------------------------------------------------------------

    def sos_active(self) -> bool:
        until = self.state.sos_until
        return bool(until) and datetime.fromisoformat(until) > self.now()

    def zero_active(self) -> bool:
        until = self.state.zero_until
        return bool(until) and datetime.fromisoformat(until) > self.now()

    def effective_mode(self) -> str:
        """Выключенный ментор (safety-контур) по тону равен 🟥 — правило №5."""
        return "red" if not self.state.mentor_enabled else self.state.mode

    def recompute_mode(self, source: str = "scheduler") -> str:
        today = self.today()
        mode, trigger = rules.guard_mode(
            sleep=self.state.series(today, 3, "sleep_min"),
            completion=self.state.series(today - timedelta(days=1), 7, "completion"),
            hp=self.state.hp,
            sos=self.sos_active(),
        )
        if mode != self.state.mode:
            with self.tx():
                self.emit("mode_changed", {"from": self.state.mode, "to": mode, "trigger": trigger}, source=source)
        return mode

    def penalty_multiplier(self, d: date | None = None, ignore_days: int = 0) -> float:
        d = d or self.today()
        day = self.state.days.get(d)
        return rules.penalty_multiplier(
            mode=self.state.mode,
            mentor_enabled=self.state.mentor_enabled,
            hp=self.state.hp,
            silent=bool(day and day.silent),
            ignore_days=ignore_days,
            protocol_zero=self.zero_active(),
        )

    # --- задачи -------------------------------------------------------------

    def resolve_task(self, ref: Any) -> Task:
        key = str(ref).strip().strip("#[]")
        tasks = self.state.tasks
        if key in tasks:
            return tasks[key]
        candidates = [t for t in tasks.values() if len(key) >= 3 and t.id.startswith(key)]
        if not candidates and key:
            low = key.lower()
            pool = [t for t in tasks.values() if t.is_open or t.status == "debt"]
            candidates = [t for t in pool if low in t.title.lower()]
            today = [t for t in candidates if t.local_date == self.today()]
            candidates = today if len(today) == 1 else candidates
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            listing = "; ".join(f"[{t.id}] {t.title}" for t in self.state.tasks_on(self.today())) or "задач нет"
            raise ArvixError(f"Задача «{ref}» не найдена. Сегодня: {listing}")
        listing = "; ".join(f"[{t.id}] {t.title} ({t.local_date})" for t in candidates[:6])
        raise ArvixError(f"Под «{ref}» подходит несколько задач: {listing}. Уточни id.")

    def add_task(
        self,
        title: str,
        *,
        sphere: str = "project",
        importance: int = 3,
        difficulty: int = 3,
        start: Any = None,
        duration_min: int = 60,
        deep_work: bool = False,
        day: Any = None,
        tags: list[str] | tuple[str, ...] = (),
        task_source: str = "user",
        source: str = "claude",
    ) -> Task:
        title = str(title).strip()
        if not title:
            raise ArvixError("Пустое название задачи")
        sphere = sphere if sphere in rules.SPHERES else "project"
        importance = rules.clamp(int(importance), 1, 5)
        difficulty = rules.clamp(int(difficulty), 1, 5)
        target = self.parse_day(day)
        with self.tx():
            debts = self.state.debts()
            if sphere in rules.OPTIONAL_SPHERES and len(debts) >= 2 and task_source == "user":
                names = ", ".join(t.title for t in debts[:3])
                raise ArvixError(
                    f"Долг: {len(debts)} задачи ({names}). Пока долг ≥ 2, новые необязательные дела "
                    "заблокированы. Закрой долг или спиши его с письменным обоснованием."
                )
            task_id = new_id()
            self.emit(
                "task_created",
                {
                    "id": task_id, "title": title[:200], "sphere": sphere, "importance": importance,
                    "difficulty": difficulty, "date": target.isoformat(), "start": parse_hhmm(start),
                    "duration_min": max(0, int(duration_min or 0)), "deep_work": bool(deep_work),
                    "proof": rules.derive_proof(importance, sphere, bool(deep_work)),
                    "source": task_source, "tags": [str(t) for t in tags],
                },
                source=source,
                entity_id=task_id,
            )
        return self.state.tasks[task_id]

    def start_task(self, ref: Any, *, source: str = "claude") -> Task:
        with self.tx():
            task = self.resolve_task(ref)
            if task.status != "planned":
                raise ArvixError(f"«{task.title}» уже {STATUS_RU[task.status]}")
            self.emit("task_started", {"id": task.id, "at": self.now().isoformat()}, source=source, entity_id=task.id)
        return task

    def complete_task(
        self,
        ref: Any,
        *,
        done_pct: int = 100,
        report: str | None = None,
        proof_kind: str | None = None,
        source: str = "claude",
    ) -> dict[str, Any]:
        with self.tx():
            task = self.resolve_task(ref)
            if task.status not in ("planned", "active", "debt"):
                raise ArvixError(f"«{task.title}» уже {STATUS_RU[task.status]} — повторно закрыть нельзя.")
            report = (report or "").strip() or None
            kind = proof_kind or ("report" if report else "confirm")
            if task.proof in ("report", "photo") and kind == "confirm":
                raise ArvixError(f"«{task.title}» требует отчёта: одним предложением — что именно сделано?")
            if kind == "photo" and task.proof != "photo":
                kind = "report"
            pct = rules.clamp(int(done_pct), 1, 100)
            delay = None
            if task.actual_start and task.start:
                delay = (datetime.fromisoformat(task.actual_start) - self.at(task.local_date, task.start)).total_seconds() / 60
            xp = rules.task_xp(task.difficulty, task.importance, kind, delay, pct)
            deep = task.duration_min * pct // 100 if task.deep_work else 0
            self.emit(
                "task_completed",
                {"id": task.id, "done_pct": pct, "xp": xp, "report": report, "proof_kind": kind, "deep_min": deep},
                source=source,
                entity_id=task.id,
            )
            if xp:
                self.emit("xp_awarded", {"amount": xp, "reason": f"task:{task.id}"}, source=source, entity_id=task.id)
        self.recompute_mode(source="l0")
        return {"task": task, "xp": xp, "debt_closed": task.debt_since is not None}

    def fail_task(self, ref: Any, *, reason: str = "", source: str = "claude") -> dict[str, Any]:
        with self.tx():
            task = self.resolve_task(ref)
            if not task.is_open:
                raise ArvixError(f"«{task.title}» уже {STATUS_RU[task.status]}")
            debt = task.importance >= 4
            hp = round(rules.HP_FAIL[task.importance] * self.penalty_multiplier())
            self.emit(
                "task_failed",
                {"id": task.id, "reason": (reason or "не указана")[:500], "debt": debt, "hp": hp},
                source=source,
                entity_id=task.id,
            )
            if hp:
                self.emit("hp_changed", {"amount": hp, "reason": f"task_failed:{task.id}"}, source=source, entity_id=task.id)
        self.recompute_mode(source="l0")  # 1.3 плана: режим пересчитывается при закрытии/провале задачи
        return {"task": task, "hp": hp, "debt": debt}

    def explain_failure(self, ref: Any, reason: str, *, source: str = "claude") -> Task:
        """Причина провала, присланная позже кнопки «Нет» — отдельным событием,
        журнал не правится задним числом."""
        with self.tx():
            task = self.resolve_task(ref)
            self.emit("task_reason", {"id": task.id, "reason": reason[:500]}, source=source, entity_id=task.id)
        return task

    def defer_task(self, ref: Any, minutes: int = 15, *, source: str = "claude") -> Task:
        with self.tx():
            task = self.resolve_task(ref)
            if task.status != "planned":
                raise ArvixError(f"Отложить можно только запланированную задачу, а «{task.title}» {STATUS_RU[task.status]}")
            base = self.at(task.local_date, task.start) if task.start else self.now()
            moved = max(base, self.now().replace(second=0, microsecond=0)) + timedelta(minutes=int(minutes))
            self.emit(
                "task_deferred",
                {"id": task.id, "from": task.start, "to": moved.strftime("%H:%M"), "date": moved.date().isoformat(), "minutes": int(minutes)},
                source=source,
                entity_id=task.id,
            )
        return task

    def cancel_task(self, ref: Any, *, reason: str, source: str = "claude") -> Task:
        if not (reason or "").strip():
            raise ArvixError("Отмена без причины не принимается — она попадёт в разбор.")
        with self.tx():
            task = self.resolve_task(ref)
            if not task.is_open:
                raise ArvixError(f"«{task.title}» {STATUS_RU[task.status]} — отменить нельзя. Долг можно только списать.")
            self.emit("task_cancelled", {"id": task.id, "reason": reason[:500]}, source=source, entity_id=task.id)
        return task

    def write_off_debt(self, ref: Any, *, justification: str, source: str = "claude") -> Task:
        if len((justification or "").strip()) < 20:
            raise ArvixError("Списание долга требует письменного обоснования — хотя бы пару предложений.")
        with self.tx():
            task = self.resolve_task(ref)
            if task.status != "debt":
                raise ArvixError(f"«{task.title}» не в долге")
            self.emit("debt_written_off", {"id": task.id, "justification": justification[:1000]}, source=source, entity_id=task.id)
        return task

    # --- журналы дня ----------------------------------------------------------

    def log_sleep(self, duration: Any, *, bedtime: Any = None, day: Any = None, source: str = "claude") -> dict[str, Any]:
        minutes = parse_duration(duration)
        if not 0 < minutes <= 20 * 60:
            raise ArvixError("Сон должен быть от 1 минуты до 20 часов")
        target = self.parse_day(day)
        with self.tx():
            self.emit(
                "sleep_recorded",
                {"duration_min": minutes, "bedtime": parse_hhmm(bedtime), "date": target.isoformat(), "source": source},
                source=source,
            )
        mode = self.recompute_mode(source="l0")
        return {"duration_min": minutes, "date": target, "mode": mode}

    def log_expense(self, amount: Any, category: str, *, impulse: bool = False, note: str = "", source: str = "claude") -> dict[str, Any]:
        try:
            value = round(float(str(amount).replace(",", ".").replace(" ", "")), 2)
        except ValueError as exc:
            raise ArvixError(f"Сумма «{amount}» не число") from exc
        if value <= 0:
            raise ArvixError("Сумма должна быть больше нуля")
        currency = self.state.profile.get("currency", "RUB")
        with self.tx():
            self.emit(
                "expense_logged",
                {"amount": value, "currency": currency, "category": (category or "прочее").strip().lower()[:40], "impulse": bool(impulse), "note": note[:200]},
                source=source,
            )
        week = self.state.week_stats(self.today())
        return {"amount": value, "currency": currency, "week_total": round(sum(week["expenses"].values()), 2)}

    def log_social(self, who: str = "", *, source: str = "claude") -> None:
        with self.tx():
            self.emit("social_contact", {"who": who[:100]}, source=source)

    def log_focus(self, minutes: int, *, task_ref: Any = None, source: str = "claude") -> None:
        task_id = self.resolve_task(task_ref).id if task_ref else None
        with self.tx():
            self.emit("focus_session", {"duration_min": int(minutes), "task_id": task_id}, source=source)

    def declare_reason(self, reason: str, *, source: str = "claude") -> dict[str, Any]:
        """Причина дня («заболел», «семья») — при закрытии дня щит снимет самый
        крупный урон, если жетоны ещё есть (02-MECHANICS §3)."""
        if not reason.strip():
            raise ArvixError("Причина пуста")
        with self.tx():
            self.emit("reason_declared", {"reason": reason[:300]}, source=source)
        left = int(self.cfg.mech("shields_per_month", 2)) - self.state.shields_used(self.today())
        return {"shields_left": max(0, left)}

    @property
    def vault(self) -> Any:
        from arvix.vault import Vault, VaultError

        if not self.cfg.vault:
            raise ArvixError("Хранилище Obsidian не настроено: `arvix setup`")
        try:
            return Vault(self.cfg.vault, self.cfg.vault_paths)
        except VaultError as exc:
            raise ArvixError(str(exc)) from exc

    def _note_event(self, result: dict[str, Any], mode: str, source: str) -> dict[str, Any]:
        with self.tx():
            self.emit("note_written", {"path": result["path"], "sha": result["sha"], "owned": result["owned"], "mode": mode,
                                       "created": result.get("created", False), "backup": result.get("backup")}, source=source)
        return result

    def write_note(self, rel: str, content: str, *, append: bool = False, force: bool = False, source: str = "claude") -> dict[str, Any]:
        """Запись в хранилище по правилам vault.py: свою нетронутую — можно, чужую — только дописать."""
        from arvix.vault import VaultError

        try:
            result = self.vault.write(rel, content, append=append, owned_sha=self.state.notes.get(str(rel).lstrip("/")), force=force)
        except VaultError as exc:
            raise ArvixError(str(exc)) from exc
        return self._note_event(result, "append" if append else ("force" if force else "write"), source)

    def write_block(self, rel: str, name: str, content: str, *, create_with: str = "", source: str = "claude") -> dict[str, Any]:
        from arvix.vault import VaultError

        try:
            result = self.vault.write_block(rel, name, content, create_with=create_with)
        except VaultError as exc:
            raise ArvixError(str(exc)) from exc
        if not result["owned"] and self.state.notes.get(result["path"]):
            result["owned"] = True  # свой файл остаётся своим
        return self._note_event(result, f"block:{name}", source)

    def update_note(self, rel: str, transform: Any, *, source: str = "claude") -> dict[str, Any]:
        result = self.vault.update_text(rel, transform, owned_sha=self.state.notes.get(rel))
        return self._note_event(result, "fields", source) if result["changed"] else result

    def capture_note(self, text: str, *, source: str = "claude") -> str | None:
        if not text.strip():
            raise ArvixError("Пустая заметка")
        path = None
        if self.cfg.vault:
            path = self.vault.inbox(text, self.now())
        with self.tx():
            self.emit("note_captured", {"text": text[:2000], "path": path}, source=source)
        return path

    # --- профиль и память -------------------------------------------------------

    def profile_set(self, key: str, value: Any, *, source: str = "claude") -> None:
        key = re.sub(r"[^a-z0-9_]", "_", str(key).strip().lower())[:40]
        if not key:
            raise ArvixError("Пустой ключ профиля")
        if key in ("bedtime_target", "wake_target", "bedtime_actual", "wake_actual"):
            value = parse_hhmm(value)
        elif key == "timezone":
            try:
                ZoneInfo(str(value))
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ArvixError(f"Неизвестный часовой пояс «{value}»") from exc
        elif key == "address" and value not in ("m", "f"):
            raise ArvixError("address: только m или f")
        elif key == "mentor_enabled":
            raise ArvixError("Режим ментора включается только вручную: /mentor on в Telegram или `arvix mentor on`.")
        with self.tx():
            self.emit("profile_set", {"key": key, "value": value}, source=source)

    def set_goal(
        self,
        title: str = "",
        *,
        why: str = "",
        kind: str | None = None,
        deadline: str | None = None,
        metric: str | None = None,
        sphere: str | None = None,
        goal_id: str | None = None,
        parent_id: str | None = None,
        status: str | None = None,
        source: str = "claude",
    ) -> str:
        """Цель или её этап (иерархия 03-DATA-MODEL §2: мечта → главная → … → веха).
        С goal_id — обновление: непереданные поля остаются прежними, событие новое."""
        old = self.state.goals.get(goal_id or "", {})
        if goal_id and not old:
            raise ArvixError(f"Цели {goal_id} нет")
        if parent_id and parent_id not in self.state.goals:
            raise ArvixError(f"Родительской цели {parent_id} нет")
        if status and status not in GOAL_STATUSES:
            raise ArvixError(f"status: {', '.join(GOAL_STATUSES)}")
        payload = {
            "id": goal_id or new_id(),
            "title": (title or old.get("title", ""))[:200],
            "why": (why or old.get("why", ""))[:500],
            "kind": kind if kind in GOAL_KINDS else old.get("kind", "milestone" if parent_id else "main"),
            "deadline": deadline or old.get("deadline"),
            "metric": metric or old.get("metric"),
            "sphere": sphere or old.get("sphere"),
            "parent_id": parent_id or old.get("parent_id"),
            "status": status or old.get("status", "active"),
        }
        if not payload["title"]:
            raise ArvixError("У цели нет названия")
        if not payload["why"].strip() and not payload["parent_id"]:
            raise ArvixError("У цели обязательно поле «зачем» (03-DATA-MODEL §2)")
        with self.tx():
            self.emit("goal_set", payload, source=source, entity_id=payload["id"])
        return payload["id"]

    def goal_tree(self) -> list[tuple[int, dict[str, Any]]]:
        """Цели деревом: (глубина, цель), этапы по дедлайну."""
        goals = self.state.goals
        children: dict[str | None, list[dict[str, Any]]] = {}
        for goal in goals.values():
            parent = goal.get("parent_id") if goal.get("parent_id") in goals else None
            children.setdefault(parent, []).append(goal)
        out: list[tuple[int, dict[str, Any]]] = []

        def walk(parent: str | None, depth: int) -> None:
            for goal in sorted(children.get(parent, []), key=lambda g: (g.get("deadline") or "9999", g["title"])):
                out.append((depth, goal))
                walk(goal["id"], depth + 1)

        walk(None, 0)
        return out

    def add_trait(self, kind: str, title: str, *, description: str = "", severity: int = 3, counter_strategy: str = "", source: str = "claude") -> str:
        if kind not in TRAIT_KINDS:
            raise ArvixError(f"kind черты: {', '.join(TRAIT_KINDS)}")
        trait_id = new_id()
        with self.tx():
            self.emit(
                "trait_set",
                {"id": trait_id, "kind": kind, "title": title[:200], "description": description[:500],
                 "severity": rules.clamp(int(severity), 1, 5), "counter_strategy": counter_strategy[:500]},
                source=source,
                entity_id=trait_id,
            )
        return trait_id

    def remember(self, topic: str, fact: str, *, confidence: int = 3, valid_days: int | None = None, source: str = "claude") -> str:
        if not fact.strip():
            raise ArvixError("Пустой факт")
        fact_id = new_id()
        valid_until = (self.today() + timedelta(days=int(valid_days))).isoformat() if valid_days else None
        with self.tx():
            self.emit(
                "fact_remembered",
                {"id": fact_id, "topic": (topic or "general")[:40], "fact": fact[:500], "confidence": rules.clamp(int(confidence), 1, 5), "valid_until": valid_until},
                source=source,
                entity_id=fact_id,
            )
        return fact_id

    def forget(self, fact_id: str, *, reason: str = "", source: str = "claude") -> None:
        if fact_id not in self.state.facts:
            raise ArvixError(f"Факта {fact_id} нет")
        with self.tx():
            self.emit("fact_retracted", {"id": fact_id, "reason": reason[:200]}, source=source)

    def set_template(self, weekdays: list[int], day_type: str, blocks: list[dict[str, Any]], *, source: str = "claude") -> None:
        """Шаблон дня (02-MECHANICS §5): из него утром материализуются задачи."""
        if day_type not in DAY_TYPES:
            raise ArvixError(f"Тип дня: {', '.join(DAY_TYPES)}")
        days = sorted({int(w) for w in weekdays})
        if not days or any(not 0 <= w <= 6 for w in days):
            raise ArvixError("weekdays: числа 0 (пн) … 6 (вс)")
        clean = []
        for block in blocks:
            importance = rules.clamp(int(block.get("importance", 3)), 1, 5)
            sphere = block.get("sphere") if block.get("sphere") in rules.SPHERES else "project"
            clean.append({
                "start": parse_hhmm(block["start"]), "duration": int(block.get("duration", 60)),
                "title": str(block["title"])[:200], "sphere": sphere, "importance": importance,
                "difficulty": rules.clamp(int(block.get("difficulty", 3)), 1, 5),
                "deep_work": bool(block.get("deep_work")), "tags": list(block.get("tags") or []),
            })
        with self.tx():
            self.emit("template_set", {"weekdays": days, "day_type": day_type, "blocks": clean}, source=source)

    # --- интервью -----------------------------------------------------------------

    def interview_status(self) -> dict[str, Any]:
        st = self.state
        status = interview.progress(set(st.interview), st.interview_skipped)
        status["next"] = interview.next_question(set(st.interview), st.interview_skipped)
        return status

    def interview_next(self, block: str | None = None) -> dict[str, Any] | None:
        st = self.state
        question = interview.next_question(set(st.interview), st.interview_skipped, block)
        if not question:
            return None
        return {**question, "block_title": interview.BLOCK_TITLES[question["block"]]}

    def interview_answer(self, qid: str, answer: str, *, source: str = "claude") -> dict[str, Any]:
        if qid not in interview.BY_ID:
            raise ArvixError(f"Нет вопроса {qid}")
        answer = answer.strip()
        if not answer:
            raise ArvixError("Пустой ответ — лучше пропусти вопрос")
        question = interview.BY_ID[qid]
        extracted = interview.extract(qid, answer)
        with self.tx():
            self.emit("interview_answer", {"qid": qid, "block": question["block"], "question": question["text"], "answer": answer[:3000]}, source=source)
            for key, value in extracted.items():
                self.emit("profile_set", {"key": key, "value": value}, source="l0")
            if qid == "main_goal_why" and self.state.profile.get("main_goal") and not any(g.get("kind") == "main" for g in self.state.goals.values()):
                self.set_goal(self.state.profile["main_goal"], why=answer, kind="main", source="l0")
            if not self.state.profile.get("season_start"):
                self.emit("profile_set", {"key": "season_start", "value": self.today().isoformat()}, source="l0")
        next_q = self.interview_next()
        block_done = next_q is None or next_q["block"] != question["block"]
        return {"saved": qid, "extracted": extracted, "block_done": block_done, "next": next_q}

    def interview_reset(self, qid: str, *, reason: str = "", source: str = "claude") -> None:
        """Снять ответ, чтобы вопрос задали снова (журнал не правится — новое событие)."""
        if qid not in interview.BY_ID:
            raise ArvixError(f"Нет вопроса {qid}")
        with self.tx():
            self.emit("interview_reset", {"qid": qid, "reason": reason[:200]}, source=source)

    def interview_skip(self, qid: str, *, source: str = "claude") -> dict[str, Any] | None:
        if qid not in interview.BY_ID:
            raise ArvixError(f"Нет вопроса {qid}")
        with self.tx():
            self.emit("interview_skipped", {"qid": qid}, source=source)
        return self.interview_next()

    # --- режимы и safety --------------------------------------------------------

    def sos(self, on: bool, *, note: str = "", source: str = "claude") -> str:
        until = (self.now() + timedelta(hours=SOS_HOURS)).isoformat() if on else None
        with self.tx():
            self.emit("sos", {"on": on, "until": until, "note": note[:300]}, source=source)
        return self.recompute_mode(source="l0")

    def silent_today(self, *, source: str = "claude") -> None:
        with self.tx():
            if not self.state.day(self.today()).silent:
                self.emit("silent_day", {"date": self.today().isoformat()}, source=source)

    def safety_flag(self, level: str, note: str, *, source: str = "l0") -> bool:
        """Safety-контур (02-MECHANICS §6): ментор выключается до ручного включения.
        Только уровни high/critical; остальное (контакт поддержки, «бывает тяжело») —
        факт о человеке. Возвращает True, если ментор выключен."""
        level = (level or "high").strip().lower()[:20]
        if level not in rules.SAFETY_ALARM_LEVELS:
            if note.strip():
                self.remember("safety", note, source=source)
            return False
        with self.tx():
            self.emit("safety_flag", {"level": level, "note": note[:300]}, source=source)
        return True

    def set_mentor(self, enabled: bool, *, by: str) -> None:
        """Включение — только явной командой человека (CLI или /mentor on), никогда
        моделью: поэтому в MCP-инструментах этой операции нет."""
        with self.tx():
            self.emit("mentor_toggled", {"enabled": enabled, "by": by}, source="user")

    # --- разбор и совет (L2) ------------------------------------------------------

    def day_facts(self, d: date | None = None) -> dict[str, Any]:
        d = d or self.today()
        st = self.state
        tasks = st.tasks_on(d)
        day = st.days.get(d)
        return {
            "date": d,
            "tasks": tasks,
            "done": sum(1 for t in tasks if t.status == "done"),
            "total": len(tasks),
            "completion": st.completion(d),
            "deep_min": day.deep_min if day else 0,
            "sleep_min": day.sleep_min if day else None,
            "debts": st.debts(),
            "week": st.week_stats(d),
            "impulse": [e for e in st.expenses if e["date"] == d.isoformat() and e.get("impulse")],
        }

    def complete_debrief(self, answers: str, *, conclusion: str = "", day: Any = None, source: str = "claude") -> None:
        target = self.parse_day(day)
        with self.tx():
            self.emit("debrief_completed", {"date": target.isoformat(), "answers": answers[:3000], "conclusion": conclusion[:1000]}, source=source)

    def add_directive(
        self,
        kind: str,
        text: str,
        *,
        evidence: list[int],
        voice_hint: str = "",
        priority: int = 3,
        valid_days: int = 7,
        created_by: str = "analyst",
        source: str = "l2",
    ) -> str:
        """Директива без доказательств отклоняется (03-DATA-MODEL §3, инв. 6)."""
        if kind not in DIRECTIVE_KINDS:
            raise ArvixError(f"kind директивы: {', '.join(DIRECTIVE_KINDS)}")
        ids = sorted({int(e) for e in evidence or []})
        if not ids:
            raise ArvixError("Директива без evidence (id событий) не принимается")
        if ids[0] < 1 or ids[-1] > self.state.last_event_id:
            raise ArvixError(f"evidence ссылается на несуществующие события: {ids}")
        directive_id = new_id()
        with self.tx():
            self.emit(
                "directive_created",
                {"id": directive_id, "kind": kind, "text": text[:600], "voice_hint": voice_hint[:300],
                 "priority": rules.clamp(int(priority), 1, 5), "evidence": ids,
                 "valid_until": (self.today() + timedelta(days=int(valid_days))).isoformat(), "created_by": created_by},
                source=source,
                entity_id=directive_id,
            )
        return directive_id

    def add_insight(self, text: str, *, evidence: list[int], source: str = "l2") -> None:
        if not evidence:
            raise ArvixError("Инсайт без evidence не принимается")
        with self.tx():
            self.emit("insight", {"text": text[:600], "evidence": sorted({int(e) for e in evidence})}, source=source)

    def events_feed(self, days: int = 7, kinds: list[str] | None = None, limit: int = 400) -> list[str]:
        """Сырая лента событий для Analyst — с id, чтобы выводы ссылались на факты."""
        since = (self.today() - timedelta(days=int(days))).isoformat()
        skip = {"message_out"}
        lines = []
        for ev in self.store.read(0):
            if ev.local_date.isoformat() < since or ev.kind in skip or (kinds and ev.kind not in kinds):
                continue
            body = ", ".join(f"{k}={str(v)[:80]}" for k, v in ev.payload.items() if v not in (None, "", [], {}))
            lines.append(f"#{ev.id} {ev.at.astimezone(self.tz):%d.%m %H:%M} {ev.kind} [{ev.source}] {body}")
        return lines[-int(limit):]

    def learning_question(self, question: str, *, direct: bool, source: str = "claude") -> None:
        with self.tx():
            self.emit("learning_question", {"question": question[:500], "mode": "direct" if direct else "hint"}, source=source)

    # --- сообщения ------------------------------------------------------------------

    def message_in(self, text: str, *, channel: str = "telegram") -> None:
        with self.tx():
            self.emit("message_in", {"text": text[:2000], "channel": channel}, source=channel)

    def message_out(self, text: str, *, key: str | None = None, channel: str = "telegram") -> None:
        with self.tx():
            self.emit("message_out", {"text": text[:600], "key": key, "channel": channel}, source="bot")

    def sent(self, key: str, d: date | None = None) -> bool:
        day = self.state.days.get(d or self.today())
        return bool(day and key in day.out_keys)

    # --- нагрузка ------------------------------------------------------------------------

    def budget(self) -> dict[str, Any]:
        """Текущий бюджет недели: из события budget_set, иначе из профиля
        (часы из интервью) или конфига. Глубокая работа по умолчанию — 35%."""
        st = self.state
        if st.budget:
            week, deep, since = int(st.budget["week_min"]), int(st.budget["deep_min"]), st.budget["since"]
        else:
            week = int(st.profile.get("week_budget_min") or self.cfg.mech("week_budget_min", 1560))
            deep = int(st.profile.get("week_deep_budget_min") or (week * 0.35 if st.profile.get("week_budget_min") else self.cfg.mech("week_deep_budget_min", 480)))
            since = st.profile.get("season_start") or (st.first_date or self.today()).isoformat()
        review = date.fromisoformat(since) + timedelta(days=rules.BUDGET_REVIEW_DAYS)
        return {"week_min": week, "deep_min": deep, "since": since, "next_review": review, "verdict": st.budget.get("verdict"), "reason": st.budget.get("reason")}

    def planned_minutes(self, start: date, end: date) -> int:
        return sum(t.duration_min for t in self.state.tasks.values() if start <= t.local_date <= end and t.status != "cancelled")

    def load_check(self, d: date | None = None) -> list[str]:
        """Перегруз недели и дня, глубокая работа без меры, задачи впритык к отбою."""
        d = d or self.today()
        budget = self.budget()
        week_start = self.state.week_start(d)
        warnings = []
        week_planned = self.planned_minutes(week_start, week_start + timedelta(days=6))
        if week_planned > budget["week_min"] * 1.1:
            warnings.append(f"неделя перегружена: запланировано {week_planned // 60}ч{week_planned % 60:02d}м при бюджете {budget['week_min'] // 60}ч")
        tasks = self.state.tasks_on(d)
        day_planned = sum(t.duration_min for t in tasks)
        day_cap = max(90, int(budget["week_min"] / 5 * 1.5))
        if self.state.mode == "yellow":
            day_cap = int(day_cap * 0.7)
        if day_planned > day_cap:
            warnings.append(f"день перегружен: {day_planned // 60}ч{day_planned % 60:02d}м при разумном максимуме {day_cap // 60}ч{day_cap % 60:02d}м")
        deep = sum(t.duration_min for t in tasks if t.deep_work)
        if deep > 240:
            warnings.append(f"глубокой работы {deep // 60}ч{deep % 60:02d}м за день — больше 4 ч качество падает")
        bedtime = self.state.profile.get("bedtime_target")
        if bedtime:
            for task in tasks:
                if task.start and task.is_open:
                    end = self.at(d, task.start) + timedelta(minutes=task.duration_min)
                    gap = rules.minutes_after(end.strftime("%H:%M"), bedtime)
                    if gap is not None and gap < 60:
                        warnings.append(f"«{task.title}» заканчивается в {end:%H:%M} — меньше часа до отбоя ({bedtime})")
        return warnings

    # --- сводка -----------------------------------------------------------------------

    def season(self) -> dict[str, Any]:
        st = self.state
        start = date.fromisoformat(st.profile.get("season_start") or (st.first_date or self.today()).isoformat())
        days_in = (self.today() - start).days
        number = days_in // (rules.SEASON_WEEKS * 7) + 1
        season_start = start + timedelta(days=(number - 1) * rules.SEASON_WEEKS * 7)
        sps = [d.closed["sp"] for x, d in st.days.items() if d.closed and x >= season_start and d.closed.get("sp") is not None]
        avg = round(sum(sps) / len(sps), 1) if sps else 0.0
        return {"number": number, "week": (self.today() - season_start).days // 7 + 1, "sp_avg": avg, "rank": rules.season_rank(avg)}

    def status(self) -> dict[str, Any]:
        st = self.state
        level, into, need = st.level()
        today = self.today()
        return {
            "level": level, "xp_into": into, "xp_need": need, "xp_total": st.xp_total, "hp": st.hp,
            "mode": st.mode, "effective_mode": self.effective_mode(), "mode_trigger": st.mode_trigger,
            "mentor_enabled": st.mentor_enabled, "streak": st.streak(today), "season": self.season(),
            "completion": st.completion(today), "debts": len(st.debts()), "protocol_zero": self.zero_active(),
            "shields_left": max(0, int(self.cfg.mech("shields_per_month", 2)) - st.shields_used(today)),
        }
