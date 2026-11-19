"""Голос Арвикса (D34, D45): голосовое — только voice_note головы, не озвучка текста; озвучка в приложении."""

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

    def test_voice_message_gets_text_only_not_its_own_reading(self) -> None:
        """D45: озвучка того же текста — дубль. На голосовое — текст; голосовое — только voice_note."""
        self.brain.answers.append({"reply": "Двигаешься. Три темы за неделю закрыл. Что мешает в остальном?", "actions": []})
        self.voice()
        self.assertIn("<dictated>", self.brain.calls[-1]["system"])
        self.assertNotIn("<spoken>", self.brain.calls[-1]["system"])
        self.assertEqual(self.voices, [])
        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("Двигаешься.", self.api.last)

    def test_voice_note_is_sent_when_it_adds_something(self) -> None:
        self.brain.answers.append({"reply": "Сегодня **английский** в 18:00, 30 минут: неправильные глаголы.",
                                   "voice_note": "Послушай и повтори вслух: bring, brought, brought. Think, thought, thought.",
                                   "actions": []})
        self.text("что по английскому?")
        self.assertEqual(self.voices, [b"OggS-fake"])
        self.assertIn("brought", self.bot.tts.texts[-1])
        self.assertIn("английский", self.api.texts[0])  # текст — первым и целиком

    def test_voice_note_that_retells_the_reply_is_dropped(self) -> None:
        reply = "Нет, на сегодня один блок: математика в 20:00, 45 минут. Физику не ставлю, день жёлтый."
        self.brain.answers.append({"reply": reply, "voice_note": "Сегодня один блок — математика в 20:00, 45 минут. Физику не ставлю.",
                                   "actions": []})
        self.voice()
        self.assertEqual(self.voices, [])

    def test_voice_notes_have_a_daily_cap(self) -> None:
        for i in range(4):
            self.brain.answers.append({"reply": f"Ответ {i}.", "voice_note": "Повтори: through, though, thought.", "actions": []})
            self.text(f"вопрос {i}")
        self.assertEqual(len(self.voices), 3)  # [tts] voice_notes_per_day

    def test_voice_note_with_pressure_is_dropped_in_red(self) -> None:
        self.core.effective_mode = lambda *a, **k: "red"  # type: ignore[method-assign]
        self.brain.answers.append({"reply": "Отдыхай, я рядом.", "voice_note": "Но дисциплина: завтра все задачи.", "actions": []})
        self.text("сил нет")
        self.assertEqual(self.voices, [])

    def test_no_voice_note_in_app_channel(self) -> None:
        sent: list[str] = []
        app = type("App", (), {"send": lambda _s, _c, text, *a, **k: sent.append(text), "typing": lambda *_: None,
                               "send_voice": lambda *_a, **_k: self.voices.append(b"x")})()
        self.brain.answers.append({"reply": "Ок.", "voice_note": "Повтори: through, though, thought.", "actions": []})
        with self.bot.via("web", app):
            self.bot.converse("вопрос")
        self.assertEqual(self.voices, [])

    def test_typed_message_has_no_dictation_hint(self) -> None:
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.text("что на сегодня?")
        self.assertNotIn("<spoken>", self.brain.calls[-1]["system"])
        self.assertNotIn("<dictated>", self.brain.calls[-1]["system"])
        self.assertEqual(self.voices, [])

    def test_no_voice_when_tts_off(self) -> None:
        self.bot.tts = TTS(self.core.cfg)  # по умолчанию выключен
        self.brain.answers.append({"reply": "Слышу.", "voice_note": "Повтори: through, though, thought.", "actions": []})
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


def wav_bytes(seconds: float = 0.3) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x01" * int(24000 * seconds))
    return buf.getvalue()


