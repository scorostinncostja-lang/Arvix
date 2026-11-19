"""Чат без сбоев (D51): голова не держит очередь, черновики не пропадают, у каждого чата своя нить,
голосовое — только то, что стоит послушать, и доходит до приложения."""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Any

from arvix.telegram.bot import voice_note_check, wants_voice
from arvix.tts import audio_path, save_audio
from arvix.web import api as web_api
from arvix.web.hub import Hub

from tests import test_v04
from tests.helpers import ArvixCase
from tests.test_telegram import BotCase
from tests.test_voice_talk import FakeTTS

STATIC = Path(__file__).resolve().parent.parent / "arvix" / "web" / "static"


class HubLaneTest(ArvixCase):
    def setUp(self) -> None:
        super().setUp()
        self.held: list[Any] = []
        self.hub = Hub(spawn=self.held.append)  # поток головы запускаем вручную

    def test_quick_jobs_run_while_the_head_thinks(self) -> None:
        """Раньше голова 10–180 с держала главный поток: кнопки отваливались, Telegram ждал."""
        log: list[str] = []
        self.hub.think(lambda: (lambda: "ответ", lambda r: log.append("записан " + r)))
        self.assertEqual(self.hub.busy, "думаю")
        self.hub.post(lambda _bot: log.append("кнопка"))
        self.hub.run_pending(None, 0.01)
        self.assertEqual(log, ["кнопка"])  # голова ещё думает — кнопка уже отработала
        self.held.pop()()                  # голова ответила
        self.hub.run_pending(None, 0.01)
        self.assertEqual(log, ["кнопка", "записан ответ"])
        self.assertEqual(self.hub.busy, "")

    def test_second_message_waits_for_the_first_answer(self) -> None:
        """Порядок разговора: запрос второго сообщения собирается, когда ответ на первое уже записан."""
        log: list[str] = []
        self.hub.think(lambda: (lambda: 1, lambda r: log.append("ответ 1")))
        self.hub.think(lambda: log.append("готовлю 2") or (lambda: 2, lambda r: log.append("ответ 2")))
        self.assertEqual(log, [])
        self.held.pop(0)()
        self.hub.run_pending(None, 0.01)
        self.assertEqual(log, ["ответ 1", "готовлю 2"])
        self.held.pop(0)()
        self.hub.run_pending(None, 0.01)
        self.assertEqual(log, ["ответ 1", "готовлю 2", "ответ 2"])

    def test_head_crash_frees_the_lane(self) -> None:
        got: list[Any] = []

        def boom() -> None:
            raise RuntimeError("сеть")

        self.hub.think(lambda: (boom, got.append))
        with self.assertLogs("arvix.hub", "ERROR"):
            self.held.pop()()
        self.hub.run_pending(None, 0.01)
        self.assertEqual(got, [None])  # записать(None) — ответит шаблон
        self.assertFalse(self.hub.in_flight)

    def test_timed_out_call_does_not_run_later(self) -> None:
        """«Арвикс занят» — и задача снята: повторное нажатие не закроет задачу дважды."""
        ran: list[int] = []
        with self.assertRaises(TimeoutError):
            self.hub.call(lambda _bot: ran.append(1), timeout=0.01)
        self.hub.run_pending(None, 0.01)
        self.assertEqual(ran, [])

    def test_telegram_updates_do_not_show_as_thinking(self) -> None:
        seen: list[str] = []
        self.hub.post(lambda _bot: seen.append(self.hub.busy), "update 7", show=False)
        self.hub.post(lambda _bot: seen.append(self.hub.busy), "слушаю")
        self.hub.run_pending(None, 0.01)
        self.assertEqual(seen, ["", "слушаю"])


