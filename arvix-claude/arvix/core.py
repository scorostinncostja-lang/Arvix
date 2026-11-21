"""Core — фасад L0. Каждая операция: проверка → формула → событие в журнал.

Им пользуются все лица Arvix: MCP-сервер (Claude Code / Desktop), Telegram-бот
и CLI. Модель сюда напрямую не пишет — она только вызывает операции, а решения
(долг, режим, нагрузку) принимает код (00-VISION П3, правило №1 CLAUDE.md).
Игры нет (D41): ни очков, ни здоровья, ни уровней — только факты.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from arvix import checks, clock, interview, load, rules
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


class ArvixError(ValueError):
    """Отказ L0 с объяснением для человека: долг, неизвестная задача и т.п."""


class NoteConflict(ArvixError):
    """Заметка изменилась после открытия: в ошибке — текущий текст, чтобы выбрать версию."""

    def __init__(self, message: str, path: str, current: str):
        super().__init__(message)
        self.path = path
        self.current = current


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


def sleep_between(bedtime: str, wake: str) -> int:
    """Минуты сна от отбоя до подъёма через полночь: 01:00 → 08:30 = 450, 23:30 → 07:00 = 450."""
    bed_h, bed_m = map(int, bedtime.split(":"))
    up_h, up_m = map(int, wake.split(":"))
    return (up_h * 60 + up_m - bed_h * 60 - bed_m) % 1440


_CLOCK = r"(\d{1,2}(?:[:.]\d{2})?|час|полночь)"
_BED_RE = re.compile(r"\b(?:лег\w*|легл\w*|уснул\w*|заснул\w*|отбой|вырубил\w*|отключил\w*)\s*(?:в|около|примерно в|где-то в)?\s*" + _CLOCK)
_WAKE_RE = re.compile(r"\b(?:встал\w*|проснул\w*|подъем)\s*(?:в|около|примерно в|где-то в)?\s*" + _CLOCK)
_MORNING_RE = re.compile(r"(?<![\d:.])" + _CLOCK + r"\s*утра")
_RANGE_RE = re.compile(r"(?:^|\bс\s+)(\d{1,2}(?:[:.]\d{2})?)\s*(?:-|–|—|до)\s*(\d{1,2}(?:[:.]\d{2})?)\b(?!\s*ч)")
_HOURS_RE = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*(?:ч\b|час\w*)")


def _clock(token: str, *, bed: bool) -> str:
    """«час» → 01:00; «11» в отбое → 23:00 (вечер), «12» → 00:00; подъём — как сказан."""
    if token == "час":
        return "01:00"
    if token == "полночь":
        return "00:00"
    value = parse_hhmm(token.replace(".", ":"))
    hours, minutes = map(int, value.split(":"))
    if bed and 6 <= hours <= 11:
        hours += 12
    elif bed and hours == 12:
        hours = 0
    return f"{hours:02d}:{minutes:02d}"


_GOODNIGHT_RE = re.compile(
    r"(?:(?:все|всё|ладно|ну|ок|окей|я)[,!.\s]*)*"
    r"(?:спокойной ночи|доброй ночи|иду спать|пошел спать|пойду спать|ложусь(?: спать)?|сплю|я спать|отбой|спать)"
    r"[\s!.)👋😴🌙]*")


def is_goodnight(text: str) -> bool:
    """«Спокойной ночи», «всё, иду спать», «ложусь» — короткое прощание на ночь (D48). Фраза целиком:
    «отбой в 23:30 поставь» или «не могу спать» — это уже разговор, его ведёт голова."""
    low = text.lower().replace("ё", "е").strip()
    return len(low) <= 40 and bool(_GOODNIGHT_RE.fullmatch(low))


def parse_sleep_text(text: str, expect: str | None = None) -> dict[str, Any]:
    """Ответ про сон словами → {duration, bedtime, wake}; чего нет — None (02-MECHANICS §7.2).

    «7:30», «7.5», «7ч30м» — длительность; «7:20 00:30» — длительность и отбой;
    «лёг в час, встал в 8:30», «с 0:30 до 8:30», «0:30–8:30» — отбой и подъём;
    «8:30 утра», «встал в 9» — только подъём (отбой код спросит сам); «23:40» — только отбой.
    Голое «8:30» — длительность: так его просит брифинг. expect — какую половину код только что
    спросил («Во сколько уснул?» → expect="bedtime»): тогда «в час» — это она."""
    low = text.lower().replace("ё", "е").strip()
    out: dict[str, Any] = {"duration": None, "bedtime": None, "wake": None}
    if match := _RANGE_RE.search(low):
        out["bedtime"], out["wake"] = _clock(match.group(1), bed=True), _clock(match.group(2), bed=False)
    if match := _BED_RE.search(low):
        out["bedtime"] = _clock(match.group(1), bed=True)
    if match := _WAKE_RE.search(low) or _MORNING_RE.search(low):
        out["wake"] = _clock(match.group(1), bed=False)
    if expect in ("bedtime", "wake") and not out[expect] and (match := re.search(r"(?<![\d:.])" + _CLOCK + r"(?![\d:.])", low)):
        out[expect] = _clock(match.group(1), bed=expect == "bedtime")
    if out["bedtime"] and out["wake"]:
        out["duration"] = sleep_between(out["bedtime"], out["wake"])
        return out
    if match := re.search(r"спал\w*\s*(?:около|примерно|где-то)?\s*(\d[\d:.,]*\s*(?:ч\w*\s*\d*\s*м?\w*|м\w*)?)", low):
        out["duration"] = parse_duration(match.group(1).replace("часов", "ч").replace("часа", "ч").replace("час", "ч").strip())
    elif match := _HOURS_RE.search(low):
        out["duration"] = parse_duration(match.group(1).replace(",", "."))
    elif not (out["bedtime"] or out["wake"]):
        words = low.replace(",", " ").split()
        if words and re.fullmatch(r"(1[3-9]|2[0-3])[:.]\d{2}", words[0]):
            out["bedtime"] = _clock(words[0], bed=True)  # 23:40 сном быть не может — это отбой
        elif 0 < len(words) <= 2:  # «5 задач сегодня?» — не сон: голое число берём только коротким ответом
            out["duration"] = parse_duration(words[0])
            if len(words) > 1 and re.fullmatch(r"\d{1,2}[:.]\d{2}", words[1]):
                out["bedtime"] = _clock(words[1], bed=True)
    if not any(out.values()):
        raise ArvixError("Не понял про сон. Примеры: «7:30», «лёг в час, встал в 8:30»")
    return out


class Core:
    def __init__(self, cfg: Config | None = None, store: Store | None = None):
        self.cfg = cfg or load_config()
        self.store = store or Store(self.cfg.db_path)
        self.state = State()
        self._tx_depth = 0
        self.refresh(catch_up=False)

    def close(self) -> None:
        self.store.close()

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

    def rollover(self) -> str:
        """Смена дня «ЧЧ:ММ» (`[schedule] rollover`, 04:00): до неё вчерашний день ещё открыт.
        Единственное место, где это считается: закрытие дня, вопросы бота, «вчера» в приложении."""
        return parse_hhmm(self.cfg.schedule("rollover")) or "04:00"

    def day_boundary(self, now: datetime | None = None) -> datetime:
        """Последняя смена дня, не позже `now`: 01:30 → вчера 04:00, 09:00 → сегодня 04:00."""
        now = now or self.now()
        boundary = self.at(now.date(), self.rollover())
        return boundary if boundary <= now else boundary - timedelta(days=1)

    def open_yesterday(self) -> list[Task]:
        """Вчерашние незакрытые задачи, пока вчера ещё не закрыто (до `rollover`, 04:00).

        После полуночи «сегодня» — уже новое число, а вчерашний день закроется только в 04:00:
        задача 23:30 или неотмеченная вечерняя ещё живая. Без этого её не видно ни в приложении,
        ни голове, проверка «Сделано?» не приходит — и в 04:00 важная задача молча уходит в долг."""
        now = self.now()
        if f"{now:%H:%M}" >= self.rollover():
            return []
        yesterday = now.date() - timedelta(days=1)
        day = self.state.days.get(yesterday)
        if day and day.closed:
            return []
        return [t for t in self.state.tasks_on(yesterday) if t.is_open]

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

    def effective_mode(self) -> str:
        """Выключенный ментор (safety-контур) по тону равен 🟥 — правило №5."""
        return "red" if not self.state.mentor_enabled else self.state.mode

    def recovery_active(self) -> bool:
        until = self.state.recovery_until
        return bool(until) and datetime.fromisoformat(until) > self.now()

    def guard_completion(self, until: date, n: int = 7) -> list[float | None]:
        """Выполнение для Burnout Guard. День, закрытый в 🟥, — None: бот сам сказал «без плана»
        и о задачах не напоминал, значит, и провала не было. Иначе 🟥 кормил сам себя:
        нет напоминаний → задачи не отмечены → выполнение 0 % → снова 🟥 (D38)."""
        out = []
        for i, value in enumerate(self.state.series(until, n, "completion")):
            day = self.state.days.get(until - timedelta(days=n - 1 - i))
            out.append(None if day and day.closed and day.closed.get("mode") == "red" else value)
        return out

    def recompute_mode(self, source: str = "scheduler") -> str:
        today = self.today()
        yesterday = self.state.days.get(today - timedelta(days=1))
        mode, trigger = rules.guard_mode(
            sleep=self.state.series(today, 3, "sleep_min"),
            completion=self.guard_completion(today - timedelta(days=1)),
            sos=self.sos_active(),
            recovery=self.recovery_active(),
            after_red=bool(yesterday and yesterday.closed and yesterday.closed.get("mode") == "red"),
        )
        if mode != self.state.mode:
            with self.tx():
                self.emit("mode_changed", {"from": self.state.mode, "to": mode, "trigger": trigger}, source=source)
        return mode

    def resume_plan(self, *, source: str = "telegram") -> str:
        """«Вернуться к плану» после 🟥 — решение человека, кнопкой, а не модели (D38).
        Снимает ручной SOS и до следующей смены дня держит режим не выше 🟨: план
        возвращается без разгона. Выключенный safety-контуром ментор так не включается —
        только /mentor on."""
        if not self.state.mentor_enabled:
            raise ArvixError("Ментор выключен safety-контуром. Включить его можешь только ты сам: /mentor on")
        until = self.at(self.today() + timedelta(days=1), self.rollover())
        with self.tx():
            if self.sos_active():
                self.emit("sos", {"on": False, "until": None, "note": "возвращение к плану"}, source=source)
            self.emit("recovery_started", {"until": until.isoformat()}, source=source)
        return self.recompute_mode(source="l0")

    def red_exit(self) -> str:
        """Как выйти из 🟥 — фактом для модели и человека, а не надеждой «цифры подтянутся сами»."""
        trigger = self.state.mode_trigger
        if trigger.startswith("ручной"):
            return "кнопка «Вернуться к плану» или сам через сутки после включения"
        if trigger.startswith("сон"):
            return "нормальный сон сегодня (запиши его — режим пересчитается сразу) или кнопка «Вернуться к плану»"
        return "кнопка «Вернуться к плану»; без неё — сам, когда дни без плана выйдут из недельного окна"

    def sleep_target(self) -> int:
        """Норма сна в минутах: явное поле профиля, иначе расстояние между целевым отбоем
        и подъёмом из интервью, иначе конфиг. Норма подростка и взрослого различается —
        её задаёт человек своим распорядком, а не константа."""
        profile = self.state.profile
        if profile.get("sleep_target_min"):
            return int(profile["sleep_target_min"])
        gap = rules.minutes_after(profile.get("bedtime_target"), profile.get("wake_target"))
        if gap is not None and 240 <= gap <= 720:
            return gap
        return int(self.cfg.mech("sleep_target_min", 450))

    def deep_target(self, d: date | None = None) -> int:
        """Норма глубокой работы на день: столько, сколько её в плане дня (автонагрузка
        уже подогнала блоки под человека), а без плана — из конфига."""
        d = d or self.today()
        planned = sum(t.duration_min for t in self.state.tasks_on(d) if t.deep_work)
        return planned or int(self.cfg.mech("deep_target_min", 120))

    def fixed_blocks(self, d: date | None = None) -> list[dict[str, Any]]:
        """Обязательные блоки шаблона на дату (школа, дорога, смена) — занятое время для
        контекста модели и проверки конфликтов. Задачами они не становятся."""
        d = d or self.today()
        template = self.state.templates.get(d.weekday()) or {}
        return sorted((b for b in template.get("blocks", []) if b.get("start") and load.is_fixed(b)), key=lambda b: b["start"])

    # --- проверки ввода: не верить на слово (02-MECHANICS §13) ---------------------

    def goal_warnings(self, goal_id: str) -> list[str]:
        goal = self.state.goals.get(goal_id)
        return checks.goal_issues(goal, self.state.goals, self.today()) if goal else []

    def task_warnings(self, task: Task) -> list[str]:
        others = [t for t in self.state.tasks_on(task.local_date) if t.id != task.id and t.is_open]
        now = self.now().strftime("%H:%M") if task.local_date == self.today() else None
        return checks.task_issues(task, others, self.fixed_blocks(task.local_date), self.state.profile.get("bedtime_target"), now)

    def audit(self, limit: int = 6) -> list[str]:
        """Несостыковки, которые модель обязана поднять сама, не дожидаясь вопроса:
        цели без срока и метрики, дубли, лишние цели года, задачи внахлёст, сон по плану меньше 7 ч."""
        st = self.state
        items: list[str] = []
        for goal in st.goals.values():
            for issue in self.goal_warnings(goal["id"])[:2]:
                items.append(f"цель «{goal['title']}» [{goal['id']}]: {issue}")
        for task in st.tasks_on(self.today()):
            if task.is_open:
                items += [f"[{task.id}] «{task.title}»: {i}" for i in self.task_warnings(task) if "пересекается" in i or "обязательное" in i]
        if st.profile.get("bedtime_target") and st.profile.get("wake_target"):
            items += checks.sleep_target_issues(self.sleep_target())
        core_done = all(q in st.interview for q in ("main_goal", "main_goal_why"))
        if core_done and not any(g.get("kind") == "main" and g.get("status", "active") == "active" for g in st.goals.values()):
            items.append("главной цели нет — без неё план не к чему привязать")
        return items[:limit]

    def frozen(self, d: date | None = None) -> bool:
        """Важное, не сделанное в этот день, не уходит в долг: 🟥, тихий день, ментор выключен,
        3+ дня тишины, заявленная причина (rules.frozen)."""
        d = d or self.today()
        day = self.state.days.get(d)
        return rules.frozen(mode=self.state.mode, mentor_enabled=self.state.mentor_enabled, silent=bool(day and day.silent),
                            ignore_days=self.state.ignore_streak(d), reason=bool(day and day.reason))

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
            listing = "; ".join(f"{t.start or '--:--'} {t.title}" for t in self.state.tasks_on(self.today())) or "задач нет"
            raise ArvixError(f"Задача «{ref}» не найдена. Сегодня: {listing}")
        listing = "; ".join(f"{t.title} ({t.local_date:%d.%m})" for t in candidates[:6])
        raise ArvixError(f"Под «{ref}» подходит несколько задач: {listing}. Назови точнее.")

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
        project: str | None = None,
        source: str = "claude",
    ) -> Task:
        title = str(title).strip()
        if not title:
            raise ArvixError("Пустое название задачи")
        sphere = sphere if sphere in rules.SPHERES else "project"
        importance = rules.clamp(int(importance), 1, 5)
        difficulty = rules.clamp(int(difficulty), 1, 5)
        target = self.parse_day(day)
        if project:
            from arvix import projects

            project = projects.resolve(self, project)["id"]  # чужой или выдуманный id — отказ, а не задача-сирота
        with self.tx():
            debts = self.state.debts()
            # В 🟥 живые люди — часть восстановления, а не «необязательное»: блок снимается.
            if sphere in rules.OPTIONAL_SPHERES and len(debts) >= 2 and task_source == "user" and self.effective_mode() != "red":
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
                    **({"project": project} if project else {}),
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
        photos: list[str] | None = None,
        source: str = "claude",
    ) -> dict[str, Any]:
        """photos — пути фото отчёта в хранилище (D49): кладёт их receive_report_photo, голова видит их в контексте."""
        photos = [self.vault_rel(p) for p in (photos or [])][:10]
        if photos:
            proof_kind = "photo"
        with self.tx():
            task = self.resolve_task(ref)
            if task.status not in ("planned", "active", "debt"):
                raise ArvixError(f"«{task.title}» уже {STATUS_RU[task.status]} — повторно закрыть нельзя.")
            report = (report or "").strip() or None
            if photos and not report:
                report = "фото-отчёт"
            kind = proof_kind or ("report" if report else "confirm")
            if task.proof in ("report", "photo") and kind == "confirm":
                raise ArvixError(f"«{task.title}» требует отчёта: одним предложением — что именно сделано?")
            if kind == "photo" and task.proof != "photo":
                kind = "report"
            pct = rules.clamp(int(done_pct), 1, 100)
            # Фокус-таймер по задаче хотя бы на половину её длительности — самое сильное
            # доказательство из доступных; отчёт он не отменяет, в журнале видно оба.
            timed = task.focus_min and task.focus_min * 2 >= max(task.duration_min, 1)
            deep = task.duration_min * pct // 100 if task.deep_work else 0
            now = self.now()
            doubts = checks.report_issues(
                task.title, now,
                self.at(task.local_date, task.start) if task.start and task.status != "debt" else None,
                datetime.fromisoformat(task.actual_start) if task.actual_start else None,
                task.duration_min, pct,
            )
            payload = {"id": task.id, "done_pct": pct, "report": report, "proof_kind": kind, "deep_min": deep}
            if photos:
                payload["photos"] = photos
            if timed:
                payload["focus_min"] = task.focus_min
            if doubts:
                payload["doubts"] = doubts  # отчёт записан, но сомнение видно в журнале и разборе
            self.emit("task_completed", payload, source=source, entity_id=task.id)
            if task.project and report:
                # Отчёт о блоке проекта — сразу запись журнала проекта (D47): прогресс виден без второго ввода.
                self.emit("project_logged", {"project_id": task.project, "kind": "update", "text": report[:2000], "minutes": 0,
                                             "task_id": task.id}, source=source, entity_id=task.project)
        if task.project:
            from arvix import projects

            projects.sync_notes(self, task.project)
        self.recompute_mode(source="l0")
        return {"task": task, "debt_closed": task.debt_since is not None, "warnings": doubts}

    def fail_task(self, ref: Any, *, reason: str = "", source: str = "claude") -> dict[str, Any]:
        with self.tx():
            task = self.resolve_task(ref)
            if not task.is_open:
                raise ArvixError(f"«{task.title}» уже {STATUS_RU[task.status]}")
            debt = task.importance >= 4 and not self.frozen()
            self.emit(
                "task_failed",
                {"id": task.id, "reason": (reason or "не указана")[:500], "debt": debt},
                source=source,
                entity_id=task.id,
            )
        self.recompute_mode(source="l0")  # 1.3 плана: режим пересчитывается при закрытии/провале задачи
        return {"task": task, "debt": debt}

    def explain_failure(self, ref: Any, reason: str, *, source: str = "claude") -> Task:
        """Причина провала, присланная позже кнопки «Нет» — отдельным событием,
        журнал не правится задним числом."""
        with self.tx():
            task = self.resolve_task(ref)
            self.emit("task_reason", {"id": task.id, "reason": reason[:500]}, source=source, entity_id=task.id)
        return task

    def defer_task(self, ref: Any, minutes: int | None = 15, *, to: Any = None, day: Any = None, source: str = "claude") -> Task:
        """Перенос: на minutes вперёд (кнопки «+15») или на точное время to («на 19:45»).
        Точное время — для головы (D46): «переношу на 19:45» и minutes, посчитанные моделью, расходились."""
        with self.tx():
            task = self.resolve_task(ref)
            if task.status != "planned":
                raise ArvixError(f"Отложить можно только запланированную задачу, а «{task.title}» {STATUS_RU[task.status]}")
            now = self.now().replace(second=0, microsecond=0)
            if (target := parse_hhmm(to)) is not None:
                moved = self.at(self.parse_day(day) if day else task.local_date, target)
                if moved < now:
                    raise ArvixError(f"{target} уже прошло — перенести «{task.title}» можно только вперёд")
                base = self.at(task.local_date, task.start) if task.start else now
                minutes = int((moved - base).total_seconds() // 60)
            elif minutes:
                base = self.at(task.local_date, task.start) if task.start else now
                moved = max(base, now) + timedelta(minutes=int(minutes))
            else:
                raise ArvixError(f"Перенос «{task.title}» без времени — скажи, на сколько или во сколько")
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

    def log_sleep(self, duration: Any = None, *, bedtime: Any = None, wake: Any = None, day: Any = None,
                  source: str = "claude") -> dict[str, Any]:
        """Сон длительностью («7:30») или отбоем и подъёмом («лёг 01:00, встал 08:30» → 7ч30м:
        арифметику через полночь делает код, а не модель)."""
        bed, up = parse_hhmm(bedtime), parse_hhmm(wake)
        if duration in (None, "") and bed and up:
            minutes = sleep_between(bed, up)
        elif duration in (None, ""):
            raise ArvixError("Нужна длительность сна или время отбоя и подъёма")
        else:
            minutes = parse_duration(duration)
        if not 0 < minutes <= 20 * 60:
            raise ArvixError("Сон должен быть от 1 минуты до 20 часов")
        target = self.parse_day(day)
        before = self.state.mode
        with self.tx():
            self.emit(
                "sleep_recorded",
                {"duration_min": minutes, "bedtime": bed, "wake": up, "date": target.isoformat(), "source": source},
                source=source,
            )
        mode = self.recompute_mode(source="l0")
        return {"duration_min": minutes, "date": target, "mode": mode, "mode_before": before, "bedtime": bed, "wake": up,
                "warnings": checks.sleep_issues(minutes)}

    # Сон без ручного ввода (D48): код угадывает отбой и подъём по действиям человека,
    # пишет только после подтверждения — от сна зависит режим, а догадка не факт.
    NIGHT_START = "18:00"

    def night_end(self) -> str:
        return parse_hhmm(self.cfg.mech("sleep_night_end", "05:00")) or "05:00"

    def is_night(self, when: datetime | None = None) -> bool:
        clock_time = f"{(when or self.now()):%H:%M}"
        return clock_time >= self.NIGHT_START or clock_time < self.night_end()

    def note_bedtime(self, *, source: str = "telegram") -> dict[str, Any]:
        """«Ложусь» — время отбоя в ночь, которая кончится утром: 23:50 — ночь на завтра, 00:40 — на сегодня."""
        now = self.now()
        if not self.is_night(now):
            raise ArvixError(f"Отбой записывается вечером и ночью ({self.NIGHT_START}–{self.night_end()})")
        night = now.date() + timedelta(days=1 if f"{now:%H:%M}" >= self.NIGHT_START else 0)
        at = f"{now:%H:%M}"
        with self.tx():
            self.emit("bedtime_noted", {"at": at, "night": night.isoformat()}, source=source)
        return {"at": at, "night": night}

    def sleep_guess(self, d: date | None = None) -> dict[str, Any] | None:
        """Ночь перед утром d: отбой — «ложусь» или последнее действие ночью, подъём — первое действие утром.
        Без обеих половин или с нелепой длительностью (меньше часа, больше 16 ч) — None."""
        d = d or self.today()
        days = self.state.days
        today, yesterday = days.get(d), days.get(d - timedelta(days=1))
        end = self.night_end()
        bed, bed_src = (today.bed_noted, "noted") if today and today.bed_noted else (None, "")
        if not bed:
            late = [t for t in (yesterday.user_times if yesterday else []) if t >= self.NIGHT_START]
            late += [t for t in (today.user_times if today else []) if t < end]
            bed, bed_src = (late[-1], "last") if late else (None, "")
        until = parse_hhmm(self.cfg.mech("sleep_ask_until", "14:00")) or "14:00"
        morning = [t for t in (today.user_times if today else []) if end <= t < until]
        if not (bed and morning):
            return None
        minutes = sleep_between(bed, morning[0])
        if not 60 <= minutes <= 16 * 60:
            return None
        return {"bedtime": bed, "bed_src": bed_src, "wake": morning[0], "wake_src": "first", "duration_min": minutes}

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

    def log_focus(self, minutes: int, *, task_ref: Any = None, topic: str | None = None, source: str = "claude") -> Task | None:
        """Фокус-сессия. topic — тема без задачи («физика»): минуты идут в глубокую работу дня."""
        task = self.resolve_task(task_ref) if task_ref else None
        payload: dict[str, Any] = {"duration_min": int(minutes), "task_id": task.id if task else None}
        if topic and not task:
            payload["topic"] = str(topic).strip()[:120]
        with self.tx():
            self.emit("focus_session", payload, source=source, entity_id=task.id if task else None)
        return task

    def note_focus(self, event_id: int, note: str, *, source: str = "claude") -> dict[str, Any]:
        """«Что сделал» к прошедшей сессии — отдельным событием, сама сессия не меняется."""
        note = note.strip()
        if not note:
            raise ArvixError("Пустая заметка к фокусу")
        ev = next((e for e in self.store.read(max(0, int(event_id) - 1)) if e.id == int(event_id)), None)
        if ev is None or ev.kind != "focus_session":
            raise ArvixError("Нет такой фокус-сессии")
        with self.tx():
            self.emit("focus_noted", {"focus_event_id": ev.id, "date": ev.local_date.isoformat(), "note": note[:1000]}, source=source,
                      entity_id=ev.entity_id)
        return {"event_id": ev.id, "note": note[:1000]}

    def declare_reason(self, reason: str, *, source: str = "claude") -> dict[str, Any]:
        """Причина дня («заболел», «семья»): важное, не сделанное сегодня, не уйдёт в долг,
        а причина попадёт в разбор (02-MECHANICS §4). Щитов и жетонов больше нет (D41)."""
        if not reason.strip():
            raise ArvixError("Причина пуста")
        with self.tx():
            self.emit("reason_declared", {"reason": reason[:300]}, source=source)
        return {"reason": reason[:300]}

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

    def save_note(self, rel: str, content: str, *, base_sha: str | None, source: str = "web") -> dict[str, Any]:
        """Правка человека из приложения (или новая заметка при base_sha=None). Файл изменился
        после открытия — NoteConflict с текущим текстом; ничего не записано."""
        from arvix.vault import VaultConflict, VaultError

        if not str(rel).endswith(".md"):
            rel = f"{rel}.md"
        try:
            result = self.vault.save(rel, content, base_sha=base_sha)
        except VaultConflict as exc:
            raise NoteConflict(str(exc), exc.path, exc.current) from exc
        except VaultError as exc:
            raise ArvixError(str(exc)) from exc
        return self._note_event(result, "create" if result["created"] else "edit", source) if result["changed"] else result

    def update_note(self, rel: str, transform: Any, *, source: str = "claude") -> dict[str, Any]:
        result = self.vault.update_text(rel, transform, owned_sha=self.state.notes.get(rel))
        return self._note_event(result, "fields", source) if result["changed"] else result

    def vault_rel(self, path: str) -> str:
        """Путь внутри хранилища или отказ: «../../etc/passwd» отчётом не станет."""
        root = self.vault.root.resolve()
        full = (root / str(path)).resolve()
        if root not in full.parents or not full.is_file():
            raise ArvixError(f"Файла «{path}» нет в хранилище")
        return full.relative_to(root).as_posix()

    def receive_report_photo(self, data: bytes, name: str, mime: str = "", *, source: str = "web") -> str:
        """Фото отчёта по задаче (D49) — в папку «Отчёты» рядом с файлами; голову не зовёт, путь вернёт."""
        from arvix import files

        if files.classify(name, mime) != "image":
            raise ArvixError(f"«{name}» — не фото (jpg, png, webp). Отчёт принимает картинки")
        base = (self.vault.paths.get("files") or "00_Inbox/Файлы").rstrip("/")
        return self.receive_file(data, name, mime, source=source, folder=f"{base}/Отчёты")["path"]

    def receive_file(self, data: bytes, name: str, mime: str = "", *, stt: Any = None, caption: str = "",
                     source: str = "telegram", folder: str | None = None) -> dict[str, Any]:
        """Файл от человека — в хранилище (arvix/files.py), факт — в журнал. Читает его голова."""
        from arvix import files

        try:
            info = files.store(self, data, name, mime, stt=stt, folder=folder)
        except files.FileError as exc:
            raise ArvixError(str(exc)) from exc
        with self.tx():
            self.emit("file_received", {"name": info["name"], "kind": info["kind"], "size": info["size"], "path": info["path"],
                                        "read": info["read"][:20], "caption": caption[:500]}, source=source)
        return info

    def capture_note(self, text: str, *, source: str = "claude") -> str | None:
        if not text.strip():
            raise ArvixError("Пустая заметка")
        path = None
        if self.cfg.vault:
            path = self.vault.inbox(text, self.now())
        with self.tx():
            self.emit("note_captured", {"text": text[:8000], "path": path}, source=source)
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
                {"id": fact_id, "topic": (topic or "general")[:40], "fact": fact[:4000], "confidence": rules.clamp(int(confidence), 1, 5), "valid_until": valid_until},
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
                **({"fixed": bool(block["fixed"])} if "fixed" in block else {}),
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
        """Директива без доказательств отклоняется (03-DATA-MODEL §4, инв. 5)."""
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

    # --- учебный блок (06-LEARNING §8) -----------------------------------------------

    def lesson_started(self, task_ref: Any, lesson: dict[str, Any], *, note_path: str | None = None, source: str = "telegram") -> Task:
        from arvix import lesson as lesson_mod

        task = self.resolve_task(task_ref)
        with self.tx():
            self.emit("lesson_started", {
                "task_id": task.id, "topic": str(lesson.get("topic", ""))[:200], "subject": lesson_mod.subject_of(task.title)[:80],
                "roadmap_node": str(lesson.get("roadmap_node") or "")[:200], "minutes": task.duration_min,
                "plan": [str(s.get("step", ""))[:160] for s in lesson.get("plan") or []][:8],
                "sources": [str(s)[:160] for s in lesson.get("sources") or []][:6],
                "questions": [str(c.get("q", ""))[:300] for c in lesson.get("check") or []][:6],
                "note": note_path, "fallback": bool(lesson.get("fallback")),
                # Урок целиком (D60): сессию, которую сменила другая, можно вернуть как была — без второго вызова головы
                "lesson": {"topic": str(lesson.get("topic", ""))[:200], "why": str(lesson.get("why") or "")[:300],
                           "roadmap_node": str(lesson.get("roadmap_node") or "")[:200],
                           "plan": [{k: s.get(k) for k in ("stage", "from_min", "to_min", "step", "tool") if s.get(k) is not None}
                                    for s in lesson.get("plan") or [] if isinstance(s, dict)][:8],
                           "check": [{"q": str(c.get("q", ""))[:400], "a": str(c.get("a", ""))[:400]} for c in lesson.get("check") or []][:6],
                           "sources": [str(x)[:300] for x in lesson.get("sources") or []][:8], "fallback": bool(lesson.get("fallback"))},
            }, source=source, entity_id=task.id)
        return task

    def lesson_checked(self, task_ref: Any, *, score_pct: int | None, answers: str, gaps: list[str], next_step: str = "", source: str = "telegram") -> Task:
        task = self.resolve_task(task_ref)
        with self.tx():
            self.emit("lesson_checked", {
                "task_id": task.id, "score_pct": None if score_pct is None else rules.clamp(int(score_pct), 0, 100),
                "answers": answers[:3000], "gaps": [str(g)[:200] for g in gaps][:8], "next_step": next_step[:300],
            }, source=source, entity_id=task.id)
        return task

    def lesson_history(self, subject: str, limit: int = 5) -> list[str]:
        """Прошлые уроки по предмету — чтобы следующий блок шёл дальше, а не по кругу."""
        rows = [x for x in self.state.lessons if x.get("subject", "").lower() == subject.lower()]
        out = []
        for x in rows[-limit:]:
            score = f" — {x['score']}%" if x.get("score") is not None else " — без проверки"
            out.append(f"{x['date'][8:10]}.{x['date'][5:7]} {x['topic']}{score}")
        return out

    def concept_template(self) -> str | None:
        """Шаблон конспекта человека ([learning] concept_template или Templates/Concept.md); нет — None."""
        from arvix.vault import VaultError

        if not self.cfg.vault:
            return None
        vault = self.vault
        rel_tpl = self.cfg.section("learning").get("concept_template") or next(
            (vault.rel(p) for p in vault.root.rglob("Concept.md") if "emplate" in str(p.parent.name)), None)
        if not rel_tpl:
            return None
        try:
            return vault.read(rel_tpl)
        except VaultError:
            return None

    def concept_skeleton(self, title: str, subject: str, questions: list[str], sources: list[str]) -> str | None:
        """Каркас заметки по шаблону человека в его папку концептов; чужой файл не трогается.
        Возвращает путь или None (хранилища нет / заметка уже есть)."""
        from arvix import lesson as lesson_mod
        from arvix.vault import VaultError

        if not self.cfg.vault:
            return None
        section = self.cfg.section("learning")
        vault = self.vault
        template = self.concept_template()
        folder = section.get("concept_dir") or next(
            (p.name for p in sorted(vault.root.iterdir()) if p.is_dir() and "concept" in p.name.lower()), None)
        if not folder:
            folder = self.cfg.vault_paths.get("notes") or vault.paths.get("notes") or "Конспекты"
        rel = f"{folder}/{lesson_mod.safe_name(title)}.md"
        try:
            if vault.resolve(rel).exists():
                return rel  # конспект уже есть — это файл человека
            result = self.write_note(rel, lesson_mod.skeleton(template, title, subject, self.today(), questions, sources), source="telegram")
        except (ArvixError, VaultError):
            return None
        return result["path"]

    # --- сообщения ------------------------------------------------------------------

    # Переписка хранится дословно: это и есть долгая память Arvix (arvix/memory.py).
    # Раньше ответ резался до 600 символов — и через неделю он «забывал» собственные объяснения.
    MESSAGE_LIMIT = 16000

    def message_in(self, text: str, *, channel: str = "telegram", project: str | None = None, study: str | None = None,
                   reply_to: int | None = None, tg_id: int | None = None) -> int:
        """reply_to — id события-сообщения, на которое человек ответил цитатой (D52);
        tg_id — номер сообщения в Telegram: по нему Arvix отвечает цитатой там же."""
        payload: dict[str, Any] = {"text": text[: self.MESSAGE_LIMIT], "channel": channel}
        if project:
            payload["project"] = project  # чат проекта (D47): своя нить в общей переписке
        if study:
            payload["study"] = study  # чат учебной сессии (D56): нить урока, id учебной задачи
        if reply_to:
            payload["reply_to"] = int(reply_to)
        if tg_id:
            payload["tg_id"] = int(tg_id)
        with self.tx():
            return self.emit("message_in", payload, source=channel).id

    def message_out(self, text: str, *, key: str | None = None, channel: str = "telegram",
                    buttons: list[list[tuple[str, str]]] | None = None, project: str | None = None,
                    study: str | None = None, reply_to: int | None = None, tg_id: int | None = None) -> int:
        payload: dict[str, Any] = {"text": text[: self.MESSAGE_LIMIT], "key": key, "channel": channel}
        if project:
            payload["project"] = project
        if study:
            payload["study"] = study
        if buttons:  # приложение показывает те же кнопки под сообщением
            payload["buttons"] = [[[t, d] for t, d in row] for row in buttons]
        if reply_to:
            payload["reply_to"] = int(reply_to)
        if tg_id:
            payload["tg_id"] = int(tg_id)
        with self.tx():
            return self.emit("message_out", payload, source="bot").id

    MESSAGE_KINDS = ("message_in", "message_out")

    # --- как в мессенджере: реакции, прочитано, в сети (D52) ---------------------------
    # Набор приложения — немного и самые ходовые. В Telegram человек может поставить любую реакцию — она тоже пишется.
    REACTIONS = ("👍", "👎", "❤️", "💔", "❓", "🔥", "😂", "🙏")
    # «Непонятно»: в Telegram знака вопроса среди реакций нет — там его роль играют 🤔 и 🤨
    CONFUSED = frozenset({"❓", "🤔", "🤨", "🤷", "🤷‍♂", "🤷‍♀"})
    ONLINE_SECONDS = 90  # пульс приложения — раз в 30 с; дольше тишины — «не в сети»

    @staticmethod
    def reaction_key(emoji: str) -> str:
        """❤ и ❤️ — одна реакция: Telegram присылает без селектора вариантов."""
        return (emoji or "").replace("\ufe0f", "").strip()

    def react(self, message_id: int, emoji: str, *, channel: str = "web") -> dict[str, Any]:
        """Реакция человека на сообщение Arvix. Пустая строка — снять. Одна реакция на сообщение, как в Telegram."""
        target = self.message(int(message_id or 0))
        if target is None or target.kind != "message_out":
            raise ArvixError("Реакция ставится на сообщение Arvix")
        emoji = (emoji or "").strip()[:16]
        current = (self.state.reactions.get(target.id) or {}).get("emoji", "")
        if self.reaction_key(emoji) == self.reaction_key(current):
            return {"message": target.id, "emoji": current, "changed": False}
        with self.tx():
            self.emit("message_reacted", {"message": target.id, "emoji": emoji, "channel": channel}, source=channel)
        return {"message": target.id, "emoji": emoji, "changed": True}

    def mark_read(self, upto: int, *, channel: str = "web") -> bool:
        """Человек дочитал ленту до сообщения upto (приложение видит это само). Источник «seen»:
        прочитать — не действие, протокол игнора на это не смотрит."""
        upto = min(int(upto or 0), self.state.last_event_id)
        if upto <= self.state.read_upto:
            return False
        with self.tx():
            self.emit("messages_read", {"upto": upto, "channel": channel}, source="seen")
        return True

    def presence_ping(self) -> None:
        """Приложение открыто и на экране. Не событие журнала: пульс раз в 30 с засорил бы его, а прошлое
        «в сети» никому не нужно — нужно, в сети ли он сейчас и давно ли зашёл (runtime, как last_in_at)."""
        now = self.now().timestamp()
        seen = self.store.kv_get("presence") or {}
        since = seen.get("since") if now - float(seen.get("seen") or 0) <= self.ONLINE_SECONDS else now
        self.store.kv_set("presence", {"seen": now, "since": since})

    def presence(self) -> dict[str, Any]:
        """{online, since, seen} — в приложении ли человек сейчас и когда был последний раз."""
        seen = self.store.kv_get("presence") or {}
        last = float(seen.get("seen") or 0)
        online = bool(last) and self.now().timestamp() - last <= self.ONLINE_SECONDS
        return {"online": online, "since": seen.get("since") if online else None, "seen": last or None}

    def message(self, event_id: int) -> Any:
        """Сообщение переписки по id события; не сообщение — None."""
        event = self.store.event(event_id) if event_id else None
        return event if event is not None and event.kind in self.MESSAGE_KINDS else None

    def message_by_tg(self, tg_id: int, window: int = 3000) -> Any:
        """Сообщение по номеру в Telegram — человек ответил цитатой на сообщение в чате."""
        start = max(0, self.state.last_event_id - window)
        for event in reversed(self.store.read(start)):
            if event.kind in self.MESSAGE_KINDS and event.payload.get("tg_id") == int(tg_id):
                return event
        return None

    def sent(self, key: str, d: date | None = None) -> bool:
        day = self.state.days.get(d or self.today())
        return bool(day and key in day.out_keys)

    # --- нагрузка ------------------------------------------------------------------------

    def budget(self) -> dict[str, Any]:
        """Нагрузка недели. С шаблонами дней — автонагрузка: объём каналов задают
        коэффициенты (arvix/load.py), пересмотр раз в неделю. Без шаблонов —
        часы из интервью или конфига, глубокая работа по умолчанию 35%."""
        st = self.state
        factors = load.factors_of(st.budget)
        since = (st.budget or {}).get("since") or (st.first_date or self.today()).isoformat()
        if st.templates:
            week = load.week_load(st.templates, factors)
            total, deep = week["total"] - week["fixed"], week["deep"]  # бюджет — своё время, без школы и смен
            channels = {ch: week[ch] for ch in (*load.CHANNELS, "fixed")}
        else:
            total = int(st.profile.get("week_budget_min") or self.cfg.mech("week_budget_min", 1560))
            deep = int(st.profile.get("week_deep_budget_min") or (total * 0.35 if st.profile.get("week_budget_min") else self.cfg.mech("week_deep_budget_min", 480)))
            channels = {}
        review = date.fromisoformat(since) + timedelta(days=load.REVIEW_DAYS)
        return {"week_min": total, "deep_min": deep, "since": since, "next_review": review, "factors": factors,
                "channels": channels, "auto": bool(st.templates), "verdict": st.budget.get("verdict"),
                "reason": st.budget.get("reason"), "change": st.budget.get("change")}

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

    def status(self) -> dict[str, Any]:
        """Сводка — только факты из журнала (D41): что сделано сегодня и за неделю, сколько глубокой
        работы, как спал, что в долге. Ни одного числа, которое код «назначает» сам."""
        st = self.state
        today = self.today()
        tasks = st.tasks_on(today)
        week = st.week_stats(today)
        plan = self.budget()
        sleeps = [s for s in st.series(today, 7, "sleep_min") if s]
        return {
            "mode": st.mode, "effective_mode": self.effective_mode(), "mode_trigger": st.mode_trigger,
            "mentor_enabled": st.mentor_enabled,
            "done": sum(1 for t in tasks if t.status == "done"), "total": len(tasks), "completion": st.completion(today),
            "week_min": week["productive_min"], "week_budget": plan["week_min"],
            "week_deep": week["deep_min"], "week_deep_budget": plan["deep_min"],
            "sleep_avg": round(sum(sleeps) / len(sleeps)) if sleeps else None, "sleep_days": len(sleeps),
            "sleep_target": self.sleep_target(),
            "debts": len(st.debts()), "autonomy": st.autonomy(today),
        }
