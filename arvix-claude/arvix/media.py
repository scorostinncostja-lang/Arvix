"""Язык через видео (06-LEARNING §11, D61): транскрипт, диктант, shadowing, добыча предложений, словарь.

Метод владельца (03_Resources/Обучение/«Обучение английскому языку с нуля»): понятный вход i+1, транскрипция
(2 минуты речи → записать слово в слово → сверить с субтитрами), добыча — предложение целиком с пропуском (cloze),
shadowing, без перевода через русский. Здесь — то, что из этого считает код:

  transcript — строки {t, d, text}: из вставленного текста (YouTube «Показать текст видео», SRT, VTT)
               или из распознавания своего ролика (STT с отметками времени). Текст субтитров YouTube код
               сам не достаёт: YouTube закрыл его токенами, обходить защиту Arvix не будет.
  accuracy   — сверка «что услышал» с оригиналом по словам: диктант и shadowing проверяет код, не модель.
  dictation  — какие строки дать на диктант: 5–14 слов, по всему ролику.
  define     — английское толкование, транскрипция и произношение (dictionaryapi.dev, без ключа).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

log = logging.getLogger("arvix.media")

MAX_LINES = 400
LANGS = {"en": "английский", "de": "немецкий", "fr": "французский", "es": "испанский"}
# Иностранный язык — не «Русский язык» ОГЭ: у него свой урок по задачам, без роликов на английском
LANG_RE = {"en": re.compile(r"англ|english|ielts|toefl|cambridge|иностранн", re.I), "de": re.compile(r"немец|german|deutsch", re.I),
           "fr": re.compile(r"француз|french|français", re.I), "es": re.compile(r"испан|spanish|español", re.I)}
DICT_OK = 0.85  # доля слов: диктант засчитан (одна-две ошибки во фразе из 10–14 слов — уже не «верно»)


# --- транскрипт ----------------------------------------------------------------------------------------

def _clock(text: str) -> float | None:
    """«1:02:03» · «01:02,500» · «0:12» · «00:00:12.300» → секунды."""
    m = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?", text.strip())
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (int(frac.ljust(3, "0")) / 1000 if frac else 0)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)  # теги VTT: <c>, <00:00:01.000>
    text = re.sub(r"\[(?:music|applause|laughter|музыка|аплодисменты|смех)\]", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def parse_transcript(raw: str) -> list[dict[str, Any]]:
    """Текст субтитров в любом из ходовых видов → строки {t, d, text} (без времени — t = None):
    SRT и VTT («00:00:01,000 --> 00:00:03,000»), копия «Показать текст видео» с YouTube («0:12» строкой
    или «0:12 текст»), просто текст по строкам."""
    lines = [l.rstrip() for l in str(raw or "").replace("\r", "").split("\n")]
    out: list[dict[str, Any]] = []
    cue = re.compile(r"^\s*([\d:.,]+)\s*-->\s*([\d:.,]+)")
    i = 0
    timed = any(cue.match(l) for l in lines)
    while i < len(lines):
        line = lines[i].strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "Kind:", "Language:")):
            i += 1
            continue
        if timed:
            m = cue.match(line)
            if not m:
                i += 1
                continue
            start, end = _clock(m.group(1)), _clock(m.group(2))
            text, i = [], i + 1
            while i < len(lines) and lines[i].strip() and not cue.match(lines[i]):
                text.append(lines[i])
                i += 1
            if start is not None and (t := _clean(" ".join(text))):
                out.append({"t": round(start, 2), "d": round(max(0.5, (end or start + 3) - start), 2), "text": t})
            continue
        stamp = re.match(r"^(\d{1,2}(?::\d{2}){1,2})(?:\s+(.*))?$", line)
        if stamp and _clock(stamp.group(1)) is not None:
            start = _clock(stamp.group(1))
            text = stamp.group(2) or ""
            if not text:  # YouTube: время строкой, текст — следующей
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                text = lines[i].strip() if i < len(lines) else ""
            if t := _clean(text):
                out.append({"t": start, "d": None, "text": t})
            i += 1
            continue
        if not re.fullmatch(r"\d+", line) and (t := _clean(line)):  # номер реплики SRT без времени — мусор
            out.append({"t": None, "d": None, "text": t})
        i += 1
    for a, b in zip(out, out[1:]):  # длительность строки без конца — до начала следующей
        if a["t"] is not None and a["d"] is None and b["t"] is not None:
            a["d"] = round(max(0.5, min(15.0, b["t"] - a["t"])), 2)
    for x in out:
        if x["t"] is not None and x["d"] is None:
            x["d"] = 4.0
    return [x for x in out if len(x["text"]) <= 400][:MAX_LINES]


def from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сегменты распознавания (verbose_json: start, end, text) → строки транскрипта."""
    out = []
    for s in segments or []:
        try:
            start, end = float(s.get("start", 0)), float(s.get("end", 0))
        except (TypeError, ValueError):
            continue
        if text := _clean(str(s.get("text") or "")):
            out.append({"t": round(start, 2), "d": round(max(0.5, end - start), 2), "text": text})
    return out[:MAX_LINES]


def clean_transcript(raw: Any) -> list[dict[str, Any]]:
    """Транскрипт, который пришёл в событии или от головы, — только числа и короткий текст."""
    out = []
    for x in (raw or [])[:MAX_LINES]:
        if not isinstance(x, dict) or not (text := _clean(str(x.get("text") or ""))[:400]):
            continue
        try:
            t = None if x.get("t") is None else max(0.0, float(x["t"]))
            d = None if x.get("d") is None else max(0.3, min(60.0, float(x["d"])))
        except (TypeError, ValueError):
            t, d = None, None
        out.append({"t": t, "d": d, "text": text})
    return out


