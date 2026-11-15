"""Распознавание голосовых: конфиг, multipart-запрос к API, своя команда — без сети."""

import io
import json
import sys
import unittest
import urllib.error
from unittest import mock

from arvix import stt
from arvix.config import Config

from tests.helpers import ROOT  # noqa: F401 — кладёт пакет в sys.path


def cfg(**section) -> Config:
    return Config({"stt": section, "roles": {"stt": {"model": "test-model"}}})


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SttTest(unittest.TestCase):
    def test_off_by_default_with_hint(self) -> None:
        engine = stt.STT(cfg())
        self.assertFalse(engine.enabled)
        self.assertIn("arvix setup --stt", engine.problem())
        with self.assertRaises(stt.STTError):
            engine.transcribe(b"x")
        self.assertIn("нет ключа", stt.STT(cfg(engine="groq")).problem())
        self.assertIn("неизвестный", stt.STT(cfg(engine="yandex")).problem())

    def test_multipart_body(self) -> None:
        body, content_type = stt.multipart({"model": "m", "language": "ru"}, "file", "voice.ogg", b"OGGDATA", "audio/ogg")
        boundary = content_type.split("boundary=")[1]
        self.assertTrue(body.startswith(f"--{boundary}".encode()))
        self.assertIn(b'name="model"\r\n\r\nm\r\n', body)
        self.assertIn(b'filename="voice.ogg"', body)
        self.assertIn(b"OGGDATA", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_api_engine_sends_key_model_and_audio(self) -> None:
        engine = stt.STT(cfg(engine="groq", api_key="k-123", language="ru"))
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"], seen["auth"], seen["body"] = request.full_url, request.headers["Authorization"], request.data
            return FakeResponse(json.dumps({"text": " сделал физику, 10 задач "}).encode())

        with mock.patch.object(stt.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(engine.transcribe(b"OGG"), "сделал физику, 10 задач")
        self.assertEqual(seen["url"], "https://api.groq.com/openai/v1/audio/transcriptions")
        self.assertEqual(seen["auth"], "Bearer k-123")
        self.assertIn(b"test-model", seen["body"])
        self.assertIn(b"OGG", seen["body"])

    def test_api_errors_are_explained(self) -> None:
        engine = stt.STT(cfg(engine="openai", api_key="bad"))
        error = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b""))
        with mock.patch.object(stt.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(stt.STTError, "ключ API не подошёл"):
                engine.transcribe(b"OGG")

    def test_command_engine_gets_the_file_and_returns_stdout(self) -> None:
        reader = f'{sys.executable} -c "import sys; print(open(sys.argv[1], encoding=\'utf-8\').read()); print(sys.argv[2].endswith(\'.wav\'))" {{input}} {{wav}}'
        engine = stt.STT(cfg(engine="command", command=reader))
        self.assertEqual(engine.transcribe("запиши мысль".encode()), "запиши мысль True")
        with self.assertRaisesRegex(stt.STTError, "кодом 3"):
            stt.STT(cfg(engine="command", command="echo боль >&2; exit 3")).transcribe(b"x")


if __name__ == "__main__":
    unittest.main()
