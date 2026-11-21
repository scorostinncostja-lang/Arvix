"""Telegram-бот без сети: подставные API и голова."""

import unittest
from datetime import timedelta
from typing import Any

from arvix.telegram import fmt
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
        self.html: list[str | None] = []
        self.replies: list[int | None] = []  # reply_to каждого отправленного (D52)

    def send(self, chat_id: int, text: str, buttons: Any = None, keyboard: Any = None, *, html: str | None = None,
             reply_to: int | None = None) -> int:
        assert chat_id == OWNER
        self.sent.append((text, buttons))
        self.html.append(html)
        self.replies.append(reply_to)
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
    """Подставная голова. В calls: system — всё, что видит модель (системный промпт + запрос),
    prompt — само сообщение человека из <message>; как есть — в raw_system / raw_prompt (D40)."""

    def __init__(self) -> None:
        self.answers: list[dict | None] = []
        self.calls: list[dict[str, Any]] = []
        self.last_error = ""

    def ask(self, **kwargs: Any) -> dict | None:
        call = dict(kwargs, raw_system=kwargs.get("system", ""), raw_prompt=kwargs.get("prompt", ""))
        prompt = call["raw_prompt"]
        if "<message>\n" in prompt:
            call["system"] = call["raw_system"] + "\n\n" + prompt
            call["prompt"] = prompt.rsplit("<message>\n", 1)[1].split("\n</message>", 1)[0]
        self.calls.append(call)
        return self.answers.pop(0) if self.answers else None

    def available(self) -> bool:
        return True


class FakeSTT:
    max_seconds = 300

    def __init__(self, text: str = "", error: str = "") -> None:
        self.text, self.error, self.enabled, self.seen = text, error, True, []

    def transcribe(self, audio: bytes, filename: str = "voice.ogg", *, browser: bool = False) -> str:
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
        self.assertTrue(self.api.last.startswith("✅ Физика — записал"), self.api.last)
        self.assertNotIn("XP", self.api.last)
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
        self.assertEqual(self.api.last, fmt.sentence_lines(tpl.GENTLE_FALLBACK))

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
        self.assertIn("Распорядок сохранён", self.api.last)  # панели следом нет — день в приложении (D50)
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
        self.assertEqual(self.api.texts, ["Шесть часов — мало.\n\nсон 6ч00м"])  # одно сообщение, квитанция в конце (D46)
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


