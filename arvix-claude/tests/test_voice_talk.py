"""Голос Арвикса (D34): ответ на голосовое — короче и голосовым, озвучка в приложении."""

from __future__ import annotations

import shutil
import unittest
from typing import Any

from arvix.tts import TTS, speakable

from tests import test_v04
from tests.test_telegram import BotCase, FakeSTT


class FakeTTS:
    enabled = True
    voice_replies = True

    def __init__(self) -> None:
        self.texts: list[str] = []

    def synth(self, text: str) -> bytes:
        self.texts.append(text)
        return b"OggS-fake"


class VoiceReplyTest(BotCase):
    def setUp(self) -> None:
        super().setUp()
        self.voices: list[bytes] = []
        self.api.send_voice = lambda chat_id, ogg, caption=None: self.voices.append(ogg) or 99  # type: ignore[attr-defined]
        self.bot.stt = FakeSTT("как думаешь, я вообще двигаюсь?")
        self.bot.tts = FakeTTS()

    def test_voice_message_gets_short_spoken_answer_and_voice(self) -> None:
        self.brain.answers.append({"reply": "Двигаешься. Три темы за неделю закрыл. Что мешает в остальном?", "actions": []})
        self.voice()
        self.assertIn("<spoken>", self.brain.calls[-1]["system"])
        self.assertEqual(self.voices, [b"OggS-fake"])
        self.assertIn("Что мешает", self.bot.tts.texts[-1])
        self.assertIn("Двигаешься.", self.api.texts[0])  # текст тоже есть — голос вдобавок

    def test_typed_message_is_not_voiced(self) -> None:
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.text("что на сегодня?")
        self.assertNotIn("<spoken>", self.brain.calls[-1]["system"])
        self.assertEqual(self.voices, [])

    def test_no_voice_when_tts_off(self) -> None:
        self.bot.tts = TTS(self.core.cfg)  # по умолчанию выключен
        self.brain.answers.append({"reply": "Слышу.", "actions": []})
        self.voice()
        self.assertEqual(self.voices, [])
        self.assertIn("Слышу.", self.api.last)


class SpeakableTest(unittest.TestCase):
    def test_markup_links_and_emoji_are_not_read_aloud(self) -> None:
        text = speakable("**Важно** 🎯 — смотри https://fipi.ru\n\n- пункт\n#тег")
        self.assertEqual(text, "Важно  — смотри ссылка в сообщении\nпункт\nтег")

    @unittest.skipUnless(shutil.which("ffmpeg"), "нет ffmpeg")
    def test_command_engine_produces_telegram_voice(self) -> None:
        class Cfg:
            def section(self, name: str) -> dict[str, Any]:
                return {"engine": "command",
                        "command": "ffmpeg -v error -y -f lavfi -i sine=frequency=300:duration=1 {out}"} if name == "tts" else {}

        audio = TTS(Cfg()).synth("Привет")
        self.assertTrue(audio.startswith(b"OggS"))


class TtsServerTest(test_v04.ServerTest):
    def test_tts_off_says_phone_speaks(self) -> None:
        status, body = self.call("/api/tts", {"text": "привет"})
        self.assertEqual(status, 404)
        self.assertIn("голос телефона", body["error"])
        status, state = self.call("/api/state")
        self.assertFalse(state["server_tts"])