class LaneBotTest(BotCase):
    def setUp(self) -> None:
        super().setUp()
        self.held: list[Any] = []
        self.hub = Hub(spawn=self.held.append)
        self.bot.lane = self.hub.think

    def test_message_is_in_the_journal_before_the_answer(self) -> None:
        self.brain.answers.append({"reply": "Привет. Что сегодня главное?", "actions": []})
        self.text("привет")
        texts = [m["text"] for m in web_api.messages_view(self.core)]
        self.assertEqual(texts, ["привет"])  # приложение видит сообщение сразу, а не через минуту
        self.assertEqual(self.api.sent, [])
        self.held.pop()()
        self.hub.run_pending(self.bot, 0.01)
        self.assertIn("Что сегодня главное?", self.api.last)

    def test_answer_goes_to_the_channel_it_came_from(self) -> None:
        """Пока голова думала над сообщением из приложения, бот обработал Telegram: ответ — всё равно в приложение."""
        self.brain.answers.append({"reply": "Ответ приложению.", "actions": []})
        self.hub.post(web_api.chat("вопрос из приложения", cid="c1"))
        self.hub.run_pending(self.bot, 0.01)
        self.press("noop")  # Telegram что-то делает между
        self.held.pop()()
        self.hub.run_pending(self.bot, 0.01)
        last = web_api.messages_view(self.core)[-1]
        self.assertEqual((last["text"], last["channel"]), ("Ответ приложению.", "web"))
        self.assertFalse(any("Ответ приложению" in t for t, _ in self.api.sent))
        mine = [m for m in web_api.messages_view(self.core) if m["who"] == "me"]
        self.assertEqual(mine[0]["cid"], "c1")


class ThreadTest(BotCase):
    def test_main_chat_history_has_no_project_threads(self) -> None:
        """Голова в общем чате видела нити проектов, которых нет в ленте — и отвечала невпопад."""
        self.core.message_in("про проект: какой стек?", channel="web", project="p1")
        self.core.message_out("Возьми FastAPI.", channel="web", project="p1")
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.text("как спал?")
        self.assertNotIn("FastAPI", self.brain.calls[-1]["system"])
        with self.bot.in_project("p1"):
            self.assertTrue(any("FastAPI" in line for line in self.bot.history()))


class VoiceRuleTest(ArvixCase):
    def test_pronunciation_may_repeat_the_text(self) -> None:
        """Слово в тексте и оно же голосом — не дубль, а смысл: прочитал и услышал."""
        reply = "Запомни: **thoroughly** — тщательно, **though** — хотя."
        self.assertTrue(voice_note_check("thoroughly. though.", reply, "pronunciation"))

    def test_russian_retelling_is_dropped_even_as_pronunciation(self) -> None:
        reply = "Сегодня математика в 20:00, потом отдых."
        self.assertEqual(voice_note_check("Сегодня математика в двадцать, потом отдых.", reply, "pronunciation"), "")
        self.assertEqual(voice_note_check("Сегодня математика в 20:00, потом отдых.", reply, "memorize"), "")

    def test_motivation_kind_is_not_a_voice_note(self) -> None:
        self.assertEqual(voice_note_check("Ты справишься, вперёд!", "План готов.", "pronunciation"), "")
        self.assertEqual(voice_note_check("Ты справишься, вперёд!", "План готов."), "")  # без назначения — тоже нет

    def test_asked_voice_skips_retelling_rule(self) -> None:
        reply = "Закон Ома: сила тока равна напряжению, делённому на сопротивление."
        self.assertTrue(voice_note_check("Сила тока равна напряжению, делённому на сопротивление.", reply, "memorize", asked=True))

    def test_wants_voice(self) -> None:
        for text in ("как это звучит?", "произнеси thought", "озвучь правило", "скажи голосом"):
            self.assertTrue(wants_voice(text), text)
        self.assertFalse(wants_voice("что на сегодня"))


