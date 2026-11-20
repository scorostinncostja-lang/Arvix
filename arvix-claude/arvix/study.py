"""Раздел «Обучение» (06-LEARNING §10, D55): учебная сессия = урок §8 + окна.

Своей модели обучения нет. Сессия — это учебная задача (сфера learning) и её урок (`lesson.py`,
`Bot.prepare_lesson`): план по минутам, таймер, проверка. Сверху — окна, которые ставит Арвикс
(в плане урока или действием `study_panel` из чата сессии) или человек (видео по ссылке):

  quiz     — тест: вопросы с вариантами проверяет код сразу; открытые — голова на проверке блока
  board    — доска: графики функций, точки, отрезки, окружности, многоугольники (рисует приложение, SVG)
  diagram  — схема: узлы и стрелки
  video    — видео: только настоящая ссылка YouTube / RuTube / Vimeo; без ссылки — поиск по запросу
  text     — объяснение «у доски» порцией на 2–3 минуты
  note     — заметка из хранилища (обычно каркас конспекта урока): человек пишет, Арвикс читает
  sources  — источники, первоисточник первым

Окно и ответ на тест — события журнала (`study_panel`, `study_answer`), состояние — свёртка
(`State.study`). Арвикс видит сессию блоком в промпте (`context_block`): окна, ответы, текст заметки,
сколько прошло. Эталоны ответов в приложение не уходят, пока человек не ответил (`public_panel`).

Темы — общая очередь `learn_item_set` (projects.py): тема из проекта, теория или практика, видна и в
проекте, и здесь. Учебный блок по теме закрыт — тема пройдена в обоих местах.
"""

from __future__ import annotations

import math
import re
import urllib.parse
from typing import Any

from arvix.core import ArvixError, new_id

LESSON = "lesson"  # ключ урока в runtime-таблице — тот же, что у Bot и web/api

PANEL_TYPES = ("quiz", "board", "diagram", "video", "text", "note", "sources")
PANEL_RU = {"quiz": "тест", "board": "доска", "diagram": "схема", "video": "видео", "text": "объяснение",
            "note": "заметка", "sources": "источники"}
LEARN_KINDS = {"theory": "теория", "practice": "практика"}
MAX_PANELS = 12  # видимых окон в сессии: больше — уже не рабочий стол, а свалка
BOARD_KINDS = ("fn", "point", "segment", "circle", "polygon", "label")
EXPR_RE = re.compile(r"^[0-9a-zA-Z_+\-*/^().,\s]{1,120}$")  # формула для доски: разбирает приложение, eval нет
EXPR_WORDS = {"x", "pi", "e", "sin", "cos", "tan", "sqrt", "abs", "log", "ln", "exp", "asin", "acos", "atan"}

# Схема окна для головы: и в плане урока (LESSON_SCHEMA.panels), и в действии study_panel.
PANEL_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(PANEL_TYPES)},
        "title": {"type": "string", "description": "заголовок окна, 2–6 слов"},
        "id": {"type": "string", "description": "id окна из блока <study> — чтобы заменить его или скрыть (hidden=true)"},
        "hidden": {"type": "boolean"},
        "questions": {
            "type": "array", "description": "quiz: 3–7 вопросов; options + answer (индекс верного с 0) — проверит код; без options — открытый, a — эталон",
            "items": {"type": "object", "properties": {
                "q": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                "answer": {"type": "integer"}, "a": {"type": "string"}, "why": {"type": "string", "description": "почему верно — покажется после ответа"},
            }, "required": ["q"]},
        },
        "items": {
            "type": "array", "description": "board: фигуры; sources: не нужно (см. list)",
            "items": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": list(BOARD_KINDS)},
                "expr": {"type": "string", "description": "fn: y = f(x), например 2*x^2-3*x+1, sin(x)"},
                "x": {"type": "number"}, "y": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"},
                "r": {"type": "number"}, "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                "label": {"type": "string"},
            }, "required": ["kind"]},
        },
        "view": {"type": "array", "items": {"type": "number"}, "description": "board: [xmin, xmax, ymin, ymax]"},
        "nodes": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                                             "required": ["id", "label"]}},
        "edges": {"type": "array", "items": {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"},
                                                                              "label": {"type": "string"}}, "required": ["from", "to"]}},
        "url": {"type": "string", "description": "video: только настоящая ссылка (видел в заметках, в поиске, прислал человек)"},
        "query": {"type": "string", "description": "video: что искать, если настоящей ссылки нет"},
        "ask": {"type": "string", "description": "video: вопрос, на который ответить после просмотра"},
        "text": {"type": "string", "description": "text: объяснение порцией на 2–3 минуты чтения, markdown"},
        "path": {"type": "string", "description": "note: путь заметки в хранилище"},
        "list": {"type": "array", "items": {"type": "string"}, "description": "sources: первоисточник первым"},
    },
    "required": ["type"],
}

