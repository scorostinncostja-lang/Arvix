"""Обработка входящих в Telegram: команды, кнопки, ожидаемые ответы, свободный текст.

Порядок для текста: safety-маркеры → ожидаемый ответ (отчёт, причина, разбор,
интервью) → голова (L1). Кнопки и команды обрабатывает код без модели (L0).
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from arvix import interview, rules, safety
from arvix.brain import (
    DEBRIEF_SCHEMA,
    EXTRACT_SCHEMA,
    LINK_RE,
    RETRO_SCHEMA,
    TEMPLATES_SCHEMA,
    VOICE_SCHEMA,
    Brain,
    apply_actions,
    clip,
    gentle_violation,
)
from arvix.context import build_context, hm, task_line
from arvix.core import ArvixError, Core, parse_duration
from arvix.prompt import constitution, system_prompt
from arvix.telegram import templates as tpl
from arvix.telegram.api import TelegramAPI, TelegramError

log = logging.getLogger("arvix.telegram")
AWAIT = "tg_await"
LAST_TEXT = "tg_last_text"
HISTORY = 10
ANALYST_RULES = """<analyst>
Ты — аналитик Арвикса. Ты не пересказываешь события — их видно и так.
Ты ищешь связь, которую человек сам не замечает.
Каждый вывод опирается минимум на 3 события — указывай их id в evidence.
Вывод без доказательств отбрасывается кодом. Лучше один вывод, чем пять догадок.
Если значимого паттерна нет — так и скажи. Это нормально.
Периоды с safety_flag не разбираются на эффективность.
</analyst>"""
EXTRACT_RULES = """<extract>
Разложи ответы интервью на структуру через actions:
set_goal (title, why — обязательно, kind: dream|main|yearly|quarterly|milestone, deadline ГГГГ-ММ-ДД если есть),
add_trait (kind: fear|weakness|bad_habit|good_habit|trigger, title, text — описание),
remember (topic: goal|fear|weakness|trigger|habit|people|money|body|work|learning|general, fact — одна мысль),
profile_set (key латиницей snake_case, value строкой) — для фактов вроде роста, дохода, учреждения,
set_template — если в ответах есть расписание недели: шаблоны дней (study|work|deep|recovery|silent),
weekdays 0=пн…6=вс, blocks с start ЧЧ:ММ, duration в минутах, title, sphere, importance 1–5, difficulty 1–5, deep_work.
Шаблон — только реалистичный: свободное время после учёбы/смен, сон по плану, 1–3 блока в день.
Ничего не выдумывай сверх ответов. summary — что записано, 1–3 строки, голосом Арвикса.
</extract>"""
SCHEDULE_RULES = """<schedule>
Собери шаблоны дней недели из ответов человека: учёба и работа, свободные окна, подъём и отбой, пики энергии.
- Бюджет недели — в строке НАГРУЗКА контекста. Сумма блоков за неделю не больше бюджета: начинать с того, что точно потянет.
- Блоки только в реально свободное время: первый — не раньше чем через 30 мин после учёбы или работы,
  последний заканчивается минимум за 60 мин до отбоя.
- 1–3 блока в будний день. Глубокая работа (deep_work) — в часы пика энергии, 45–90 минут.
- Обязательные дела человека (работа, тренировки, репетиторы) — блоками с их реальным временем.
- Спорт — сколько человек уже делает (sphere sport), не меньше.
- Один восстановительный день (recovery): прогулка, спорт, отдых без экрана (tags offscreen), без учёбы.
- Названия конкретные («Математика ОГЭ: задание 1–5»), если в ответах есть предметы, экзамены и цели.
- importance 4–5 — только главное (экзамены, главная цель), остальное 2–3.
- Только факты: не ставь блоки под то, чего ещё нет («скоро устроюсь», «запишусь») — работы или кружка нет, значит, нет и блока.
- Предметы и экзамены, если их нет в ответах, сначала посмотри в хранилище (Grep/Read: карты предметов в 02_Areas,
  папка подготовки к экзаменам) — не угадывай.