class VoiceToAppTest(BotCase):
    def setUp(self) -> None:
        super().setUp()
        self.voices: list[bytes] = []
        self.api.send_voice = lambda chat_id, ogg, caption=None: self.voices.append(ogg) or 99  # type: ignore[attr-defined]
        self.bot.tts = FakeTTS()

    def test_telegram_voice_note_is_playable_in_the_app(self) -> None:
        self.brain.answers.append({"reply": "Неправильные глаголы: bring — brought.", "voice_note": "bring, brought, brought",
                                   "voice_kind": "pronunciation", "actions": []})
        self.text("как звучит brought?")
        self.assertEqual(self.voices, [b"OggS-fake"])
        last = web_api.messages_view(self.core)[-1]
        self.assertTrue(last["audio"])
        self.assertEqual(audio_path(last["audio"]).read_bytes(), b"OggS-fake")

    def test_app_gets_voice_notes_too(self) -> None:
        """Раньше голосовое шло только в Telegram — в приложении от него оставалась строка «🔊 …»."""
        self.brain.answers.append({"reply": "Слушай.", "voice_note": "through, though, thought", "voice_kind": "pronunciation", "actions": []})
        web_api.chat("как произносится through?")(self.bot)
        self.assertEqual(self.voices, [])  # в Telegram не дублируется
        last = web_api.messages_view(self.core)[-1]
        self.assertEqual((last["channel"], last["text"]), ("web", "🔊 through, though, thought"))
        self.assertTrue(audio_path(last["audio"]).is_file())

    def test_project_chat_voice_note(self) -> None:
        from arvix import projects

        pid = projects.start(self.core, "выучить английский для собеседования", source="web")
        self.brain.answers.append({"reply": "Фраза дня.", "voice_note": "Could you walk me through it?", "voice_kind": "pronunciation",
                                   "actions": []})
        web_api.project_chat(pid, "как это звучит по-английски?")(self.bot)
        msgs = web_api.project_messages(self.core, pid)
        self.assertTrue(msgs[-1]["audio"])

    def test_asked_voice_ignores_daily_cap(self) -> None:
        self.bot.voice_notes_per_day = 0
        self.brain.answers.append({"reply": "Вот.", "voice_note": "thought", "voice_kind": "pronunciation", "actions": []})
        self.text("произнеси thought")
        self.assertEqual(len(self.voices), 1)
        self.brain.answers.append({"reply": "Вот.", "voice_note": "thought", "voice_kind": "pronunciation", "actions": []})
        self.text("что дальше по английскому")
        self.assertEqual(len(self.voices), 1)  # без просьбы — лимит

    def test_audio_names_are_checked(self) -> None:
        name = save_audio(b"OggS-1")
        self.assertTrue(audio_path(name).is_file())
        for bad in ("../arvix.db", "x.ogg", name.replace(".ogg", ".db")):
            with self.assertRaises(ValueError):
                audio_path(bad)


class ServerAudioTest(test_v04.ServerTest):
    def test_audio_route_and_cid(self) -> None:
        name = save_audio(b"OggS-route")
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/audio?name={name}",
                                         headers={"Authorization": f"Bearer {self.app.token}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual((response.headers["Content-Type"], response.read()), ("audio/ogg", b"OggS-route"))
        status, body = self.call("/api/audio?name=..%2Farvix.db")
        self.assertEqual(status, 400)
        self.brain.answers.append({"reply": "Принял.", "actions": []})
        status, _ = self.call("/api/message", {"text": "черновик", "cid": "abc123"})
        self.assertEqual(status, 202)
        for _ in range(200):
            msgs = self.call("/api/messages")[1]["messages"]
            if any(m.get("cid") == "abc123" for m in msgs):
                break
            time.sleep(0.02)
        self.assertTrue(any(m.get("cid") == "abc123" and m["text"] == "черновик" for m in msgs))


class NoCallTest(ArvixCase):
    def test_call_screen_is_gone(self) -> None:
        """Звонок убран (D51): голова думает 10–60 с, разговора не выходило; вместо него — голосовые по делу и 🔊."""
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for word in ("openTalk", "talkListen", "top-call"):
            self.assertNotIn(word, js + html)
        self.assertIn("X-Client-Id", js)
        self.assertIn("navigator.vibrate", js)

    def test_stylesheet_blocks_are_closed(self) -> None:
        """Незакрытый @media (min-width: 900px) с проектов 3 проглатывал всё ниже: планшет вертикально
        (600–899 px) не получал свою раскладку, а новые стили чата не применялись нигде."""
        import re

        css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
        depth = 0
        for line in css.split("\n"):
            depth += line.count("{") - line.count("}")
            self.assertGreaterEqual(depth, 0, line)
        self.assertEqual(depth, 0)
        self.assertIn("\n.voice {", css)  # правило верхнего уровня, а не внутри чужого @media

    def test_spoken_mode_is_gone(self) -> None:
        bot_src = (STATIC.parent.parent / "telegram" / "bot.py").read_text(encoding="utf-8")
        self.assertNotIn("<spoken>", bot_src)


def load_tests(loader: Any, tests: Any, pattern: Any) -> Any:
    """ServerAudioTest берёт у test_v04.ServerTest только обвязку сервера — его тесты не повторяем."""
    import unittest

    suite = unittest.TestSuite()
    for case in (HubLaneTest, LaneBotTest, ThreadTest, VoiceRuleTest, VoiceToAppTest, NoCallTest):
        suite.addTests(loader.loadTestsFromTestCase(case))
    suite.addTests(ServerAudioTest(name) for name in ServerAudioTest.__dict__ if name.startswith("test_"))
    return suite
