"""Telegram-бот без сети: подставные API и голова."""

import unittest
from datetime import timedelta
from typing import Any

from arvix.telegram import templates as tpl
from arvix.telegram.bot import Bot, parse_quick_task
from arvix.telegram.scheduler import Scheduler

from tests.helpers import ArvixCase, moscow

OWNER = 111


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []
        self.keyboards: list[Any] = []
        self.edited: list[tuple[int, str, Any]] = []
        self.pinned: list[int] = []
        self.unpinned: list[int] = []
        self.typing_calls = 0

    def send(self, chat_id: int, text: str, buttons: Any = None, keyboard: Any = None) -> int:
        assert chat_id == OWNER
        self.sent.append((text, buttons))
        if keyboard:
            self.keyboards.append(keyboard)
        return len(self.sent)  # message_id

    def edit(self, chat_id: int, message_id: int, text: str, buttons: Any = None) -> None:
        self.edited.append((message_id, text, buttons))

    def pin(self, chat_id: int, message_id: int) -> None:
        self.pinned.append(message_id)

    def unpin(self, chat_id: int, message_id: int) -> None:
        self.unpinned.append(message_id)

    def answer_callback(self, *a: Any, **k: Any) -> None:
        pass

    def drop_buttons(self, *a: Any) -> None:
        pass

    def typing(self, *a: Any) -> None:
        self.typing_calls += 1

    def download(self, file_id: str) -> bytes:
        return b"OGG:" + file_id.encode()

    @property
    def last(self) -> str:
        return self.sent[-1][0]

    @property
    def texts(self) -> list[str]:
        return [t for t, _ in self.sent]


class FakeBrain:
    def __init__(self) -> None:
        self.answers: list[dict | None] = []
        self.calls: list[dict[str, Any]] = []
        self.last_error = ""

    def ask(self, **kwargs: Any) -> dict | None:
        self.calls.append(kwargs)
        return self.answers.pop(0) if self.answers else None

    def available(self) -> bool:
        return True


class FakeSTT:
    max_seconds = 300

    def __init__(self, text: str = "", error: str = "") -> None:
        self.text, self.error, self.enabled, self.seen = text, error, True, []

    def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        from arvix.stt import STTError

        self.seen.append(audio)
        if self.error:
            raise STTError(self.error)
        return self.text


class BotCase(ArvixCase):
    def setUp(self) -> None:
        super().setUp()
        self.api = FakeAPI()
        self.brain = FakeBrain()
        self.pauses: list[float] = []
        self.bot = Bot(self.core, self.api, self.brain, OWNER, sleep=self.pauses.append)
        self.scheduler = Scheduler(self.bot)

    def text(self, text: str, sender: int = OWNER) -> None:
        self.bot.handle({"update_id": 1, "message": {"from": {"id": sender}, "chat": {"id": sender}, "text": text}})

    def voice(self, file_id: str = "v1", duration: int = 5) -> None:
        self.bot.handle({"update_id": 3, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "voice": {"file_id": file_id, "duration": duration}}})

    def press(self, data: str) -> None:
        self.bot.handle({"update_id": 2, "callback_query": {"id": "c", "from": {"id": OWNER}, "data": data, "message": {"chat": {"id": OWNER}, "message_id": 5}}})


