"""HTTP-сервер приложения на stdlib (05-INTERFACES §7).

Слушает только 127.0.0.1: наружу его выставляет Caddy с HTTPS (deploy/web-setup.sh),
к терминалу на ноутбуке — SSH-туннель (arvix/tui.py). Без зависимостей и без сборки фронта.

GET  /                        приложение (static/)
GET  /api/state               экран «Сегодня»
GET  /api/messages?before=id  переписка из журнала
GET  /api/history?days=30     прогресс, цели, неделя
GET  /api/notes?dir=…         папка хранилища · /api/note?path=… — заметка · /api/notes/search?q=…
GET  /api/stream              поток событий: строка {"v": …} при любом изменении (fetch + ReadableStream)
GET  /api/pair                ключ для PWA и терминала (только из Mini App)
POST /api/message {text} · /api/voice (аудио) · /api/button {data}
POST /api/tasks {…} · /api/tasks/<id>/<op> · /api/lesson/<id> · /api/focus {minutes, task} · /api/focus/stop
POST /api/capture {text}      мысль в Inbox
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from arvix import __version__
from arvix.config import Config
from arvix.core import ArvixError, Core
from arvix.store import Store
from arvix.web import api
from arvix.web.auth import app_token, authorize
from arvix.web.hub import Hub

log = logging.getLogger("arvix.web")
STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 25 * 1024 * 1024  # голосовое до ~25 МБ
STREAM_EVERY = 1.0
STREAM_PING = 15.0


class WebApp:
    """Всё, что нужно обработчику: Core только для чтения (под замком), очередь, ключи."""

    def __init__(self, cfg: Config, hub: Hub, *, core: Core | None = None):
        self.cfg = cfg
        self.hub = hub
        self.core = core or Core(cfg, Store(cfg.db_path, shared=True))
        self.lock = threading.RLock()
        tg = cfg.section("telegram")
        self.bot_token = str(tg.get("token") or "")
        self.owner_id = int(tg.get("owner_id") or 0)
        with self.lock:
            self.token = app_token(self.core)

    def read(self, fn: Any) -> Any:
        with self.lock:
            self.core.refresh(catch_up=False)
            return fn(self.core)

    def version(self) -> str:
        """Отпечаток всего, что видит приложение: журнал, таймер, урок, «думаю»."""
        with self.lock:
            row = self.core.store._conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()
            focus = self.core.store.kv_get(api.FOCUS)
            lesson = self.core.store.kv_get(api.LESSON)
        raw = json.dumps([row[0], focus, lesson, self.hub.busy], default=str, sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def vault(self) -> Any:
        from arvix.vault import Vault

        if not self.cfg.vault:
            raise ArvixError("Хранилище не настроено")
        return Vault(self.cfg.vault, self.cfg.vault_paths)


def make_handler(app: WebApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "Arvix"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # без access-лога: в URL нет секретов, но и шума не надо
            return

        # --- ответы ------------------------------------------------------------------

        def send_json(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def fail(self, status: int, message: str) -> None:
            self.send_json({"error": message}, status)

        def body_json(self) -> dict[str, Any]:
            raw = self.body_bytes()
            try:
                data = json.loads(raw or b"{}")
            except ValueError as exc:
                raise ArvixError("Тело запроса — не JSON") from exc
            return data if isinstance(data, dict) else {}

        def body_bytes(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ArvixError("Слишком большой запрос")
            return self.rfile.read(length) if length else b""

        def authorized(self) -> str | None:
            return authorize(self.headers, token=app.token, bot_token=app.bot_token, owner_id=app.owner_id)

        # --- маршруты ------------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 — имя задаёт http.server
            url = urllib.parse.urlsplit(self.path)
            if not url.path.startswith("/api/"):
                self.static(url.path)
                return
            who = self.authorized()
            if who is None:
                self.fail(HTTPStatus.UNAUTHORIZED, "Нужен вход: откройте приложение из Telegram или привяжите ключ")
                return
            query = dict(urllib.parse.parse_qsl(url.query))
            try:
                if url.path == "/api/state":
                    self.send_json(app.read(lambda c: api.state_view(c, thinking=app.hub.busy)) | {"app_version": __version__})
                elif url.path == "/api/messages":
                    before = int(query["before"]) if query.get("before") else None
                    self.send_json({"messages": app.read(lambda c: api.messages_view(c, before=before)), "thinking": app.hub.busy})
                elif url.path == "/api/history":
                    days = max(7, min(int(query.get("days") or 30), 120))
                    self.send_json(app.read(lambda c: api.history_view(c, days)))
                elif url.path == "/api/notes":
                    self.send_json(self.notes_dir(query.get("dir") or ""))
                elif url.path == "/api/note":
                    vault = app.vault()
                    self.send_json({"path": query.get("path"), "text": vault.read(query.get("path") or "")})
                elif url.path == "/api/notes/search":
                    self.send_json({"results": app.vault().search(query.get("q") or "", 20)})
                elif url.path == "/api/stream":
                    self.stream()
                elif url.path == "/api/pair":
                    if who != "telegram":
                        self.fail(HTTPStatus.FORBIDDEN, "Ключ выдаётся только внутри Telegram")
                        return
                    base = str(app.cfg.section("web").get("public_url") or "").rstrip("/")
                    self.send_json({"token": app.token, "url": f"{base}/#t={app.token}" if base else ""})
                else:
                    self.fail(HTTPStatus.NOT_FOUND, "Нет такого адреса")
            except (ArvixError, ValueError, KeyError) as exc:
                self.fail(HTTPStatus.BAD_REQUEST, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            url = urllib.parse.urlsplit(self.path)
            if self.authorized() is None:
                self.fail(HTTPStatus.UNAUTHORIZED, "Нужен вход")
                return
            parts = [p for p in url.path.split("/") if p][1:]  # без «api»
            try:
                if parts == ["message"]:
                    text = str(self.body_json().get("text") or "").strip()
                    if not text:
                        raise ArvixError("Пустое сообщение")
                    app.hub.post(api.chat(text[:16000]), label="думаю")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["voice"]:
                    audio = self.body_bytes()
                    if not audio:
                        raise ArvixError("Пустая запись")
                    kind = (self.headers.get("Content-Type") or "audio/webm").split(";")[0]
                    ext = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(kind, "webm")
                    app.hub.post(api.voice(audio, f"voice.{ext}"), label="слушаю")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["button"]:
                    data = str(self.body_json().get("data") or "")
                    app.hub.post(api.button(data), label="думаю")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["tasks"]:
                    self.send_json(app.hub.call(api.add_task(self.body_json())))
                elif len(parts) == 3 and parts[0] == "tasks":
                    self.send_json(app.hub.call(api.task_op(parts[1], parts[2], self.body_json())))
                elif len(parts) == 2 and parts[0] == "lesson":
                    app.hub.post(api.lesson(parts[1]), label="готовлю урок")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["focus"]:
                    body = self.body_json()
                    self.send_json(app.hub.call(api.focus_start(int(body.get("minutes") or 25), body.get("task"))))
                elif parts == ["focus", "stop"]:
                    self.send_json(app.hub.call(api.focus_stop()))
                elif parts == ["capture"]:
                    text = str(self.body_json().get("text") or "").strip()
                    if not text:
                        raise ArvixError("Пустая мысль")
                    self.send_json(app.hub.call(api.capture(text)))
                else:
                    self.fail(HTTPStatus.NOT_FOUND, "Нет такого адреса")
            except TimeoutError as exc:
                self.fail(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            except (ArvixError, ValueError, KeyError, TypeError) as exc:
                self.fail(HTTPStatus.BAD_REQUEST, str(exc))

        # --- разное --------------------------------------------------------------------

        def notes_dir(self, rel: str) -> dict[str, Any]:
            vault = app.vault()
            folder = vault.root if not rel else vault.resolve(rel)
            if not folder.is_dir():
                raise ArvixError(f"Нет такой папки: {rel}")
            dirs, files = [], []
            for item in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                if item.name.startswith(".") or item.name in ("node_modules", "Cache"):
                    continue
                if item.is_dir():
                    dirs.append({"name": item.name, "path": vault.rel(item)})
                elif item.suffix.lower() == ".md":
                    files.append({"name": item.stem, "path": vault.rel(item), "modified": int(item.stat().st_mtime)})
            return {"dir": rel, "dirs": dirs, "files": files}

        def stream(self) -> None:
            """Живое обновление: строка JSON при каждом изменении, пинг раз в 15 с.
            Не EventSource, а fetch-поток: так ключ идёт в заголовке, а не в URL."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last, pinged = "", time.monotonic()
            try:
                while True:
                    current = app.version()
                    if current != last:
                        last = current
                        self.wfile.write(f"data: {json.dumps({'v': current, 'thinking': app.hub.busy}, ensure_ascii=False)}\n\n".encode())
                        self.wfile.flush()
                        pinged = time.monotonic()
                    elif time.monotonic() - pinged > STREAM_PING:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        pinged = time.monotonic()
                    time.sleep(STREAM_EVERY)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def static(self, path: str) -> None:
            name = path.lstrip("/") or "index.html"
            target = (STATIC / name).resolve()
            if not target.is_relative_to(STATIC) or not target.is_file():
                target = STATIC / "index.html"  # одностраничное приложение
            body = target.read_bytes()
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".webmanifest":
                kind = "application/manifest+json"
            self.send_response(200)
            self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith(("text/", "application/javascript", "application/manifest")) else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            if target.name == "sw.js":
                self.send_header("Service-Worker-Allowed", "/")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_web(cfg: Config, hub: Hub) -> Server | None:
    """Поднять API в фоновом потоке. Ошибка (порт занят) не роняет бота."""
    section = cfg.section("web")
    if not section.get("enabled", True):
        return None
    port = int(section.get("port") or 8787)
    try:
        app = WebApp(cfg, hub)
        server = Server(("127.0.0.1", port), make_handler(app))
    except OSError as exc:
        log.warning("приложение не запущено (порт %s): %s", port, exc)
        return None
    threading.Thread(target=server.serve_forever, name="web", daemon=True).start()
    log.info("приложение: http://127.0.0.1:%s%s", port, f" · снаружи {section.get('public_url')}" if section.get("public_url") else "")
    return server
