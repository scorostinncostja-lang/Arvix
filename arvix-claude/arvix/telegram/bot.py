"""Обработка входящих в Telegram: команды, кнопки, ожидаемые ответы, свободный текст.

Порядок для текста: кнопка меню → safety-маркеры → ожидаемый ответ (отчёт, причина,
разбор, интервью) → голова (L1). Кнопки и команды обрабатывает код без модели (L0).

Ответ головы — одно сообщение (D45): абзацы через пустую строку, квитанция кода (что записано,
что отказано, сомнения) — в конце того же сообщения. Голосовое — отдельно и только если голова
сочла, что это стоит послушать (voice_note), а не пересказ текста.
Панель дня — одно закреплённое сообщение с кнопками, которое бот правит на месте.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from contextlib import contextmanager
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from arvix import interview, load, rules, safety, weather
from arvix import lesson as lesson_mod
from arvix.memory import Memory, export_transcripts
from arvix.brain import (
    DEBRIEF_SCHEMA,
    EXTRACT_SCHEMA,
    RETRO_SCHEMA,
    TEMPLATES_SCHEMA,
    UI_ACTIONS,
    VOICE_SCHEMA,
    Brain,
    apply_actions,
    clip,
    effort_for,
    gentle_violation,
    has_source,
    mode_shift,
)
from arvix.context import build_context, end_time, hm, task_line
from arvix.core import ArvixError, Core, parse_sleep_text
from arvix.prompt import constitution, voice_prompt
from arvix.stt import STT, STTError
from arvix.tts import TTS, TTSError
from arvix.telegram import fmt
from arvix.telegram import templates as tpl
from arvix.telegram.api import TelegramAPI, TelegramError

log = logging.getLogger("arvix.telegram")
AWAIT = "tg_await"
LAST_TEXT = "tg_last_text"
PANEL = "tg_panel"
FOCUS = "focus"
LESSON = "lesson"
HISTORY = 14
DIALOG_DAY = "dialog_day"
TYPING_EVERY = 4.0  # «печатает…» в Telegram гаснет через 5 с — обновляем чуть чаще
NOTES_ASK = re.compile(r"заметк|обсидиан|obsidian|хранилищ|конспект|роадмап|роудмап|в моих|найди|поищи|записано|файл", re.IGNORECASE)
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
- Обязательные дела человека (школа, работа, дорога, репетиторы, секции) — блоками с их реальным временем и fixed=true:
  это занятое время. Код не меняет его объём и не делает из него задач с напоминаниями и отчётами.
  Всё остальное (самостоятельная учёба, глубокая работа, спорт, отдых) — fixed=false: длительность этих блоков
  код сам подстраивает раз в неделю по фактам (автонагрузка, старт — 70 %), ставь честную норму.
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


def render_templates(templates: list[dict[str, Any]], factors: dict[str, float] | None = None) -> str:
    """Распорядок текстом; итоговые часы считает код, а не модель. С factors своё время
    показано так, как его поставит автонагрузка («90→65 мин»): человек подтверждает то,
    что реально придёт задачами, а не то, что записала модель."""
    lines = ["📅 Распорядок недели", ""]
    week_total = deep_total = fixed_total = 0
    for template in templates:
        days = len(template["weekdays"])
        lines.append(f"{weekdays_label(template['weekdays'])} · {DAY_TYPE_RU.get(template['day_type'], template['day_type'])}")
        for block in sorted(template["blocks"], key=lambda b: b.get("start") or ""):
            written = int(block.get("duration") or 60)
            fixed = load.is_fixed(block)
            duration = load.scaled_duration(block, factors) if factors else written
            start = block.get("start") or "00:00"
            marks = (", обязательное" if fixed else "") + (", глубокая" if block.get("deep_work") else "")
            marks += f", ★{block['importance']}" if int(block.get("importance") or 3) >= 4 else ""
            size = f"{written}→{duration} мин" if duration != written else f"{duration} мин"
            lines.append(f"  {start}–{end_time(start, duration)} {block['title']} ({size}{marks})")
            if fixed:
                fixed_total += duration * days
            else:
                week_total += duration * days
                deep_total += duration * days if block.get("deep_work") else 0
        lines.append("")
    lines.append(f"Итого {hm(week_total)} в неделю, из них глубокой {hm(deep_total)}." + (f" Обязательное: {hm(fixed_total)}." if fixed_total else ""))
    if factors:
        lines.append("Своё время код ставит с запасом (старт — 70 %) и раз в неделю пересматривает по фактам. Обязательное — занятое время, без напоминаний и отчётов.")
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


VOICE_NOTE_MAX = 400  # символов: голосовое — до ~30 секунд, не лекция
_WORD = re.compile(r"\w{3,}")


def voice_note_check(note: str, reply: str) -> str:
    """Голосовое пропускается, только если оно не пересказ текста (D45). Пустая строка — не отправлять.
    Повтор — когда 70 % слов голосового уже есть в тексте ответа: озвучивать прочитанное незачем."""
    note = (note or "").strip()
    if not note or len(note) > VOICE_NOTE_MAX:
        return ""
    words = [w.lower() for w in _WORD.findall(note)]
    if not words:
        return ""
    seen = {w.lower() for w in _WORD.findall(reply or "")}
    return "" if sum(w in seen for w in words) / len(words) >= 0.7 else note


class Bot:
    def __init__(self, core: Core, api: TelegramAPI, brain: Brain, owner_id: int, stt: STT | None = None,
                 sleep: Callable[[float], None] | None = None, tts: Any = None):
        self.core = core
        self.api = api   # канал текущего разговора: Telegram или приложение (via)
        self.tg = api    # всегда Telegram: панель и таймер живут там, где бы их ни запустили
        self.brain = brain
        self.owner = int(owner_id)
        self.stt = stt if stt is not None else STT(core.cfg)
        self.tts = tts if tts is not None else TTS(core.cfg)
        self.sleep = sleep or time.sleep
        self.voice_notes_per_day = int(core.cfg.section("tts").get("voice_notes_per_day", 3) or 0)
        self.channel = "telegram"  # приложение (arvix/web) создаёт свой Bot с channel="web"
        self.memory = Memory(core)
        self.first_today = False

    # --- отправка и ожидание ответа ------------------------------------------

    def send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None, *, key: str | None = None,
             keyboard: list[list[str]] | None = None) -> int | None:
        message_id = self.api.send(self.owner, text, buttons, keyboard=keyboard)
        self.core.message_out(text, key=key, channel=self.channel, buttons=buttons)
        return message_id

    @contextmanager
    def via(self, channel: str, api: Any) -> Any:
        """Обработать сообщение из приложения тем же кодом, что и из Telegram: ответы идут
        в журнал (приложение их видит), а не в чат. Пауз «печатает…» в приложении нет."""
        saved = (self.channel, self.api, self.sleep)
        self.channel, self.api, self.sleep = channel, api, (lambda _seconds: None)
        try:
            yield
        finally:
            self.channel, self.api, self.sleep = saved

    def tg_send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None, *, key: str | None = None) -> int | None:
        """Сообщение, которое живёт в Telegram независимо от канала (таймер, панель)."""
        message_id = self.tg.send(self.owner, text, buttons)
        self.core.message_out(text, key=key, channel="telegram", buttons=buttons)
        return message_id

    def log_in(self, text: str) -> None:
        self.core.message_in(text, channel=self.channel)
        self.core.store.kv_set("last_in_at", self.core.now().timestamp())

    def reply(self, text: str, receipt: str = "", *, keyboard: list[list[str]] | None = None, key: str | None = None,
              voice_note: str = "") -> None:
        """Ответ головы — одним сообщением (D45): абзацы через пустую строку, предложения по строкам,
        квитанция кода — в конце того же сообщения. voice_note — отдельное короткое голосовое,
        только если голова сочла, что это стоит послушать, и код не нашёл в нём пересказа текста."""
        parts = [fmt.sentence_lines(text)] if text.strip() else []
        if receipt.strip():
            parts.append(receipt.strip())
        body = "\n\n".join(parts) or "…"
        self.api.send(self.owner, fmt.strip_markup(body), keyboard=keyboard, html=fmt.to_html(body))
        self.core.message_out(body, channel=self.channel, key=key)
        if note := voice_note_check(voice_note, text):
            self.send_voice_note(note)

    def send_voice_note(self, note: str) -> None:
        """Голосовое в Telegram: озвучка включена, не больше [tts] voice_notes_per_day в сутки."""
        if self.channel != "telegram" or not (self.tts.enabled and self.tts.voice_replies):
            return
        today = self.core.today().isoformat()
        count = self.core.store.kv_get("voice_notes") or {}
        sent = int(count.get("n", 0)) if count.get("day") == today else 0
        if sent >= self.voice_notes_per_day:
            log.info("голосовое не отправлено: лимит %s в день", self.voice_notes_per_day)
            return
        try:
            self.api.send_voice(self.owner, self.tts.synth(note))
        except (TTSError, TelegramError) as exc:
            log.info("голосовое не отправлено: %s", exc)
            return
        self.core.store.kv_set("voice_notes", {"day": today, "n": sent + 1})
        self.core.message_out("🔊 " + note, channel=self.channel)

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
        if media := msg.get("voice") or msg.get("audio"):
            self.on_voice(media, sent_at=msg.get("date"))
        elif msg.get("photo") and (self.await_get() or {}).get("kind") == "report":
            self.on_photo(text)  # ждём отчёт — фото и есть отчёт
        elif media := self.file_media(msg):
            self.on_file(media, caption=text)
        elif text in tpl.MENU:
            self.log_in(text)
            self.on_menu(tpl.MENU[text])
        elif text.startswith("/"):
            self.on_command(text)
        elif text:
            self.on_text(text, sent_at=msg.get("date"))

    def on_text(self, text: str, sent_at: float | None = None, *, voice: bool = False) -> None:
        previous = self.core.store.kv_get(LAST_TEXT)
        self.core.store.kv_set(LAST_TEXT, text)
        today = self.core.today().isoformat()
        self.first_today = self.core.store.kv_get(DIALOG_DAY) != today
        self.core.store.kv_set(DIALOG_DAY, today)
        self.log_in(("🎙 " if voice else "") + text)
        if safety.detect(text):
            self.safety_protocol(text)
            return
        waiting = self.await_get()
        if waiting and sent_at and sent_at < waiting.get("asked_at", 0):
            if text == previous:
                return  # повтор, отправленный, пока бот был без сети
            self.converse(text, voice=voice)
            return
        if waiting and self.on_await(waiting, text):
            return
        self.converse(text, voice=voice)

    def on_voice(self, media: dict[str, Any], sent_at: float | None = None) -> None:
        """Голосовое → текст → тот же путь, что у набранного сообщения (safety, ожидаемый ответ, голова).
        Расшифровку бот по умолчанию не показывает — отвечает по делу; что он понял, видно по
        квитанции (что записано). Показ «🎙 «…»» — [stt] show_transcript = true."""
        if not self.stt.enabled:
            self.log_in("[голосовое — распознавание не настроено]")
            self.send(tpl.VOICE_OFF)
            return
        if int(media.get("duration") or 0) > self.stt.max_seconds:
            self.log_in("[голосовое — слишком длинное]")
            self.send(f"Голосовое длиннее {self.stt.max_seconds // 60} мин. Разбей на части или напиши текстом.")
            return
        try:
            self.api.typing(self.owner)
        except TelegramError:
            pass
        try:
            audio = self.api.download(media["file_id"])
            text = self.stt.transcribe(audio, filename=media.get("file_name") or "voice.ogg")
        except (TelegramError, STTError, KeyError) as exc:
            self.log_in("[голосовое — не распознано]")
            self.send(f"Голосовое не распознал: {exc}. Напиши текстом.")
            return
        if not text.strip():
            self.log_in("[голосовое — пусто]")
            self.send("В голосовом не разобрал слов. Повтори или напиши текстом.")
            return
        if getattr(self.stt, "show_transcript", False):
            self.send(f"🎙 «{clip(text, 600)}»")
        self.on_text(text, sent_at=sent_at, voice=True)

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
                self.send(tpl.completed(result["task"].title, result["debt_closed"]) + tpl.warn(result["warnings"]))
                self.refresh_panel()
            elif kind == "partial":
                self.await_clear()
                pct = int(m.group(1)) if (m := re.search(r"\b(\d{1,2})\b", text)) else 50
                result = self.core.complete_task(waiting["task"], done_pct=pct, report=text, source="telegram")
                self.send(tpl.completed(result["task"].title) + f" · {pct}%" + tpl.warn(result["warnings"]))
                self.refresh_panel()
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
                self.sleep_answer(text, waiting)
            elif kind == "add":
                self.await_clear()
                fields = parse_quick_task(text)
                if fields.get("title") and fields.get("start"):
                    self.quick_add(fields)
                else:  # без времени — пусть голова подберёт окно по контексту
                    self.converse(f"Добавь задачу: {text}")
            elif kind == "lesson_check":
                self.await_clear()
                self.grade_lesson(text)
            elif kind == "focus_note":
                if text.rstrip().endswith("?") or len(text) > 500:
                    self.await_clear()
                    return False  # вопрос или длинный текст — это уже разговор, не заметка к фокусу
                self.await_clear()
                self.core.note_focus(int(waiting["event"]), text, source="telegram")
                self.send("Вписал в сессию.")
            else:
                return False
        except ArvixError as exc:
            if kind == "sleep":
                self.await_clear()
                return False  # это был не ответ про сон — отдаём голове
            self.send(f"Отказ: {exc}")
        return True

    def sleep_answer(self, text: str, waiting: dict[str, Any] | None = None) -> None:
        """Сон словами без модели (02-MECHANICS §7.2). «8:30 утра» — это подъём, а не 8,5 часа сна:
        код спросит отбой и посчитает сам. Половина ответа ждёт вторую в том же ожидании."""
        waiting = waiting or {}
        expect = "bedtime" if waiting.get("wake") else "wake" if waiting.get("bedtime") else None
        parsed = parse_sleep_text(text, expect=expect)
        bed = parsed["bedtime"] or waiting.get("bedtime")
        wake = parsed["wake"] or waiting.get("wake")
        if parsed["duration"] is None and not (bed and wake):
            if waiting.get("bedtime") or waiting.get("wake"):  # второй раз половина — дальше голова
                raise ArvixError("сон не дособран")
            self.await_set("sleep", bedtime=bed, wake=wake)
            self.send(f"Подъём {wake}. Во сколько уснул?" if wake else f"Отбой {bed}. Во сколько встал?")
            return
        self.await_clear()
        result = self.core.log_sleep(parsed["duration"], bedtime=bed, wake=wake, source="telegram")
        self.send(tpl.sleep_logged(result) + tpl.warn(result["warnings"]))
        if result["mode_before"] == "red" and result["mode"] != "red":
            self.send_panel(pin=True, hint="Возвращаемся без разгона: первым — самое короткое дело.")
        elif result["mode"] == "red":
            self.refresh_panel()

    @staticmethod
    def file_media(msg: dict[str, Any]) -> dict[str, Any] | None:
        """Что прислано файлом: фото (самое крупное), документ, видео, кружок, анимация."""
        if photos := msg.get("photo"):
            best = max(photos, key=lambda p: p.get("file_size") or p.get("width", 0) * p.get("height", 0))
            return {**best, "file_name": f"фото {msg.get('date') or ''}.jpg".replace(" .", ".").strip(), "mime_type": "image/jpeg"}
        for key, default in (("document", "файл"), ("video", "видео.mp4"), ("video_note", "кружок.mp4"), ("animation", "анимация.mp4")):
            if media := msg.get(key):
                return {**media, "file_name": media.get("file_name") or default}
        return None

    def on_file(self, media: dict[str, Any], *, caption: str = "", data: bytes | None = None) -> None:
        """Файл → хранилище (L0) → голова читает его по пути и отвечает по содержимому."""
        from arvix import files

        name = files.safe_name(media.get("file_name") or "файл")
        self.log_in(f"📎 {name}" + (f" — {caption}" if caption else ""))
        if data is None and int(media.get("file_size") or 0) > files.MAX_BYTES:
            self.send(f"«{name}» больше 20 МБ — Telegram не отдаёт боту такие файлы. Сожми, раздели или пришли ссылкой.")
            return
        try:
            self.api.typing(self.owner)
        except TelegramError:
            pass
        try:
            if data is None:
                data = self.api.download(media["file_id"])
            info = self.core.receive_file(data, name, media.get("mime_type") or "", stt=self.stt, caption=caption, source=self.channel)
        except (TelegramError, ArvixError, KeyError) as exc:
            self.send(f"Файл не принял: {exc}")
            return
        ask = caption or f"Я прислал {info['kind_ru']} «{info['name']}». Посмотри и скажи, что видишь и что с этим делать."
        if not info["read"]:
            self.send(f"Положил в хранилище: {info['path']}.\n" + "; ".join(info["notes"]))
            return
        self.converse(ask, extra=files.attachment_block(self.core, [info]))

    def on_photo(self, caption: str) -> None:
        self.log_in(f"[фото] {caption}")
        waiting = self.await_get()
        if waiting and waiting.get("kind") == "report":
            self.await_clear()
            result = self.core.complete_task(waiting["task"], report=caption or "фото-отчёт", proof_kind="photo", source="telegram")
            self.send(tpl.completed(result["task"].title, result["debt_closed"]) + tpl.warn(result["warnings"]))
            self.refresh_panel()
        else:
            self.send("Фото принимаю как отчёт, когда жду его: нажми ✅ у задачи или напиши, что за задача.")

    # --- клавиатура (L0) ------------------------------------------------------------

    def on_menu(self, action: str) -> None:
        """Кнопки под полем ввода — то, что в приложении-трекере было бы экранами."""
        try:
            if action == "day":
                self.send_panel(pin=True)
            elif action == "status":
                self.send(tpl.status(self.core))
            elif action == "focus":
                self.offer_focus()
            elif action == "sleep":
                self.await_set("sleep")
                self.send("Как спал? «7:20» — или словами: «лёг в час, встал в 8:30».")
            elif action == "add":
                self.await_set("add")
                self.send("Что и когда? Например: «Физика 18:00 60м !4». Без времени — подберу окно сам.")
            elif action == "done":
                self.report_current()
            elif action == "app":
                self.send_app_link()
        except ArvixError as exc:
            self.send(f"Отказ: {exc}")

    def report_current(self) -> None:
        """✅ Сделал: отчёт по задаче, которая идёт; если такой нет и открыта одна — по ней;
        иначе — панель, где у каждой задачи своя кнопка."""
        open_tasks = [t for t in self.core.state.tasks_on(self.core.today()) if t.is_open]
        active = [t for t in open_tasks if t.status == "active"]
        pick = active[0] if len(active) == 1 else (open_tasks[0] if len(open_tasks) == 1 else None)
        if pick is None:
            self.send_panel(pin=False, hint="Какую? Нажми ✅ у задачи." if open_tasks else "Открытых задач нет. Напиши, что сделал, — запишу.")
            return
        self.on_task_button(pick.id, "yes")

    def quick_add(self, fields: dict[str, Any]) -> None:
        task = self.core.add_task(fields.pop("title"), source="telegram", **fields)
        self.send(f"+ {task_line(task, with_id=False)}" + tpl.warn([f"«{task.title}»: {w}" for w in self.core.task_warnings(task)]))
        self.refresh_panel()

    # --- кнопки ----------------------------------------------------------------

    def on_callback(self, callback: dict[str, Any]) -> None:
        try:
            self.api.answer_callback(callback["id"])
        except TelegramError:
            pass
        if (callback.get("from") or {}).get("id") != self.owner:
            return
        message = callback.get("message") or {}
        data = callback.get("data") or ""
        kind, _, rest = data.partition(":")
        panel = self.core.store.kv_get(PANEL) or {}
        on_panel = kind == "p" or (panel.get("message_id") is not None and message.get("message_id") == panel.get("message_id"))
        if not on_panel:  # панель правится на месте, у остальных сообщений кнопки снимаются
            try:
                self.api.drop_buttons(message["chat"]["id"], message["message_id"])
            except (TelegramError, KeyError):
                pass
        self.core.refresh()
        self.log_in(f"[кнопка {data}]")
        try:
            if kind == "t":
                task_id, _, op = rest.partition(":")
                self.on_task_button(task_id, op)
            elif kind == "q":
                self.on_interview_button(rest)
            elif kind == "s":
                self.on_schedule_button(rest)
            elif kind == "f":
                self.on_focus_button(rest)
            elif kind == "p":
                self.on_panel_button(rest)
            elif kind == "l":
                task_id, _, op = rest.partition(":")
                self.on_lesson_button(task_id, op)
            elif kind == "r":
                self.on_return_button(rest)
            elif kind == "j":
                project_id, _, op = rest.partition(":")
                self.on_project_button(project_id, op)
        except ArvixError as exc:
            self.send(f"Отказ: {exc}")

    def on_task_button(self, task_id: str, op: str) -> None:
        core = self.core
        task = core.resolve_task(task_id)
        if op == "start":
            if self.is_lesson_task(task):
                self.begin_lesson(task)
            else:
                core.start_task(task.id, source="telegram")
                self.send(tpl.reminder_start(task))
        elif op in ("d15", "d30"):
            moved = core.defer_task(task.id, int(op[1:]), source="telegram")
            self.send(f"⏳ «{moved.title}» → {moved.start}")
        elif op == "yes" and self.lesson_pending(task.id):
            self.send_lesson_check()  # отчёт по учебному блоку — ответы на вопросы, а не «что сделано»
        elif op == "yes":
            if task.proof == "confirm":
                result = core.complete_task(task.id, source="telegram")
                self.send(tpl.completed(task.title, result["debt_closed"]) + tpl.warn(result["warnings"]))
            else:
                self.await_set("report", task=task.id)
                self.send((tpl.ASK_PHOTO if task.proof == "photo" else tpl.ASK_REPORT).replace("?", f" — «{task.title}»?", 1))
        elif op == "part":
            self.await_set("partial", task=task.id)
            self.send(tpl.ASK_PARTIAL)
        elif op == "no":
            result = core.fail_task(task.id, reason="отмечено кнопкой", source="telegram")
            self.await_set("fail_reason", task=task.id)
            self.send(tpl.failed(task.title, result["debt"]) + "\n" + tpl.ASK_FAIL_REASON)
        self.refresh_panel()

    def on_panel_button(self, op: str) -> None:
        if op == "refresh":
            self.refresh_panel(force=True)
        elif op == "focus":
            self.offer_focus()
        elif op == "add":
            self.on_menu("add")

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
            if today:
                self.send_panel(pin=True)
        elif op == "edit":
            self.await_set("schedule_edit")
            self.send("Напиши, что поменять: «в среду тренировка в 18:00», «английский утром перед школой», «меньше часов».")
        elif op == "save":
            self.send("Предложение устарело. Опиши неделю ещё раз — соберу новое.")

    # --- панель дня ---------------------------------------------------------------------

    def panel_view(self) -> tuple[str, list[list[tuple[str, str]]]]:
        core = self.core
        if core.effective_mode() == "red":  # в 🟥 — без задач и цифр (правило №5), но с выходом (D38)
            if not core.state.mentor_enabled:
                return "📋 Сегодня без плана и без цифр. Одна маленькая вещь — любая.", [[("🔄", "p:refresh")]]
            return tpl.RED_PANEL, tpl.red_buttons()
        text = tpl.day_panel(core)
        open_tasks = [t for t in core.state.tasks_on(core.today()) if t.is_open]
        return text, tpl.panel_buttons(open_tasks, focus_running=bool(core.store.kv_get(FOCUS)))

    def send_panel(self, *, pin: bool, hint: str = "") -> None:
        """Новая панель дня: отправить, запомнить message_id, закрепить вместо старой."""
        text, buttons = self.panel_view()
        if hint:
            text += f"\n\n{hint}"
        if self.channel != "telegram":  # в приложении панель — это экран «Сегодня», здесь только текст
            self.send(text, buttons)
            return
        previous = self.core.store.kv_get(PANEL) or {}
        message_id = self.send(text, buttons, key=None)
        self.core.store.kv_set(PANEL, {"message_id": message_id, "date": self.core.today().isoformat(), "hash": _digest(text, buttons)})
        if not pin or message_id is None:
            return
        try:
            if previous.get("message_id"):
                self.tg.unpin(self.owner, previous["message_id"])
            self.tg.pin(self.owner, message_id)
        except TelegramError as exc:
            log.info("панель не закреплена: %s", exc)

    def tick_daily_note(self) -> None:
        """Закрытая задача → [x] у её строки в отчёте дня (как галочка в Obsidian); заодно
        сырые {{date:…}} шаблона подставляются. Файл читается раз в день и когда набор
        закрытых задач изменился."""
        core = self.core
        if not core.cfg.vault:
            return
        today = core.today()
        done = sorted(t.id for t in core.state.tasks_on(today) if t.status == "done")
        mark = f"{today.isoformat()}:{','.join(done)}"
        if mark == getattr(self, "_daily_ticked", None):
            return
        self._daily_ticked = mark
        try:
            from arvix import daily_note

            rel = core.vault.daily_path(today)
            if (core.vault.root / rel).is_file():
                daily_note.repair(core, today, rel)
        except (ArvixError, ValueError, OSError) as exc:
            log.info("отчёт дня не отмечен: %s", exc)

    def refresh_panel(self, force: bool = False) -> None:
        """Правит панель на месте, если она сегодняшняя и её содержимое изменилось.
        Зовётся после любого действия с задачами и каждый тик планировщика."""
        self.tick_daily_note()
        panel = self.core.store.kv_get(PANEL) or {}
        if not panel.get("message_id") or panel.get("date") != self.core.today().isoformat():
            return
        text, buttons = self.panel_view()
        digest = _digest(text, buttons)
        if digest == panel.get("hash") and not force:
            return
        try:
            self.tg.edit(self.owner, panel["message_id"], text, buttons)
        except TelegramError as exc:
            if "not modified" not in str(exc):
                log.info("панель не обновилась: %s", exc)
                return
        self.core.store.kv_set(PANEL, {**panel, "hash": digest})

    # --- фокус-таймер --------------------------------------------------------------------
    # Состояние таймера — в kv FOCUS: until, started, minutes, task_id | topic, message_id,
    # paused_at (идёт пауза), paused_sec (сколько стояли). Считаются только активные минуты.

    def focus_target(self) -> Any:
        """Задача для таймера: та, что идёт; иначе ближайшая запланированная на сегодня."""
        tasks = [t for t in self.core.state.tasks_on(self.core.today()) if t.is_open]
        active = [t for t in tasks if t.status == "active"]
        if active:
            return active[0]
        now = self.core.now().strftime("%H:%M")
        upcoming = sorted((t for t in tasks if t.start), key=lambda t: t.start)
        return next((t for t in upcoming if t.start >= now), upcoming[0] if upcoming else None)

    def focus_active_min(self, state: dict[str, Any], now: datetime | None = None) -> int:
        """Минуты работы без пауз: с начала до сейчас (или до начала текущей паузы)."""
        end = datetime.fromisoformat(state["paused_at"]) if state.get("paused_at") else (now or self.core.now())
        seconds = (end - datetime.fromisoformat(state["started"])).total_seconds() - float(state.get("paused_sec") or 0)
        return max(0, min(int(seconds // 60), int(state["minutes"])))

    def focus_what(self, state: dict[str, Any]) -> str | None:
        if state.get("task_id") in self.core.state.tasks:
            return self.core.state.tasks[state["task_id"]].title
        return state.get("topic") or None

    def focus_buttons(self, state: dict[str, Any]) -> list[list[tuple[str, str]]]:
        pause = ("▶ Продолжить", "f:resume") if state.get("paused_at") else ("⏸ Пауза", "f:pause")
        return [[pause, ("⏹ Закончить", "f:stop")], [("✕ Отменить, не записывать", "f:cancel")]]

    def focus_message(self, state: dict[str, Any], now: datetime | None = None) -> str:
        now = now or self.core.now()
        until = datetime.fromisoformat(state["until"])
        if state.get("paused_at"):
            left = max(0, int((until - datetime.fromisoformat(state["paused_at"])).total_seconds() // 60) + 1)
            return tpl.focus_paused_text(int(state["minutes"]), self.focus_what(state), left, tpl.FOCUS_MAX_PAUSE_MIN)
        left = max(0, int((until - now).total_seconds() // 60) + 1)
        return tpl.focus_text(int(state["minutes"]), f"{until:%H:%M}", self.focus_what(state), None if left > int(state["minutes"]) else left)

    def _edit_focus(self, state: dict[str, Any], *, final_minutes: int | None = None) -> None:
        if not state.get("message_id"):
            return
        try:
            if final_minutes is not None:
                self.tg.edit(self.owner, state["message_id"], tpl.focus_text(final_minutes, state["until"][11:16], self.focus_what(state), 0))
            else:
                self.tg.edit(self.owner, state["message_id"], self.focus_message(state), self.focus_buttons(state))
        except TelegramError:
            pass

    def release_stale_focus(self) -> None:
        """Задача закрыта или отменена, пока шёл её таймер (например, /done руками): таймер
        снимается сам, прошедшее записывается — иначе он молча блокирует следующий фокус."""
        state = self.core.store.kv_get(FOCUS)
        task = self.core.state.tasks.get(state.get("task_id") or "") if state else None
        if not state or task is None or task.is_open:
            return
        self.core.store.kv_del(FOCUS)
        active = self.focus_active_min(state)
        self._edit_focus(state, final_minutes=active)
        if active >= tpl.FOCUS_MIN_LOGGED:
            self.core.log_focus(active, task_ref=task.id, source="telegram")
        if self.lesson_pending(task.id):
            self.core.store.kv_del(LESSON)

    def offer_focus(self) -> None:
        """🎯 без слов: не запускать сразу, а спросить длительность (случайное нажатие ничего не стоит)."""
        if self.core.store.kv_get(FOCUS):
            self.send_focus_state()
            return
        target = self.focus_target()
        if target is not None and self.is_lesson_task(target):
            self.begin_lesson(target)  # учебная задача: у урока свой план и длительность (D22)
            return
        what = f"на «{target.title}»" if target else "глубокая работа"
        self.send(f"🎯 Фокус {what}. На сколько?\nДругая тема — словами: «фокус 45 минут физика».",
                  [[(f"{m} мин", f"f:go:{m}") for m in tpl.FOCUS_CHOICES]])

    def start_focus(self, minutes: int, task_ref: Any = None, *, lesson: bool = False, topic: str | None = None) -> None:
        self.release_stale_focus()
        if self.core.store.kv_get(FOCUS):
            self.send_focus_state()
            return
        minutes = max(5, min(int(minutes), 180))
        task = None
        if task_ref:
            try:
                task = self.core.resolve_task(task_ref)
            except ArvixError:
                topic = topic or str(task_ref)  # «фокус 45 физика» без такой задачи — это тема, а не ошибка
        elif not topic:
            task = self.focus_target()
        if task is not None and not lesson and self.is_lesson_task(task):
            self.begin_lesson(task)  # учебный блок: план, источники, вопросы, и уже потом таймер
            return
        if task is not None and task.status == "planned":
            self.core.start_task(task.id, source="telegram")
        now = self.core.now()
        state = {"until": (now + timedelta(minutes=minutes)).isoformat(), "started": now.isoformat(), "minutes": minutes,
                 "task_id": task.id if task else None, "topic": (topic or "").strip()[:120] or None, "left": minutes,
                 "paused_at": None, "paused_sec": 0}
        state["message_id"] = self.tg_send(self.focus_message(state, now), self.focus_buttons(state))  # в журнале — его видит и приложение
        self.core.store.kv_set(FOCUS, state)
        self.refresh_panel()

    def send_focus_state(self) -> None:
        state = self.core.store.kv_get(FOCUS) or {}
        self.send(self.focus_message(state), self.focus_buttons(state))

    def pause_focus(self) -> None:
        state = self.core.store.kv_get(FOCUS)
        if not state or state.get("paused_at"):
            return
        state = {**state, "paused_at": self.core.now().isoformat()}
        self.core.store.kv_set(FOCUS, state)
        self._edit_focus(state)
        self.refresh_panel()

    def resume_focus(self) -> None:
        state = self.core.store.kv_get(FOCUS)
        if not state or not state.get("paused_at"):
            return
        stood = (self.core.now() - datetime.fromisoformat(state["paused_at"])).total_seconds()
        until = datetime.fromisoformat(state["until"]) + timedelta(seconds=stood)
        state = {**state, "until": until.isoformat(), "paused_at": None, "paused_sec": float(state.get("paused_sec") or 0) + stood}
        self.core.store.kv_set(FOCUS, state)
        self._edit_focus(state)
        self.refresh_panel()

    def cancel_focus(self) -> None:
        """Случайный старт: таймер снят, ничего не записано, задача остаётся как была."""
        state = self.core.store.kv_get(FOCUS)
        if not state:
            return
        self.core.store.kv_del(FOCUS)
        if state.get("message_id"):
            try:
                self.tg.edit(self.owner, state["message_id"], "🎯 Фокус отменён — ничего не записано.")
            except TelegramError:
                pass
        self.send("Фокус отменён, ничего не записано.")
        self.refresh_panel()

    def ask_focus_note(self, minutes: int, what: str | None) -> None:
        """Зовётся сразу после log_focus: последнее событие журнала — эта сессия."""
        event_id = self.core.state.last_event_id
        self.await_set("focus_note", event=event_id)
        self.send(f"Фокус: {minutes} мин" + (f" · {what}" if what else "") + " — записано.\n"
                  "Что успел? Одной строкой — впишу в сессию. Не хочешь — просто пиши дальше о другом.")

    def on_focus_button(self, rest: str) -> None:
        op, _, minutes = rest.partition(":")
        if op == "stop":
            self.stop_focus()
            return
        if op in ("pause", "resume", "cancel"):
            getattr(self, f"{op}_focus")()
            return
        if op == "go":
            self.start_focus(int(minutes))
            return
        minutes_done = int(minutes) if op == "ok" else int(minutes) // 2
        done = self.core.store.kv_get("focus_done") or {}
        self.core.store.kv_del("focus_done")
        task_id = done.get("task_id")
        task = self.core.log_focus(minutes_done, task_ref=task_id if task_id in self.core.state.tasks else None, topic=done.get("topic"),
                                   source="telegram")
        self.ask_focus_note(minutes_done, task.title if task else done.get("topic"))
        if task and task.is_open:
            self.send("Закрыть задачу — ✅ на панели.")
        self.refresh_panel()

    def stop_focus(self) -> int | None:
        """Закончить раньше: записываются активные минуты (без пауз). Возвращает id сессии."""
        state = self.core.store.kv_get(FOCUS)
        if not state:
            self.send("Фокус не идёт. Запустить — 🎯 внизу или «засеки 25 минут».")
            return None
        self.core.store.kv_del(FOCUS)
        active = self.focus_active_min(state)
        task_id = state.get("task_id") if state.get("task_id") in self.core.state.tasks else None
        self._edit_focus(state, final_minutes=active)
        self.refresh_panel()
        if active < tpl.FOCUS_MIN_LOGGED:
            self.send(f"Фокус сброшен: меньше {tpl.FOCUS_MIN_LOGGED} минут — не сессия.")
            return None
        task = self.core.log_focus(active, task_ref=task_id, topic=state.get("topic"), source="telegram")
        event_id = self.core.state.last_event_id
        self.ask_focus_note(active, task.title if task else state.get("topic"))
        return event_id

    def focus_tick(self, now: datetime) -> None:
        """Обратный отсчёт в сообщении таймера раз в минуту; по окончании — вопрос о прерываниях.
        Пауза дольше FOCUS_MAX_PAUSE_MIN — фокус закрывается с активными минутами."""
        self.release_stale_focus()
        state = self.core.store.kv_get(FOCUS)
        if not state:
            return
        if state.get("paused_at"):
            if (now - datetime.fromisoformat(state["paused_at"])).total_seconds() > tpl.FOCUS_MAX_PAUSE_MIN * 60:
                self.send(f"Пауза дольше {tpl.FOCUS_MAX_PAUSE_MIN} минут — фокус закрыт.")
                self.stop_focus()
            return
        until = datetime.fromisoformat(state["until"])
        if until > now:
            left = int((until - now).total_seconds() // 60) + 1
            if left != state.get("left"):
                state = {**state, "left": left}
                self._edit_focus(state)
                self.core.store.kv_set(FOCUS, state)
            return
        self.core.store.kv_del(FOCUS)
        minutes = int(state["minutes"])
        self._edit_focus(state, final_minutes=minutes)
        if state.get("task_id") and self.lesson_pending(state["task_id"]):
            # Учебный блок: таймер засчитан целиком, вместо «без прерываний?» — вопросы проверки
            self.core.log_focus(minutes, task_ref=state["task_id"], source="telegram")
            self.send_lesson_check(key=f"focus:{state['until']}")
            self.refresh_panel()
            return
        self.core.store.kv_set("focus_done", {"task_id": state.get("task_id"), "topic": state.get("topic")})
        self.send(
            f"Фокус {minutes} минут закончен. Без прерываний?",
            [[("✅ Да", f"f:ok:{minutes}"), ("⚠️ Прерывали", f"f:int:{minutes}")]],
            key=f"focus:{state['until']}",
        )
        self.refresh_panel()

    # --- учебный блок (06-LEARNING §8) ----------------------------------------------------

    def is_lesson_task(self, task: Any) -> bool:
        return task.sphere == "learning" and bool(self.core.cfg.section("learning").get("auto_lesson", True))

    def lesson_pending(self, task_id: str) -> bool:
        """Урок по задаче подготовлен и ещё не проверен."""
        state = self.core.store.kv_get(LESSON) or {}
        return state.get("task_id") == task_id

    def prepare_lesson(self, task: Any, *, key: str | None = None) -> dict[str, Any]:
        """Один вызов головы: роадмап, журнал ошибок и метод человека → план по минутам, источники,
        вопросы проверки. Голова молчит — запасной план кодом, проверка — обычное «Сделано?»."""
        core = self.core
        section = core.cfg.section("learning")
        questions = int(section.get("check_questions") or lesson_mod.DEFAULT_QUESTIONS)
        subject = lesson_mod.subject_of(task.title)
        paths = core.cfg.vault_paths
        methods = paths.get("notes") or "03_Resources/Обучение"
        tools = section.get("tools") or []
        rules_text = lesson_mod.LESSON_RULES.format(
            minutes=task.duration_min, title=task.title, sphere=task.sphere, date=core.today().isoformat(),
            roadmaps=paths.get("roadmaps") or "03_Resources/Роадмапы", methods=methods,
            history="; ".join(core.lesson_history(subject)) or "нет",
            tools=(": " + ", ".join(str(t) for t in tools)) if tools else "", questions=questions,
        )
        system = "\n\n".join([
            constitution(core.state.profile, gentle=True, sections=("identity", "mission", "autonomy_rule", "honesty")),
            rules_text, "<context>\n" + build_context(core) + "\n</context>",
        ])
        with self.typing_kept():
            result = self.brain.ask(system=system, prompt=f"Подготовь учебный блок: {task.title}, {task.duration_min} минут.",
                                    schema=lesson_mod.LESSON_SCHEMA, role="voice", vault_tools=True)
        if not result or not result.get("plan"):
            result = {"topic": task.title, "why": "", "roadmap_node": "", "plan": lesson_mod.fallback_plan(task.duration_min),
                      "sources": [], "check": [], "fallback": True}
        result["check"] = [c for c in result.get("check") or [] if c.get("q") and c.get("a")][:questions]
        note_path = core.concept_skeleton(result.get("note_title") or result["topic"], subject,
                                          [c["q"] for c in result["check"]], list(result.get("sources") or []))
        core.lesson_started(task.id, result, note_path=note_path)
        lesson = {"task_id": task.id, "topic": result["topic"], "plan": result["plan"], "check": result["check"],
                  "note": note_path, "sources": result.get("sources") or [], "started": None}
        core.store.kv_set(LESSON, lesson)
        text = lesson_mod.render(result, task, note_path)
        if result.get("fallback"):
            text += "\n\nГолова недоступна — план общий, тема по названию задачи." + (" " + self.brain_down_hint() if self.brain_down_hint() else "")
        buttons = [[(f"▶️ Начать · {task.duration_min} мин", f"l:{task.id}:go")]] if task.status == "planned" else None
        self.send(text, buttons, key=key)
        return lesson

    def begin_lesson(self, task: Any) -> None:
        """▶️ у учебной задачи: план (если ещё не было) → задача запущена → таймер на всю длительность."""
        if not self.lesson_pending(task.id):
            self.prepare_lesson(task)
        lesson = self.core.store.kv_get(LESSON) or {}
        if lesson.get("started"):
            self.send_focus_state() if self.core.store.kv_get(FOCUS) else self.send("Блок уже идёт. Готов отвечать — ✅ на панели.")
            return
        task = self.core.resolve_task(task.id)
        if task.status == "planned":
            self.core.start_task(task.id, source="telegram")
        self.core.store.kv_set(LESSON, {**lesson, "started": self.core.now().isoformat()})
        self.start_focus(task.duration_min, task.id, lesson=True)

    def on_lesson_button(self, task_id: str, op: str) -> None:
        task = self.core.resolve_task(task_id)
        if op == "go":
            self.begin_lesson(task)
        elif op == "check" and self.lesson_pending(task.id):
            self.send_lesson_check()
        elif op == "plan":
            if self.lesson_pending(task.id):
                self.send("План уже есть — выше. ▶️ Начать — там же.")
            else:
                self.prepare_lesson(task)
        elif op == "timer":
            if task.status == "planned":
                self.core.start_task(task.id, source=self.channel)
            self.start_focus(task.duration_min, task.id)
        elif op == "later":
            self.send("Хорошо, блок остаётся в плане. Скажешь — начнём.")

    def send_lesson_check(self, *, key: str | None = None) -> None:
        lesson = self.core.store.kv_get(LESSON) or {}
        if not lesson.get("check"):
            task = self.core.resolve_task(lesson["task_id"])
            self.core.store.kv_del(LESSON)
            self.send(tpl.reminder_check(task), tpl.task_buttons_check(task.id), key=key)
            return
        self.await_set("lesson_check", task=lesson["task_id"])
        self.send(lesson_mod.render_check(lesson), key=key)

    def grade_lesson(self, answers: str) -> None:
        """Второй вызов головы: ответы против эталонов → оценка, пробелы, что дочитать.
        Задача закрывается кодом: done_pct по оценке, отчёт — ответы человека."""
        core = self.core
        lesson = core.store.kv_get(LESSON) or {}
        task = core.resolve_task(lesson["task_id"])
        system = "\n\n".join([
            constitution(core.state.profile, gentle=True, sections=("identity", "voice", "honesty")),
            lesson_mod.CHECK_RULES.format(topic=lesson.get("topic", ""), pairs=lesson_mod.check_pairs(lesson)),
        ])
        try:
            self.api.typing(self.owner)
        except TelegramError:
            pass
        result = self.brain.ask(system=system, prompt=answers, schema=lesson_mod.CHECK_SCHEMA, role="voice")
        core.store.kv_del(LESSON)
        score = None if result is None else rules.clamp(int(result.get("score_pct") or 0), 0, 100)
        gaps = list((result or {}).get("gaps") or [])
        core.lesson_checked(task.id, score_pct=score, answers=answers, gaps=gaps, next_step=(result or {}).get("next_step", ""))
        receipt_lines = []
        if task.is_open or task.status == "debt":
            pct = 100 if score is None else max(30, score)
            done = core.complete_task(task.id, done_pct=pct, report=f"проверка {score}%: {answers}" if score is not None else answers, source="telegram")
            receipt_lines.append(tpl.completed(task.title) + (f" · проверка {score}%" if score is not None else ""))
            receipt_lines += [f"⚠️ Проверь: {w}" for w in done["warnings"]]
        if gaps:
            receipt_lines.append("В карточки и журнал ошибок: " + "; ".join(gaps[:4]))
        if lesson.get("note"):
            receipt_lines.append(f"📝 Заметка своими словами: {lesson['note']}")
        if result is None:
            feedback = "Оценить не могу — голова недоступна. Ответы записаны, блок закрыт как сделанный."
        else:
            feedback = (result.get("feedback") or "").strip()
            if result.get("next_step"):
                feedback += f"\n\nСледующий блок: {result['next_step'].strip()}"
        self.reply(feedback, "\n".join(receipt_lines))
        self.refresh_panel()

    def lesson_context(self) -> str:
        """Блок <lesson> в промпт L1, пока идёт учебный блок: объяснение у доски вместо подсказки."""
        lesson = self.core.store.kv_get(LESSON) or {}
        if not lesson.get("started"):
            return ""
        task = self.core.state.tasks.get(lesson["task_id"])
        if task is None:
            return ""
        elapsed = int((self.core.now() - datetime.fromisoformat(lesson["started"])).total_seconds() // 60)
        plan = "; ".join(f"{s.get('from_min')}–{s.get('to_min')} {s.get('step')}" for s in lesson.get("plan") or [])
        return lesson_mod.LESSON_CONTEXT.format(topic=lesson.get("topic", ""), title=task.title, minutes=task.duration_min,
                                                elapsed=f"{elapsed} мин", plan=plan)

    def on_block_start(self, task: Any, *, key: str) -> bool:
        """T+0 у учебной задачи: вместо «Блок пошёл» — план урока с кнопкой «Начать». False — обычный путь."""
        if not self.is_lesson_task(task) or self.lesson_pending(task.id):
            return False
        self.prepare_lesson(task, key=key)
        return True

    def propose_schedule(self, wishes: str = "") -> None:
        """Один вызов модели: ответы интервью + бюджет → шаблоны дней на подтверждение."""
        core = self.core
        st = core.state
        answers = [f"В: {q['text']}\nО: {st.interview[q['id']]}" for q in interview.QUESTIONS
                   if q["id"] in st.interview and q["block"] not in ("inner", "money", "people")]
        if not answers and not wishes:
            self.send("Опиши неделю словами: учёба или работа по дням, когда свободен, подъём и отбой. Соберу распорядок.")
            return
        prompt = ("Ответы человека:\n\n" + "\n\n".join(answers)) if answers else "Ответов интервью нет — только его слова ниже."
        previous = core.store.kv_get(PENDING)
        if previous:
            prompt += "\n\nПрежний вариант распорядка:\n" + render_templates(previous)
        if wishes:
            prompt += f"\n\nПожелания человека: {wishes}"
        system = "\n\n".join([constitution(st.profile, gentle=True, sections=("identity", "honesty")), SCHEDULE_RULES,
                                "<context>\n" + build_context(core) + "\n</context>"])
        with self.typing_kept():
            result = self.brain.ask(system=system, prompt=prompt, schema=TEMPLATES_SCHEMA, role="voice", vault_tools=True)
        if not result or not result.get("templates"):
            self.send("Не вышло собрать распорядок. " + (self.brain_down_hint() or "Опиши неделю ещё раз чуть позже."))
            return
        core.store.kv_set(PENDING, result["templates"])
        self.send(clip(result.get("summary", ""), 500) + "\n\n" + render_templates(result["templates"], load.factors_of(core.state.budget)),
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
        done, failed, warnings = apply_actions(self.core, result.get("actions") or [], source="telegram")
        summary = result.get("summary", "").strip()
        receipt = self.receipt(done, failed, warnings)
        if summary or receipt:
            self.reply(summary, receipt)

    # --- голова (L1) ---------------------------------------------------------------

    @staticmethod
    def receipt(done: list[str], failed: list[str], warnings: list[str]) -> str:
        """Квитанция кода под ответом: по строке на запись, отказ и сомнение — без id."""
        lines = list(done)
        lines += [f"⚠️ Не выполнено: {f}" for f in failed]
        lines += [f"⚠️ Проверь: {w}" for w in warnings]
        return "\n".join(lines)

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

    @contextmanager
    def typing_kept(self) -> Any:
        """«печатает…» всё время, пока думает голова: Telegram гасит индикатор через 5 с,
        а ответ идёт 5–30 с. Поток трогает только HTTP, базу — нет."""
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(TYPING_EVERY):
                try:
                    self.api.typing(self.owner)
                except TelegramError:
                    pass

        try:
            self.api.typing(self.owner)
        except TelegramError:
            pass
        worker = threading.Thread(target=loop, daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()

    def dialog_block(self, text: str) -> str:
        """Человеческий ритм разговора считает код: первое сообщение дня — привет,
        поздний вечер — пора прощаться. Модель это не угадывает, а получает фактом."""
        now = self.core.now()
        lines = []
        if self.first_today:
            part = "Доброе утро" if 5 <= now.hour < 12 else "Добрый вечер" if now.hour >= 18 else "Привет"
            lines.append(f"Первое сообщение человека за сегодня: начни с короткого приветствия отдельным сообщением "
                         f"(«{part}» или «Привет», по-своему, без вопросов «как дела?»), потом — ответ.")
        bedtime = self.core.state.profile.get("bedtime_target") or "23:00"
        try:
            bed = self.core.at(now.date(), bedtime)
        except ValueError:
            bed = self.core.at(now.date(), "23:00")
        if bed.hour < 5:  # отбой после полуночи
            bed += timedelta(days=1)
        if now >= bed - timedelta(minutes=45) or now.hour < 4:
            lines.append(f"Поздно: отбой по плану в {bedtime}. Если разговор закругляется — коротко попрощайся и "
                         "пожелай спокойной ночи. Новых дел на вечер не предлагай.")
        return "<dialog>\n" + "\n".join(lines) + "\n</dialog>" if lines else ""

    def notes_block(self, text: str) -> str:
        """Человек спрашивает про свои заметки — код сам ищет в хранилище и кладёт находки
        в промпт. Модели не нужно три хода Grep/Read (это 20–40 с ожидания)."""
        if not self.core.cfg.vault or not NOTES_ASK.search(text):
            return ""
        from arvix.vault import Vault

        try:
            found = Vault(self.core.cfg.vault, self.core.cfg.vault_paths).search(text, 5)
        except OSError:
            return ""
        if not found:
            return ""
        rows = [f"{r['path']}" + (f" — «{r['heading']}»" if r["heading"] else "") + f": {r['snippet']}" for r in found]
        return ("<vault_hits>\nНайдено кодом в хранилище по словам сообщения. Если этого мало — открой файл (Read).\n"
                + "\n".join(rows) + "\n</vault_hits>")

    def recall_block(self, text: str) -> str:
        try:
            self.memory.sync()
            window = self.history_start_id()
            return self.memory.recall_block(text, before_id=window)
        except Exception:  # noqa: BLE001 — память не должна ронять ответ
            log.exception("память недоступна")
            return ""

    def history_start_id(self) -> int | None:
        """Первое событие, которое уже лежит в промпте как свежая история (+ текущее сообщение).
        Всё, что новее, в <recall> не повторяется."""
        start = max(0, self.core.state.last_event_id - 400)
        ids = [e.id for e in self.core.store.read(start) if e.kind in ("message_in", "message_out")]
        return ids[-(HISTORY + 1):][0] if ids else None

    def converse(self, text: str, extra: str = "", *, voice: bool = False) -> None:
        core = self.core
        if voice and self.channel == "telegram":
            # Голосовое в Telegram: ответ читают глазами (D45), а распознавание может путать слова.
            extra += ("\n<dictated>Человек надиктовал это голосом; распознавание могло исказить слова — понимай по смыслу. "
                      "Ответ он прочитает текстом: обычный ответ по правилам канала, не пересказ для слуха.</dictated>")
        elif voice:
            # Режим разговора в приложении: ответ озвучивается целиком (D34).
            extra += ("\n<spoken>Человек говорит голосом, ответ будут слушать: 2–5 коротких предложений, без списков, "
                      "заголовков и смайлов; если разговор продолжается — закончи вопросом.</spoken>")
        if core.store.kv_get("answer_mode"):
            core.store.kv_del("answer_mode")
            extra += "\n<answer_mode>Человек запросил готовый ответ. Дай полный ответ с источниками и action learning_question с direct=true.</answer_mode>"
        silent_days = core.state.ignore_streak(core.today() - timedelta(days=1))
        today = core.state.days.get(core.today())
        if silent_days >= 2 and today and today.user_actions <= 2:
            extra += "\n" + tpl.RETURN_HINT.format(days=silent_days)
        if lesson := self.lesson_context():
            extra += "\n" + lesson
        if dialog := self.dialog_block(text):
            extra += "\n" + dialog
        if weather.asks_weather(text):
            extra += "\n" + weather.weather_block(core)
        for block in (self.recall_block(text), self.notes_block(text)):
            if block:
                extra += "\n" + block
        # Статичная часть — системный промпт (из кэша), всё живое — в запросе (D40).
        system, prompt = voice_prompt(core, channel=self.channel if self.channel == "telegram" else "telegram",
                                      message=text, history=self.history(exclude_last=text), extra=extra.strip())
        # Навыки (D33): в 🟥 и при выключенном менторе — только мягкие (разговор, тревога), правило №5.
        skills = "gentle" if core.effective_mode() == "red" or not core.state.mentor_enabled else "full"
        ask = {"system": system, "schema": VOICE_SCHEMA, "vault_tools": True, "web": True, "skills": skills, "effort": effort_for(text)}
        with self.typing_kept():
            result = self.brain.ask(prompt=prompt, **ask)
            if result is None:
                heard = f"🎙 «{clip(text, 300)}»\n" if voice else ""  # голова молчит — пусть хотя бы видно, что услышано
                self.send(heard + " ".join(x for x in (tpl.FALLBACK, self.brain_down_hint()) if x))
                return
            reply = (result.get("reply") or "").strip()
            # Перегенерация — с пометкой в запросе, а не в системном промпте: кэш системного остаётся.
            if core.effective_mode() == "red" and gentle_violation(reply):
                retry = self.brain.ask(
                    prompt=prompt + "\n\n<validator>В ответе были слова про дисциплину, задачи или метрики. В мягком режиме это запрещено. Перепиши по-человечески.</validator>",
                    **ask,
                )
                ok = retry is not None and not gentle_violation(retry.get("reply", ""))
                result = retry if ok else {"actions": []}
                reply = retry["reply"].strip() if ok else tpl.GENTLE_FALLBACK
            if result.get("learning") and not has_source(reply):
                retry = self.brain.ask(
                    prompt=prompt + "\n\n<validator>Ответ обучающий, но первоисточник не назван. Назови его: учебник и параграф, "
                    "официальная документация или спецификация. Ссылку давай только настоящую; не уверен — без ссылки. Не выдумывай URL.</validator>",
                    **ask,
                )
                if retry and has_source(retry.get("reply", "")):
                    result, reply = retry, retry["reply"].strip()
                else:
                    reply += "\n\n(Первоисточник не назван — сверь тему с учебником или официальной документацией.)"
        actions = result.get("actions") or []
        voice_note = str(result.get("voice_note") or "")
        if core.effective_mode() == "red" and gentle_violation(voice_note):
            voice_note = ""  # правило №5 и для голоса: в 🟥 про дисциплину не говорят ни текстом, ни вслух
        done, failed, warnings = apply_actions(core, actions, source=self.channel, fallback_report=text)
        self.reply(reply, self.receipt(done, failed, warnings), voice_note=voice_note)
        if done:
            self.refresh_panel()
        self.run_ui_actions([a for a in actions if a.get("type") in UI_ACTIONS], text)
        try:  # папка памяти для поиска головы — после ответа: человек не ждёт записи файлов
            export_transcripts(core)
        except OSError as exc:
            log.warning("папка памяти: %s", exc)

    # --- действия интерфейса по словам человека (05-INTERFACES §2.1) -------------------

    def run_ui_actions(self, actions: list[dict[str, Any]], text: str) -> None:
        """Человек говорит словами — бот делает то, что раньше требовало команды.
        Модель выбирает действие, код исполняет. Ошибка одного не мешает остальным."""
        for action in actions[:3]:
            kind = action.get("type")
            try:
                if kind == "plan_schedule":
                    self.propose_schedule(action.get("wishes") or action.get("text") or text)
                elif kind == "show_schedule":
                    self.cmd_schedule("show")
                elif kind == "start_lesson":
                    self.offer_lesson(action, text)
                elif kind == "start_focus":
                    self.start_focus(int(action.get("minutes") or tpl.FOCUS_DEFAULT_MIN), action.get("task") or action.get("title") or None)
                elif kind == "stop_focus":
                    self.stop_focus()
                elif kind == "show_day":
                    self.send_panel(pin=True)
                elif kind == "show_status":
                    self.send(tpl.status(self.core))
                elif kind == "show_week":
                    self.send(tpl.week(self.core))
                elif kind == "show_goals":
                    self.cmd_goals("")
                elif kind == "debrief_now":
                    self.send_debrief(manual=True)
                elif kind == "rest_day":
                    self.cmd_sos("")
                elif kind == "offer_return":
                    self.offer_return()
                elif kind == "silent_day":
                    self.cmd_silent("")
                elif kind == "open_app":
                    self.send_app_link()
                elif kind == "install_app":
                    self.send_install()
            except ArvixError as exc:
                self.send(f"Не вышло: {exc}")
            except Exception:  # noqa: BLE001 — сбой действия не должен ронять уже отправленный ответ
                log.exception("действие %s", kind)

    def offer_lesson(self, action: dict[str, Any], text: str) -> None:
        """«Давай позанимаемся физикой» → карточка: какой блок, какая задача, сколько длится.
        Подтверждение — кнопкой: план урока стоит отдельного вызова головы, зря его не тратим."""
        core = self.core
        minutes = int(action.get("minutes") or 0) or None
        topic = (action.get("topic") or action.get("title") or "").strip()
        task = None
        if ref := action.get("task"):
            try:
                task = core.resolve_task(ref)
            except ArvixError:
                task = None
        if task is None:
            today = [t for t in core.state.tasks_on(core.today()) if t.is_open and t.sphere == "learning"]
            if topic:
                today = [t for t in today if topic.lower()[:5] in t.title.lower()] or today
            task = next((t for t in today if t.status == "active"), None) or (today[0] if today else None)
        if task is None:
            if not topic:
                self.send("Учебных блоков сегодня нет. Скажи предмет и сколько минут — поставлю блок прямо сейчас.")
                return
            task = core.add_task(topic, sphere="learning", importance=3, deep_work=True, start=core.now().strftime("%H:%M"),
                                 duration_min=minutes or lesson_mod.DEFAULT_MINUTES, source=self.channel)
        when = f"{task.start}–{end_time(task.start, task.duration_min)}" if task.start else "сейчас"
        lines = [f"📚 **{task.title}**", f"⏱ {task.duration_min} мин · {when}"]
        history = core.lesson_history(lesson_mod.subject_of(task.title), 1)
        if history:
            lines.append(f"Прошлый урок: {history[-1]}")
        lines.append("Тему возьму из роадмапа, план — по минутам, в конце 3 вопроса.")
        self.send_rich("\n".join(lines), [[("📚 План урока", f"l:{task.id}:plan"), ("🎯 Просто таймер", f"l:{task.id}:timer")],
                                          [("✖️ Не сейчас", f"l:{task.id}:later")]])

    def send_rich(self, text: str, buttons: list[list[tuple[str, str]]] | None = None, *, key: str | None = None) -> int | None:
        """Сообщение кода с разметкой (жирный, строки) — как ответ головы, но одним пузырём."""
        message_id = self.api.send(self.owner, fmt.strip_markup(text), buttons, html=fmt.to_html(text))
        self.core.message_out(fmt.strip_markup(text), key=key, channel=self.channel, buttons=buttons)
        return message_id

    def app_url(self) -> str:
        return str(self.core.cfg.section("web").get("public_url") or "").rstrip("/")

    def install_link(self) -> str:
        from arvix.web.auth import pair_code

        url = self.app_url()
        return f"{url}/#p={pair_code(self.core)}" if url else ""

    def send_install(self) -> None:
        """Арвикс на телефон «как APK»: Chrome сам собирает из приложения WebAPK — иконка,
        своё окно, обновляется сам (D26). Ссылка одноразовая: постоянный ключ в чат не попадает."""
        link = self.install_link()
        if not link:
            self.send("Приложение ещё не включено на сервере: нужен HTTPS-адрес (deploy/web-setup.sh).")
            return
        self.send_rich(
            "📲 **Арвикс на телефон** — настоящее приложение: иконка на экране, своё окно, без адресной строки, обновляется само.\n"
            "1. Нажми «Установить» — откроется браузер. Если открылось внутри Telegram — ⋮ → «Открыть в Chrome».\n"
            "2. В Chrome появится кнопка «Установить Арвикс» (или ⋮ → «Установить приложение»).\n"
            "Ссылка одноразовая и живёт 15 минут.",
            [[("📲 Установить", f"url:{link}")]],
        )

    def send_app_link(self) -> None:
        url = self.app_url()
        if not url:
            self.send("Приложение ещё не включено на сервере: нужен HTTPS-адрес (deploy/web-setup.sh).")
            return
        self.send_rich("📱 **Арвикс** — задачи, фокус, заметки и прогресс. Обновляется сам.",
                       [[("Открыть", f"app:{url}/")]])

    def send_curiosity(self) -> bool:
        """Раз в день Арвикс сам пишет первым — не «как дела», а про то, что помнит:
        пробник, разговор, обещание. Вызывает планировщик ([schedule] curiosity)."""
        core = self.core
        st = core.state
        if core.effective_mode() == "red" or not st.mentor_enabled:
            return False
        recent = [f for f in list(st.facts.values())[-25:]]
        facts = "\n".join(f"- {f['fact']}" for f in recent) or "—"
        system = "\n\n".join([
            constitution(st.profile, gentle=False, sections=("identity", "voice", "honesty")),
            "<context>\n" + build_context(core) + "\n</context>",
            "<history>\n" + "\n".join(self.history()) + "\n</history>",
            "<curiosity>\nНапиши человеку первым — одно короткое сообщение, 1–2 предложения. Как наставник, которому "
            "правда интересно: спроси про конкретное из памяти (событие, пробник, разговор, решение, проект) или "
            "поделись одной мыслью по его цели. Не «как дела?», не про задачи из списка, не напоминание. "
            "Если спросить нечего — reply пустой.\n</curiosity>",
        ])
        result = self.brain.ask(system=system, prompt="Факты о человеке:\n" + facts, schema=VOICE_SCHEMA)
        reply = ((result or {}).get("reply") or "").strip()
        if not reply:
            return False
        self.reply(reply, key=f"curiosity:{core.today().isoformat()}")
        return True

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
        self.send(f"{prefix}\n\n{text}" if prefix else text, key=f"brief:{self.core.today().isoformat()}", keyboard=tpl.keyboard(self.app_url()))
        day = self.core.state.days.get(self.core.today())
        if not (day and day.sleep_min):
            self.await_set("sleep")
        red = self.core.effective_mode() == "red"
        if (red and self.core.state.mentor_enabled) or (not red and self.core.state.tasks_on(self.core.today())):
            self.send_panel(pin=True)  # в 🟥 — панель восстановления с кнопкой «Вернуться к плану»

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
                text += "\nТихий день — разбор без долга, только выводы."
            text += "\n\nДва вопроса:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions[:2], 1))
            text += "\nОтветь одним сообщением."
        if not manual and not day.user_actions:
            text = tpl.SILENT_TODAY + "\n\n" + text
        self.send(text, key=f"debrief:{today.isoformat()}")
        self.await_set("debrief")

    def debrief_answer(self, text: str) -> None:
        core = self.core
        extra = "<debrief>Человек ответил на вопросы вечернего разбора. Один вывод — что меняем завтра — и коротко про план завтра (блок ЗАВТРА в контексте). До 5 строк.</debrief>"
        system, prompt = voice_prompt(core, message=text, extra=extra)
        result = self.brain.ask(system=system, prompt=prompt, schema=VOICE_SCHEMA, effort="medium")
        conclusion = (result or {}).get("reply", "").strip()
        receipt = ""
        if result:
            receipt = self.receipt(*apply_actions(core, result.get("actions") or [], source="telegram"))
        core.complete_debrief(text, conclusion=conclusion, source="telegram")
        try:
            from arvix import daily_note

            if rel := daily_note.sync(core, core.today()):
                receipt = (receipt + "\n" if receipt else "") + f"📝 Разбор вписан в {rel}"
        except ArvixError as exc:
            log.warning("ежедневный отчёт не обновлён: %s", exc)
        self.reply(conclusion or "Разбор записан. Завтра — по плану, отбой вовремя.", receipt)

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
        self.log_in(text)
        head, _, rest = text.partition(" ")
        name = head[1:].split("@")[0].lower()
        handler = getattr(self, f"cmd_{name}", None)
        if handler is None:
            self.send("Команды не нужны — напиши словами, что сделать.")
            return
        try:
            handler(rest.strip())
        except ArvixError as exc:
            self.send(f"Отказ: {exc}")

    def cmd_start(self, rest: str) -> None:
        status = self.core.interview_status()
        core_block = next(b for b in status["blocks"] if b["block"] == "core")
        if core_block["done"] < core_block["total"]:
            self.send("Я Арвикс. Не ассистент и не друг по переписке — внешний контур дисциплины, пока не выстроится свой.", keyboard=tpl.keyboard(self.app_url()))
            self.cmd_onboard("")
        else:
            self.send_brief()

    def cmd_menu(self, rest: str) -> None:
        self.send("Кнопки внизу: панель дня, отчёт, фокус, сон, задача, статус.", keyboard=tpl.keyboard(self.app_url()))

    def cmd_schedule(self, rest: str) -> None:
        if rest.strip() == "show" and self.core.state.templates:
            current = [{"weekdays": [w], **t} for w, t in sorted(self.core.state.templates.items())]
            self.send(render_templates(current, load.factors_of(self.core.state.budget)))
            return
        self.propose_schedule(rest.strip())

    def cmd_goals(self, rest: str) -> None:
        icons = {"active": "○", "done": "●", "dropped": "✖"}
        rows = ["  " * depth + f"{icons.get(g.get('status'), '○')} {g['title']}" + (f" · до {g['deadline']}" if g.get("deadline") else "")
                for depth, g in self.core.goal_tree() if g.get("status") != "dropped"]
        self.send("🎯 Цели\n\n" + "\n".join(rows) if rows else "Целей пока нет. Разложить цель на этапы — в Claude Code: «хочу …, разложи».")

    def cmd_help(self, rest: str) -> None:
        self.send(tpl.HELP, keyboard=tpl.keyboard(self.app_url()))

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
        self.send("Пауза. Продолжить — «продолжим знакомство».")

    def cmd_day(self, rest: str) -> None:
        target = self.core.parse_day(rest or None)
        if target == self.core.today():
            self.send_panel(pin=True)
            return
        facts = self.core.day_facts(target)
        lines = [f"{facts['date']:%d.%m}: {facts['done']}/{facts['total']} · глубокая {hm(facts['deep_min'])}"]
        lines += [task_line(t, with_id=False) for t in facts["tasks"]] or ["Задач нет."]
        self.send("\n".join(lines))

    def cmd_week(self, rest: str) -> None:
        self.send(tpl.week(self.core))

    def cmd_status(self, rest: str) -> None:
        self.send(tpl.status(self.core))

    def cmd_done(self, rest: str) -> None:
        ref, _, report = rest.partition(" ")
        if not ref:
            self.report_current()
            return
        result = self.core.complete_task(ref, report=report or None, source="telegram")
        self.send(tpl.completed(result["task"].title, result["debt_closed"]) + tpl.warn(result["warnings"]))
        self.refresh_panel()

    def cmd_add(self, rest: str) -> None:
        fields = parse_quick_task(rest)
        if not fields.get("title"):
            self.on_menu("add")
            return
        self.quick_add(fields)

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
        if not rest.strip():
            self.on_menu("sleep")
            return
        self.sleep_answer(rest)

    def cmd_sos(self, rest: str) -> None:
        mode = self.core.sos(rest.strip().lower() != "off", source="telegram")
        if mode == "red":
            self.send(f"Режим: {rules.MODE_LABELS[mode]}\nСегодня без задач и цифр. Сон, еда, движение. Отдохнёшь — вернёшь план кнопкой.",
                      tpl.red_buttons(refresh=False))
        else:
            self.send(f"Режим: {rules.MODE_LABELS[mode]}")
        self.refresh_panel()

    def offer_return(self) -> None:
        """Голова услышала «отдохнул, готов» — но режим меняет не она: кнопку жмёт человек (D38)."""
        core = self.core
        if core.effective_mode() != "red":
            return  # и так в плане — лишняя кнопка только путает
        if not core.state.mentor_enabled:
            self.send("Ментор выключен safety-контуром — включить его можешь только ты сам: /mentor on")
            return
        self.send("Вернуть план? Мягко: без разгона, первым — самое короткое дело.", tpl.red_buttons(refresh=False))

    def on_project_button(self, project_id: str, op: str) -> None:
        """Кнопки напоминания о застое проекта (D43): блок в план или честная пауза — решает человек."""
        from arvix import projects

        project = projects.resolve(self.core, project_id)
        if op in ("b30", "t60"):
            task = projects.plan_block(self.core, project["id"], minutes=int(op[1:]), day="tomorrow" if op[0] == "t" else None,
                                       source="telegram")
            when = "завтра " if task.local_date > self.core.today() else ""
            self.send(f"+ «{task.title}» — {when}{task.start}, {task.duration_min} мин. Напомню за 5 минут.")
            self.refresh_panel()
        elif op == "pause":
            projects.set_project(self.core, project_id=project["id"], status="paused", source="telegram")
            self.send(f"⏸ «{project['title']}» на паузе. Это решение, а не провал: вернуть — во вкладке «Проекты» или словами.")

    def build_project_roadmap(self, goal_id: str) -> None:
        """Роадмап проектов под цель (D44): совет в фоне — проекты ложатся идеями, ответ приходит сообщением."""
        from arvix import project_roadmap

        try:
            result = project_roadmap.generate(self.core, self.brain, goal_id, system=self.analyst_system(""))
        except ArvixError as exc:
            self.send(f"Роадмап не собрался: {exc}")
            return
        text = f"🗺 Роадмап проектов к цели «{result['goal']['title']}»\n\n{clip(result['summary'], 900)}"
        if result["created"]:
            text += "\n\nДобавил идеями по порядку: " + " → ".join(result["created"]) + ". В работу берёшь сам — во вкладке «Проекты»."
        else:
            text += "\n\nНовых проектов не добавил: текущий роадмап уже ведёт к цели."
        if result["path"]:
            text += f"\n📝 {result['path']}"
        self.send(text)

    def on_return_button(self, op: str) -> None:
        core = self.core
        if op == "rest":
            self.send("Отдыхай. Я рядом — вернуть план можно в любой момент кнопкой на панели.")
            return
        if core.effective_mode() != "red":
            self.send("План уже на месте.")
            self.send_panel(pin=True)
            return
        mode = core.resume_plan(source=self.channel)
        today = [t for t in core.state.tasks_on(core.today()) if t.is_open]
        first = min(today, key=lambda t: (t.duration_min or 999, t.start or "")) if today else None
        hint = (f"Первым — «{first.title}», {first.duration_min} мин: ▶️ у задачи или 🎯."
                if first else "Задач на сегодня нет. 🎯 — засеку 25 минут на самое важное; или напиши, чем займёшься, — поставлю.")
        self.send(f"Возвращаемся. Режим {rules.MODE_LABELS[mode]} — без разгона и без новых обязательств.")
        self.send_panel(pin=True, hint=hint)

    def cmd_silent(self, rest: str) -> None:
        self.core.silent_today(source="telegram")
        self.send("Тихий день. Я молчу до вечера, долга за сегодня нет. Ведёшь день сам.")

    def cmd_export(self, rest: str) -> None:
        from arvix.export import export_all

        written = export_all(self.core)
        self.send("Экспорт в Obsidian:\n" + "\n".join(f"• {p}" for p in written[:12]))

    def cmd_debrief(self, rest: str) -> None:
        self.send_debrief(manual=True)

    def cmd_mentor(self, rest: str) -> None:
        """Выключение — только явным «off»: пустой или опечатанный аргумент показывает
        состояние, а не отключает ментора молча."""
        arg = rest.strip().lower()
        if arg in ("on", "вкл", "1"):
            self.core.set_mentor(True, by="telegram")
            self.send("Режим ментора включён.")
        elif arg in ("off", "выкл", "0"):
            self.core.set_mentor(False, by="telegram")
            self.send("Режим ментора выключен.")
        else:
            state = "включён" if self.core.state.mentor_enabled else "выключен"
            self.send(f"Режим ментора {state}. Команды: /mentor on · /mentor off")

    def cmd_reason(self, rest: str) -> None:
        result = self.core.declare_reason(rest, source="telegram")
        self.send(f"Причина записана: «{result['reason']}». Невыполненное важное сегодня в долг не уйдёт, причина — в разбор.")

    def cmd_learn(self, rest: str) -> None:
        """/learn — урок по ближайшей учебной задаче дня; /learn 30 физика — новый блок на 30 минут прямо сейчас."""
        words = rest.split()
        minutes = int(words.pop(0)) if words and words[0].isdigit() else None
        topic = " ".join(words).strip()
        today = [t for t in self.core.state.tasks_on(self.core.today()) if t.is_open and t.sphere == "learning"]
        if topic:
            today = [t for t in today if topic.lower() in t.title.lower()]
        task = next((t for t in today if t.status == "active"), None) or (today[0] if today else None)
        if task is None:
            if not topic:
                self.send("Учебных задач на сегодня нет. Скажи «физика 30 минут» — начну блок прямо сейчас.")
                return
            task = self.core.add_task(topic, sphere="learning", importance=3, deep_work=True, start=self.core.now().strftime("%H:%M"),
                                      duration_min=minutes or lesson_mod.DEFAULT_MINUTES, source="telegram")
        self.begin_lesson(task)

    def cmd_focus(self, rest: str) -> None:
        """/focus · /focus 45 · /focus 45 физика · /focus физика · /focus stop"""
        words = rest.split()
        if words and words[0].lower() in ("stop", "стоп", "off"):
            self.stop_focus()
            return
        minutes = tpl.FOCUS_DEFAULT_MIN
        if words and words[0].isdigit():
            minutes = int(words.pop(0))
        self.start_focus(minutes, " ".join(words) or None)


def _digest(text: str, buttons: list[list[tuple[str, str]]]) -> str:
    return hashlib.sha1(repr((text, buttons)).encode("utf-8")).hexdigest()[:16]
