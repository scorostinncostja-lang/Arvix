"""Голос Арвикса (D34, D36): ответ на голосовое — голосовым, голос в звонке (режим разговора).

Движки [tts] engine:
- gemini — Gemini TTS по API Google AI Studio (бесплатный тариф): живой нейросетевой голос,
  по умолчанию мужской Charon. Модель — [roles.tts] model (правило №4), ключ — [tts] api_key
  (arvix setup --tts gemini, скрытый ввод). Текст ответа уходит в Google; на бесплатном тарифе
  Google может использовать его для улучшения своих продуктов;
- command — своя команда на машине бота (Piper: deploy/tts-local.sh — без сети, но голос
  механический). Текст — в файле {in} (или на stdin, если {in} в команде нет), звук — в {out};
- off — по умолчанию: звонок в приложении говорит голосом телефона, в Telegram — только текст.

fallback_command — запасная команда, если основной движок не дал звука. По умолчанию её нет:
лучше голос телефона или текст, чем робот (владелец, 18.11).
Звук → OGG (кодек libopus) через ffmpeg — только такой файл Telegram показывает как голосовое.
"""

from __future__ import annotations

import base64
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MAX_CHARS = 1500  # больше минуты-двух речи: длинный ответ слушать тяжело, он придёт и текстом
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_VOICE = "Charon"  # мужской, «информативный»: спокойный голос наставника
# Как говорить — отдельно от текста: Gemini читает текст дословно, стиль берёт из speech_metadata.
DEFAULT_STYLE = "calm, warm and confident mentor; natural conversational pace, slightly brisk; friendly, not theatrical"
MALE_VOICES = ("Charon", "Orus", "Iapetus", "Algieba", "Sadaltager", "Puck", "Fenrir", "Enceladus", "Umbriel", "Algenib",
               "Rasalgethi", "Alnilam", "Schedar", "Achird", "Zubenelgenubi", "Sadachbia")


class TTSError(RuntimeError):
    pass