class OneMessageTest(BotCase):
    """Ответ головы — одно сообщение (D46): абзацы через пустую строку, квитанция — в конце, без id."""

    def test_paragraphs_stay_in_one_readable_message(self) -> None:
        self.brain.answers.append({"reply": "Прогулка не засчитана: телефон был в кармане.\n\nПушкин завтра, ставлю на 19:30.\n\n\nСегодня 0 из 3.", "actions": []})
        self.text("гулял с телефоном")
        self.assertEqual(len(self.api.sent), 1)  # прежде — три сообщения подряд
        self.assertEqual(self.api.last, "Прогулка не засчитана: телефон был в кармане.\n\nПушкин завтра, ставлю на 19:30.\n\nСегодня 0 из 3.")
        self.assertEqual(self.pauses, [])  # без искусственных пауз «набирает…»
        outs = [e for e in self.core.store.read(0) if e.kind == "message_out"]
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs[-1].payload["text"], self.api.last)

    def test_receipt_is_at_the_end_of_the_same_message_without_ids(self) -> None:
        self.brain.answers.append({"reply": "Ставлю Пушкина на 19:30, блок математики сдвигаю на 20:40.", "actions": [
            {"type": "add_task", "title": "Русский: биография Пушкина", "start": "19:30", "duration_min": 60, "importance": 4},
        ]})
        self.text("пушкин завтра сдаётся")
        self.assertEqual(len(self.api.sent), 1)
        message = self.api.last
        self.assertTrue(message.startswith("Ставлю Пушкина на 19:30"))
        self.assertIn("\n\n+ Русский: биография Пушкина · 19:30, 60 мин", message)
        self.assertNotRegex(message, r"\[[0-9a-f]{8}\]")  # id задач — для модели, не для человека

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

    def test_defer_to_exact_time_matches_the_reply(self) -> None:
        """Баг 19.11: «переношу на 19:45», а блок уехал на 19:09 — модель не дала minutes, код молча добавил 15.
        Теперь голова называет время (start), минуты считает код (D46)."""
        self.at(moscow(2026, 11, 19, 18, 54))
        math = self.core.add_task("Математика: блок 45 минут", start="18:54", duration_min=45, importance=3)
        self.brain.answers.append({"reply": "Переношу блок на 19:45, до 20:30.", "actions": [
            {"type": "defer_task", "task": math.id, "start": "19:45"},
        ]})
        self.text("пойду погуляю, сяду в 19:45")
        self.assertEqual(self.core.state.tasks[math.id].start, "19:45")
        self.assertIn("⏳ Математика: блок 45 минут → 19:45", self.api.last)

    def test_defer_without_time_is_refused_not_plus_fifteen(self) -> None:
        self.at(moscow(2026, 11, 19, 18, 54))
        math = self.core.add_task("Математика", start="19:00", duration_min=45, importance=3)
        self.brain.answers.append({"reply": "Переношу на 19:45.", "actions": [{"type": "defer_task", "task": math.id}]})
        self.text("перенеси")
        self.assertEqual(self.core.state.tasks[math.id].start, "19:00")  # не 19:15
        self.assertIn("⚠️ Не выполнено", self.api.last)

    def test_defer_into_the_past_is_refused(self) -> None:
        self.at(moscow(2026, 11, 19, 18, 54))
        math = self.core.add_task("Математика", start="19:00", duration_min=45, importance=3)
        self.brain.answers.append({"reply": "Ок.", "actions": [{"type": "defer_task", "task": math.id, "start": "18:30"}]})
        self.text("перенеси на 18:30")
        self.assertEqual(self.core.state.tasks[math.id].start, "19:00")
        self.assertIn("уже прошло", self.api.last)

    def test_receipt_alone_when_reply_is_empty(self) -> None:
        task = self.core.add_task("Английский", importance=2, start="12:00")
        self.brain.answers.append({"reply": "", "actions": [{"type": "complete_task", "task": task.id}]})
        self.text("английский сделал")
        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.last.splitlines()[0], "✅ Английский")  # квитанция — факт, без очков (D41)


class PanelTest(BotCase):
    """Панели дня в Telegram нет (D50): старые кнопки ещё работают, новых пультов нет."""

    start = moscow(2026, 11, 2, 15, 0)

    def setUp(self) -> None:
        super().setUp()
        self.math = self.core.add_task("Математика ОГЭ", start="16:00", duration_min=45, importance=3, deep_work=True)
        self.push = self.core.add_task("Русский: биография Пушкина", start="19:30", duration_min=60, importance=4)

    def test_old_day_button_points_to_the_app(self) -> None:
        """D50: панели дня в Telegram нет — ни сообщения с кнопками, ни закрепа."""
        self.text(tpl.MENU_DAY)
        text, buttons = self.api.sent[-1]
        self.assertIn("в приложении", text)
        self.assertIsNone(buttons)
        self.assertEqual(self.api.pinned, [])
        self.assertEqual(self.brain.calls, [])

    def test_task_button_from_an_old_message_still_works(self) -> None:
        self.press(f"t:{self.math.id}:start")
        self.assertEqual(self.core.state.tasks[self.math.id].status, "active")
        self.assertEqual(self.api.last, tpl.reminder_start(self.math))
        self.assertEqual(self.api.edited, [])

    def test_done_button_reports_current_task_or_shows_panel(self) -> None:
        self.text(tpl.MENU_DONE)
        self.assertIn("Напиши название", self.api.last)  # две открытые, ни одна не идёт
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

    def test_brief_removes_old_keyboard_and_sends_no_panel(self) -> None:
        self.bot.send_brief()
        self.assertEqual(self.api.keyboards, [])  # [] не попадает в FakeAPI.keyboards: это снятие клавиатуры
        self.assertFalse(any(t.startswith("📋") for t in self.api.texts))
        self.assertEqual(self.api.pinned, [])

    def test_red_mode_panel_has_no_tasks_or_numbers(self) -> None:
        self.core.sos(True)
        self.text(tpl.MENU_DAY)
        text, buttons = self.api.sent[-1]
        self.assertNotIn("Математика", text)
        self.assertNotIn("HP", text)
        flat = [data for row in buttons for _, data in row]
        self.assertIn("r:back", flat)  # без задач, но с выходом (D38) — разовым сообщением, не панелью (D50)
        self.assertNotIn("p:refresh", flat)
        self.assertFalse(any(data.startswith("t:") for data in flat))