class InboxTest(BotCase):
    def test_strangers_are_ignored(self) -> None:
        self.text("/status", sender=999)
        self.assertEqual(self.api.sent, [])

    def test_start_runs_onboarding_and_answers_flow(self) -> None:
        self.text("/start")
        self.assertIn("Как к тебе обращаться?", self.api.last)
        self.text("Дастан")
        self.assertIn("роде", self.api.last)
        self.press("q:skip:address")
        self.assertIn("Город", self.api.last)
        self.assertEqual(self.core.state.profile["name"], "Дастан")

    def test_block_end_runs_one_extraction_call(self) -> None:
        for qid in ("name", "address", "city", "sleep", "week", "main_goal"):
            self.core.interview_answer(qid, "ответ" if qid != "sleep" else "01:00-09:00, хочу 23:30-07:30")
        self.bot.ask_question(self.core.interview_next())
        self.brain.answers.append({"summary": "Записал цель.", "actions": [{"type": "remember", "topic": "goal", "fact": "хочет уйти со смен"}]})
        self.text("Чтобы уйти со смен")
        self.assertEqual(len(self.brain.calls), 1)
        self.assertTrue(any("Записал цель" in t for t, _ in self.api.sent))
        self.assertIn("Продолжаем", self.api.last)

    def test_report_button_flow(self) -> None:
        task = self.core.add_task("Физика", importance=3, start="12:00")
        self.press(f"t:{task.id}:yes")
        self.assertIn("что именно сделано — «Физика»?", self.api.last)
        self.text("решил 10 задач")
        self.assertIn("+", self.api.last)
        self.assertEqual(self.core.state.tasks[task.id].status, "done")
        self.assertEqual(self.brain.calls, [])  # кнопки и отчёт — без модели

    def test_fail_button_asks_reason_then_converses(self) -> None:
        task = self.core.add_task("Экзамен", importance=5, start="12:00")
        self.press(f"t:{task.id}:no")
        self.assertIn("ушла в долг", self.api.last)
        self.brain.answers.append({"reply": "Причина записана. Завтра 09:00 — первым делом.", "actions": []})
        self.text("проспал")
        self.assertEqual(self.core.state.tasks[task.id].reason, "проспал")
        self.assertIn("09:00", self.api.last)

    def test_safety_marker_switches_off_mentor_without_model(self) -> None:
        self.text("я не хочу жить")
        self.assertFalse(self.core.state.mentor_enabled)
        self.assertIn("112", self.api.last)
        self.assertEqual(self.brain.calls, [])
        self.text("/mentor on")
        self.assertTrue(self.core.state.mentor_enabled)

    def test_brain_down_gives_template(self) -> None:
        self.text("как дела?")
        self.assertEqual(self.api.last, tpl.FALLBACK)

    def test_mentor_command_needs_explicit_off(self) -> None:
        """«/mentor» без аргумента или с опечаткой показывает состояние, а не выключает ментора."""
        for arg in ("", " вкл?", " of"):
            self.text(f"/mentor{arg}")
            self.assertTrue(self.core.state.mentor_enabled, arg)
            self.assertIn("включён", self.api.last)
        self.text("/mentor off")
        self.assertFalse(self.core.state.mentor_enabled)
        self.text("/mentor on")
        self.assertTrue(self.core.state.mentor_enabled)

    def test_onboarding_intro_counts_real_questions(self) -> None:
        from arvix import interview

        self.assertIn(f"{len(interview.QUESTIONS)} вопросов, {len(interview.BLOCKS)} блоков", tpl.ONBOARD_INTRO)

    def test_learning_answer_needs_a_named_source_not_a_url(self) -> None:
        """Учебник с параграфом — источник; требовать URL значит учить модель их выдумывать."""
        self.brain.answers.append({"reply": "Сначала сам: что такое равнодействующая? Источник: Перышкин, 9 класс, §12. 20 минут.", "actions": [], "learning": True})
        self.text("как складывать силы?")
        self.assertEqual(len(self.brain.calls), 1)  # источник назван — без повторного вызова
        self.assertNotIn("Первоисточник не назван", self.api.last)
        self.brain.answers += [{"reply": "Подумай сам, 20 минут.", "actions": [], "learning": True}, {"reply": "Всё ещё без всего.", "actions": [], "learning": True}]
        self.text("а что такое импульс?")
        self.assertEqual(len(self.brain.calls), 3)
        self.assertIn("первоисточник не назван", self.brain.calls[-1]["system"].lower())
        self.assertIn("Первоисточник не назван", self.api.last)

    def test_actions_are_applied_and_reported_honestly(self) -> None:
        task = self.core.add_task("Английский", importance=2, start="12:00", sphere="work")
        self.brain.answers.append({"reply": "Принято.", "actions": [
            {"type": "complete_task", "task": task.id},
            {"type": "complete_task", "task": "несуществующая"},
        ]})
        self.text("английский сделал")
        self.assertIn("✅ Английский", self.api.last)
        self.assertIn("Не выполнено", self.api.last)

    def test_report_falls_back_to_user_words_and_deadline_to_start(self) -> None:
        """Живой прогон показал: модель забывает report и пишет «до 20:30» в deadline."""
        task = self.core.add_task("Английский", importance=3, start="12:00")
        self.brain.answers.append({"reply": "Принято.", "actions": [
            {"type": "complete_task", "task": task.id},
            {"type": "add_task", "title": "Матан", "duration_min": 60, "deadline": "20:30", "importance": 4},
        ]})
        self.text("английский сделал: 30 карточек")
        self.assertEqual(self.core.state.tasks[task.id].report, "английский сделал: 30 карточек")
        added = next(t for t in self.core.state.tasks.values() if t.title == "Матан")
        self.assertEqual(added.start, "19:30")
        self.assertNotIn("Не выполнено", self.api.last)

    def test_gentle_validator_replaces_harsh_reply(self) -> None:
        self.core.sos(True)
        self.brain.answers += [{"reply": "Дисциплина важнее, выполнение 0%.", "actions": []}, {"reply": "Опять про продуктивность.", "actions": []}]
        self.text("мне тяжело сегодня")
        self.assertEqual(self.api.last, tpl.GENTLE_FALLBACK)

    def test_stale_duplicate_after_outage_is_not_next_answer(self) -> None:
        self.text("/start")
        self.text("Дастан")  # ответ на «Как обращаться?» → бот спросил про род
        asked = self.core.store.kv_get("tg_await")
        stale = {"update_id": 9, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "text": "Дастан", "date": asked["asked_at"] - 60}}
        self.bot.handle(stale)
        self.assertNotIn("address", self.core.state.interview)
        self.assertEqual(self.core.store.kv_get("tg_await")["qid"], "address")

    def test_schedule_proposal_save_flow(self) -> None:
        self.core.interview_answer("week", "школа пн-пт 9:00-15:00")
        self.brain.answers.append({"summary": "Учёба после школы.", "templates": [
            {"weekdays": [0, 1, 2, 3, 4], "day_type": "study", "blocks": [
                {"start": "23:30", "duration": 30, "title": "Математика ОГЭ", "sphere": "learning", "importance": 4, "deep_work": True}]},
        ]})
        self.text("/schedule")
        self.assertIn("пн–пт · учебный", self.api.last)
        self.assertIn("(30→20 мин, глубокая, ★4)", self.api.last)  # показано то, что реально придёт задачей
        self.assertIn("Итого 1ч40м в неделю", self.api.last)
        self.press("s:save")
        self.assertEqual(self.core.state.templates[0]["blocks"][0]["title"], "Математика ОГЭ")
        self.assertIn("Распорядок сохранён", self.api.texts[-2])
        self.assertTrue(self.api.last.startswith("📋"), self.api.last)  # сразу панель с сегодняшними блоками
        self.assertIsNone(self.core.store.kv_get("tg_pending_templates"))

    def test_region_block_explained(self) -> None:
        self.brain.last_error = "API Error: Request blocked (HTTP 403) unsupported region, or a VPN"
        self.text("привет")
        self.assertIn("VPN", self.api.last)

    def test_voice_is_answered_without_showing_the_transcript(self) -> None:
        """Расшифровку бот не показывает — отвечает по делу; что он понял, видно по квитанции.
        В журнале сообщение помечено как голосовое."""
        self.bot.stt = FakeSTT("спал шесть часов, лёг в час")
        self.brain.answers.append({"reply": "Шесть часов — мало.", "actions": [{"type": "log_sleep", "duration": "6:00", "bedtime": "01:00"}]})
        self.voice("abc")
        self.assertEqual(self.bot.stt.seen, [b"OGG:abc"])
        self.assertFalse(any(t.startswith("🎙") for t in self.api.texts), self.api.texts)
        self.assertEqual(self.api.texts, ["Шесть часов — мало.", "сон 6ч00м"])
        self.assertEqual(self.brain.calls[-1]["prompt"], "спал шесть часов, лёг в час")
        self.assertEqual(self.core.state.days[self.core.today()].sleep_min, 360)
        heard = [e for e in self.core.store.read(0) if e.kind == "message_in"][-1]
        self.assertEqual(heard.payload["text"], "🎙 спал шесть часов, лёг в час")

    def test_voice_transcript_shown_when_configured_and_when_brain_is_down(self) -> None:
        self.bot.stt = FakeSTT("запиши мысль про графы")
        self.bot.stt.show_transcript = True
        self.brain.answers.append({"reply": "Записал.", "actions": []})
        self.voice()
        self.assertEqual(self.api.texts[-2], "🎙 «запиши мысль про графы»")
        self.bot.stt = FakeSTT("а это голова не услышит")
        self.voice()  # ответов у FakeBrain больше нет → голова «недоступна»
        self.assertTrue(self.api.last.startswith("🎙 «а это голова не услышит»\n" + tpl.FALLBACK), self.api.last)

    def test_voice_answers_a_waiting_question_without_the_model(self) -> None:
        task = self.core.add_task("Физика", importance=3, start="12:00")
        self.press(f"t:{task.id}:yes")
        self.bot.stt = FakeSTT("решил десять задач из параграфа")
        self.voice()
        self.assertEqual(self.core.state.tasks[task.id].report, "решил десять задач из параграфа")
        self.assertEqual(self.brain.calls, [])

    def test_voice_safety_markers_still_work(self) -> None:
        self.bot.stt = FakeSTT("я не хочу жить")
        self.voice()
        self.assertFalse(self.core.state.mentor_enabled)
        self.assertEqual(self.brain.calls, [])

    def test_voice_off_too_long_and_failed(self) -> None:
        self.voice()
        self.assertEqual(self.api.last, tpl.VOICE_OFF)
        self.bot.stt = FakeSTT("x")
        self.voice(duration=900)
        self.assertIn("длиннее 5 мин", self.api.last)
        self.bot.stt = FakeSTT(error="лимит распознавания")
        self.voice()
        self.assertIn("лимит распознавания", self.api.last)
        self.assertEqual(self.brain.calls, [])

    def test_reply_shows_doubts_found_by_code(self) -> None:
        self.brain.answers.append({"reply": "Поставил.", "actions": [{"type": "add_task", "title": "Матан", "start": "09:00", "duration_min": 60}]})
        self.text("поставь матан на 9 утра")
        self.assertIn("⚠️ Проверь:", self.api.last)
        self.assertIn("уже прошло", self.api.last)

    def test_quick_add_parser(self) -> None:
        fields = parse_quick_task("Физика: задачи 18:00 60м !4 deep завтра")
        self.assertEqual(fields, {"start": "18:00", "duration_min": 60, "importance": 4, "deep_work": True, "day": "tomorrow", "title": "Физика: задачи"})

    def test_sleep_answer_after_brief(self) -> None:
        self.bot.send_brief()
        self.text("7:20")
        self.assertEqual(self.core.state.days[self.core.today()].sleep_min, 440)


