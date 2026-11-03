"""Проактив L0 (02-MECHANICS §7, §10): брифинг, напоминания T−5 / T+0 / T+конец,
чек-ин в 15:00, разбор, отбой, ретро, фокус-таймер и протокол игнора.

Решение «когда и что писать» — код. Модель зовётся только для разбора и ретро.
Каждое сообщение дедуплицируется ключом в журнале (message_out.key), поэтому
после сна ноутбука ничего не дублируется, а пропущенное отправляется только
в разумном окне.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from arvix.config import parse_hhmm
from arvix.telegram import templates as tpl

log = logging.getLogger("arvix.scheduler")
BRIEF_WINDOW = timedelta(hours=3)
CHECK_WINDOW = timedelta(hours=3)
RETRY_AFTER = timedelta(hours=1)


class Scheduler:
    def __init__(self, bot: Any):
        self.bot = bot
        self.core = bot.core

    def _when(self, key: str) -> datetime | None:
        value = parse_hhmm(self.core.cfg.schedule(key))
        return datetime.combine(self.core.today(), value, tzinfo=self.core.tz) if value else None

    def brief_time(self) -> datetime:
        configured = self._when("brief")
        if configured:
            return configured
        wake = self.core.state.profile.get("wake_target") or "07:30"
        return self.core.at(self.core.today(), wake) + timedelta(minutes=15)

    def tick(self) -> None:
        core = self.core
        core.refresh()
        now = core.now()
        today = now.date()
        day = core.state.day(today)
        silent_days = core.state.ignore_streak(today - timedelta(days=1))
        quiet = day.silent or not core.state.mentor_enabled

        self.focus(now)
        if silent_days >= 2:
            self.ignore_protocol(now, silent_days)
            return
        if not quiet:
            if silent_days == 0:  # на второй день молчания — только утро и вечер
                self.reminders(now)
                self.midday(now)
                self.bedtime(now)
            self.brief(now, prefix=tpl.IGNORE_DAY2 if silent_days == 1 else "")
            self.retro(now)
        self.debrief(now)

    def _once(self, key: str, when: datetime, now: datetime, window: timedelta) -> bool:
        return when <= now < when + window and not self.core.sent(key)

    def brief(self, now: datetime, prefix: str = "") -> None:
        if self._once(f"brief:{now.date().isoformat()}", self.brief_time(), now, BRIEF_WINDOW):
            self.bot.send_brief(prefix)

    def reminders(self, now: datetime) -> None:
        core = self.core
        for task in core.state.tasks_on(now.date()):
            if not task.start or not task.is_open:
                continue
            start = core.at(task.local_date, task.start)
            end = start + timedelta(minutes=max(task.duration_min, 5))
            before = f"rem5:{task.id}:{task.start}"
            if start - timedelta(minutes=5) <= now < start and task.status == "planned" and not core.sent(before):
                minutes = max(1, int((start - now).total_seconds() // 60) + 1)
                self.bot.send(tpl.reminder_before(task, minutes), tpl.task_buttons_before(task.id), key=before)
            go = f"rem0:{task.id}:{task.start}"
            if start <= now < start + timedelta(minutes=10) and task.status == "planned" and not core.sent(go):
                self.bot.send(tpl.reminder_start(task), key=go)
            check = f"remend:{task.id}"
            if end <= now < end + CHECK_WINDOW and not core.sent(check):
                self.bot.send(tpl.reminder_check(task), tpl.task_buttons_check(task.id), key=check)

    def midday(self, now: datetime) -> None:
        when = self._when("midday")
        key = f"midday:{now.date().isoformat()}"
        due = when and self._once(key, when, now, timedelta(hours=2)) and self.core.effective_mode() != "red"
        if due and (text := tpl.midday(self.core)):
            self.bot.send(text, key=key)

    def debrief(self, now: datetime) -> None:
        when = self._when("debrief")
        if not when:
            return
        rollover = parse_hhmm(self.core.cfg.schedule("rollover")) or datetime.min.time()
        until = datetime.combine(now.date() + timedelta(days=1), rollover, tzinfo=self.core.tz)
        if when <= now < until and not self.core.sent(f"debrief:{now.date().isoformat()}"):
            self.bot.send_debrief()

    def bedtime(self, now: datetime) -> None:
        target = self.core.state.profile.get("bedtime_target")
        if not target:
            return
        warn = int(self.core.cfg.schedule("bedtime_warning_min") or 30)
        bed = self.core.at(now.date(), target)
        if bed.hour < 12:  # отбой после полуночи — это ночь следующей даты
            bed += timedelta(days=1)
        key = f"bed:{now.date().isoformat()}"
        if self._once(key, bed - timedelta(minutes=warn), now, timedelta(minutes=warn)):
            self.bot.send(f"🌙 Через {warn} минут отбой ({target}). Экран убрать, задачи закрыть.", key=key)

    def retro(self, now: datetime) -> None:
        core = self.core
        if now.weekday() != int(core.cfg.schedule("retro_weekday") or 6) or core.effective_mode() == "red":
            return
        when = self._when("retro")
        key = f"retro:{now.date().isoformat()}"
        if not when or not (when <= now < when + timedelta(hours=4)) or core.sent(key):
            return
        attempt = core.store.kv_get("retro_attempt")
        if attempt and datetime.fromisoformat(attempt) > now - RETRY_AFTER:
            return
        core.store.kv_set("retro_attempt", now.isoformat())
        if not self.bot.run_retro():
            log.warning("ретро не собралось — повтор через час")

    def focus(self, now: datetime) -> None:
        state = self.core.store.kv_get("focus")
        if state and datetime.fromisoformat(state["until"]) <= now:
            self.core.store.kv_del("focus")
            minutes = int(state["minutes"])
            self.bot.send(
                f"Фокус {minutes} минут закончен. Без прерываний?",
                [[("✅ Да", f"f:ok:{minutes}"), ("⚠️ Прерывали", f"f:int:{minutes}")]],
                key=f"focus:{state['until']}",
            )

    def ignore_protocol(self, now: datetime, silent_days: int) -> None:
        """02-MECHANICS §7: день 3 — одно сообщение и заморозка штрафов, дни 4–7 —
        «я здесь» раз в день, дальше — тишина до возвращения."""
        if silent_days > 7:
            return
        key = f"ignore:{now.date().isoformat()}"
        if self._once(key, self.brief_time(), now, timedelta(hours=12)):
            self.bot.send(tpl.IGNORE.get(silent_days, tpl.IGNORE_LATER), key=key)