def speakable(text: str) -> str:
    """Текст для голоса: без разметки, ссылок, эмодзи и списков-символов."""
    text = re.sub(r"https?://\S+", "ссылка в сообщении", text)
    text = re.sub(r"[*_`#>|~=\[\]]", "", text)
    text = re.sub(r"^[\s—–-]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) > MAX_CHARS:
        cut = text.rfind(".", 0, MAX_CHARS)
        text = text[: cut + 1 if cut > 200 else MAX_CHARS] + " Остальное — текстом."
    return text


def find_audio(node: Any) -> str | None:
    """Base64 последнего аудио в ответе Interactions API (steps[].content[] с type == audio).
    Ищем рекурсивно: форма ответа preview-API меняется, а «кусок с type audio и data» — нет."""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "audio" and isinstance(value.get("data"), str):
                found.append(value["data"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return found[-1] if found else None


class TTS:
    def __init__(self, cfg: Any):
        section = cfg.section("tts")
        self.engine = str(section.get("engine") or "off").strip().lower()
        self.command = str(section.get("command") or "")
        self.fallback_command = str(section.get("fallback_command") or "")
        self.voice_replies = bool(section.get("voice_replies", True))
        self.timeout = int(section.get("timeout_sec") or 60)
        self.api_key = str(section.get("api_key") or "")
        self.voice = str(section.get("voice") or DEFAULT_VOICE)
        self.style = str(section.get("style") or DEFAULT_STYLE)
        self.url = str(section.get("base_url") or GEMINI_URL)
        model = getattr(cfg, "model", None)
        self.model = (model("tts") if callable(model) else None) or ""

    @property
    def enabled(self) -> bool:
        if not shutil.which("ffmpeg"):
            return False
        if self.engine == "gemini":
            return bool(self.api_key and self.model)
        return self.engine == "command" and bool(self.command)

    @property
    def label(self) -> str:
        return f"Gemini · {self.voice}" if self.engine == "gemini" else self.engine

    def problem(self) -> str:
        if self.engine == "off":
            return "голос выключен — arvix setup --tts gemini"
        if not shutil.which("ffmpeg"):
            return "нет ffmpeg"
        if self.engine == "gemini" and not self.api_key:
            return "нет ключа Gemini — arvix setup --tts gemini"
        if self.engine == "gemini" and not self.model:
            return "не задана модель [roles.tts] model"
        if self.engine == "command" and not self.command:
            return "не задана [tts] command"
        return ""

    def synth(self, text: str) -> bytes:
        """Текст → OGG для sendVoice и для плеера в приложении."""
        if not self.enabled:
            raise TTSError(self.problem())
        text = speakable(text)
        if not text:
            raise TTSError("нечего озвучивать")
        errors = []
        primary = (lambda: self._gemini(text)) if self.engine == "gemini" else (lambda: self._run(self.command, text))
        attempts = [primary] + ([lambda: self._run(self.fallback_command, text)] if self.fallback_command else [])
        for attempt in attempts:
            try:
                return self._to_ogg(attempt())
            except TTSError as exc:
                errors.append(str(exc))
        raise TTSError("; ".join(errors))

    # --- движки: вернуть звук любого формата, который понимает ffmpeg --------------------------

    def _gemini(self, text: str) -> bytes:
        body = {
            "model": self.model,
            "input": [{"type": "user_input", "content": [{
                "type": "text", "text": text,
                "annotations": [{"type": "speech_metadata", "style": self.style}],
            }]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": self.voice}]},
        }
        request = urllib.request.Request(self.url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                         headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise TTSError(gemini_error(exc.code, exc.read())) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise TTSError(f"Gemini недоступен: {exc}") from exc
        audio = find_audio(data)
        if not audio:
            raise TTSError("Gemini ответил без звука")
        try:
            return base64.b64decode(audio)
        except ValueError as exc:
            raise TTSError("Gemini прислал испорченный звук") from exc

    def _run(self, command: str, text: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            # {out} — .wav: команды вроде ffmpeg выбирают формат по расширению; Piper и так пишет WAV
            src, audio = Path(tmp) / "speech.txt", Path(tmp) / "speech.wav"
            src.write_text(text, encoding="utf-8")
            uses_file = "{in}" in command
            argv = [part.replace("{out}", str(audio)).replace("{in}", str(src)) for part in shlex.split(command)]
            try:
                subprocess.run(argv, input=None if uses_file else text, text=True, capture_output=True, timeout=self.timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TTSError(f"озвучка не удалась: {exc}") from exc
            if not audio.is_file() or not audio.stat().st_size:
                raise TTSError(f"{Path(argv[0]).name if argv else 'команда'}: звук не создан")
            return audio.read_bytes()

    def _to_ogg(self, audio: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            src, ogg = Path(tmp) / "speech.audio", Path(tmp) / "speech.ogg"
            src.write_bytes(audio)
            try:
                subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "48000",
                                "-c:a", "libopus", "-b:a", "32k", str(ogg)], capture_output=True, timeout=self.timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TTSError(f"перекодирование не удалось: {exc}") from exc
            if not ogg.is_file() or not ogg.stat().st_size:
                raise TTSError("звук не перекодировался в OGG — проверь ffmpeg")
            return ogg.read_bytes()


def gemini_error(code: int, raw: bytes) -> str:
    """Ошибка API — словами для человека: что случилось и что делать."""
    try:
        message = str((json.loads(raw or b"{}").get("error") or {}).get("message") or "")
    except ValueError:
        message = ""
    if code == 429:
        return "лимит бесплатного тарифа Gemini исчерпан — сбросится в полночь по тихоокеанскому времени (~11:00 МСК)"
    if code in (401, 403) or "API key" in message:
        return "ключ Gemini не подходит — создай новый в AI Studio и запусти arvix setup --tts gemini"
    if "location" in message.lower() or "region" in message.lower():
        return "Gemini недоступен из страны сервера"
    return f"Gemini: HTTP {code} {message[:160]}".strip()


__all__ = ["DEFAULT_VOICE", "MALE_VOICES", "TTS", "TTSError", "find_audio", "gemini_error", "speakable"]
