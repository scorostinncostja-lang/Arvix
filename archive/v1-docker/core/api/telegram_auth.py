"""Валидация Telegram WebApp initData — алгоритм из официальной документации
(https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

Минимально, только для эндпоинта онбординга (шаг 0.3). Шаг 0.6 обобщит это
в core/api/auth.py как FastAPI-зависимость для всех /api-роутов и WebSocket."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AUTH_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str, *, max_age: int = MAX_AUTH_AGE_SECONDS) -> dict:
    """Возвращает распарсенные поля initData (включая `user` как dict) при валидной
    подписи. Бросает InitDataError, если подпись неверна, просрочена или отсутствует."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("no hash in init data")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InitDataError("signature mismatch")

    auth_date = int(pairs.get("auth_date", 0))
    if max_age and time.time() - auth_date > max_age:
        raise InitDataError("stale init data")

    result: dict = dict(pairs)
    if "user" in result:
        result["user"] = json.loads(result["user"])
    return result
