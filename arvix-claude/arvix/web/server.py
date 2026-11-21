"""HTTP-сервер приложения на stdlib (05-INTERFACES §7).

Слушает только 127.0.0.1: наружу его выставляет Caddy с HTTPS (deploy/web-setup.sh),
к терминалу на ноутбуке — SSH-туннель (arvix/tui.py). Без зависимостей и без сборки фронта.

GET  /                        приложение (static/)
GET  /api/state               экран «Сегодня»
GET  /api/messages?before=id  переписка из журнала
GET  /api/history?days=30     прогресс, цели, неделя
GET  /api/notes?dir=…         папка хранилища · /api/note?path=… — заметка · /api/notes/search?q=…
GET  /api/file?path=…         вложение заметки (картинка, PDF) — для ![[…]]
GET  /api/graph               граф заметок: узлы, связи, призраки, одинокие, подсказки «связать»
GET  /api/stream              поток событий: строка {"v": …} при любом изменении (fetch + ReadableStream)
GET  /api/pair                одноразовая ссылка установки на телефон (только из Mini App)
GET  /api/pair/claim?code=…   без входа: одноразовый код → ключ приложения (15 мин, один раз)
POST /api/message {text} · /api/voice (аудио) · /api/button {data}
POST /api/tts {text}          озвучка ответа (ogg), если [tts] включена; иначе 404 — говорит голос телефона
POST /api/upload              файл телом запроса (X-File-Name, X-Caption — urlencoded), до 20 МБ
POST /api/tasks {…} · /api/tasks/<id>/<op> · /api/tasks/<id>/photo (фото отчёта телом, X-File-Name) · /api/lesson/<id>
    · /api/study/open {task | item} · /api/study/learn · /api/study/<task>/<answer|stage|fix|panel|hide|message|check|upload|voice>
    · /api/study/review · /api/study/review/<answer|drop> (D55–D60); GET /api/study?task=
    · /api/study/<task>/<transcript|mine|pick|video|shadow> — язык через видео (D61); GET /api/define?word=
POST /api/focus {minutes, task | topic} · /api/focus/<pause|resume|stop|cancel> · /api/focus/note {event, note}
POST /api/capture {text}      мысль в Inbox
POST /api/note {path, text, sha} · /api/note/new {dir, name} · /api/note/toggle {path, line, sha} · /api/note/link {a, b}
                              правка заметки человеком; файл изменился после открытия — 409 и текущий текст
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
from arvix.core import ArvixError, Core, NoteConflict
from arvix.store import Store
from arvix.web import api
from arvix.web.auth import app_token, authorize
from arvix.web.hub import Hub

log = logging.getLogger("arvix.web")
STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 25 * 1024 * 1024  # голосовое до ~25 МБ
STREAM_EVERY = 1.0
STREAM_PING = 15.0


def reply_id(value: object) -> int | None:
    """id сообщения, на которое ответ (D52): из JSON или заголовка X-Reply-To; мусор — без ответа."""
    text = str(value if value is not None else "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


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
            """Тело читается один раз и всегда: непрочитанные байты остались бы в keep-alive
            соединении и испортили бы следующий запрос («{}GET /api/state» → 501)."""
            if not hasattr(self, "_body"):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self.close_connection = True
                    raise ArvixError("Слишком большой запрос")
                self._body = self.rfile.read(length) if length else b""
            return self._body

        def authorized(self) -> str | None:
            return authorize(self.headers, token=app.token, bot_token=app.bot_token, owner_id=app.owner_id)

        # --- маршруты ------------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 — имя задаёт http.server
            self.__dict__.pop("_body", None)  # обработчик живёт всё keep-alive соединение — тело у каждого запроса своё
            url = urllib.parse.urlsplit(self.path)
            if not url.path.startswith("/api/"):
                self.static(url.path)
                return
            if url.path == "/api/pair/claim":  # без входа: сам код и есть одноразовый пропуск
                code = dict(urllib.parse.parse_qsl(url.query)).get("code") or ""
                try:
                    token = app.hub.call(api.claim_pair(code), timeout=10)
                except TimeoutError as exc:
                    self.fail(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
                    return
                if token:
                    self.send_json({"token": token})
                else:
                    self.fail(HTTPStatus.FORBIDDEN, "Ссылка устарела или уже открыта. Попроси Arvix прислать новую.")
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
                elif url.path == "/api/projects":
                    self.send_json(app.read(api.projects_view))
                elif url.path == "/api/project":
                    self.send_json(app.read(lambda c: api.project_view(c, query.get("id") or "")))
                elif url.path == "/api/study":
                    self.send_json(app.read(lambda c: api.study_view(c, query.get("task") or None)))
                elif url.path == "/api/define":  # словарь (D61): сеть — в потоке HTTP, очередь не держим
                    from arvix import media

                    self.send_json({"entry": media.define(query.get("word") or "")})
                elif url.path == "/api/notes":
                    self.send_json(self.notes_dir(query.get("dir") or ""))
                elif url.path == "/api/note":
                    app.vault()
                    self.send_json(app.read(lambda c: api.note_view(c, query.get("path") or "")))
                elif url.path == "/api/file":
                    self.send_asset(app.vault().asset(query.get("path") or ""))
                elif url.path == "/api/graph":
                    from arvix import graph

                    self.send_json(graph.build(app.vault()))
                elif url.path == "/api/notes/search":
                    self.send_json({"results": app.vault().search(query.get("q") or "", 20)})
                elif url.path == "/api/stream":
                    self.stream()
                elif url.path == "/api/pair":
                    if who != "telegram":
                        self.fail(HTTPStatus.FORBIDDEN, "Ключ выдаётся только внутри Telegram")
                        return
                    self.send_json(app.hub.call(api.pair_link()))
                else:
                    self.fail(HTTPStatus.NOT_FOUND, "Нет такого адреса")
            except (ArvixError, ValueError, KeyError) as exc:
                self.fail(HTTPStatus.BAD_REQUEST, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            # Один обработчик отвечает на все запросы keep-alive соединения: тело прошлого POST
            # нельзя переиспользовать — иначе второй POST получит чужое тело, а своё останется в сокете (501).
            self.__dict__.pop("_body", None)
            url = urllib.parse.urlsplit(self.path)
            try:
                self.body_bytes()
            except ArvixError as exc:
                self.fail(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(exc))
                return
            if url.path == "/share":  # «Поделиться» до установки service worker: файлы не дошли, ведём в чат
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/?tab=chat")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.authorized() is None:
                self.fail(HTTPStatus.UNAUTHORIZED, "Нужен вход")
                return
            parts = [p for p in url.path.split("/") if p][1:]  # без «api»
            try:
                if parts == ["message"]:
                    body = self.body_json()
                    text = str(body.get("text") or "").strip()
                    if not text:
                        raise ArvixError("Пустое сообщение")
                    app.hub.post(api.chat(text[:16000], reply_to=reply_id(body.get("reply_to"))), label="думаю", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["voice"]:
                    audio = self.body_bytes()
                    if not audio:
                        raise ArvixError("Пустая запись")
                    kind = (self.headers.get("Content-Type") or "audio/webm").split(";")[0]
                    ext = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(kind, "webm")
                    app.hub.post(api.voice(audio, f"voice.{ext}", reply_to=reply_id(self.headers.get("X-Reply-To"))),
                                 label="слушаю", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["upload"]:
                    data = self.body_bytes()
                    if not data:
                        raise ArvixError("Пустой файл")
                    name = urllib.parse.unquote(self.headers.get("X-File-Name") or "файл")
                    caption = urllib.parse.unquote(self.headers.get("X-Caption") or "").strip()[:4000]
                    kind = (self.headers.get("Content-Type") or "").split(";")[0]
                    app.hub.post(api.upload(data, name, kind, caption, reply_to=reply_id(self.headers.get("X-Reply-To"))),
                                 label="смотрю файл", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["react"]:
                    body = self.body_json()
                    message, emoji = reply_id(body.get("message")), str(body.get("emoji") or "")
                    if not message:
                        raise ArvixError("Нет сообщения")
                    job = api.react(message, emoji)  # неизвестная реакция — 400 сразу, не в очереди
                    app.hub.post(job, label="думаю" if Core.reaction_key(emoji) in Core.CONFUSED else "")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["seen"]:
                    app.hub.post(api.seen(reply_id(self.body_json().get("upto"))))
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["button"]:
                    data = str(self.body_json().get("data") or "")
                    app.hub.post(api.button(data), label="думаю")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["tasks"]:
                    self.send_json(app.hub.call(api.add_task(self.body_json())))
                elif len(parts) == 3 and parts[0] == "tasks" and parts[2] == "photo":
                    data = self.body_bytes()
                    if not data:
                        raise ArvixError("Пустой файл")
                    name = urllib.parse.unquote(self.headers.get("X-File-Name") or "фото.jpg")
                    kind = (self.headers.get("Content-Type") or "").split(";")[0]
                    self.send_json(app.hub.call(api.task_photo(parts[1], data, name, kind)))
                elif len(parts) == 3 and parts[0] == "tasks":
                    self.send_json(app.hub.call(api.task_op(parts[1], parts[2], self.body_json())))
                elif len(parts) == 2 and parts[0] == "lesson":
                    app.hub.post(api.lesson(parts[1]), label="готовлю урок")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["projects", "new"]:
                    body = self.body_json()
                    text = str(body.get("text") or "").strip()[:4000]
                    created = app.hub.call(api.project_new(text, body.get("goal") or None))
                    # Карточка есть сразу; заполняет её Arvix в чате проекта — фоном, ответ придёт потоком
                    app.hub.post(api.project_chat(created["project"]["id"], text, kickoff=True), label="думаю")
                    self.send_json(created)
                elif len(parts) == 3 and parts[0] == "projects" and parts[2] == "chat":
                    text = str(self.body_json().get("text") or "").strip()
                    if not text:
                        raise ArvixError("Пустое сообщение")
                    app.hub.post(api.project_chat(parts[1], text[:16000]), label="думаю", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif len(parts) == 3 and parts[0] == "projects" and parts[2] == "upload":
                    data = self.body_bytes()
                    if not data:
                        raise ArvixError("Пустой файл")
                    name = urllib.parse.unquote(self.headers.get("X-File-Name") or "файл")
                    caption = urllib.parse.unquote(self.headers.get("X-Caption") or "").strip()[:4000]
                    kind = (self.headers.get("Content-Type") or "").split(";")[0]
                    app.hub.post(api.project_upload(parts[1], data, name, kind, caption), label="смотрю файл")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif parts == ["projects", "roadmap"]:
                    goal = str(self.body_json().get("goal") or "")
                    app.hub.post(api.project_roadmap(goal), label="строю роадмап")
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif len(parts) == 3 and parts[0] == "projects":
                    self.send_json(app.hub.call(api.project_op(parts[1], parts[2], self.body_json())))
                elif parts == ["study", "open"]:
                    body = self.body_json()
                    opened = app.hub.call(api.study_open(body.get("task") or None, body.get("item") or None,
                                                         max(15, min(int(body.get("minutes") or 45), 180))))
                    if opened.get("queued"):  # план с окнами готовит голова — фоном, рабочий стол обновится потоком
                        app.hub.post(api.study_prepare(opened["task_id"]), label="готовлю урок")
                    self.send_json(opened)
                elif parts == ["study", "learn"]:
                    self.send_json(app.hub.call(api.study_learn(self.body_json())))
                elif parts == ["study", "review"]:  # повторение тем (D60): голова собирает задачи, ждём здесь же
                    self.send_json(app.hub.call(api.review_start(), timeout=200, label="собираю повторение"))
                elif len(parts) == 3 and parts[:2] == ["study", "review"]:
                    self.send_json(app.hub.call(api.review_op(parts[2], self.body_json())))
                elif len(parts) == 3 and parts[0] == "study" and parts[2] == "check":
                    self.send_json(app.hub.call(api.study_check(parts[1]), timeout=60))
                elif len(parts) == 3 and parts[0] == "study" and parts[2] == "upload":
                    data = self.body_bytes()
                    if not data:
                        raise ArvixError("Пустой файл")
                    name = urllib.parse.unquote(self.headers.get("X-File-Name") or "файл")
                    caption = urllib.parse.unquote(self.headers.get("X-Caption") or "").strip()[:4000]
                    kind = (self.headers.get("Content-Type") or "").split(";")[0]
                    app.hub.post(api.study_upload(parts[1], data, name, kind, caption), label="смотрю файл", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif len(parts) == 3 and parts[0] == "study" and parts[2] in ("transcript", "mine", "pick"):
                    self.send_json(app.hub.call(api.study_media_op(parts[1], parts[2], self.body_json()), timeout=150))
                elif len(parts) == 3 and parts[0] == "study" and parts[2] == "shadow":
                    # Shadowing (D61): распознавание — здесь, в потоке HTTP; в очередь — только сверка и событие
                    from arvix.stt import STT, STTError

                    audio = self.body_bytes()
                    if not audio:
                        raise ArvixError("Пустая запись")
                    kind = (self.headers.get("Content-Type") or "audio/webm").split(";")[0]
                    ext = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(kind, "webm")
                    stt = STT(app.cfg)
                    if not stt.enabled:
                        raise ArvixError("Распознавание речи не настроено — shadowing без него не проверить")
                    try:
                        heard = stt.transcribe(audio, filename=f"voice.{ext}", browser=True, language=self.headers.get("X-Lang") or "en")
                    except STTError as exc:
                        raise ArvixError(f"Не распознал: {exc}") from exc
                    body = {"panel": self.headers.get("X-Panel") or "", "i": int(self.headers.get("X-Line") or -1), "heard": heard}
                    self.send_json(app.hub.call(api.study_media_op(parts[1], "shadow", body), timeout=150))
                elif len(parts) == 3 and parts[0] == "study" and parts[2] == "video":
                    # Своё видео на стол (D61): поиск роликов — здесь, в потоке HTTP; ссылка — как есть
                    from arvix import videos

                    body = self.body_json()
                    q, link = str(body.get("query") or "").strip()[:160], str(body.get("url") or "").strip()[:400]
                    lang = body.get("lang") if body.get("lang") in ("en", "de", "fr", "es") else None
                    stage = body.get("stage") if body.get("stage") in ("diag", "learn", "practice", "fix", "check") else "learn"
                    raw: dict[str, Any] = {"stage": stage, "title": "Видео" if link else f"Видео: {q}"[:80], **({"lang": lang} if lang else {})}
                    if link:
                        raw["url"] = link
                    elif q:
                        raw.update(query=q, results=videos.search(q, limit=5, lang="en" if lang == "en" else "ru"))
                    else:
                        raise ArvixError("Нужен запрос или ссылка")
                    self.send_json(app.hub.call(api.study_media_op(parts[1], "video", {"panel": raw}), timeout=150))
                elif len(parts) == 3 and parts[0] == "study" and parts[2] == "voice":
                    audio = self.body_bytes()
                    if not audio:
                        raise ArvixError("Пустая запись")
                    kind = (self.headers.get("Content-Type") or "audio/webm").split(";")[0]
                    ext = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(kind, "webm")
                    app.hub.post(api.study_voice(parts[1], audio, f"voice.{ext}"), label="слушаю", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif len(parts) == 3 and parts[0] == "study" and parts[2] == "message":
                    text = str(self.body_json().get("text") or "").strip()
                    if not text:
                        raise ArvixError("Пустое сообщение")
                    app.hub.post(api.study_chat(parts[1], text[:16000]), label="думаю", chat=True)
                    self.send_json({"queued": True}, HTTPStatus.ACCEPTED)
                elif len(parts) == 3 and parts[0] == "study":
                    # Ответ на задачу ждёт, пока Arvix договорит в чате (голова держит очередь до полминуты),
                    # а не падает «Arvix занят»: проверка — код, она быстрая, когда до неё дошла очередь
                    self.send_json(app.hub.call(api.study_op(parts[1], parts[2], self.body_json()), timeout=150))
                elif parts == ["focus"]:
                    body = self.body_json()
                    self.send_json(app.hub.call(api.focus_start(int(body.get("minutes") or 25), body.get("task"), body.get("topic"))))
                elif parts == ["focus", "note"]:
                    body = self.body_json()
                    self.send_json(app.hub.call(api.focus_note(int(body.get("event")), str(body.get("note") or ""))))
                elif len(parts) == 2 and parts[0] == "focus":
                    self.send_json(app.hub.call(api.focus_op(parts[1])))
                elif parts == ["capture"]:
                    text = str(self.body_json().get("text") or "").strip()
                    if not text:
                        raise ArvixError("Пустая мысль")
                    self.send_json(app.hub.call(api.capture(text)))
                elif parts[:1] == ["note"]:
                    app.vault()
                    body = self.body_json()
                    if parts == ["note"]:
                        text = body.get("text")
                        if not isinstance(text, str) or len(text.encode()) > 2_000_000:
                            raise ArvixError("Нет текста заметки")
                        self.send_json(app.hub.call(api.note_save(str(body.get("path") or ""), text, body.get("sha") or None)))
                    elif parts == ["note", "new"]:
                        self.send_json(app.hub.call(api.note_create(str(body.get("dir") or ""), str(body.get("name") or ""))))
                    elif parts == ["note", "link"]:
                        self.send_json(app.hub.call(api.graph_link(str(body.get("a") or ""), str(body.get("b") or ""))))
                    elif parts == ["note", "toggle"]:
                        self.send_json(app.hub.call(api.note_toggle(str(body.get("path") or ""), int(body.get("line")), str(body.get("sha") or ""))))
                    else:
                        self.fail(HTTPStatus.NOT_FOUND, "Нет такого адреса")
                else:
                    self.fail(HTTPStatus.NOT_FOUND, "Нет такого адреса")
            except NoteConflict as exc:
                from arvix.vault import sha

                self.send_json({"error": str(exc), "conflict": True, "path": exc.path, "text": exc.current, "sha": sha(exc.current)},
                               HTTPStatus.CONFLICT)
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

        def send_asset(self, path: Path) -> None:
            from arvix.vault import ASSET_TYPES

            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ASSET_TYPES.get(path.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "sandbox")  # SVG из заметки не выполнит скрипт
            self.end_headers()
            self.wfile.write(body)

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