PANEL_RULES = """Окна сессии (раздел «Обучение»): к плану можно приложить 1–3 окна panels — только те, что нужны этому
блоку. quiz — короткий тест на вспоминание с вариантами (код проверит сразу); board — график или чертёж, если тема про
функции, геометрию, движение; diagram — схема связей понятий; video — только настоящая ссылка, иначе query для поиска,
и ask — вопрос после просмотра (видео — источник, а не замена работы); text — не нужен в начале: объяснение — когда
человек спросит. Заметку и источники приложение покажет само."""


# --- окна: проверка того, что прислала голова или человек --------------------------------------------

def _num(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def safe_expr(expr: str) -> str | None:
    """Формула доски — только числа, x, операции и известные функции. Разбирает приложение, без eval."""
    expr = str(expr or "").strip().removeprefix("y=").removeprefix("y =").strip()
    if not expr or not EXPR_RE.match(expr):
        return None
    words = set(re.findall(r"[a-zA-Z_]+", expr))
    return expr if words <= EXPR_WORDS else None


def embed_url(url: str) -> tuple[str, str] | None:
    """Ссылка → (адрес для встраивания, площадка). Только YouTube, RuTube, Vimeo: их плееры встраиваются
    без ключей и без чужих скриптов в приложении. Остальное — просто ссылка."""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https"):
        return None
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    query = dict(urllib.parse.parse_qsl(u.query))
    vid = None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com", "music.youtube.com"):
        if u.path == "/watch":
            vid = query.get("v")
        elif m := re.match(r"^/(?:embed|shorts|live)/([^/?#]+)", u.path):
            vid = m.group(1)
    if vid and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid):
        start = re.match(r"^(\d+)", query.get("t") or query.get("start") or "")
        return f"https://www.youtube-nocookie.com/embed/{vid}" + (f"?start={start.group(1)}" if start else ""), "youtube"
    if host == "rutube.ru" and (m := re.match(r"^/(?:video|play/embed)/([0-9a-f]{16,40})", u.path)):
        return f"https://rutube.ru/play/embed/{m.group(1)}", "rutube"
    if host == "vimeo.com" and (m := re.match(r"^/(\d{5,12})", u.path)):
        return f"https://player.vimeo.com/video/{m.group(1)}", "vimeo"
    return None


def _quiz(raw: dict[str, Any]) -> dict[str, Any]:
    questions = []
    for q in (raw.get("questions") or [])[:10]:
        if not isinstance(q, dict) or not _text(q.get("q"), 400):
            continue
        item: dict[str, Any] = {"q": _text(q.get("q"), 400), "why": _text(q.get("why"), 400)}
        options = [_text(o, 200) for o in (q.get("options") or []) if _text(o, 200)][:6]
        answer = q.get("answer")
        if len(options) >= 2 and isinstance(answer, int) and not isinstance(answer, bool) and 0 <= answer < len(options):
            item.update(options=options, answer=answer)
        elif _text(q.get("a"), 400):
            item["a"] = _text(q.get("a"), 400)
        else:
            continue  # вопрос без эталона нечем проверить — не вопрос, а шум
        questions.append(item)
    if not questions:
        raise ArvixError("В тесте нет вопросов с ответом")
    return {"questions": questions}


