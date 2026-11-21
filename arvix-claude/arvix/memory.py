"""Долгая память Arvix (04-AI-LAYER §8, D25): журнал хранит всё дословно, код находит нужное.

Модель не может держать в промпте месяцы переписки, а пересказ теряет детали. Поэтому
память не сжимается вовсе: источник правды — события журнала (переписка, факты, заметки,
уроки, ответы интервью), а здесь — два производных индекса, которые можно стереть и собрать заново.

1. FTS5-индекс в той же базе (`memory_fts`). На каждое сообщение код ищет по нему
   похожие места прошлых разговоров и кладёт их в промпт дословно, с датой (`<recall>`).
2. Папка `data_dir()/memory/` — переписка по дням в Markdown. Голова получает её вместе
   с хранилищем (Grep/Read) и ищет сама, когда в контексте ответа нет.

Индекс не доменное состояние: задач и режима в нём нет, правило №3 не нарушается.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from arvix.config import data_dir

log = logging.getLogger("arvix.memory")
INDEXED = "memory_indexed"
KINDS = {
    "message_in": "ЧЕЛОВЕК", "message_out": "АРВИКС", "fact_remembered": "ФАКТ", "note_captured": "ЗАМЕТКА",
    "interview_answer": "ИНТЕРВЬЮ", "lesson_checked": "УРОК", "insight": "ВЫВОД", "debrief_completed": "РАЗБОР",
}
SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    text, who UNINDEXED, at UNINDEXED, event_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""
WORD = re.compile(r"[\wё]{3,}", re.IGNORECASE)
# Служебные слова не ищутся: «что», «это», «надо» есть в каждом втором сообщении.
STOP = frozenset("""что это как так там тут уже еще ещё или его она они оно мне меня тебя тебе мой моя мои твой
надо было будет есть нет для при про над под без через после перед когда где куда чем чего кто весь все всё
вот ну да же ли бы не ни только очень можно нужно сегодня завтра вчера сейчас тоже просто давай""".split())


def _text_of(kind: str, payload: dict[str, Any]) -> str:
    if kind in ("message_in", "message_out", "note_captured", "insight"):
        return str(payload.get("text") or "")
    if kind == "fact_remembered":
        return f"{payload.get('topic', '')}: {payload.get('fact', '')}"
    if kind == "interview_answer":
        return f"{payload.get('question') or payload.get('qid', '')}: {payload.get('answer', '')}"
    if kind == "lesson_checked":
        return f"проверка урока {payload.get('score_pct')}%: {payload.get('answers', '')} · пробелы: {', '.join(payload.get('gaps') or [])}"
    if kind == "debrief_completed":
        return f"разбор {payload.get('date', '')}: {payload.get('answers', '')} → {payload.get('conclusion', '')}"
    return ""


def stems(text: str, limit: int = 12) -> list[str]:
    """Грубая морфология без словарей: первые 6 букв слова как префикс («экзамен*»
    найдёт «экзамены», «экзаменов»). Для русского этого хватает в 9 случаях из 10."""
    out: list[str] = []
    for word in WORD.findall(text.lower()):
        if word in STOP or word.isdigit() and len(word) < 3:
            continue
        stem = word[:6] if len(word) > 6 else word
        if stem not in out:
            out.append(stem)
    return out[:limit]


class Memory:
    def __init__(self, core: Any):
        self.core = core
        self.conn: sqlite3.Connection = core.store._conn
        try:
            self.conn.executescript(SCHEMA)
            self.ok = True
        except sqlite3.OperationalError as exc:  # SQLite без FTS5 — память работает только через папку
            log.warning("FTS5 недоступен: %s", exc)
            self.ok = False

    def sync(self) -> int:
        """Доиндексировать новые события. Возвращает, сколько добавлено."""
        if not self.ok:
            return 0
        last = int(self.core.store.kv_get(INDEXED, 0) or 0)
        rows = []
        for event in self.core.store.read(last):
            if event.kind in KINDS and (text := _text_of(event.kind, event.payload).strip()):
                if event.payload.get("key") and event.kind == "message_out" and len(text) < 40:
                    continue  # «Блок пошёл» и прочие шаблоны L0 — не память
                rows.append((text, KINDS[event.kind], event.at.isoformat(), event.id))
            last = event.id
        if rows:
            self.conn.executemany("INSERT INTO memory_fts (text, who, at, event_id) VALUES (?, ?, ?, ?)", rows)
        self.core.store.kv_set(INDEXED, last)
        return len(rows)

    def search(self, query: str, *, limit: int = 6, before_id: int | None = None, chars: int = 500) -> list[dict[str, Any]]:
        """Дословные куски прошлого, самые похожие на запрос. before_id отсекает то,
        что и так лежит в промпте как свежая история."""
        if not self.ok:
            return []
        words = stems(query)
        if not words:
            return []
        match = " OR ".join(f'"{w}"*' for w in words)
        sql = "SELECT text, who, at, event_id FROM memory_fts WHERE memory_fts MATCH ?"
        params: list[Any] = [match]
        if before_id:
            sql += " AND CAST(event_id AS INTEGER) < ?"
            params.append(before_id)
        sql += " ORDER BY bm25(memory_fts) LIMIT ?"
        params.append(limit)
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("поиск по памяти: %s", exc)
            return []
        tz = self.core.tz
        out = []
        for text, who, at, event_id in rows:
            when = datetime.fromisoformat(at).astimezone(tz)
            out.append({"who": who, "at": when, "event_id": int(event_id), "text": _excerpt(text, words, chars)})
        out.sort(key=lambda r: r["event_id"])
        return out

    def recall_block(self, query: str, *, before_id: int | None = None, limit: int = 6) -> str:
        found = self.search(query, limit=limit, before_id=before_id)
        if not found:
            return ""
        lines = [f"[{r['at']:%d.%m.%Y %H:%M} {r['who']}] {r['text']}" for r in found]
        return ("<recall>\nИз памяти — дословно, найдено кодом по словам сообщения. Опирайся, если относится к делу; "
                "не пересказывай всё подряд.\n" + "\n".join(lines) + "\n</recall>")


def _excerpt(text: str, words: list[str], chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= chars:
        return text
    low = text.lower()
    first = min((i for i in (low.find(w) for w in words) if i >= 0), default=0)
    start = max(0, first - chars // 3)
    return ("…" if start else "") + text[start : start + chars].strip() + "…"


def export_transcripts(core: Any, folder: Path | None = None) -> Path:
    """Переписка по дням — `memory/ГГГГ-ММ-ДД.md`. Прошлые дни пишутся один раз,
    сегодняшний — заново. Голова ищет по папке Grep'ом (brain.py, --add-dir)."""
    folder = folder or data_dir() / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    days: dict[date, list[str]] = {}
    facts: list[str] = []
    for event in core.store.read(0):
        if event.kind in ("message_in", "message_out"):
            who = "Я" if event.kind == "message_in" else "Arvix"
            text = str(event.payload.get("text") or "").strip()
            if text:
                days.setdefault(event.local_date, []).append(f"**{event.at.astimezone(core.tz):%H:%M} {who}:** {text}")
        elif event.kind == "task_completed" and (event.payload.get("report") or event.payload.get("photos")):
            task = core.state.tasks.get(event.payload.get("id") or "")  # отчёт по задаче — тоже память (D49)
            line = f"**{event.at.astimezone(core.tz):%H:%M} Отчёт** «{task.title if task else event.payload.get('id')}»: {event.payload.get('report') or ''}"
            if event.payload.get("photos"):
                line += " · фото: " + ", ".join(event.payload["photos"])
            days.setdefault(event.local_date, []).append(line)
    for fact in core.state.facts.values():
        facts.append(f"- [{fact.get('topic', 'general')}] {fact['fact']}")
    today = core.today()
    for day, lines in days.items():
        path = folder / f"{day.isoformat()}.md"
        if day < today and path.exists():
            continue
        path.write_text(f"# Переписка {day:%d.%m.%Y}\n\n" + "\n\n".join(lines) + "\n", encoding="utf-8")
    (folder / "ФАКТЫ.md").write_text("# Что Arvix знает о человеке\n\n" + "\n".join(facts) + "\n", encoding="utf-8")
    return folder
