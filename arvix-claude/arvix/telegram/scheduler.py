"""Проактив L0 (02-MECHANICS §8, §12): брифинг, напоминания T−5 / T+0 / T+конец,
чек-ин в 15:00, разбор, отбой, ретро, фокус-таймер, панель дня и протокол игнора.

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
from arvix.telegram.api import TelegramError

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
        red = core.effective_mode() == "red"
        back = bool(day.user_actions)  # человек уже что-то написал или нажал сегодня

        self.focus(now)
        self.panel()
        if silent_days >= 2 and not back:
            self.ignore_protocol(now, silent_days)
            return
        # Обычный день — или вернулся после одного дня тишины. После долгого молчания день
        # возвращения идёт без стены напоминаний: брифинг, отбой и разбор (02-MECHANICS §8).
        full = silent_days == 0 or (back and silent_days == 1)
        if not quiet:
            if full and not red:  # в 🟥 план — одна маленькая вещь: напоминаний о задачах нет
                self.reminders(now)
                self.midday(now)
                self.initiative(now)
                self.curiosity(now)
            if full or back:
                self.bedtime(now, gentle=red)
            self.brief(now, prefix=tpl.IGNORE_DAY2 if silent_days == 1 and not back else "")
            self.sleep_question(now, day)
            self.retro(now)
        self.debrief(now)

    def _once(self, key: str, when: datetime, now: datetime, window: timedelta) -> bool:
        return when <= now < when + window and not self.core.sent(key)

    def initiative(self, now: datetime) -> None:
        """Повод написать первым (D59): блок прошёл молча, тема снова уезжает. Повод и гигиену проверяет код
        (arvix/initiative.py), слова и решение «стоит ли» — голова. Квоты нет, есть интервал GAP_MIN."""
        from arvix import initiative

        if initiative.blocked(self.core, now):
            return
        keys, lines = initiative.reasons(self.core, now)
        if not keys:
            return
        initiative.remember(self.core, now, keys)  # до вызова головы: упавший вызов не повторяется каждые 5 с
        try:
            self.bot.send_initiative(lines)
        except TelegramError as exc:
            log.warning("инициатива не отправлена: %s", exc)

    def curiosity(self, now: datetime) -> None:
        """Раз в день Arvix пишет первым (bot.send_curiosity). Не во время разговора и не
        во время фокуса; одна попытка в день — молчащая голова не дёргается каждые 20 с."""
        when = self._when("curiosity")
        key = f"curiosity:{now.date().isoformat()}"
        if not when or not (when <= now < when + CHECK_WINDOW) or self.core.sent(key):
            return
        if self.core.store.kv_get("curiosity_tried") == now.date().isoformat() or self.core.store.kv_get("focus"):
            return
        last_in = self.core.store.kv_get("last_in_at")
        if last_in and now.timestamp() - float(last_in) < 2 * 3600:
            return
        self.core.store.kv_set("curiosity_tried", now.date().isoformat())
        try:
            self.bot.send_curiosity()
        except TelegramError as exc:
            log.warning("любопытство не отправлено: %s", exc)

    def brief(self, now: datetime, prefix: str = "") -> None:
        if self._once(f"brief:{now.date().isoformat()}", self.brief_time(), now, BRIEF_WINDOW):
            self.bot.send_brief(prefix)

    def reminders(self, now: datetime) -> None:
        core = self.core
        # Вчерашние незакрытые — тоже: задача 23:30–00:15 иначе не получала «Сделано?» и в 04:00
        # уходила в долг без вопроса.
        for task in core.open_yesterday() + core.state.tasks_on(now.date()):
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
                if not self.bot.on_block_start(task, key=go):  # шаги «что и чем» (D62) — вместе с «Блок пошёл»
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
        until = self.core.at(now.date() + timedelta(days=1), self.core.rollover())
        if not (when <= now < until) or self.core.sent(f"debrief:{now.date().isoformat()}"):
            return
        # Разбор зовёт голову. Не дошёл (бот заблокирован, сеть) — следующая попытка через час,
        # а не на каждом тике: иначе каждые 5 с вызов модели впустую (как у ретро).
        attempt = self.core.store.kv_get("debrief_attempt")
        if attempt and datetime.fromisoformat(attempt) > now - RETRY_AFTER:
            return
        self.core.store.kv_set("debrief_attempt", now.isoformat())
        try:
            self.bot.send_debrief()
        except TelegramError as exc:
            log.warning("разбор не отправлен — повтор через час: %s", exc)

    def sleep_question(self, now: datetime, day: Any) -> None:
        """Сон не записан, человек уже что-то сделал этим утром — спросить с догадкой (D48).
        До первого действия не спрашиваем: подъёма ещё не видно, а вопрос в пустоту — шум."""
        until = self.core.cfg.mech("sleep_ask_until", "14:00")
        end = self.core.night_end()
        if day.sleep_min or f"{now:%H:%M}" >= until or not any(end <= t < until for t in day.user_times):
            return
        self.bot.ask_sleep()

    def bedtime(self, now: datetime, gentle: bool = False) -> None:
        target = self.core.state.profile.get("bedtime_target")
        if not target:
            return
        warn = int(self.core.cfg.schedule("bedtime_warning_min") or 30)
        bed = self.core.at(now.date(), target)
        if bed.hour < 12:  # отбой после полуночи — это ночь следующей даты
            bed += timedelta(days=1)
        key = f"bed:{now.date().isoformat()}"
        tail = "Сон сейчас важнее всего." if gentle else "Экран убрать, задачи закрыть."
        if self._once(key, bed - timedelta(minutes=warn), now, timedelta(minutes=warn)):
            self.bot.send(f"🌙 Через {warn} минут отбой ({target}). {tail}", tpl.BED_BUTTONS, key=key)

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
        """Обратный отсчёт в сообщении таймера и вопрос о прерываниях по окончании — в боте."""
        self.bot.focus_tick(now)

    def panel(self) -> None:
        """Панель дня живёт: сделанное снаружи (CLI, Claude Code, голова) видно без нажатий."""
        try:
            self.bot.refresh_panel()
        except TelegramError as exc:
            log.info("панель не обновилась: %s", exc)

    def ignore_protocol(self, now: datetime, silent_days: int) -> None:
        """02-MECHANICS §8: день 3 — одно сообщение и заморозка долга, дни 4–8 —
        «Я здесь.» раз в день, дальше — раз в неделю, пока человек не вернётся.
        Дни без сообщений бота серию не рвут (State.ignore_streak), поэтому цикл
        «брифинг → три дня → …» после долгого молчания не начинается заново."""
        if silent_days > 7:
            last = max((d for d, day in self.core.state.days.items() if day.msgs_out), default=None)
            if last is not None and (now.date() - last).days < 7:
                return
        key = f"ignore:{now.date().isoformat()}"
        if self._once(key, self.brief_time(), now, timedelta(hours=12)):
            self.bot.send(tpl.IGNORE.get(silent_days, tpl.IGNORE_LATER), key=key)
