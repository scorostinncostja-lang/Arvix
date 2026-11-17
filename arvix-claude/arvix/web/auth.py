"""Вход в приложение (05-INTERFACES §7.3). Пользователь один — owner_id, регистрации нет.

1. Mini App в Telegram: заголовок X-Telegram-Init-Data — подпись Telegram, проверяется
   ключом бота (HMAC-SHA256 по документации Bot API). Подделать без токена бота нельзя.
2. PWA на телефоне и `arvix` в терминале: ключ приложения (Authorization: Bearer …).
   Ключ живёт в runtime-таблице базы (генерируется один раз) или в [web] token конфига.
   В URL ключ не попадает никогда — только в заголовке или во фрагменте «#t=» при первой
   привязке (фрагмент браузер на сервер не отправляет).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from typing import Any

TOKEN_KEY = "web_token"
INIT_MAX_AGE = 7 * 24 * 3600  # Mini App живёт долго: неделя, потом Telegram выдаст свежую подпись


def app_token(core: Any) -> str:
    """Ключ приложения: из конфига или из базы; нет — создаётся."""
    configured = str(core.cfg.section("web").get("token") or "").strip()
    if configured:
        return configured
    token = core.store.kv_get(TOKEN_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        core.store.kv_set(TOKEN_KEY, token)
    return str(token)


def check_init_data(init_data: str, bot_token: str, owner_id: int, now: float | None = None) -> bool:
    """Подпись Mini App: secret = HMAC("WebAppData", bot_token); hash = HMAC(secret, строки k=v по алфавиту)."""
    if not init_data or not bot_token:
        return False
    pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    if not received:
        return False
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return False
    try:
        auth_date = int(pairs.get("auth_date") or 0)
        user = json.loads(pairs.get("user") or "{}")
    except ValueError:
        return False
    if (now or time.time()) - auth_date > INIT_MAX_AGE:
        return False
    return int(user.get("id") or 0) == int(owner_id)


def sign_init_data(fields: dict[str, Any], bot_token: str) -> str:
    """Для тестов: собрать initData так, как это делает Telegram."""
    pairs = {k: (json.dumps(v, separators=(",", ":")) if isinstance(v, dict) else str(v)) for k, v in fields.items()}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(pairs)


def authorize(headers: Any, *, token: str, bot_token: str, owner_id: int) -> str | None:
    """'telegram' | 'token' | None. headers — что угодно с .get()."""
    init_data = headers.get("X-Telegram-Init-Data") or ""
    if init_data and check_init_data(init_data, bot_token, owner_id):
        return "telegram"
    bearer = headers.get("Authorization") or ""
    if bearer.startswith("Bearer ") and token and hmac.compare_digest(bearer[7:].strip(), token):
        return "token"
    return None