- Если есть пожелания человека или прежний вариант — исправь именно то, о чём он просит.
summary — логика распорядка, 2–4 строки, голосом Арвикса.
</schedule>"""
WEEKDAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
DAY_TYPE_RU = {"study": "учебный", "work": "рабочий", "deep": "глубокий", "recovery": "восстановительный", "silent": "тихий"}
PENDING = "tg_pending_templates"


def weekdays_label(days: list[int]) -> str:
    days = sorted(set(days))
    if len(days) > 2 and days == list(range(days[0], days[-1] + 1)):
        return f"{WEEKDAY_NAMES[days[0]]}–{WEEKDAY_NAMES[days[-1]]}"
    return ", ".join(WEEKDAY_NAMES[d] for d in days)


def render_templates(templates: list[dict[str, Any]]) -> str:
    """Распорядок текстом; итоговые часы считает код, а не модель."""
    lines = ["📅 Распорядок недели", ""]
    week_total = deep_total = 0
    for template in templates:
        lines.append(f"{weekdays_label(template['weekdays'])} · {DAY_TYPE_RU.get(template['day_type'], template['day_type'])}")
        for block in sorted(template["blocks"], key=lambda b: b.get("start") or ""):
            duration = int(block.get("duration") or 60)
            hours, minutes = map(int, (block.get("start") or "00:00").split(":")[:2])
            end = hours * 60 + minutes + duration
            marks = (", глубокая" if block.get("deep_work") else "") + (f", ★{block['importance']}" if int(block.get("importance") or 3) >= 4 else "")
            lines.append(f"  {block.get('start')}–{end // 60 % 24:02d}:{end % 60:02d} {block['title']} ({duration} мин{marks})")
            week_total += duration * len(template["weekdays"])
            deep_total += duration * len(template["weekdays"]) if block.get("deep_work") else 0
        lines.append("")
    lines.append(f"Итого {hm(week_total)} в неделю, из них глубокой {hm(deep_total)}.")
    return "\n".join(lines)


QUICK_START = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
QUICK_DUR = re.compile(r"\b(\d{1,3})\s*(м|мин|min|m)\b|\b(\d(?:[.,]\d)?)\s*(ч|h)\b", re.IGNORECASE)
QUICK_IMP = re.compile(r"(?:!|imp)([1-5])\b", re.IGNORECASE)


def parse_quick_task(text: str) -> dict[str, Any]:
    """/add Физика: задачи 18:00 60м !4 deep завтра → поля задачи, без модели."""
    out: dict[str, Any] = {}
    if m := QUICK_START.search(text):
        out["start"] = f"{int(m.group(1)):02d}:{m.group(2)}"
        text = text.replace(m.group(0), " ")
    if m := QUICK_DUR.search(text):
        out["duration_min"] = int(m.group(1)) if m.group(1) else int(float(m.group(3).replace(",", ".")) * 60)
        text = text.replace(m.group(0), " ")
    if m := QUICK_IMP.search(text):
        out["importance"] = int(m.group(1))
        text = text.replace(m.group(0), " ")
    words = text.split()
    if any(w.lower() in ("deep", "глубокая", "глуб") for w in words):
        out["deep_work"] = True
    if any(w.lower() == "завтра" for w in words):
        out["day"] = "tomorrow"
    out["title"] = " ".join(w for w in words if w.lower() not in ("deep", "глубокая", "глуб", "завтра")).strip(" ,.-")
    return out


class Bot:
    def __init__(self, core: Core, api: TelegramAPI, brain: Brain, owner_id: int):
        self.core = core
        self.api = api
        self.brain = brain
        self.owner = int(owner_id)

    # --- отправка и ожидание ответа ------------------------------------------

    def send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None, *, key: str | None = None) -> None:
        self.api.send(self.owner, text, buttons)
        self.core.message_out(text, key=key)

    def await_set(self, kind: str, **data: Any) -> None:
        # asked_at: сообщение, отправленное раньше вопроса (очередь после обрыва сети),
        # ответом на этот вопрос быть не может.
        self.core.store.kv_set(AWAIT, {"kind": kind, "asked_at": self.core.now().timestamp(), **data})

    def await_get(self) -> dict[str, Any] | None:
        return self.core.store.kv_get(AWAIT)

    def await_clear(self) -> None:
        self.core.store.kv_del(AWAIT)

    # --- входящие --------------------------------------------------------------

    def handle(self, update: dict[str, Any]) -> None:
        if callback := update.get("callback_query"):
            self.on_callback(callback)
            return
        msg = update.get("message") or {}
        if (msg.get("from") or {}).get("id") != self.owner:
            return  # single-user: всех остальных молча игнорируем
        self.core.refresh()
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if msg.get("photo"):
            self.on_photo(text)
        elif text.startswith("/"):
            self.on_command(text)
        elif text:
            self.on_text(text, sent_at=msg.get("date"))

    def on_text(self, text: str, sent_at: float | None = None) -> None:
        previous = self.core.store.kv_get(LAST_TEXT)
        self.core.store.kv_set(LAST_TEXT, text)
        self.core.message_in(text)
        if safety.detect(text):
            self.safety_protocol(text)
            return
        waiting = self.await_get()
        if waiting and sent_at and sent_at < waiting.get("asked_at", 0):
            if text == previous:
                return  # повтор, отправленный, пока бот был без сети
            self.converse(text)
            return
        if waiting and self.on_await(waiting, text):
            return
        self.converse(text)

    def safety_protocol(self, text: str) -> None:
        self.core.safety_flag("high", text[:200], source="l0")
        self.await_clear()
        self.send(tpl.safety(self.core.state.profile.get("support_person")))

    def on_await(self, waiting: dict[str, Any], text: str) -> bool:
        kind = waiting.get("kind")
        try:
            if kind == "interview":
                self.interview_answer(waiting["qid"], text)
            elif kind == "report":
                self.await_clear()
                result = self.core.complete_task(waiting["task"], report=text, source="telegram")
                self.send(tpl.completed(result["task"].title, result["xp"], result["debt_closed"]))
            elif kind == "partial":
                self.await_clear()
                pct = int(m.group(1)) if (m := re.search(r"\b(\d{1,2})\b", text)) else 50
                result = self.core.complete_task(waiting["task"], done_pct=pct, report=text, source="telegram")
                self.send(tpl.completed(result["task"].title, result["xp"]) + f" · {pct}%")
            elif kind == "fail_reason":
                self.await_clear()
                task = self.core.explain_failure(waiting["task"], text, source="telegram")
                self.converse(f"Причина провала «{task.title}»: {text}")
            elif kind == "debrief":
                self.await_clear()
                self.debrief_answer(text)
            elif kind == "schedule_edit":
                self.await_clear()
                self.propose_schedule(text)
            elif kind == "sleep":
                self.await_clear()
                result = self.core.log_sleep(parse_duration(text.split()[0]), source="telegram")
                self.send(f"Сон {hm(result['duration_min'])}. Режим: {rules.MODE_LABELS[result['mode']]}")
            else:
                return False
        except ArvixError as exc:
            if kind == "sleep":
                return False  # это был не ответ про сон — отдаём голове
            self.send(f"Отказ: {exc}")
        return True

    def on_photo(self, caption: str) -> None:
        self.core.message_in(f"[фото] {caption}")
        waiting = self.await_get()
        if waiting and waiting.get("kind") == "report":
            self.await_clear()
            result = self.core.complete_task(waiting["task"], report=caption or "фото-отчёт", proof_kind="photo", source="telegram")
            self.send(tpl.completed(result["task"].title, result["xp"], result["debt_closed"]))
        else:
            self.send("Фото принимаю как отчёт, когда жду его: кнопка «✅ Да» у задачи или /done <id>.")

    # --- кнопки ----------------------------------------------------------------

    def on_callback(self, callback: dict[str, Any]) -> None:
        try:
            self.api.answer_callback(callback["id"])
        except TelegramError:
            pass
        if (callback.get("from") or {}).get("id") != self.owner:
            return
        message = callback.get("message") or {}
        try:
            self.api.drop_buttons(message["chat"]["id"], message["message_id"])
        except (TelegramError, KeyError):
            pass
        self.core.refresh()
        data = callback.get("data") or ""
        self.core.message_in(f"[кнопка {data}]")
        kind, _, rest = data.partition(":")
        try:
            if kind == "t":
                task_id, _, op = rest.partition(":")
                self.on_task_button(task_id, op)
            elif kind == "q":
                self.on_interview_button(rest)
            elif kind == "s":
                self.on_schedule_button(rest)
            elif kind == "f":
                op, _, minutes = rest.partition(":")
                minutes_done = int(minutes) if op == "ok" else int(minutes) // 2
                self.core.log_focus(minutes_done, source="telegram")
                self.send(f"Фокус: {minutes_done} мин глубокой работы записано.")
        except ArvixError as exc:
            self.send(f"Отказ: {exc}")

    def on_task_button(self, task_id: str, op: str) -> None:
        core = self.core
        task = core.resolve_task(task_id)
        if op == "start":
            core.start_task(task.id, source="telegram")
            self.send(tpl.reminder_start(task))
        elif op == "d15":
            moved = core.defer_task(task.id, 15, source="telegram")
            self.send(f"⏳ «{moved.title}» → {moved.start}")
        elif op == "yes":
            if task.proof == "confirm":
                result = core.complete_task(task.id, source="telegram")
                self.send(tpl.completed(task.title, result["xp"], result["debt_closed"]))
            else:
                self.await_set("report", task=task.id)
                self.send(tpl.ASK_PHOTO if task.proof == "photo" else tpl.ASK_REPORT)
        elif op == "part":
            self.await_set("partial", task=task.id)
            self.send(tpl.ASK_PARTIAL)
        elif op == "no":
            result = core.fail_task(task.id, reason="отмечено кнопкой", source="telegram")
            self.await_set("fail_reason", task=task.id)
            self.send(tpl.failed(task.title, result["hp"], result["debt"]) + "\n" + tpl.ASK_FAIL_REASON)

    def on_interview_button(self, rest: str) -> None:
        op, _, qid = rest.partition(":")
        if op == "skip" and qid:
            nxt = self.core.interview_skip(qid, source="telegram")
            self.ask_question(nxt) if nxt else self.send(tpl.ONBOARD_DONE)
        elif op == "next":
            self.cmd_onboard("")
        elif op == "pause":
            self.cmd_pause("")

    def on_schedule_button(self, op: str) -> None:
        pending = self.core.store.kv_get(PENDING)
        if op == "save" and pending:
            for template in pending:
                self.core.set_template(template["weekdays"], template["day_type"], template["blocks"], source="telegram")
            self.core.store.kv_del(PENDING)
            self.core.refresh()
            today = [t for t in self.core.state.tasks_on(self.core.today()) if t.is_open]
            self.send(
                "Распорядок сохранён. Каждое утро из него появятся задачи, за 5 минут до блока — напоминание."
                + (f"\nСегодня ещё {len(today)}: " + ", ".join(f"{t.start} {t.title}" for t in today) if today else "\nНа сегодня блоков уже не осталось — начнём завтра.")
            )
        elif op == "edit":
            self.await_set("schedule_edit")
            self.send("Напиши, что поменять: «в среду тренировка в 18:00», «английский утром перед школой», «меньше часов».")
        elif op == "save":
            self.send("Предложение устарело — /schedule соберёт новое.")

    def propose_schedule(self, wishes: str = "") -> None:
        """Один вызов модели: ответы интервью + бюджет → шаблоны дней на подтверждение."""
        core = self.core
        st = core.state
        answers = [f"В: {q['text']}\nО: {st.interview[q['id']]}" for q in interview.QUESTIONS
                   if q["id"] in st.interview and q["block"] not in ("inner", "money", "people")]
        if not answers:
            self.send("Сначала нужны ответы про неделю и распорядок — /onboard.")
            return
        prompt = "Ответы человека:\n\n" + "\n\n".join(answers)
        previous = core.store.kv_get(PENDING)
        if previous:
            prompt += "\n\nПрежний вариант распорядка:\n" + render_templates(previous)
        if wishes:
            prompt += f"\n\nПожелания человека: {wishes}"
        system = "\n\n".join([constitution(st.profile, gentle=True, sections=("identity", "honesty")), SCHEDULE_RULES,
                                "<context>\n" + build_context(core) + "\n</context>"])
        try:
            self.api.typing(self.owner)
        except TelegramError:
            pass
        result = self.brain.ask(system=system, prompt=prompt, schema=TEMPLATES_SCHEMA, role="voice", vault_tools=True)
        if not result or not result.get("templates"):
            self.send("Не вышло собрать распорядок. " + (self.brain_down_hint() or "Попробуй /schedule ещё раз."))
            return
        core.store.kv_set(PENDING, result["templates"])
        self.send(clip(result.get("summary", ""), 500) + "\n\n" + render_templates(result["templates"]),
                  [[("✅ Сохранить", "s:save"), ("✏️ Поправить", "s:edit")]])

    # --- интервью ----------------------------------------------------------------

    def ask_question(self, question: dict[str, Any]) -> None:
        number = next(i for i, q in enumerate(interview.QUESTIONS, 1) if q["id"] == question["id"])
        self.await_set("interview", qid=question["id"])
        self.send(tpl.question(question, number, len(interview.QUESTIONS)), [[("Пропустить", f"q:skip:{question['id']}")]])

    def interview_answer(self, qid: str, text: str) -> None:
        result = self.core.interview_answer(qid, text, source="telegram")
        self.await_clear()
        if not result["block_done"]:
            self.ask_question(result["next"])
            return
        block = interview.BY_ID[qid]["block"]
        self.extract_block(block)
        if block == "day" or (block == "core" and not self.core.state.templates and "day_weekday" in self.core.state.interview):
            self.propose_schedule()
        nxt = result["next"]
        if nxt:
            self.send(f"Блок закрыт. Дальше — «{nxt['block_title']}». Продолжаем?", [[("Дальше", "q:next"), ("Пауза", "q:pause")]])
        else:
            self.send(tpl.ONBOARD_DONE)

    def extract_block(self, block: str) -> None:
        """Одна модель-вызов на блок: свободные ответы → цели, черты, факты, шаблоны."""
        st = self.core.state
        pairs = [f"В: {q['text']}\nО: {st.interview[q['id']]}" for q in interview.QUESTIONS if q["block"] == block and q["id"] in st.interview]
        if not pairs:
            return
        system = "\n\n".join([constitution(st.profile, gentle=True, sections=("identity", "honesty")), EXTRACT_RULES])
        result = self.brain.ask(system=system, prompt="\n\n".join(pairs), schema=EXTRACT_SCHEMA, role="voice")
        if result is None:
            self.send("Ответы сохранены. " + self.brain_down_hint() + " Разложу их, когда голова вернётся (или /arvix:onboarding в Claude Code).")
            return
        done, failed = apply_actions(self.core, result.get("actions") or [], source="telegram")
        summary = result.get("summary", "").strip()
        if done:
            summary += "\n" + " · ".join(done)
        if failed:
            summary += "\n⚠️ Не записано: " + "; ".join(failed)
        if summary:
            self.send(summary.strip())

    # --- голова (L1) ---------------------------------------------------------------

    def history(self, exclude_last: str = "") -> list[str]:
        start = max(0, self.core.state.last_event_id - 400)
        events = [e for e in self.core.store.read(start) if e.kind in ("message_in", "message_out")]
        lines = []
        for event in events[-(HISTORY + 1):]:
            who = "ЧЕЛОВЕК" if event.kind == "message_in" else "АРВИКС"
            lines.append(f"{who} ({event.at.astimezone(self.core.tz):%d.%m %H:%M}): {event.payload.get('text', '')}")
        if lines and exclude_last and lines[-1].endswith(exclude_last[:600]):
            lines.pop()
        return lines[-HISTORY:]

    def converse(self, text: str, extra: str = "") -> None:
        core = self.core
        try:
            self.api.typing(self.owner)
        except TelegramError:
            pass
        if core.store.kv_get("answer_mode"):
            core.store.kv_del("answer_mode")
            extra += "\n<answer_mode>Человек запросил готовый ответ (/answer). Дай полный ответ с источниками и action learning_question с direct=true.</answer_mode>"
        silent_days = core.state.ignore_streak(core.today() - timedelta(days=1))
        today = core.state.days.get(core.today())
        if silent_days >= 2 and today and today.user_actions <= 2:
            extra += "\n" + tpl.RETURN_HINT.format(days=silent_days)
        system = system_prompt(core, message=text, history=self.history(exclude_last=text), extra=extra.strip())
        result = self.brain.ask(system=system, prompt=text, schema=VOICE_SCHEMA, vault_tools=True)
        if result is None:
            self.send(" ".join(x for x in (tpl.FALLBACK, self.brain_down_hint()) if x))
            return
        reply = (result.get("reply") or "").strip()
        if core.effective_mode() == "red" and gentle_violation(reply):
            retry = self.brain.ask(
                system=system + "\n\n<validator>В ответе были слова про дисциплину, задачи или метрики. В мягком режиме это запрещено. Перепиши по-человечески.</validator>",
                prompt=text, schema=VOICE_SCHEMA,
            )
            ok = retry is not None and not gentle_violation(retry.get("reply", ""))
            result = retry if ok else {"actions": []}
            reply = retry["reply"].strip() if ok else tpl.GENTLE_FALLBACK
        if result.get("learning") and not LINK_RE.search(reply):
            retry = self.brain.ask(
                system=system + "\n\n<validator>Ответ обучающий, но без ссылки на первоисточник. Добавь 1–3 реальные ссылки, официальная документация первой. Не выдумывай URL.</validator>",
                prompt=text, schema=VOICE_SCHEMA, vault_tools=True,
            )
            if retry and LINK_RE.search(retry.get("reply", "")):
                result, reply = retry, retry["reply"].strip()
            else:
                reply += "\n\n(Ссылку на первоисточник приложить не вышло — проверь по официальной документации.)"
        done, failed = apply_actions(core, result.get("actions") or [], source="telegram", fallback_report=text)
        if done:
            reply += "\n\n" + " · ".join(done)
        if failed:
            reply += "\n⚠️ Не выполнено: " + "; ".join(failed)
        self.send(reply or "…")

    def brain_down_hint(self) -> str:
        """Почему голова молчит — человеку нужен следующий шаг, а не «ошибка»."""
        error = (getattr(self.brain, "last_error", "") or "").lower()
        if "region" in error or "403" in error or "vpn" in error:
            return tpl.REGION_HINT
        return ""

    # --- ритуалы (их вызывает планировщик или команда) ------------------------------

    def analyst_system(self, task: str) -> str:
        st = self.core.state
        return "\n\n".join([constitution(st.profile, gentle=True, sections=("identity", "mission", "honesty")), ANALYST_RULES, task])

    def send_brief(self, prefix: str = "") -> None:
        text = tpl.brief(self.core)
        try:
            from arvix import daily_note

            if rel := daily_note.ensure(self.core, self.core.today()):
                text += f"\n📝 Отчёт дня: {rel}"
        except ArvixError as exc:
            log.warning("ежедневный отчёт не создан: %s", exc)
        self.send(f"{prefix}\n\n{text}" if prefix else text, key=f"brief:{self.core.today().isoformat()}")
        day = self.core.state.days.get(self.core.today())
        if not (day and day.sleep_min):
            self.await_set("sleep")

    def send_debrief(self, *, manual: bool = False) -> None:
        core = self.core
        today = core.today()
        day = core.state.day(today)
        if core.effective_mode() == "red":
            text = "🌙 Как ты сегодня? Одной фразой, без цифр."
        else:
            text = tpl.debrief_facts(core)
            result = self.brain.ask(
                system=self.analyst_system("<task>Одна честная оценка дня — не льстивая и не уничижительная — и ровно два вопроса, подобранных под этот день, не шаблонных.</task>"),
                prompt=f"Факты дня:\n{text}\n\nСобытия сегодня:\n" + "\n".join(core.events_feed(days=0)) + f"\n\nКонтекст:\n{build_context(core)}",
                schema=DEBRIEF_SCHEMA, role="analyst",
            )
            questions = (result or {}).get("questions") or tpl.DEBRIEF_FALLBACK_QUESTIONS
            if result and result.get("assessment"):
                text += "\n\n" + clip(result["assessment"], 300)
            if day.silent:
                text += "\nТихий день — разбор без штрафов, только выводы."
            text += "\n\nДва вопроса:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions[:2], 1))
            text += "\nОтветь одним сообщением."
        if not manual and not day.user_actions:
            text = tpl.SILENT_TODAY + "\n\n" + text
        self.send(text, key=f"debrief:{today.isoformat()}")
        self.await_set("debrief")

    def debrief_answer(self, text: str) -> None:
        core = self.core
        extra = "<debrief>Человек ответил на вопросы вечернего разбора. Один вывод — что меняем завтра — и коротко про план завтра (блок ЗАВТРА в контексте). До 5 строк.</debrief>"
        result = self.brain.ask(system=system_prompt(core, message=text, extra=extra), prompt=text, schema=VOICE_SCHEMA)
        conclusion = (result or {}).get("reply", "").strip()
        if result:
            apply_actions(core, result.get("actions") or [], source="telegram")
        core.complete_debrief(text, conclusion=conclusion, source="telegram")
        note = ""
        try:
            from arvix import daily_note

            if rel := daily_note.sync(core, core.today()):
                note = f"\n\n📝 Разбор вписан в {rel}"
        except ArvixError as exc:
            log.warning("ежедневный отчёт не обновлён: %s", exc)
        self.send((conclusion or "Разбор записан. Завтра — по плану, отбой вовремя.") + note)

    def run_retro(self) -> bool:
        """Недельное ретро (L2): аналитик ищет паттерны, директивы без evidence отбрасывает код."""
        core = self.core
        result = self.brain.ask(
            system=self.analyst_system("<task>Недельное ретро: паттерны, квоты, бюджет, коррекция плана. message — для человека голосом Арвикса; directives — 1–5, каждая с evidence.</task>"),
            prompt="Лента событий за 7 дней:\n" + "\n".join(core.events_feed(days=7)) + f"\n\nКонтекст:\n{build_context(core)}",
            schema=RETRO_SCHEMA, role="analyst",
        )
        if result is None:
            return False
        accepted, rejected = 0, 0
        for item in (result.get("directives") or [])[:7]:
            try:
                core.add_directive(item.get("kind", "insight"), item.get("text", ""), evidence=item.get("evidence") or [],
                                   voice_hint=item.get("voice_hint", ""), priority=item.get("priority") or 3, valid_days=item.get("valid_days") or 7)
                accepted += 1
            except ArvixError:
                rejected += 1
        for item in result.get("insights") or []:
            try:
                core.add_insight(item.get("text", ""), evidence=item.get("evidence") or [])
            except ArvixError:
                rejected += 1
        message = clip(result.get("message", ""), 900) + f"\n\nДиректив принято: {accepted}" + (f", отклонено без доказательств: {rejected}" if rejected else "")
        self.send("📊 Ретро недели\n\n" + message, key=f"retro:{core.today().isoformat()}")
        return True

    # --- команды -------------------------------------------------------------------

    def on_command(self, text: str) -> None:
        self.core.message_in(text)
        head, _, rest = text.partition(" ")
        name = head[1:].split("@")[0].lower()
        handler = getattr(self, f"cmd_{name}", None)
        if handler is None:
            self.send("Не знаю такой команды. /help")
            return
        try:
            handler(rest.strip())
        except ArvixError as exc:
            self.send(f"Отказ: {exc}")

    def cmd_start(self, rest: str) -> None:
        status = self.core.interview_status()
        core_block = next(b for b in status["blocks"] if b["block"] == "core")
        if core_block["done"] < core_block["total"]:
            self.send("Я Арвикс. Не ассистент и не друг по переписке — внешний контур дисциплины, пока не выстроится свой.")
            self.cmd_onboard("")
        else:
            self.send_brief()

    def cmd_schedule(self, rest: str) -> None:
        if rest.strip() == "show" and self.core.state.templates:
            current = [{"weekdays": [w], **t} for w, t in sorted(self.core.state.templates.items())]
            self.send(render_templates(current))
            return
        self.propose_schedule(rest.strip())

    def cmd_goals(self, rest: str) -> None:
        icons = {"active": "○", "done": "●", "dropped": "✖"}
        rows = ["  " * depth + f"{icons.get(g.get('status'), '○')} {g['title']}" + (f" · до {g['deadline']}" if g.get("deadline") else "")
                for depth, g in self.core.goal_tree() if g.get("status") != "dropped"]
        self.send("🎯 Цели\n\n" + "\n".join(rows) if rows else "Целей пока нет. Разложить цель на этапы — в Claude Code: «хочу …, разложи».")

    def cmd_help(self, rest: str) -> None:
        self.send(tpl.HELP)

    def cmd_onboard(self, rest: str) -> None:
        question = self.core.interview_next()
        if not question:
            self.send(tpl.ONBOARD_DONE)
            return
        if self.core.interview_status()["answered"] == 0:
            self.send(tpl.ONBOARD_INTRO)
        self.ask_question(question)

    def cmd_skip(self, rest: str) -> None:
        waiting = self.await_get()
        if not waiting or waiting.get("kind") != "interview":
            self.send("Сейчас нечего пропускать.")
            return
        self.on_interview_button(f"skip:{waiting['qid']}")

    def cmd_pause(self, rest: str) -> None:
        self.await_clear()
        self.send("Пауза. Продолжить — /onboard.")

    def cmd_day(self, rest: str) -> None:
        facts = self.core.day_facts(self.core.parse_day(rest or None))
        lines = [f"{facts['date']:%d.%m}: {facts['done']}/{facts['total']} · глубокая {hm(facts['deep_min'])}"]
        lines += [task_line(t) for t in facts["tasks"]] or ["Задач нет. Напиши, что делаешь, или /add."]
        self.send("\n".join(lines))

    def cmd_week(self, rest: str) -> None:
        self.send(tpl.week(self.core))

    def cmd_status(self, rest: str) -> None:
        self.send(tpl.status(self.core))

    def cmd_done(self, rest: str) -> None:
        ref, _, report = rest.partition(" ")
        if not ref:
            self.send("Формат: /done <id или часть названия> [что сделано]")
            return
        result = self.core.complete_task(ref, report=report or None, source="telegram")
        self.send(tpl.completed(result["task"].title, result["xp"], result["debt_closed"]))

    def cmd_add(self, rest: str) -> None:
        fields = parse_quick_task(rest)
        if not fields.get("title"):
            self.send("Формат: /add Физика: задачи 18:00 60м !4 [deep] [завтра]")
            return
        task = self.core.add_task(fields.pop("title"), source="telegram", **fields)
        self.send(f"+ {task_line(task)}")

    def cmd_answer(self, rest: str) -> None:
        self.core.store.kv_set("answer_mode", True)
        self.send("Следующий учебный вопрос — с готовым ответом. Это пишется в лог и минус к автономности.")

    def cmd_note(self, rest: str) -> None:
        path = self.core.capture_note(rest, source="telegram")
        self.send(f"Записано: {path or 'в журнал'}")

    def cmd_find(self, rest: str) -> None:
        from arvix.vault import Vault

        if not self.core.cfg.vault:
            self.send("Хранилище не настроено.")
            return
        found = Vault(self.core.cfg.vault, self.core.cfg.vault_paths).search(rest, 5)
        self.send("\n\n".join(f"📄 {r['path']}" + (f" — «{r['heading']}»" if r["heading"] else "") + f"\n{r['snippet']}" for r in found) or "Ничего не найдено.")

    def cmd_spend(self, rest: str) -> None:
        parts = rest.split()
        if len(parts) < 2:
            self.send("Формат: /spend 1200 еда [!]")
            return
        impulse = "!" in parts
        words = [p for p in parts[1:] if p != "!"]
        result = self.core.log_expense(parts[0], " ".join(words) or "прочее", impulse=impulse, source="telegram")
        self.send(f"Трата {result['amount']:.0f} {result['currency']}" + (" (импульсивная)" if impulse else "") + f" · за неделю {result['week_total']:.0f}")

    def cmd_sleep(self, rest: str) -> None:
        parts = rest.split()
        if not parts:
            self.send("Формат: /sleep 7:30 [время отбоя 00:10]")
            return
        result = self.core.log_sleep(parts[0], bedtime=parts[1] if len(parts) > 1 else None, source="telegram")
        self.await_clear()
        self.send(f"Сон {hm(result['duration_min'])}. Режим: {rules.MODE_LABELS[result['mode']]}")

    def cmd_sos(self, rest: str) -> None:
        mode = self.core.sos(rest.strip().lower() != "off", source="telegram")
        self.send(f"Режим: {rules.MODE_LABELS[mode]}" + ("" if mode != "red" else "\nСегодня без задач и цифр. Сон, еда, движение."))

    def cmd_silent(self, rest: str) -> None:
        self.core.silent_today(source="telegram")
        self.send("Тихий день. Я молчу до вечера, разбор — без штрафов. Ведёшь день сам.")

    def cmd_export(self, rest: str) -> None:
        from arvix.export import export_all

        written = export_all(self.core)
        self.send("Экспорт в Obsidian:\n" + "\n".join(f"• {p}" for p in written[:12]))

    def cmd_debrief(self, rest: str) -> None:
        self.send_debrief(manual=True)

    def cmd_mentor(self, rest: str) -> None:
        enabled = rest.strip().lower() in ("on", "вкл", "1")
        self.core.set_mentor(enabled, by="telegram")
        self.send("Режим ментора включён." if enabled else "Режим ментора выключен.")

    def cmd_reason(self, rest: str) -> None:
        result = self.core.declare_reason(rest, source="telegram")
        self.send(f"Причина записана. Щитов осталось: {result['shields_left']} — снимет самый крупный урон при закрытии дня.")

    def cmd_focus(self, rest: str) -> None:
        minutes = int(rest) if rest.strip().isdigit() else 25
        until = self.core.now() + timedelta(minutes=minutes)
        self.core.store.kv_set("focus", {"until": until.isoformat(), "minutes": minutes})
        self.send(f"🎯 Фокус {minutes} минут. Телефон убрать. Отмечу в {until:%H:%M}.")