# --- сверка по словам: диктант и shadowing ------------------------------------------------------------

# «that's» и «that is», «gonna» и «going to» — одни и те же услышанные слова: субтитры пишут то так, то так
CONTRACTIONS = [(r"\bcan't\b", "can not"), (r"\bwon't\b", "will not"), (r"\bshan't\b", "shall not"), (r"\bcannot\b", "can not"),
                (r"n't\b", " not"), (r"'re\b", " are"), (r"'m\b", " am"), (r"'ve\b", " have"), (r"'ll\b", " will"), (r"'d\b", " would"),
                (r"'s\b", " is"), (r"\bgonna\b", "going to"), (r"\bwanna\b", "want to"), (r"\bgotta\b", "got to"),
                (r"\bokay\b", "ok"), (r"\bprogramme\b", "program")]


def words(text: str) -> list[str]:
    s = str(text or "").lower().replace("’", "'").replace("‘", "'").replace("`", "'")
    for pattern, full in CONTRACTIONS:
        s = re.sub(pattern, full, s)
    s = re.sub(r"[^\w'\s-]", " ", s)
    s = s.replace("-", " ")
    return [w.strip("'") for w in s.split() if w.strip("'")]


def accuracy(given: str, truth: str) -> dict[str, Any]:
    """Сколько слов оригинала услышано верно и в каком месте ошибка: ok / miss (пропустил) /
    wrong (написал не то) / extra (лишнее). pct — верные слова от большего из двух: оригинала и написанного."""
    g, t = words(given), words(truth)
    if not t:
        return {"pct": 0, "diff": []}
    sm = difflib.SequenceMatcher(a=t, b=g, autojunk=False)
    diff: list[dict[str, str]] = []
    right = 0
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            right += a2 - a1
            diff += [{"w": w, "s": "ok"} for w in t[a1:a2]]
        elif op == "delete":
            diff += [{"w": w, "s": "miss"} for w in t[a1:a2]]
        elif op == "insert":
            diff += [{"w": w, "s": "extra"} for w in g[b1:b2]]
        else:
            diff += [{"w": w, "s": "wrong", "heard": " ".join(g[b1:b2])} for w in t[a1:a2]]
    return {"pct": round(100 * right / max(len(t), len(g))), "diff": diff}  # лишние слова — тоже ошибка диктанта


def dictation_ok(given: Any, truth: str) -> bool:
    return accuracy(str(given or ""), truth)["pct"] >= DICT_OK * 100


def pick_dictation(transcript: list[dict[str, Any]], n: int = 5) -> list[int]:
    """Строки для диктанта: с отметкой времени, 5–14 слов, по всему ролику, без соседних."""
    good = [i for i, x in enumerate(transcript) if x.get("t") is not None and 5 <= len(words(x["text"])) <= 14]
    if len(good) <= n:
        return good
    step = len(good) / n
    return [good[int(k * step + step / 2)] for k in range(n)]


# --- словарь ------------------------------------------------------------------------------------------

def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "arvix", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 — свой адрес, https
        return resp.read(500_000)


FETCH: Callable[[str], bytes] = _fetch  # тесты подменяют: сети в тестах нет
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_lock = threading.Lock()


def define(word: str) -> dict[str, Any] | None:
    """Толкование по-английски (без перевода — метод владельца), транскрипция, аудио произношения.
    Не нашлось или сеть недоступна — None."""
    word = re.sub(r"[^a-z'-]", "", str(word or "").lower().strip())[:40]
    if not word:
        return None
    with _lock:
        hit = _cache.get(word)
        if hit and time.monotonic() - hit[0] < 7 * 24 * 3600:
            return hit[1]
    try:
        data = json.loads(FETCH("https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)))
    except Exception as exc:  # noqa: BLE001 — словарь внешний: нет — значит нет
        log.info("словарь %s: %s", word, exc)
        data = None
    out = None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        entry = data[0]
        audio = next((p.get("audio") for p in entry.get("phonetics") or [] if isinstance(p, dict)
                      and str(p.get("audio") or "").startswith("https://")), "")
        meanings = []
        for m in entry.get("meanings") or []:
            for d in (m.get("definitions") or [])[:2]:
                meanings.append({"pos": str(m.get("partOfSpeech") or "")[:20], "def": str(d.get("definition") or "")[:300],
                                 "example": str(d.get("example") or "")[:200]})
            if len(meanings) >= 3:
                break
        out = {"word": str(entry.get("word") or word)[:40], "phonetic": str(entry.get("phonetic") or "")[:60],
               "audio": audio, "meanings": meanings[:3]}
    with _lock:
        _cache[word] = (time.monotonic(), out)
    return out


def cloze(sentence: str, word: str) -> str:
    """Предложение с пропуском для Anki: «I was {{c1::reluctant}} to go.» — карточка без перевода."""
    pattern = re.compile(rf"(?<![\w']){re.escape(word)}(?![\w'])", re.I)
    return pattern.sub(lambda m: "{{c1::" + m.group(0) + "}}", sentence, count=1) if pattern.search(sentence) else sentence


def language_of(*texts: str) -> str | None:
    """Код иностранного языка урока по названию задачи, теме или предмету; не язык — None."""
    joined = " ".join(str(t or "") for t in texts)
    return next((code for code, rx in LANG_RE.items() if rx.search(joined)), None)
