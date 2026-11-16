"""Голосовой ввод: голосовое из Telegram → текст (05-INTERFACES §2.6).

`claude -p` звук не понимает, Telegram боту голос не расшифровывает — нужен отдельный
распознаватель. Три движка, выбор — секция [stt] конфига, модель — [roles.stt] (правило №4):

- groq   — Whisper на Groq: быстро, хорошо по-русски, бесплатный тариф; нужен ключ API;
- openai — Whisper / transcribe-модели OpenAI; нужен ключ API;
- command — своя команда на этой машине (например, whisper.cpp): голос никуда не уходит.

Без зависимостей: multipart-запрос собирается вручную через urllib.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ENDPOINTS = {"groq": "https://api.groq.com/openai/v1", "openai": "https://api.openai.com/v1"}
API_ENGINES = tuple(ENDPOINTS)


class STTError(RuntimeError):
    """Не распознано — с причиной, понятной человеку."""


def multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes, content_type: str) -> tuple[bytes, str]:
    """Тело multipart/form-data и заголовок Content-Type."""
    boundary = f"arvix-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode() + data + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class STT:
    def __init__(self, cfg: Any):
        section = cfg.section("stt")
        self.engine = str(section.get("engine") or "off").strip().lower()
        self.api_key = str(section.get("api_key") or "")
        self.base_url = str(section.get("base_url") or ENDPOINTS.get(self.engine, "")).rstrip("/")
        self.language = str(section.get("language") or "")
        self.command = str(section.get("command") or "")
        self.max_seconds = int(section.get("max_seconds") or 300)
        self.timeout = int(section.get("timeout_sec") or 90)
        # Показывать ли расшифровку перед ответом. По умолчанию нет: проверка распознавания —
        # квитанция под ответом (что записано), а не лишнее сообщение (09-DECISIONS D20).
        self.show_transcript = bool(section.get("show_transcript", False))
        self.model = cfg.model("stt") or ""

    def problem(self) -> str:
        """Почему голосовые не работают; пусто — всё настроено."""
        if self.engine == "off":
            return "голосовые выключены: arvix setup --stt groq"
        if self.engine in API_ENGINES:
            if not self.api_key:
                return f"нет ключа API для {self.engine}: arvix setup --stt {self.engine}"
            if not self.model:
                return "не задана модель [roles.stt] model"
            return ""
        if self.engine == "command":
            return "" if self.command else "не задана [stt] command"
        return f"неизвестный движок «{self.engine}»: groq, openai, command или off"

    @property
    def enabled(self) -> bool:
        return not self.problem()

    def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if not self.enabled:
            raise STTError(self.problem())
        if self.engine == "command":
            return self._command(audio, filename)
        return self._api(audio, filename)

    def _api(self, audio: bytes, filename: str) -> str:
        fields = {"model": self.model, "response_format": "json"}
        if self.language:
            fields["language"] = self.language
        body, content_type = multipart(fields, "file", filename, audio, "audio/ogg")
        request = urllib.request.Request(
            f"{self.base_url}/audio/transcriptions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": content_type, "User-Agent": "arvix-stt"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            exc.close()
            reason = {401: "ключ API не подошёл", 403: "доступ запрещён — регион или права ключа", 413: "файл слишком большой",
                      429: "лимит распознавания — попробуй через минуту"}.get(exc.code, f"сервис ответил HTTP {exc.code}")
            raise STTError(reason) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise STTError(f"сервис распознавания недоступен: {exc}") from exc
        return str(data.get("text") or "").strip()

    def _command(self, audio: bytes, filename: str) -> str:
        """{input} — путь к присланному файлу, {wav} — путь для промежуточного wav (например, для ffmpeg)."""
        with tempfile.TemporaryDirectory(prefix="arvix-stt-") as tmp:
            source = Path(tmp) / (Path(filename).name or "voice.ogg")
            source.write_bytes(audio)
            wav = Path(tmp) / "voice.wav"
            command = self.command.replace("{input}", shlex.quote(str(source))).replace("{wav}", shlex.quote(str(wav)))
            try:
                done = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=self.timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise STTError(f"распознавание дольше {self.timeout} с") from exc
            except OSError as exc:
                raise STTError(f"команда не запустилась: {exc}") from exc
            if done.returncode != 0:
                raise STTError(f"команда завершилась с кодом {done.returncode}: {(done.stderr or '').strip()[-200:]}")
            return " ".join(line.strip() for line in done.stdout.splitlines() if line.strip())
