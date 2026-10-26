"""verify_init_data — чистая функция, БД не нужна. Строим initData так же, как
это делает клиент Telegram (по документации), затем проверяем нашей же функцией
плюс негативные сценарии (подмена подписи, отсутствие hash)."""

import hashlib
import hmac
import json
import time

import pytest

from core.api.telegram_auth import InitDataError, verify_init_data

BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"  # тестовый токен, не настоящий


def _build_init_data(bot_token: str, user_id: int, auth_date: int | None = None) -> str:
    auth_date = auth_date if auth_date is not None else int(time.time())
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": user_id, "first_name": "Aktan"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = signature
    return "&".join(f"{k}={v}" for k, v in fields.items())


def test_valid_signature_is_accepted():
    init_data = _build_init_data(BOT_TOKEN, user_id=42)

    result = verify_init_data(init_data, BOT_TOKEN)

    assert result["user"]["id"] == 42


def test_tampered_field_is_rejected():
    init_data = _build_init_data(BOT_TOKEN, user_id=42).replace("Aktan", "Mallory")

    with pytest.raises(InitDataError):
        verify_init_data(init_data, BOT_TOKEN)


def test_missing_hash_is_rejected():
    with pytest.raises(InitDataError):
        verify_init_data("auth_date=123&user=%7B%7D", BOT_TOKEN)


def test_stale_init_data_is_rejected():
    old = int(time.time()) - 999_999
    init_data = _build_init_data(BOT_TOKEN, user_id=42, auth_date=old)

    with pytest.raises(InitDataError):
        verify_init_data(init_data, BOT_TOKEN)