class BubblesTest(BotCase):
    """Ответ головы уходит абзацами — отдельными сообщениями, квитанция кода — последним, без id."""

    def test_paragraphs_become_separate_messages_with_pauses(self) -> None:
        self.brain.answers.append({"reply": "Прогулка не засчитана: телефон был в кармане.\n\nПушкин завтра, ставлю на 19:30.\n\n\nСегодня 0 из 3.", "actions": []})
        self.text("гулял с телефоном")
        self.assertEqual(self.api.texts[-3:], ["Прогулка не засчитана: телефон был в кармане.", "Пушкин завтра, ставлю на 19:30.", "Сегодня 0 из 3."])
        self.assertEqual(len(self.pauses), 2)  # пауза перед вторым и третьим, «набирает…» между ними
        self.assertTrue(all(0 < p <= 2.5 for p in self.pauses), self.pauses)
        self.assertEqual(self.api.typing_calls, 3)  # один перед головой, два между пузырьками
        outs = [e for e in self.core.store.read(0) if e.kind == "message_out"]
        self.assertEqual(len(outs), 1)  # в журнале и истории — одно сообщение целиком
        self.assertIn("Сегодня 0 из 3.", outs[-1].payload["text"])

    def test_too_many_paragraphs_are_merged_and_receipt_is_last_without_ids(self) -> None:
        from arvix.telegram.bot import bubbles

        self.assertEqual(bubbles("а\n\nб\n\nв\n\nг\n\nд\n\nе"), ["а", "б", "в", "г\n\nд\n\nе"])
        self.assertEqual(bubbles("   "), [])
        self.brain.answers.append({"reply": "Ставлю Пушкина на 19:30, блок математики сдвигаю на 20:40.", "actions": [
            {"type": "add_task", "title": "Русский: биография Пушкина", "start": "19:30", "duration_min": 60, "importance": 4},
        ]})
        self.text("пушкин завтра сдаётся")
        receipt = self.api.last
        self.assertIn("+ Русский: биография Пушкина · 19:30, 60 мин", receipt)
        self.assertNotRegex(receipt, r"\[[0-9a-f]{8}\]")  # id задач — для модели, не для человека
        self.assertEqual(len(self.api.sent), 2)

    def test_doubts_are_checked_after_all_actions(self) -> None:
        """Модель добавляет блок и тем же ответом сдвигает соседний: проверка внахлёст — по итогу, а не по ходу."""
        self.at(moscow(2026, 11, 2, 18, 0))
        math = self.core.add_task("Математика", start="19:30", duration_min=45, importance=3)
        self.brain.answers.append({"reply": "Пушкин в 19:30, математику на 20:40.", "actions": [
            {"type": "add_task", "title": "Пушкин", "start": "19:30", "duration_min": 60, "importance": 4},
            {"type": "defer_task", "task": math.id, "minutes": 70},
        ]})
        self.text("пушкин первым")
        self.assertNotIn("пересекается", self.api.last)
        self.assertIn("⏳ Математика → 20:40", self.api.last)

    def test_receipt_alone_when_reply_is_empty(self) -> None:
        task = self.core.add_task("Английский", importance=2, start="12:00")
        self.brain.answers.append({"reply": "", "actions": [{"type": "complete_task", "task": task.id}]})
        self.text("английский сделал")
        self.assertEqual(len(self.api.sent), 1)
        self.assertTrue(self.api.last.startswith("✅ Английский +"), self.api.last)


