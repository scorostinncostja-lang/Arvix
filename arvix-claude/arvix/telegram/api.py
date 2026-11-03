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


class TelegramAPI:
    def __init__(self, token: str, http_timeout: int = 40):
        self.base = f"https://api.telegram.org/bot{token}/"
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

    def send(self, chat_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> None:
        chunks = split_text(text) or ["…"]
        for i, chunk in enumerate(chunks):
            params: dict[str, Any] = {"chat_id": chat_id, "text": chunk, "link_preview_options": {"is_disabled": True}}
            if buttons and i == len(chunks) - 1:
                params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
            self.call("sendMessage", **params)

    def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        params: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        self.call("answerCallbackQuery", **params)

    def drop_buttons(self, chat_id: int, message_id: int) -> None:
        self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []})

    def typing(self, chat_id: int) -> None:
        self.call("sendChatAction", chat_id=chat_id, action="typing")