class FocusTest(BotCase):
    start = moscow(2026, 11, 2, 15, 55)

    def setUp(self) -> None:
        super().setUp()
        self.math = self.core.add_task("Математика ОГЭ", start="16:00", duration_min=40, importance=3, deep_work=True)

    def test_focus_runs_on_next_task_and_raises_proof(self) -> None:
        """D50: в Telegram ни пульта, ни обратного отсчёта, ни «Без прерываний?» — таймер в приложении."""
        self.text(tpl.MENU_FOCUS)  # кнопка старой клавиатуры: отсылает в приложение, ничего не запускает
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertIn("в приложении", self.api.last)
        self.press("f:go:25")  # кнопка из старого сообщения ещё работает
        self.assertFalse(any(b for _, b in self.api.sent[-1:] if b))
        self.assertEqual(self.core.state.tasks[self.math.id].status, "active")  # таймер = блок пошёл
        self.at(moscow(2026, 11, 2, 16, 3))
        self.scheduler.tick()
        self.assertEqual(self.api.edited, [])
        self.at(moscow(2026, 11, 2, 16, 21))
        self.scheduler.tick()
        self.assertFalse(any("Без прерываний?" in t for t in self.api.texts))
        self.assertEqual(self.core.state.tasks[self.math.id].focus_min, 25)
        self.core.complete_task(self.math.id, report="40 задач")
        closed = [e for e in self.core.store.read(0) if e.kind == "task_completed"][-1].payload
        self.assertEqual(closed["focus_min"], 25)  # таймер — доказательство в журнале, а не множитель очков
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
        self.assertIn("Фокус: 12 мин · Математика ОГЭ — записано", self.api.last)
        self.assertEqual(self.core.state.tasks[self.math.id].focus_min, 12)

    def test_second_focus_shows_state_instead_of_restart(self) -> None:
        self.text("/focus 30")
        self.at(moscow(2026, 11, 2, 16, 5))
        self.text(tpl.MENU_FOCUS)
        self.assertIn("осталось 21 мин", self.api.last)
        self.assertEqual(self.core.store.kv_get("focus")["minutes"], 30)


