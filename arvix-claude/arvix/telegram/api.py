"""Telegram Bot API через urllib — без зависимостей.

Long polling: бот сам опрашивает Telegram, поэтому ни сервер, ни публичный адрес,
ни вебхук не нужны — достаточно ноутбука с интернетом.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

LIMIT = 4000
Buttons = list[list[tuple[str, str]]]


class TelegramError(RuntimeError):
    pass


def split_text(text: str, limit: int = LIMIT) -> list[str]:
    chunks, rest = [], text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return chunks + [rest] if rest else chunks


def inline_button(text: str, data: str) -> dict[str, Any]:
    """«app:https://…» — кнопка, открывающая Mini App; «url:https://…» — ссылка; иначе callback."""
    if data.startswith("app:"):
        return {"text": text, "web_app": {"url": data[4:]}}
    if data.startswith("url:"):
        return {"text": text, "url": data[4:]}
    return {"text": text, "callback_data": data}


def inline_markup(buttons: Buttons) -> dict[str, Any]:
    return {"inline_keyboard": [[inline_button(t, d) for t, d in row] for row in buttons]}


def reply_markup(keyboard: list[list[str]], app_url: str = "") -> dict[str, Any]:
    """Постоянная клавиатура под полем ввода: кнопки шлют свой текст как сообщение.
    Кнопка «📱 …» при заданном app_url открывает приложение внутри Telegram."""
    rows = []
    for row in keyboard:
        rows.append([{"text": t, "web_app": {"url": app_url}} if app_url and t.startswith("📱") else {"text": t} for t in row])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


class TelegramAPI:
    app_url = ""  # публичный адрес Mini App ([web] public_url); пусто — кнопки приложения нет

    def __init__(self, token: str, http_timeout: int = 40):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.file_base = f"https://api.telegram.org/file/bot{token}/"
        self.http_timeout = http_timeout

    def call(self, method: str, _http_timeout: int | None = None, **params: Any) -> Any:
        request = urllib.request.Request(
            self.base + method,
            data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=_http_timeout or self.http_timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read() or b"{}")
            except ValueError:
                raise TelegramError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise TelegramError(f"сеть: {exc}") from exc
        if not body.get("ok"):
            raise TelegramError(str(body.get("description") or body))
        return body["result"]

    def get_updates(self, offset: int, timeout: int = 25) -> list[dict[str, Any]]:
        return self.call("getUpdates", _http_timeout=timeout + 15, offset=offset, timeout=timeout,
                         allowed_updates=["message", "callback_query"])

    def send(self, chat_id: int, text: str, buttons: Buttons | None = None, keyboard: list[list[str]] | None = None,
             *, html: str | None = None) -> int | None:
        """Отправка; возвращает message_id последнего куска (им потом можно править панель).
        У сообщения одна разметка: либо inline-кнопки под текстом, либо постоянная клавиатура.
        html — тот же текст в разметке Telegram (fmt.render); не принят — уходит text как есть."""
        if html is not None and len(html) <= LIMIT:
            try:
                return self._send_one(chat_id, html, buttons, keyboard, parse_mode="HTML")
            except TelegramError as exc:
                if "parse" not in str(exc).lower() and "entit" not in str(exc).lower():
                    raise
        chunks = split_text(text) or ["…"]
        message_id = None
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            message_id = self._send_one(chat_id, chunk, buttons if last else None, keyboard if last else None)
        return message_id

    def _send_one(self, chat_id: int, text: str, buttons: Buttons | None, keyboard: list[list[str]] | None,
                  parse_mode: str | None = None) -> int | None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if buttons:
            params["reply_markup"] = inline_markup(buttons)
        elif keyboard:
            params["reply_markup"] = reply_markup(keyboard, self.app_url)
        result = self.call("sendMessage", **params)
        return (result or {}).get("message_id")

    def edit(self, chat_id: int, message_id: int, text: str, buttons: Buttons | None = None) -> None:
        """Правка сообщения на месте — так живёт панель дня и обратный отсчёт фокуса."""
        params: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": split_text(text)[0],
                                  "link_preview_options": {"is_disabled": True}}
        params["reply_markup"] = inline_markup(buttons) if buttons else {"inline_keyboard": []}
        self.call("editMessageText", **params)

    def pin(self, chat_id: int, message_id: int) -> None:
        self.call("pinChatMessage", chat_id=chat_id, message_id=message_id, disable_notification=True)

    def unpin(self, chat_id: int, message_id: int) -> None:
        self.call("unpinChatMessage", chat_id=chat_id, message_id=message_id)

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        """Меню команд в клиенте Telegram (кнопка «/» слева от поля ввода). Пустой список —
        меню убирается: с Арвиксом говорят словами (D23)."""
        if not commands:
            self.call("deleteMyCommands")
            return
        self.call("setMyCommands", commands=[{"command": c, "description": d[:256]} for c, d in commands])

    def set_menu_button(self, url: str, text: str = "Арвикс") -> None:
        """Кнопка слева от поля ввода: с url — открывает Mini App, без — стандартная."""
        button = {"type": "web_app", "text": text, "web_app": {"url": url}} if url else {"type": "default"}
        self.call("setChatMenuButton", menu_button=button)

    def download(self, file_id: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        """Файл из Telegram (голосовое, фото): getFile → загрузка. Боту доступны файлы до 20 МБ."""
        info = self.call("getFile", file_id=file_id)
        try:
            with urllib.request.urlopen(self.file_base + info["file_path"], timeout=self.http_timeout) as response:
                data = response.read(max_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError, KeyError) as exc:
            raise TelegramError(f"файл не скачался: {exc}") from exc
        if len(data) > max_bytes:
            raise TelegramError("файл больше 20 МБ")
        return data

    def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        params: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        self.call("answerCallbackQuery", **params)

    def drop_buttons(self, chat_id: int, message_id: int) -> None:
        self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []})

    def typing(self, chat_id: int) -> None:
        self.call("sendChatAction", chat_id=chat_id, action="typing")
