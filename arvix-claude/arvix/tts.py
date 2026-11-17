"""Голос Арвикса (D34): ответ на голосовое — голосовым, озвучка в режиме разговора.

Движки:
- off — по умолчанию; приложение озвучивает само (голос телефона, speechSynthesis);
- command — своя команда на машине бота, например Piper с русским голосом
  (deploy/tts-local.sh): текст уходит на stdin, команда пишет WAV в {out}. Бесплатно,
  без сети, текст никуда не отправляется.

WAV → OGG (кодек libopus) через ffmpeg — только такой файл Telegram показывает как голосовое.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MAX_CHARS = 1500  # больше минуты-двух речи: длинный ответ слушать тяжело, он придёт и текстом


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


class TTS:
    def __init__(self, cfg: Any):
        section = cfg.section("tts")
        self.engine = str(section.get("engine") or "off").strip().lower()
        self.command = str(section.get("command") or "")
        self.voice_replies = bool(section.get("voice_replies", True))
        self.timeout = int(section.get("timeout_sec") or 60)

    @property
    def enabled(self) -> bool:
        return self.engine == "command" and bool(self.command) and shutil.which("ffmpeg") is not None

    def problem(self) -> str:
        if self.engine == "off":
            return "озвучка выключена ([tts] engine = \"command\", deploy/tts-local.sh)"
        if not self.command:
            return "не задана [tts] command"
        if not shutil.which("ffmpeg"):
            return "нет ffmpeg"
        return ""

    def synth(self, text: str) -> bytes:
        """Текст → OGG для sendVoice и для плеера в приложении."""
        if not self.enabled:
            raise TTSError(self.problem())
        text = speakable(text)
        if not text:
            raise TTSError("нечего озвучивать")
        with tempfile.TemporaryDirectory() as tmp:
            wav, ogg = Path(tmp) / "speech.wav", Path(tmp) / "speech.ogg"
            argv = [part.replace("{out}", str(wav)) for part in shlex.split(self.command)]
            try:
                subprocess.run(argv, input=text, text=True, capture_output=True, timeout=self.timeout, check=False)
                subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-ar", "48000",
                                "-c:a", "libopus", "-b:a", "32k", str(ogg)], capture_output=True, timeout=self.timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TTSError(f"озвучка не удалась: {exc}") from exc
            if not ogg.is_file() or not ogg.stat().st_size:
                raise TTSError("команда озвучки не создала звук — проверь [tts] command")
            return ogg.read_bytes()


__all__ = ["TTS", "TTSError", "speakable"]