class PanelTest(BotCase):
    """Панель дня: закреплённое сообщение с кнопками, которое бот правит на месте."""

    start = moscow(2026, 11, 2, 15, 0)

    def setUp(self) -> None:
        super().setUp()
        self.math = self.core.add_task("Математика ОГЭ", start="16:00", duration_min=45, importance=3, deep_work=True)
        self.push = self.core.add_task("Русский: биография Пушкина", start="19:30", duration_min=60, importance=4)

    def panel_id(self) -> int:
        return self.core.store.kv_get("tg_panel")["message_id"]

    def test_menu_button_sends_pinned_panel_with_task_buttons(self) -> None:
        self.text(tpl.MENU_DAY)
        text, buttons = self.api.sent[-1]
        self.assertTrue(text.startswith("📋 Понедельник · 0 из 2 · 🟩 · HP 100 · серия 0 дн"), text)
        self.assertIn("○ 16:00 Математика ОГЭ (45 мин)", text)
        self.assertEqual(buttons[0], [("▶️ Математика ОГЭ", f"t:{self.math.id}:start"), ("✅", f"t:{self.math.id}:yes"), ("⏳ 30", f"t:{self.math.id}:d30")])
        self.assertEqual(buttons[1][0][0], "▶️ Русский: биография Пу…")
        self.assertEqual(buttons[-1], [("🔄", "p:refresh"), ("🎯 25 мин", "p:focus"), ("➕", "p:add")])
        self.assertEqual(self.api.pinned, [self.panel_id()])
        self.assertEqual(self.brain.calls, [])

    def test_panel_button_edits_panel_in_place(self) -> None:
        self.text(tpl.MENU_DAY)
        before = len(self.api.sent)
        self.press(f"t:{self.math.id}:start")
        self.assertEqual(self.core.state.tasks[self.math.id].status, "active")
        self.assertEqual(self.api.sent[before][0], tpl.reminder_start(self.math))
        message_id, text, buttons = self.api.edited[-1]
        self.assertEqual(message_id, self.panel_id())
        self.assertIn("▶️ 16:00 Математика ОГЭ (45 мин) — идёт с 15:00", text)
        self.assertEqual(buttons[0], [("✅ Математика ОГЭ", f"t:{self.math.id}:yes"), ("⚠️ частично", f"t:{self.math.id}:part")])

    def test_scheduler_refreshes_panel_after_outside_change(self) -> None:
        self.text(tpl.MENU_DAY)
        self.scheduler.tick()
        self.assertEqual(self.api.edited, [])  # ничего не поменялось — правок нет
        self.core.complete_task(self.math.id, report="10 задач", source="cli")
        self.scheduler.tick()
        self.assertIn("📋 Понедельник · 1 из 2", self.api.edited[-1][1])
        edits = len(self.api.edited)
        self.scheduler.tick()
        self.assertEqual(len(self.api.edited), edits)

    def test_done_button_reports_current_task_or_shows_panel(self) -> None:
        self.text(tpl.MENU_DONE)
        self.assertIn("Нажми ✅ у задачи", self.api.last)  # две открытые, ни одна не идёт
        self.core.start_task(self.math.id)
        self.text(tpl.MENU_DONE)
        self.assertIn("«Математика ОГЭ»", self.api.last)
        self.text("45 минут задач из банка")
        self.assertEqual(self.core.state.tasks[self.math.id].status, "done")

    def test_add_button_quick_or_via_brain(self) -> None:
        self.text(tpl.MENU_ADD)
        self.text("Физика 18:00 30м !3")
        self.assertTrue(any(t.title == "Физика" and t.start == "18:00" for t in self.core.state.tasks.values()))
        self.assertEqual(self.brain.calls, [])
        self.text(tpl.MENU_ADD)
        self.brain.answers.append({"reply": "Ставлю на 18:30.", "actions": []})
        self.text("повторить карточки")
        self.assertEqual(self.brain.calls[-1]["prompt"], "Добавь задачу: повторить карточки")

    def test_brief_brings_keyboard_and_panel(self) -> None:
        self.bot.send_brief()
        self.assertEqual(self.api.keyboards, [tpl.KEYBOARD])
        self.assertTrue(self.api.last.startswith("📋"), self.api.last)
        self.assertEqual(self.api.pinned, [self.panel_id()])

    def test_red_mode_panel_has_no_tasks_or_numbers(self) -> None:
        self.core.sos(True)
        self.text(tpl.MENU_DAY)
        text, buttons = self.api.sent[-1]
        self.assertNotIn("Математика", text)
        self.assertNotIn("HP", text)
        self.assertEqual(buttons, [[("🔄", "p:refresh")]])