class LessonTest(BotCase):
    """Учебный блок: план по роадмапу и методу человека, таймер, проверка в конце, оценка кодом."""

    start = moscow(2026, 11, 2, 15, 58)
    LESSON = {
        "topic": "Закон Ома для участка цепи", "why": "ОГЭ физика №8 — 1 балл первой части", "roadmap_node": "Постоянный ток (3/12)",
        "plan": [
            {"from_min": 0, "to_min": 5, "step": "Вспомни с пустого листа: ток, напряжение, сопротивление", "tool": "лист бумаги"},
            {"from_min": 5, "to_min": 20, "step": "Перышкин 8 кл., §44–45 — выпиши формулу и единицы", "tool": "учебник + NotebookLM: выжимка"},
            {"from_min": 20, "to_min": 35, "step": "5 задач №8 про постоянный ток", "tool": "Решу ОГЭ"},
            {"from_min": 35, "to_min": 42, "step": "Заметка «Закон Ома» своими словами", "tool": "Obsidian"},
            {"from_min": 42, "to_min": 45, "step": "Проверка: 3 вопроса", "tool": "Telegram"},
        ],
        "sources": ["Перышкин, 8 класс, §44", "открытый банк ФИПИ, физика, №8", "03_Resources/Обучение/Метод Фейнмана.md"],
        "check": [{"q": "Как связаны I, U и R?", "a": "I = U/R"}, {"q": "Что будет с током при удвоении R?", "a": "уменьшится вдвое"},
                  {"q": "U = 12 В, R = 4 Ом. I?", "a": "3 А"}],
        "note_title": "Закон Ома",
    }

    def setUp(self) -> None:
        super().setUp()
        (self.vault / "05_System" / "Templates").mkdir(parents=True)
        (self.vault / "05_System" / "Templates" / "Concept.md").write_text(
            "---\ntype: concept\nsubject: \ncreated: {{date:YYYY-MM-DD}}\n---\n# {{title}}\n\n## Объяснение по Фейнману\n\n## Самопроверка\n- [ ] Вопрос 1\n- [ ] Вопрос 2\n", encoding="utf-8")
        (self.vault / "06_Feyn Concept").mkdir()
        self.core.cfg.raw["schedule"]["midday"] = ""  # чек-ин 15:00 не мешает смотреть на последнее сообщение
        self.phys = self.core.add_task("Физика: постоянный ток", sphere="learning", start="16:00", duration_min=45, importance=4, deep_work=True)

    def test_block_start_sends_lesson_plan_from_roadmap(self) -> None:
        self.brain.answers.append(dict(self.LESSON))
        self.at(moscow(2026, 11, 2, 16, 0))
        self.scheduler.tick()
        text, buttons = self.api.sent[-1]
        self.assertTrue(text.startswith("📚 Физика: постоянный ток · 45 мин\nЗакон Ома для участка цепи\nЗачем: ОГЭ физика №8"), text)
        self.assertIn("Роадмап: Постоянный ток (3/12)", text)
        self.assertIn("20–35  5 задач №8 про постоянный ток · Решу ОГЭ", text)
        self.assertIn("Источники: Перышкин, 8 класс, §44 · открытый банк ФИПИ", text)
        self.assertIn("📝 Каркас заметки: 06_Feyn Concept/Закон Ома.md", text)
        self.assertIn("В конце — 3 вопроса", text)
        self.assertEqual(buttons, [[("▶️ Начать · 45 мин", f"l:{self.phys.id}:go")]])
        self.assertNotIn("Блок пошёл", self.api.texts)
        call = self.brain.calls[-1]
        self.assertTrue(call["vault_tools"])
        self.assertIn("Роадмап", call["system"])
        self.assertIn("NotebookLM", call["system"])
        note = (self.vault / "06_Feyn Concept" / "Закон Ома.md").read_text(encoding="utf-8")
        self.assertIn("# Закон Ома", note)
        self.assertIn("subject: Физика", note)
        self.assertIn("created: 2026-11-02", note)
        self.assertIn("- [ ] Как связаны I, U и R?", note)
        self.assertNotIn("Вопрос 1", note)
        self.assertEqual(self.core.state.tasks[self.phys.id].status, "planned")  # план — не старт: человек жмёт сам
        self.assertEqual(self.core.state.lessons[-1]["topic"], "Закон Ома для участка цепи")

    def test_full_cycle_timer_check_grade_and_close(self) -> None:
        self.brain.answers.append(dict(self.LESSON))
        self.text(tpl.MENU_FOCUS)  # 🎯 на учебную задачу = урок, не просто таймер
        self.assertTrue(any(t.startswith("📚") for t in self.api.texts))
        self.assertTrue(self.api.last.startswith("🎯 Фокус 45 мин · Физика: постоянный ток"), self.api.last)
        self.assertEqual(self.core.state.tasks[self.phys.id].status, "active")
        self.brain.answers.append({"reply": "Шаг первый: что такое сила тока? Это заряд за секунду. Пример: 2 Кл за 1 с — 2 А.\n\nТеперь ты: что покажет амперметр при 6 Кл за 3 с?", "actions": [], "learning": True})
        self.text("объясни, что такое сила тока")
        self.assertIn("<lesson>", self.brain.calls[-1]["system"])
        self.assertIn("Закон Ома для участка цепи", self.brain.calls[-1]["system"])
        self.at(moscow(2026, 11, 2, 16, 46))
        self.scheduler.tick()
        self.assertTrue(self.api.last.startswith("Время вышло. Проверка по теме «Закон Ома для участка цепи» — 3 вопроса"), self.api.last)
        self.assertIn("3. U = 12 В, R = 4 Ом. I?", self.api.last)
        self.assertFalse(any(t.startswith("Сделано:") for t in self.api.texts))  # «Сделано?» не дублирует проверку
        self.assertFalse(any("Без прерываний" in t for t in self.api.texts))
        self.assertEqual(self.core.store.kv_get("tg_await")["kind"], "lesson_check")
        self.brain.answers.append({"score_pct": 67, "feedback": "I = U/R верно, задача верно: 3 А.\n\nПро удвоение R ответа нет — ток падает вдвое, это обратная зависимость. Дочитай Перышкин §44, абзац про сопротивление.", "gaps": ["при удвоении R ток уменьшается вдвое"], "next_step": "5 задач №8 с изменением R"})
        self.text("I равно U делить на R. Не знаю. 12/4 = 3 ампера")
        self.assertIn("Вопросы и эталоны", self.brain.calls[-1]["system"])
        task = self.core.state.tasks[self.phys.id]
        self.assertEqual(task.status, "done")
        self.assertEqual(task.done_pct, 67)
        self.assertEqual(task.focus_min, 45)
        receipt = self.api.last
        self.assertIn("✅ Физика: постоянный ток — записал", receipt)
        self.assertNotIn("XP", receipt)
        self.assertIn("проверка 67%", receipt)
        self.assertIn("В карточки и журнал ошибок: при удвоении R ток уменьшается вдвое", receipt)
        self.assertIn("📝 Заметка своими словами: 06_Feyn Concept/Закон Ома.md", receipt)
        self.assertIn("Следующий блок: 5 задач №8", receipt)  # отзыв и квитанция — одним сообщением (D46)
        self.assertIsNone(self.core.store.kv_get("lesson"))
        self.assertEqual(self.core.state.lessons[-1]["score"], 67)
        from arvix.context import build_context

        self.assertIn("УРОКИ: 02.11 Физика: Закон Ома для участка цепи 67%", build_context(self.core))

    def test_history_feeds_next_lesson_and_brain_down_falls_back(self) -> None:
        self.brain.answers.append(dict(self.LESSON))
        self.text("/learn")
        self.text(f"/done физика ответ")  # закрыть руками, чтобы следующий урок был «следующим»
        self.core.store.kv_del("lesson")
        nxt = self.core.add_task("Физика: мощность тока", sphere="learning", start="17:00", duration_min=30, importance=3)
        self.text("/learn мощность")  # голова недоступна — ответов нет
        self.assertIn("Прошлые уроки по этому предмету: 02.11 Закон Ома для участка цепи — без проверки", self.brain.calls[-1]["system"])
        plan = next(t for t in self.api.texts if t.startswith("📚 Физика: мощность тока"))
        self.assertIn("Голова недоступна — план общий", plan)
        self.assertIn("0–4  Диагностика: Вспомни с пустого листа", plan)  # без головы — те же этапы (D60)
        self.assertIn("В конце — «Сделано?»", plan)
        self.assertEqual(self.core.state.tasks[nxt.id].status, "active")
        self.at(moscow(2026, 11, 2, 16, 30))
        self.scheduler.tick()
        self.assertEqual(self.api.last, f"Сделано: {nxt.title}?")  # без вопросов проверки — обычный отчёт
        self.assertIsNone(self.core.store.kv_get("lesson"))

    def test_learn_creates_block_now_and_auto_lesson_can_be_off(self) -> None:
        self.brain.answers.append(dict(self.LESSON))
        self.text("/learn 30 Информатика: Python циклы")
        task = next(t for t in self.core.state.tasks.values() if t.title == "Информатика: Python циклы")
        self.assertEqual((task.sphere, task.duration_min, task.start, task.status, task.deep_work), ("learning", 30, "15:58", "active", True))
        self.core.cfg.raw["learning"] = {"auto_lesson": False}
        other = self.core.add_task("Химия", sphere="learning", start="18:00")
        self.core.store.kv_del("lesson"); self.core.store.kv_del("focus")
        self.press(f"t:{other.id}:start")
        self.assertEqual(self.api.last, tpl.reminder_start(other))


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
        self.assertTrue(all(c.closed["frozen"] for d, c in self.core.state.days.items() if c.closed and c.closed.get("ignored")
                            and self.core.state.ignore_streak(d) >= 3))  # с третьего дня тишины долга нет

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