def _board(raw: dict[str, Any]) -> dict[str, Any]:
    items = []
    for it in (raw.get("items") or [])[:20]:
        if not isinstance(it, dict) or it.get("kind") not in BOARD_KINDS:
            continue
        kind, label = it["kind"], _text(it.get("label"), 40)
        if kind == "fn":
            if expr := safe_expr(it.get("expr", "")):
                items.append({"kind": "fn", "expr": expr, "label": label})
        elif kind in ("point", "label"):
            items.append({"kind": kind, "x": _num(it.get("x")), "y": _num(it.get("y")), "label": label})
        elif kind == "segment":
            items.append({"kind": kind, "x": _num(it.get("x")), "y": _num(it.get("y")), "x2": _num(it.get("x2")),
                          "y2": _num(it.get("y2")), "label": label})
        elif kind == "circle" and _num(it.get("r")) > 0:
            items.append({"kind": kind, "x": _num(it.get("x")), "y": _num(it.get("y")), "r": _num(it.get("r")), "label": label})
        elif kind == "polygon":
            pts = [[_num(p[0]), _num(p[1])] for p in (it.get("points") or [])[:12] if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(pts) >= 3:
                items.append({"kind": kind, "points": pts, "label": label})
    if not items:
        raise ArvixError("На доске нечего рисовать: формулы не разобрались")
    view = [_num(v) for v in (raw.get("view") or [])[:4]]
    if len(view) != 4 or view[0] >= view[1] or view[2] >= view[3]:
        view = [-10.0, 10.0, -10.0, 10.0]
    return {"items": items, "view": view}


def _diagram(raw: dict[str, Any]) -> dict[str, Any]:
    nodes, seen = [], set()
    for n in (raw.get("nodes") or [])[:16]:
        nid = _text((n or {}).get("id"), 40) if isinstance(n, dict) else ""
        if nid and nid not in seen and _text(n.get("label"), 60):
            seen.add(nid)
            nodes.append({"id": nid, "label": _text(n.get("label"), 60)})
    edges = [{"from": _text(e.get("from"), 40), "to": _text(e.get("to"), 40), "label": _text(e.get("label"), 40)}
             for e in (raw.get("edges") or [])[:30] if isinstance(e, dict) and e.get("from") in seen and e.get("to") in seen]
    if len(nodes) < 2:
        raise ArvixError("В схеме меньше двух узлов")
    return {"nodes": nodes, "edges": edges}


def _video(raw: dict[str, Any]) -> dict[str, Any]:
    url, query = _text(raw.get("url"), 400), _text(raw.get("query"), 160)
    out: dict[str, Any] = {"ask": _text(raw.get("ask"), 300)}
    if url:
        if not re.match(r"^https?://", url):
            raise ArvixError("Ссылка на видео должна начинаться с http")
        out["url"] = url
        if found := embed_url(url):
            out["embed"], out["site"] = found
    elif query:
        out["query"] = query
        out["search"] = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    else:
        raise ArvixError("У видео нет ни ссылки, ни запроса")
    return out


def clean_panel(raw: Any, *, by: str = "arvix") -> dict[str, Any]:
    """Окно из ответа головы или от человека → проверенный словарь. Мусор — ArvixError, а не битое окно."""
    if not isinstance(raw, dict) or raw.get("type") not in PANEL_TYPES:
        raise ArvixError("Неизвестный вид окна")
    kind = raw["type"]
    panel: dict[str, Any] = {"id": _text(raw.get("id"), 40) or new_id(), "type": kind, "by": by,
                             "title": _text(raw.get("title"), 80) or PANEL_RU[kind].capitalize()}
    if kind == "quiz":
        panel.update(_quiz(raw))
    elif kind == "board":
        panel.update(_board(raw))
    elif kind == "diagram":
        panel.update(_diagram(raw))
    elif kind == "video":
        panel.update(_video(raw))
    elif kind == "text":
        if not (text := _text(raw.get("text"), 4000)):
            raise ArvixError("Пустое объяснение")
        panel["text"] = text
    elif kind == "note":
        if not (path := _text(raw.get("path"), 300)) or ".." in path.split("/"):
            raise ArvixError("Нет пути заметки")
        panel["path"] = path if path.endswith(".md") else path + ".md"
    elif kind == "sources":
        items = [_text(s, 300) for s in (raw.get("list") or raw.get("items") or []) if isinstance(s, str) and _text(s, 300)][:8]
        if not items:
            raise ArvixError("Пустой список источников")
        panel["list"] = items
    return panel


# --- журнал ------------------------------------------------------------------------------------

def session_task(core: Any, task_ref: Any = None) -> Any:
    """Задача сессии: названная или та, у которой сейчас урок."""
    ref = task_ref or (core.store.kv_get(LESSON) or {}).get("task_id")
    if not ref:
        raise ArvixError("Учебной сессии сейчас нет — открой её из раздела «Обучение» или ▶ у учебной задачи")
    task = core.resolve_task(ref)
    if task.sphere != "learning":
        raise ArvixError("Окна бывают только у учебного блока")
    return task


def add_panel(core: Any, raw: Any, *, task_ref: Any = None, by: str = "arvix", source: str = "web") -> dict[str, Any]:
    task = session_task(core, task_ref)
    if isinstance(raw, dict) and raw.get("hidden") and raw.get("id"):
        return hide_panel(core, raw["id"], task_ref=task.id, source=source)
    panel = clean_panel(raw, by=by)
    session = core.state.study.get(task.id) or {}
    visible = [p for p in session.get("panels", []) if not p.get("hidden") and p["id"] != panel["id"]]
    if len(visible) >= MAX_PANELS:
        raise ArvixError(f"В сессии уже {MAX_PANELS} окон — скрой лишние")
    with core.tx():
        core.emit("study_panel", {"task_id": task.id, "panel": panel}, source=source, entity_id=task.id)
    return panel


def hide_panel(core: Any, panel_id: str, *, task_ref: Any = None, source: str = "web") -> dict[str, Any]:
    task = session_task(core, task_ref)
    panel = next((p for p in (core.state.study.get(task.id) or {}).get("panels", []) if p["id"] == panel_id), None)
    if panel is None:
        raise ArvixError("Такого окна в сессии нет")
    with core.tx():
        core.emit("study_panel", {"task_id": task.id, "panel": {**panel, "hidden": True}}, source=source, entity_id=task.id)
    return {**panel, "hidden": True}


def grade(panel: dict[str, Any], answers: list[Any]) -> list[bool | None]:
    """Вопрос с вариантами — True/False кодом; открытый — None: его оценит голова на проверке блока."""
    out: list[bool | None] = []
    for i, q in enumerate(panel.get("questions") or []):
        given = answers[i] if i < len(answers) else None
        if "options" in q:
            out.append(isinstance(given, int) and not isinstance(given, bool) and given == q["answer"])
        else:
            out.append(None)
    return out


def answer_quiz(core: Any, panel_id: str, answers: list[Any], *, task_ref: Any = None, source: str = "web") -> dict[str, Any]:
    task = session_task(core, task_ref)
    session = core.state.study.get(task.id) or {}
    panel = next((p for p in session.get("panels", []) if p["id"] == panel_id and p["type"] == "quiz"), None)
    if panel is None:
        raise ArvixError("Такого теста в сессии нет")
    if panel_id in session.get("answers", {}):
        raise ArvixError("На этот тест уже ответил — попроси Арвикса дать новый")
    questions = panel["questions"]
    clean: list[Any] = []
    for i, q in enumerate(questions):
        given = answers[i] if i < len(answers) else None
        if "options" in q:
            clean.append(given if isinstance(given, int) and not isinstance(given, bool) and 0 <= given < len(q["options"]) else None)
        else:
            clean.append(_text(given, 1000))
    results = grade(panel, clean)
    scored = [r for r in results if r is not None]
    score = round(100 * sum(scored) / len(scored)) if scored else None
    with core.tx():
        core.emit("study_answer", {"task_id": task.id, "panel_id": panel_id, "answers": clean, "results": results,
                                   "score_pct": score}, source=source, entity_id=task.id)
    return {"results": results, "score_pct": score}


# --- что видит приложение и что видит Арвикс -------------------------------------------------------

def public_panel(panel: dict[str, Any], answer: dict[str, Any] | None) -> dict[str, Any]:
    """Окно для приложения: эталоны теста — только после ответа (иначе тест превращается в чтение ответов)."""
    if panel["type"] != "quiz":
        return panel
    questions = []
    for i, q in enumerate(panel["questions"]):
        item = {"q": q["q"], "options": q.get("options"), "open": "options" not in q}
        if answer is not None:
            item.update(answer=q.get("answer"), a=q.get("a"), why=q.get("why"), given=answer["answers"][i] if i < len(answer["answers"]) else None,
                        ok=answer["results"][i] if i < len(answer["results"]) else None)
        questions.append(item)
    return {**panel, "questions": questions, "done": answer is not None,
            "score_pct": answer.get("score_pct") if answer else None}


def note_excerpt(core: Any, path: str | None, limit: int = 1500) -> str:
    """Начало заметки, которую человек пишет на сессии: Арвикс видит, что уже написано своими словами."""
    if not path or not core.cfg.vault:
        return ""
    from arvix.vault import VaultError

    try:
        text = core.vault.read(path)
    except (VaultError, OSError, ArvixError):
        return ""
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def context_block(core: Any, task_id: str, note_path: str | None = None) -> str:
    """Сессия глазами Арвикса — в <lesson>: какие окна открыты, что человек ответил, что написал в заметке.
    Так он может «видеть и управлять»: добавить тест, если ошибки, скрыть лишнее, сослаться на ответ."""
    session = core.state.study.get(task_id) or {}
    lines = []
    for p in session.get("panels", []):
        if p.get("hidden"):
            continue
        head = f"[{p['id']}] {PANEL_RU[p['type']]} «{p['title']}»" + (" (поставил человек)" if p.get("by") == "me" else "")
        ans = session.get("answers", {}).get(p["id"])
        if p["type"] == "quiz":
            if ans is None:
                head += f" — {len(p['questions'])} вопр., ещё не ответил"
            else:
                marks = []
                for q, given, ok in zip(p["questions"], ans["answers"], ans["results"]):
                    if "options" in q:
                        pick = q["options"][given] if isinstance(given, int) else "—"
                        marks.append(f"{'верно' if ok else 'ошибка'}: «{q['q'][:80]}» → {pick}")
                    else:
                        marks.append(f"открытый: «{q['q'][:80]}» → {str(given)[:200] or '—'} (эталон: {q.get('a', '')[:120]})")
                head += f" — ответил, {ans['score_pct']}%" if ans.get("score_pct") is not None else " — ответил"
                head += "".join(f"\n    {m}" for m in marks)
        elif p["type"] == "video":
            head += f" — {p.get('url') or 'поиск: ' + p.get('query', '')}"
        elif p["type"] == "note":
            head += f" — {p['path']}"
        lines.append(head)
    out = "<study>\nОкна сессии в разделе «Обучение» (их видит человек):\n" + ("\n".join(lines) or "пока только план и таймер")
    if excerpt := note_excerpt(core, note_path):
        out += f"\nЗаметка урока {note_path} — что он уже написал сам:\n{excerpt}"
    out += ("\nМожешь добавить окно действием study_panel (поле panel): тест, доска, схема, видео, объяснение — когда это "
            "нужно по ходу: ошибка в тесте → разбор и новый вопрос; «покажи график» → board; «найди видео» → только настоящая "
            "ссылка. Тот же id — заменить окно, hidden=true — скрыть. Заметку за него не пиши: он пишет своими словами.\n</study>")
    return out


def quiz_summary(core: Any, task_id: str) -> str:
    """Ответы на тесты сессии — для оценки блока (голова №2): открытые вопросы она оценивает вместе с проверкой."""
    session = core.state.study.get(task_id) or {}
    rows = []
    for p in session.get("panels", []):
        ans = session.get("answers", {}).get(p["id"])
        if p["type"] != "quiz" or ans is None:
            continue
        for q, given, ok in zip(p["questions"], ans["answers"], ans["results"]):
            if "options" in q:
                rows.append(f"- {q['q']} → {'верно' if ok else 'неверно'}")
            else:
                rows.append(f"- {q['q']} → «{str(given)[:300]}» (эталон: {q.get('a', '')})")
    return "\n".join(rows)


def learn_item_of(core: Any, task: Any) -> dict[str, Any] | None:
    """Тема очереди, по которой поставлен блок (метка learn:<id>, projects.learn_start)."""
    for tag in getattr(task, "tags", ()) or ():
        if tag.startswith("learn:") and (item := core.state.learn_items.get(tag[6:])):
            return item
    return None


def lesson_hint(core: Any, task: Any) -> str:
    """Блок взят из очереди «учиться» — тема задана, голова не ищет её в роадмапе (иначе тема проекта терялась)."""
    item = learn_item_of(core, task)
    if not item:
        return ""
    project = core.state.projects.get(item.get("project_id") or "")
    kind = item.get("kind") or "theory"
    text = (f"Тема задана очередью «учиться»: «{item['topic']}» — {LEARN_KINDS.get(kind, kind)}"
            + (f", для проекта «{project['title']}»" if project else "") + (f". Зачем: {item['why']}" if item.get("why") else "")
            + (f". Источники темы: {'; '.join(item['sources'])}" if item.get("sources") else "") + ". Тему не меняй.")
    if kind == "practice":
        text += " Это практика: большая часть блока — делать самому (задачи, код, упражнение), теории — минимум для старта."
    return text