class FocusTest(BotCase):
    start = moscow(2026, 11, 2, 15, 55)

    def setUp(self) -> None:
        super().setUp()
        self.math = self.core.add_task("Математика ОГЭ", start="16:00", duration_min=40, importance=3, deep_work=True)

    def test_focus_runs_on_next_task_counts_down_and_raises_proof(self) -> None:
        self.text(tpl.MENU_FOCUS)
        text, buttons = self.api.sent[-1]
        self.assertEqual(text, "🎯 Фокус 25 мин · Математика ОГЭ\nДо 16:20. Телефон убрать.")
        self.assertEqual(buttons, [[("⏹ Стоп", "f:stop")]])
        self.assertEqual(self.core.state.tasks[self.math.id].status, "active")  # таймер = блок пошёл
        timer_id = len(self.api.sent)
        self.at(moscow(2026, 11, 2, 16, 3))
        self.scheduler.tick()
        self.assertEqual(self.api.edited[-1][0], timer_id)
        self.assertIn("осталось 18 мин", self.api.edited[-1][1])  # 16:03 → до 16:20: 17 полных минут + текущая
        self.at(moscow(2026, 11, 2, 16, 21))
        self.scheduler.tick()
        self.assertIn("закончен", self.api.edited[-1][1])
        self.assertIn("Без прерываний?", self.api.last)
        self.press("f:ok:25")
        self.assertIn("25 мин по «Математика ОГЭ»", self.api.last)
        self.assertEqual(self.core.state.tasks[self.math.id].focus_min, 25)
        result = self.core.complete_task(self.math.id, report="40 задач")
        self.assertEqual(result["xp"], 14)  # 10 × 1.0 × 1.0 × K_proof timer 1.4, вместо 11 за отчёт
        self.assertEqual(self.core.state.days[self.core.today()].deep_min, 40)

    def test_stop_logs_elapsed_or_drops_short_session(self) -> None:
        self.text("/focus 50 матем")
        self.at(moscow(2026, 11, 2, 15, 58))
        self.press("f:stop")
        self.assertIn("меньше 5 минут", self.api.last)
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.text("/focus")
        self.at(moscow(2026, 11, 2, 16, 10))
        self.text("/focus stop")
        self.assertIn("12 мин записано по «Математика ОГЭ»", self.api.last)
        self.assertEqual(self.core.state.tasks[self.math.id].focus_min, 12)

    def test_second_focus_shows_state_instead_of_restart(self) -> None:
        self.text("/focus 30")
        self.at(moscow(2026, 11, 2, 16, 5))
        self.text(tpl.MENU_FOCUS)
        self.assertIn("осталось 21 мин", self.api.last)
        self.assertEqual(self.core.store.kv_get("focus")["minutes"], 30)


