"""Поиск видео-объяснений кодом (06-LEARNING §10, D60).

Голова не знает настоящих адресов видео и выдумывать их не должна (§2.1), а «найди сам по запросу» —
трение, из-за которого видео не смотрят. Поэтому запрос формулирует голова (или человек), а ищет код:
открытый поиск RuTube (JSON) и страница результатов YouTube (данные ytInitialData). Ключей и счетов нет,
ответ — 1–2 секунды. Отбираются ролики-объяснения: от 2 до 75 минут, без трансляций, платного и 18+.

Сеть недоступна, площадка поменяла разметку — пустой список: окно видео покажет ссылку на поиск, урок
не ломается. Результат пишется в журнал вместе с окном: свёртка журнала сеть не трогает.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

log = logging.getLogger("arvix.videos")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
TIMEOUT = 6
MIN_SEC, MAX_SEC = 60, 75 * 60  # короче — шортс, длиннее — запись трансляции на полтора часа
CACHE_SEC = 24 * 3600


def _fetch(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ru,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 — адреса только свои, https
        return resp.read(4_000_000)


# Подмена в тестах: тесты не ходят в сеть (tests/helpers.py ставит заглушку).
FETCH: Callable[[str, str], bytes] = _fetch
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()


def _seconds(text: str) -> int:
    """«1:02:03» / «11:58» → секунды; мусор — 0."""
    parts = [p for p in str(text or "").strip().split(":") if p.isdigit()]
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


def rutube(query: str) -> list[dict[str, Any]]:
    data = json.loads(FETCH("https://rutube.ru/api/search/video/?query=" + urllib.parse.quote(query), "application/json"))
    out = []
    for r in data.get("results") or []:
        if not isinstance(r, dict) or r.get("is_adult") or r.get("is_paid") or r.get("is_livestream") or r.get("is_hidden"):
            continue
        vid = str(r.get("id") or "")
        if not re.fullmatch(r"[0-9a-f]{16,40}", vid):
            continue
        out.append({"url": f"https://rutube.ru/video/{vid}/", "embed": f"https://rutube.ru/play/embed/{vid}", "site": "rutube",
                    "title": str(r.get("title") or "")[:160], "channel": str((r.get("author") or {}).get("name") or "")[:80],
                    "sec": int(r.get("duration") or 0)})
    return out


def _renderers(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("videoRenderer"), dict):
            out.append(node["videoRenderer"])
        for value in node.values():
            _renderers(value, out)
    elif isinstance(node, list):
        for value in node:
            _renderers(value, out)


def _run_text(field: Any) -> str:
    if not isinstance(field, dict):
        return ""
    if field.get("simpleText"):
        return str(field["simpleText"])
    return "".join(str(r.get("text") or "") for r in field.get("runs") or [] if isinstance(r, dict))


def youtube(query: str, lang: str = "ru") -> list[dict[str, Any]]:
    region = "&hl=en&gl=US" if lang == "en" else "&hl=ru"
    html = FETCH("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) + region, "text/html").decode("utf-8", "replace")
    start = html.find("ytInitialData")
    brace = html.find("{", start) if start >= 0 else -1
    if brace < 0:
        return []  # страница согласия на cookies или другая разметка — тихо без YouTube
    data, _ = json.JSONDecoder().raw_decode(html, brace)
    found: list[dict[str, Any]] = []
    _renderers(data, found)
    out = []
    for v in found:
        vid = str(v.get("videoId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid):
            continue
        out.append({"url": f"https://www.youtube.com/watch?v={vid}", "embed": f"https://www.youtube-nocookie.com/embed/{vid}",
                    "site": "youtube", "title": _run_text(v.get("title"))[:160], "channel": _run_text(v.get("ownerText"))[:80],
                    "sec": _seconds(_run_text(v.get("lengthText")))})  # нет длины — трансляция или премьера: отсеется
    return out


def _safe(fn: Callable[..., list[dict[str, Any]]], query: str, box: dict[str, list[dict[str, Any]]], *args: Any) -> None:
    try:
        box[fn.__name__] = fn(query, *args)
    except Exception as exc:  # noqa: BLE001 — чужая площадка не должна ронять урок
        log.info("поиск видео %s: %s", fn.__name__, exc)
        box[fn.__name__] = []


def search(query: str, limit: int = 3, *, lang: str = "ru") -> list[dict[str, Any]]:
    """Лучшие ролики по запросу с обеих площадок вперемешку (порядок площадки = её релевантность).
    lang="en" — урок иностранного языка (D61): только YouTube на английском, RuTube там почти пуст.
    Каждый: url, embed, site, title, channel, minutes."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:160]
    if not query:
        return []
    key = f"{lang}:{query}"
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SEC:
            return [dict(x) for x in hit[1][:limit]]
    box: dict[str, list[dict[str, Any]]] = {}
    sources = [(youtube, (lang,))] + ([] if lang == "en" else [(rutube, ())])
    threads = [threading.Thread(target=_safe, args=(fn, query, box, *extra), daemon=True) for fn, extra in sources]
    for t in threads:
        t.start()
    for t in threads:
        t.join(TIMEOUT + 2)
    lists = [[x for x in box.get(name) or [] if MIN_SEC <= x["sec"] <= MAX_SEC and x["title"]] for name in ("youtube", "rutube")]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in range(max((len(x) for x in lists), default=0)):
        for items in lists:
            if i < len(items) and items[i]["title"].lower() not in seen:
                seen.add(items[i]["title"].lower())
                merged.append(items[i])
    for x in merged:
        x["minutes"] = max(1, round(x.pop("sec") / 60))
    if merged:
        with _lock:
            _cache[key] = (time.monotonic(), merged)
    return [dict(x) for x in merged[:limit]]
