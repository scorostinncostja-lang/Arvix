"""Погода по городу человека — кодом через Open-Meteo, без ключа и без модели.

Голова не ходит в интернет за погодой: код видит в сообщении слово про погоду, берёт
город из профиля (profile_set city), спрашивает Open-Meteo и кладёт короткую сводку
в промпт. Наружу уходит только название города и его координаты. Ответ кэшируется на 30 минут.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("arvix.weather")
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE = "weather_cache"
TTL = 30 * 60
ASKS = re.compile(r"погод|прогноз|градус|холодн|тепло|жарк|дожд|снег|ветр|зонт|одеться|оденься|куртк|мороз|гололёд|гололед",
                  re.IGNORECASE)
CODES = {
    0: "ясно", 1: "почти ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "туман с инеем",
    51: "морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
    80: "ливень", 81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "гроза с градом",
}


def asks_weather(text: str) -> bool:
    return bool(ASKS.search(text or ""))


def _get(url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "arvix"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def locate(city: str, timeout: float = 5) -> dict[str, Any] | None:
    data = _get(GEO_URL, {"name": city, "count": 1, "language": "ru", "format": "json"}, timeout)
    found = (data.get("results") or [None])[0]
    if not found:
        return None
    return {"name": found.get("name") or city, "lat": found["latitude"], "lon": found["longitude"]}


def forecast(lat: float, lon: float, timeout: float = 5) -> dict[str, Any]:
    return _get(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2, "wind_speed_unit": "ms",
        "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
    }, timeout)


def summary(place: str, data: dict[str, Any]) -> str:
    """«Санкт-Петербург сейчас −3°, ощущается −8°, пасмурно, ветер 5 м/с. Сегодня −5…−1°, осадки 70%. Завтра …»"""
    now = data.get("current") or {}
    daily = data.get("daily") or {}
    parts = [f"{place} сейчас {_deg(now.get('temperature_2m'))}"]
    if now.get("apparent_temperature") is not None:
        parts[0] += f", ощущается {_deg(now['apparent_temperature'])}"
    parts[0] += f", {CODES.get(int(now.get('weather_code') or 0), 'без осадков')}"
    if now.get("wind_speed_10m") is not None:
        parts[0] += f", ветер {round(now['wind_speed_10m'])} м/с"
    for i, label in enumerate(("Сегодня", "Завтра")):
        try:
            low, high = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
        except (KeyError, IndexError):
            continue
        rain = (daily.get("precipitation_probability_max") or [None, None])[i]
        code = CODES.get(int((daily.get("weather_code") or [0, 0])[i] or 0), "")
        parts.append(f"{label} {_deg(low)}…{_deg(high)}, {code}" + (f", осадки {rain}%" if rain is not None else ""))
    return ". ".join(parts) + "."


def _deg(value: Any) -> str:
    if value is None:
        return "?"
    number = round(float(value))
    return f"{'−' if number < 0 else ''}{abs(number)}°"


def weather_block(core: Any, *, timeout: float = 5) -> str:
    """Блок для промпта. Город неизвестен — просьба спросить его и записать в профиль."""
    city = (core.state.profile.get("city") or core.cfg.section("weather").get("city") or "").strip()
    if not city:
        return ("<weather>Город человека неизвестен — погоду не узнать. Спроси город одной фразой и запиши "
                "action profile_set key=city value=<город>.</weather>")
    cached = core.store.kv_get(CACHE) or {}
    if cached.get("city") == city and time.time() - float(cached.get("at") or 0) < TTL:
        return cached["block"]
    try:
        place = cached.get("place") if cached.get("city") == city else None
        place = place or locate(city, timeout)
        if not place:
            return f"<weather>Город «{city}» не нашёлся в справочнике погоды. Скажи об этом и уточни город.</weather>"
        text = summary(place["name"], forecast(place["lat"], place["lon"], timeout))
    except (OSError, ValueError, KeyError) as exc:
        log.warning("погода недоступна: %s", exc)
        return "<weather>Сервис погоды сейчас не ответил. Скажи честно, что не смог узнать.</weather>"
    block = (f"<weather>{text}\nОтветь коротко: температура, осадки, что надеть или взять. "
             "Без лекций о климате. Источник — Open-Meteo, называть не обязательно.</weather>")
    core.store.kv_set(CACHE, {"city": city, "place": place, "at": time.time(), "block": block})
    return block