class SchedulerTest(BotCase):
    start = moscow(2026, 11, 2, 7, 0)

    def keys(self) -> list[str]:
        return sorted(k for d in self.core.state.days.values() for k in d.out_keys)

    def test_task_reminders_and_dedupe(self) -> None:
        task = self.core.add_task("Алгоритмы", importance=4, start="09:00", duration_min=60)
        self.at(moscow(2026, 11, 2, 8, 56))
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual(sum(1 for t, _ in self.api.sent if "Через" in t), 1)
        self.at(moscow(2026, 11, 2, 9, 1))
        self.scheduler.tick()
        self.assertIn("Блок пошёл", self.api.last)
        self.at(moscow(2026, 11, 2, 10, 2))
        self.scheduler.tick()
        self.assertEqual(self.api.last, f"Сделано: {task.title}?")

    def test_brief_and_debrief_windows(self) -> None:
        self.core.profile_set("wake_target", "07:30")
        self.at(moscow(2026, 11, 2, 7, 50))
        self.scheduler.tick()
        self.assertTrue(any(t.startswith("☀️") for t, _ in self.api.sent))
        self.brain.answers.append({"assessment": "День пустой.", "questions": ["Почему без плана?", "Что завтра первым?"]})
        self.at(moscow(2026, 11, 2, 22, 31))
        self.scheduler.tick()
        self.assertIn("Почему без плана?", self.api.last)
        self.assertEqual(self.core.store.kv_get("tg_await")["kind"], "debrief")
        self.brain.answers.append({"reply": "Вывод: план с вечера.", "actions": []})
        self.text("не составил план")
        self.assertTrue(self.core.state.days[self.core.today()].debrief)

    def test_missed_brief_is_not_sent_hours_later(self) -> None:
        self.core.profile_set("wake_target", "07:30")
        self.at(moscow(2026, 11, 2, 13, 0))
        self.scheduler.tick()
        self.assertFalse(any(t.startswith("☀️") for t, _ in self.api.sent))

    def test_ignore_protocol_day_three(self) -> None:
        self.core.profile_set("wake_target", "07:30", source="l0")  # не действие человека
        for offset in range(2):
            self.at(moscow(2026, 11, 2 + offset, 8, 0))
            self.scheduler.tick()
        self.at(moscow(2026, 11, 4, 8, 0))
        self.scheduler.tick()
        self.assertEqual(self.api.last, tpl.IGNORE[2])

    def test_silent_day_sends_only_debrief(self) -> None:
        self.core.silent_today()
        self.core.add_task("Что-то", start="09:00")
        self.at(moscow(2026, 11, 2, 8, 57))
        self.scheduler.tick()
        self.assertEqual(self.api.sent, [])

    def test_red_mode_sends_no_task_reminders(self) -> None:
        """🟥: план — одна маленькая вещь. «Через 5 мин», «Блок пошёл», «Сделано?» не приходят; отбой — мягко."""
        self.core.profile_set("bedtime_target", "23:00", source="l0")
        self.core.add_task("Алгоритмы", importance=4, start="09:00", duration_min=60)
        self.core.sos(True)
        for hour, minute in ((8, 56), (9, 1), (10, 2), (22, 31)):
            self.at(moscow(2026, 11, 2, hour, minute))
            self.scheduler.tick()
        texts = [t for t, _ in self.api.sent]
        self.assertFalse(any("Алгоритмы" in t for t in texts), texts)
        self.assertTrue(any("Сон сейчас важнее всего" in t for t in texts), texts)

    def test_long_silence_goes_weekly_and_never_restarts(self) -> None:
        """Дни 1–2 — брифинг, день 3 — «Три дня…», 4–8 — «Я здесь.», дальше раз в неделю.
        Раньше на 9-й день серия рвалась и протокол начинался заново со штрафами."""
        self.core.profile_set("wake_target", "07:30", source="l0")
        by_day = []
        for offset in range(16):
            self.at(moscow(2026, 11, 2, 8, 0) + timedelta(days=offset))
            before = len(self.api.sent)
            self.scheduler.tick()
            by_day.append([t for t, _ in self.api.sent[before:]])
        self.assertTrue(by_day[0][0].startswith("☀️"), by_day[0])
        self.assertTrue(by_day[1][0].startswith(tpl.IGNORE_DAY2), by_day[1])
        self.assertEqual(by_day[2], [tpl.IGNORE[2]])
        for offset in range(3, 8):
            self.assertEqual(by_day[offset], [tpl.IGNORE_LATER], offset)
        for offset in range(8, 14):
            self.assertEqual(by_day[offset], [], offset)
        self.assertEqual(by_day[14], [tpl.IGNORE_LATER])
        self.assertEqual(by_day[15], [])
        self.assertEqual(sum(t == tpl.IGNORE[2] for day in by_day for t in day), 1)
        self.assertEqual(self.core.state.hp, 80)  # −10 за первые два дня, с третьего штрафы заморожены

    def test_return_after_silence_is_gentle_and_not_greeted_as_absent(self) -> None:
        self.core.profile_set("wake_target", "07:30", source="l0")
        for offset in range(5):
            self.at(moscow(2026, 11, 2, 8, 0) + timedelta(days=offset))
            self.scheduler.tick()
        self.at(moscow(2026, 11, 7, 7, 40))
        self.brain.answers.append({"reply": "Что случилось? И один маленький шаг на сегодня — какой?", "actions": []})
        self.text("я тут")
        self.assertIn("return_protocol", self.brain.calls[-1]["system"])
        self.at(moscow(2026, 11, 7, 8, 0))
        before = len(self.api.sent)
        self.scheduler.tick()
        sent = [t for t, _ in self.api.sent[before:]]
        self.assertNotIn(tpl.IGNORE_LATER, sent)  # человек уже вернулся — «Я здесь.» не к месту
        self.assertTrue(sent and sent[0].startswith("☀️"), sent)


if __name__ == "__main__":
    unittest.main()