class GeminiVoiceTest(BotCase):
    """D36: голос Gemini (бесплатный тариф AI Studio), мужской Charon; запрос — по официальному примеру."""

    def gemini(self, **tts: Any) -> TTS:
        self.core.cfg.raw["tts"] = {"engine": "gemini", "api_key": "test-key", **tts}
        return TTS(self.core.cfg)

    def fake_response(self, payload: dict, seen: dict) -> Any:
        import io
        import json as _json

        class Response(io.BytesIO):
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *a: Any) -> None:
                return None

        def urlopen(request: Any, timeout: int = 0) -> Response:
            seen["url"], seen["headers"], seen["body"] = request.full_url, dict(request.header_items()), _json.loads(request.data)
            return Response(_json.dumps(payload).encode())

        return urlopen

    def test_request_follows_docs_and_model_comes_from_config(self) -> None:
        import base64
        from unittest import mock

        tts = self.gemini()
        self.assertTrue(tts.model)  # [roles.tts] model из defaults.toml — правило №4
        audio = base64.b64encode(wav_bytes()).decode()
        payload = {"steps": [{"type": "model_output", "content": [{"type": "audio", "mime_type": "audio/wav", "data": audio}]}]}
        seen: dict = {}
        with mock.patch("urllib.request.urlopen", self.fake_response(payload, seen)):
            if shutil.which("ffmpeg"):
                self.assertTrue(tts.synth("**Привет** 🎯, это Арвикс").startswith(b"OggS"))
            else:
                tts._gemini("Привет")
        self.assertEqual(seen["url"], "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(seen["headers"]["X-goog-api-key"], "test-key")
        body = seen["body"]
        self.assertEqual(body["model"], tts.model)
        self.assertEqual(body["generation_config"]["speech_config"], [{"voice": "Charon"}])  # мужской голос по умолчанию
        self.assertEqual(body["response_format"], {"type": "audio"})
        part = body["input"][0]["content"][0]
        self.assertEqual(part["annotations"][0]["type"], "speech_metadata")
        if shutil.which("ffmpeg"):
            self.assertEqual(part["text"], "Привет , это Арвикс")  # разметка и эмодзи не читаются вслух

    def test_quota_and_bad_key_are_explained_in_words(self) -> None:
        import io
        import urllib.error
        from unittest import mock

        from arvix.tts import TTSError

        def limited(request: Any, timeout: int = 0) -> Any:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b'{"error": {"message": "quota"}}'))

        with mock.patch("urllib.request.urlopen", limited), self.assertRaises(TTSError) as ctx:
            self.gemini()._gemini("привет")
        self.assertIn("лимит", str(ctx.exception))

    @unittest.skipUnless(shutil.which("ffmpeg"), "нет ffmpeg")
    def test_fallback_command_only_when_configured(self) -> None:
        import urllib.error
        from unittest import mock

        from arvix.tts import TTSError

        def down(request: Any, timeout: int = 0) -> Any:
            raise urllib.error.URLError("нет сети")

        with mock.patch("urllib.request.urlopen", down):
            with self.assertRaises(TTSError):  # по умолчанию робота в запасе нет: лучше текст или голос телефона
                self.gemini().synth("привет")
            tts = self.gemini(fallback_command="ffmpeg -v error -y -f lavfi -i sine=frequency=300:duration=1 {out}")
            self.assertTrue(tts.synth("привет").startswith(b"OggS"))

    def test_without_key_voice_is_off_and_says_how_to_enable(self) -> None:
        self.core.cfg.raw["tts"] = {"engine": "gemini"}
        tts = TTS(self.core.cfg)
        self.assertFalse(tts.enabled)
        self.assertIn("arvix setup --tts gemini", tts.problem())

    def test_find_audio_takes_last_audio_part(self) -> None:
        from arvix.tts import find_audio

        data = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "x"}, {"type": "audio", "data": "QQ=="}]},
                          {"type": "model_output", "content": [{"type": "audio", "data": "Qg=="}]}]}
        self.assertEqual(find_audio(data), "Qg==")
        self.assertIsNone(find_audio({"steps": []}))

    def test_setup_asks_key_hidden_and_keeps_male_voice(self) -> None:
        from unittest import mock

        from arvix import cli

        with mock.patch.object(cli.sys.stdin, "isatty", return_value=True), mock.patch.object(cli.getpass, "getpass", return_value="k-1"):
            self.assertEqual(cli._setup_tts("gemini", None), {"engine": "gemini", "api_key": "k-1", "voice": "Charon"})
            self.assertEqual(cli._setup_tts("gemini", "Orus")["voice"], "Orus")
