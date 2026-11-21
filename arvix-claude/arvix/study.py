"""Раздел «Обучение» (06-LEARNING §10, D55, D60): учебная сессия = урок §8, разложенный по этапам.

Своей модели обучения нет: сессия — учебная задача (сфера learning) и её урок (`lesson.py`,
`Bot.prepare_lesson`). Но урок идёт не россыпью окон, а по одному алгоритму для любой темы (D60):

  diag     Диагностика — задачи от простой к сложной: что человек уже умеет. Проверяет код.
  learn    Разбор — только то, где ошибся: пример с решением по шагам, видео, заметка своими словами.
  practice Практика — задачи с ответом, проверка кодом сразу; ошибки копятся сами.
  fix      Работа над ошибками — почему ошибся и похожая задача; решил похожую — ошибка закрыта.
  check    Проверка — вопросы конца блока (голова №2); ответ и есть отчёт, после неё — повторение темы.

Порядок, пороги уровня и сбор ошибок — код (правило №1). Голова наполняет этапы под тему и человека:
задачи, подтемы, разбор, запрос видео. Человек видит один этап за раз и кнопку «Дальше».

Окна этапов — события журнала (`study_panel`, `study_answer`, `study_stage`, `study_fix`), состояние —
свёртка (`State.study`). Arvix видит сессию блоком в промпте (`context_block`): этап, уровень, ошибки,
текст заметки. Эталоны в приложение не уходят, пока человек не ответил (`public_panel`, `public_errors`).

Темы — общая очередь `learn_item_set` (projects.py): тема из проекта, теория или практика, видна и в
проекте, и здесь. Повторения тем после сессии — `review.py`.
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
MAX_PANELS = 16  # видимых окон на всю сессию (по этапам): больше — уже не рабочий стол, а свалка
BOARD_KINDS = ("fn", "point", "segment", "circle", "polygon", "label")
EXPR_RE = re.compile(r"^[0-9a-zA-Z_+\-*/^().,\s]{1,120}$")  # формула для доски: разбирает приложение, eval нет
EXPR_WORDS = {"x", "pi", "e", "sin", "cos", "tan", "sqrt", "abs", "log", "ln", "exp", "asin", "acos", "atan"}

# --- алгоритм сессии (D60) ------------------------------------------------------------------------

STAGES = ("diag", "learn", "practice", "fix", "check")
STAGE_RU = {"diag": "Диагностика", "learn": "Разбор", "practice": "Практика", "fix": "Работа над ошибками", "check": "Проверка"}
STAGE_SHORT = {**STAGE_RU, "fix": "Ошибки"}  # в полосе этапов на телефоне
STAGE_GOAL = {
    "diag": "Узнаём, что ты уже умеешь: задачи от простой к сложной. Решай в тетради, ответ — в поле. "
            "Не знаешь — жми «Не знаю», не угадывай: разбор будет точнее.",
    "learn": "Разбор только того, где ошибся: правило, пример с решением по шагам, ловушка. Видео — по желанию. "
             "Потом закрой всё и запиши суть своими словами в заметку.",
    "practice": "Решай сам, без подсказок и без заметок. Ответ проверяется сразу, ошибки уходят в работу над ошибками.",
    "fix": "У каждой ошибки: посмотри решение, отметь, почему ошибся, и реши похожую. Решил похожую — ошибка закрыта.",
    "check": "Ответь без заметок. Это и есть отчёт о блоке: Arvix оценит и назначит повторение темы.",
}
ERROR_KINDS = {"rule": "не знал правило", "calc": "ошибка в счёте", "read": "невнимательно прочитал", "start": "не понял, с чего начать"}
UNKNOWN = "?"  # ответ «не знаю»: честнее угадывания, разбор получает точную картину
LEVELS = {  # порог уровня по диагностике — код, а не модель
    "know": {"min": 80, "label": "Тему знаешь", "next": "practice",
             "advice": "Разбор можно пропустить — сразу к практике, начни с задач посложнее."},
    "gaps": {"min": 40, "label": "Есть пробелы", "next": "learn",
             "advice": "Разбор — только по слабым местам: {weak}. Остальное ты уже умеешь."},
    "new": {"min": 0, "label": "Тема новая", "next": "learn",
            "advice": "Начнём с разбора: правило и пример с решением по шагам, потом задачи от простых."},
}

_TWIN_PROPS = {
    "q": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}, "answer": {"type": "integer"},
    "short": {"type": "string"}, "accept": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"},
}
QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "q": {"type": "string", "description": "условие задачи или вопрос"},
        "options": {"type": "array", "items": {"type": "string"}, "description": "варианты, если вопрос с выбором"},
        "answer": {"type": "integer", "description": "индекс верного варианта с 0"},
        "short": {"type": "string", "description": "короткий ответ, как в бланке ОГЭ: число или слово — проверит код"},
        "accept": {"type": "array", "items": {"type": "string"}, "description": "другие верные записи ответа: «0,5», «1/2»"},
        "a": {"type": "string", "description": "эталон открытого ответа (своими словами) — оценит Arvix на проверке"},
        "why": {"type": "string", "description": "решение в 1–3 строки — покажется после ответа"},
        "skill": {"type": "string", "description": "подтема, которую проверяет задача — то же имя, что в skills"},
        "level": {"type": "integer", "description": "1 — простая, 2 — средняя, 3 — сложная"},
        "twin": {"type": "object", "properties": _TWIN_PROPS, "required": ["q"],
                 "description": "похожая задача с другими числами и своим ответом (short или options) — для работы над ошибками"},
    },
    "required": ["q"],
}

# Схема окна для головы: и в плане урока (LESSON_SCHEMA.panels), и в действии study_panel.
PANEL_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(PANEL_TYPES)},
        "title": {"type": "string", "description": "заголовок окна, 2–6 слов"},
        "id": {"type": "string", "description": "id окна из блока <study> — чтобы заменить его или скрыть (hidden=true)"},
        "hidden": {"type": "boolean"},
        "stage": {"type": "string", "enum": list(STAGES), "description": "этап, на котором окно видно; пусто — текущий"},
        "questions": {"type": "array", "items": QUESTION_SCHEMA,
                      "description": "quiz: 3–7 вопросов; short или options+answer — проверит код; a — открытый"},
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
        "query": {"type": "string", "description": "video: что искать — ролики найдёт код"},
        "ask": {"type": "string", "description": "video: вопрос, на который ответить после просмотра"},
        "text": {"type": "string", "description": "text: объяснение порцией на 2–3 минуты чтения, markdown"},
        "skill": {"type": "string", "description": "text: подтема, которую разбирает объяснение"},
        "path": {"type": "string", "description": "note: путь заметки в хранилище"},
        "list": {"type": "array", "items": {"type": "string"}, "description": "sources: первоисточник первым"},
    },
    "required": ["type"],
}

PANEL_RULES = """panels — 0–2 окна для этапа «Разбор»: board — график или чертёж, если тема про функции, геометрию,
движение; diagram — схема связей понятий. Тесты, видео, заметку и источники приложение соберёт само из полей выше."""


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


# --- короткий ответ: сверяет код ---------------------------------------------------------------------

def _norm(value: Any) -> str:
    s = str(value or "").strip().lower().replace("ё", "е")
    for dash in ("−", "–", "—"):
        s = s.replace(dash, "-")
    s = re.sub(r"\s+", "", s).rstrip(".")
    return re.sub(r"^(ответ:|[a-zа-я]=)", "", s)


def as_number(value: Any) -> float | None:
    """«3,5» · «7/2» · «-2» · «13 см» · «50%» → число; не число — None."""
    s = _norm(value).replace(",", ".")
    if m := re.fullmatch(r"([+-]?\d+(?:\.\d+)?)/([+-]?\d+(?:\.\d+)?)", s):
        den = float(m.group(2))
        return float(m.group(1)) / den if den else None
    if m := re.fullmatch(r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))(?:[a-zа-я°%²³]{0,6})", s):
        return float(m.group(1))
    return None


def _same(given: str, key: str) -> bool:
    a, b = as_number(given), as_number(key)
    if a is not None and b is not None:
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    return bool(_norm(key)) and _norm(given) == _norm(key)


def match_short(given: Any, q: dict[str, Any]) -> bool:
    """Ответ числом или словом против эталона и его других записей. «-2; 3» и «3;-2» — один ответ:
    корни через «;» сравниваются без порядка."""
    if given is None or str(given).strip() in ("", UNKNOWN):
        return False
    keys = [q.get("short", ""), *(q.get("accept") or [])]
    for key in keys:
        if not str(key).strip():
            continue
        if ";" in str(key) or ";" in str(given):
            gp = [p for p in _norm(given).split(";") if p]
            kp = [p for p in _norm(key).split(";") if p]
            if len(gp) != len(kp) or not gp:
                continue
            nums_g, nums_k = [as_number(p) for p in gp], [as_number(p) for p in kp]
            if None not in nums_g and None not in nums_k:
                if all(abs(x - y) <= 1e-6 * max(1.0, abs(y)) for x, y in zip(sorted(nums_g), sorted(nums_k))):  # type: ignore[arg-type]
                    return True
            elif sorted(gp) == sorted(kp):
                return True
            continue
        if _same(given, key):
            return True
    return False


def _question(q: Any, *, nested: bool = False) -> dict[str, Any] | None:
    """Вопрос теста: варианты (код), короткий ответ (код) или открытый (голова). Без эталона — None:
    вопрос, который нечем проверить, — не вопрос, а шум. nested — похожая задача: только то, что проверит код."""
    if not isinstance(q, dict) or not _text(q.get("q"), 600):
        return None
    item: dict[str, Any] = {"q": _text(q.get("q"), 600), "why": _text(q.get("why"), 600)}
    options = [_text(o, 200) for o in (q.get("options") or []) if _text(o, 200)][:6]
    answer = q.get("answer")
    if len(options) >= 2 and isinstance(answer, int) and not isinstance(answer, bool) and 0 <= answer < len(options):
        item.update(options=options, answer=answer)
    elif _text(q.get("short"), 60):
        item["short"] = _text(q.get("short"), 60)
        accept = [_text(a, 60) for a in (q.get("accept") or []) if _text(a, 60)][:5]
        if accept:
            item["accept"] = accept
    elif _text(q.get("a"), 600) and not nested:  # у похожей задачи открытого ответа нет: её проверяет код
        item["a"] = _text(q.get("a"), 600)
    else:
        return None
    if nested:
        return item
    if skill := _text(q.get("skill"), 60):
        item["skill"] = skill
    level = q.get("level")
    if isinstance(level, int) and not isinstance(level, bool) and 1 <= level <= 3:
        item["level"] = level
    if "a" not in item and (t := _question(q.get("twin"), nested=True)):
        item["twin"] = t
    return item


def _quiz(raw: dict[str, Any]) -> dict[str, Any]:
    questions = [x for x in (_question(q) for q in (raw.get("questions") or [])[:10]) if x]
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


def _results(raw: Any) -> list[dict[str, Any]]:
    """Найденные кодом ролики (videos.search) — только с настоящим плеером."""
    out = []
    for r in (raw or [])[:5]:
        if not isinstance(r, dict) or not (found := embed_url(str(r.get("url") or ""))):
            continue
        out.append({"url": _text(r.get("url"), 300), "embed": found[0], "site": found[1], "title": _text(r.get("title"), 160),
                    "channel": _text(r.get("channel"), 80), "minutes": int(_num(r.get("minutes")))})
    return out


def _video(raw: dict[str, Any]) -> dict[str, Any]:
    url, query = _text(raw.get("url"), 400), _text(raw.get("query"), 160)
    out: dict[str, Any] = {"ask": _text(raw.get("ask"), 300)}
    if query:
        out["query"] = query
        out["search"] = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    if results := _results(raw.get("results")):
        out["results"] = results
        url = url or results[0]["url"]
    if url:
        if not re.match(r"^https?://", url):
            raise ArvixError("Ссылка на видео должна начинаться с http")
        out["url"] = url
        if found := embed_url(url):
            out["embed"], out["site"] = found
    elif not query:
        raise ArvixError("У видео нет ни ссылки, ни запроса")
    return out


def clean_panel(raw: Any, *, by: str = "arvix") -> dict[str, Any]:
    """Окно из ответа головы или от человека → проверенный словарь. Мусор — ArvixError, а не битое окно."""
    if not isinstance(raw, dict) or raw.get("type") not in PANEL_TYPES:
        raise ArvixError("Неизвестный вид окна")
    kind = raw["type"]
    panel: dict[str, Any] = {"id": _text(raw.get("id"), 40) or new_id(), "type": kind, "by": by,
                             "title": _text(raw.get("title"), 80) or PANEL_RU[kind].capitalize()}
    if raw.get("stage") in STAGES:
        panel["stage"] = raw["stage"]
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
        if skill := _text(raw.get("skill"), 60):
            panel["skill"] = skill
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


def session_of(core: Any, task_id: str) -> dict[str, Any]:
    return core.state.study.get(task_id) or {"panels": [], "answers": {}, "fixes": {}}


def visible(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in session.get("panels", []) if not p.get("hidden")]


def panel_stage(panel: dict[str, Any], session: dict[str, Any] | None = None) -> str:
    """Этап окна. Окна до D60 этапа не знали: первый тест — диагностика, следующие — практика, остальное — разбор."""
    if panel.get("stage") in STAGES:
        return panel["stage"]
    if panel["type"] == "quiz":
        quizzes = [p for p in visible(session or {}) if p["type"] == "quiz" and p.get("stage") not in STAGES]
        return "diag" if quizzes and quizzes[0]["id"] == panel["id"] else "practice"
    return "learn"


def has_diag(session: dict[str, Any]) -> bool:
    return any(p["type"] == "quiz" and panel_stage(p, session) == "diag" for p in visible(session))


def current_stage(session: dict[str, Any]) -> str:
    if session.get("stage") in STAGES:
        return session["stage"]
    return "diag" if has_diag(session) or not visible(session) else "learn"


def add_panel(core: Any, raw: Any, *, task_ref: Any = None, by: str = "arvix", source: str = "web") -> dict[str, Any]:
    task = session_task(core, task_ref)
    if isinstance(raw, dict) and raw.get("hidden") and raw.get("id"):
        return hide_panel(core, raw["id"], task_ref=task.id, source=source)
    if isinstance(raw, dict) and raw.get("type") == "video" and not raw.get("url") and "results" not in raw and raw.get("query") \
            and core.cfg.section("learning").get("video_search", True):
        from arvix import videos

        raw = {**raw, "results": videos.search(str(raw["query"]))}  # ролики ищет код: голова адресов не выдумывает
    panel = clean_panel(raw, by=by)
    session = session_of(core, task.id)
    if "stage" not in panel:  # окно из чата — на этап, где человек сейчас
        panel["stage"] = current_stage(session)
    others = [p for p in visible(session) if p["id"] != panel["id"]]
    if len(others) >= MAX_PANELS:
        raise ArvixError(f"В сессии уже {MAX_PANELS} окон — скрой лишние")
    with core.tx():
        core.emit("study_panel", {"task_id": task.id, "panel": panel}, source=source, entity_id=task.id)
    return panel


def hide_panel(core: Any, panel_id: str, *, task_ref: Any = None, source: str = "web") -> dict[str, Any]:
    task = session_task(core, task_ref)
    panel = next((p for p in session_of(core, task.id).get("panels", []) if p["id"] == panel_id), None)
    if panel is None:
        raise ArvixError("Такого окна в сессии нет")
    with core.tx():
        core.emit("study_panel", {"task_id": task.id, "panel": {**panel, "hidden": True}}, source=source, entity_id=task.id)
    return {**panel, "hidden": True}


def set_stage(core: Any, stage: str, *, task_ref: Any = None, source: str = "web") -> str:
    task = session_task(core, task_ref)
    if stage not in STAGES:
        raise ArvixError("Такого этапа нет")
    if session_of(core, task.id).get("stage") != stage:
        with core.tx():
            core.emit("study_stage", {"task_id": task.id, "stage": stage}, source=source, entity_id=task.id)
    return stage


def grade(panel: dict[str, Any], answers: list[Any]) -> list[bool | None]:
    """Варианты и короткий ответ — True/False кодом; открытый — None: его оценит голова на проверке блока."""
    out: list[bool | None] = []
    for i, q in enumerate(panel.get("questions") or []):
        given = answers[i] if i < len(answers) else None
        if "options" in q:
            out.append(isinstance(given, int) and not isinstance(given, bool) and given == q["answer"])
        elif "short" in q:
            out.append(match_short(given, q))
        else:
            out.append(None)
    return out


def answer_quiz(core: Any, panel_id: str, answers: list[Any], *, task_ref: Any = None, source: str = "web") -> dict[str, Any]:
    task = session_task(core, task_ref)
    session = session_of(core, task.id)
    panel = next((p for p in session.get("panels", []) if p["id"] == panel_id and p["type"] == "quiz"), None)
    if panel is None:
        raise ArvixError("Такого теста в сессии нет")
    if panel_id in session.get("answers", {}):
        raise ArvixError("На этот тест уже ответил — попроси Arvix дать новый")
    clean: list[Any] = []
    for i, q in enumerate(panel["questions"]):
        given = answers[i] if i < len(answers) else None
        if given == UNKNOWN:
            clean.append(UNKNOWN)
        elif "options" in q:
            clean.append(given if isinstance(given, int) and not isinstance(given, bool) and 0 <= given < len(q["options"]) else None)
        else:
            clean.append(_text(given, 1000 if "a" in q else 120))
    results = grade(panel, clean)
    scored = [r for r in results if r is not None]
    score = round(100 * sum(scored) / len(scored)) if scored else None
    with core.tx():
        core.emit("study_answer", {"task_id": task.id, "panel_id": panel_id, "answers": clean, "results": results,
                                   "score_pct": score}, source=source, entity_id=task.id)
    return {"results": results, "score_pct": score}


# --- уровень, ошибки, работа над ошибками ----------------------------------------------------------

def _given_text(q: dict[str, Any], given: Any) -> str:
    if given == UNKNOWN:
        return "не знаю"
    if "options" in q:
        return q["options"][given] if isinstance(given, int) and 0 <= given < len(q["options"]) else "—"
    return str(given or "").strip() or "—"


def right_text(q: dict[str, Any]) -> str:
    if "options" in q:
        return q["options"][q["answer"]]
    return q.get("short") or q.get("a") or ""


def route(session: dict[str, Any]) -> dict[str, Any] | None:
    """Уровень по диагностике — код: доля верного и слабые подтемы. «Не знаю» — не знание, а не ошибка внимания.
    Задачи без подтемы (тесты до D60) в уровень идут, в списки «слабое / умеешь» — нет."""
    rows: list[tuple[str | None, bool]] = []
    for p in visible(session):
        if p["type"] != "quiz" or panel_stage(p, session) != "diag":
            continue
        ans = (session.get("answers") or {}).get(p["id"])
        if not ans:
            continue
        for i, (q, ok) in enumerate(zip(p["questions"], ans["results"])):
            if ok is not None:
                rows.append((q.get("skill"), bool(ok)))
    if not rows:
        return None
    right = sum(ok for _, ok in rows)
    pct = round(100 * right / len(rows))
    skills: dict[str, list[bool]] = {}
    for skill, ok in rows:
        if skill:
            skills.setdefault(skill, []).append(ok)
    weak = [s for s, oks in skills.items() if not all(oks)]
    level = next(k for k, v in LEVELS.items() if pct >= v["min"])
    info = LEVELS[level]
    return {"level": level, "label": info["label"], "pct": pct, "right": right, "total": len(rows), "weak": weak,
            "strong": [s for s in skills if s not in weak], "next": info["next"],
            "advice": info["advice"].format(weak=", ".join(weak[:4]) or "задачи, где ошибся")}


def errors(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Ошибки сессии — из ответов на тесты (диагностика, практика, тесты из чата). Открытые вопросы не ошибки:
    их оценит голова на проверке."""
    out = []
    fixes = session.get("fixes") or {}
    for p in visible(session):
        ans = (session.get("answers") or {}).get(p["id"]) if p["type"] == "quiz" else None
        if not ans:
            continue
        for i, (q, given, ok) in enumerate(zip(p["questions"], ans["answers"], ans["results"])):
            if ok is not False:
                continue
            key = f"{p['id']}:{i}"
            fix = fixes.get(key) or {}
            out.append({"key": key, "panel": p["id"], "i": i, "stage": panel_stage(p, session), "q": q, "given": given,
                        "unknown": given == UNKNOWN, "kind": fix.get("kind"), "twin_given": fix.get("twin_given"),
                        "twin_ok": fix.get("twin_ok"), "closed": bool(fix.get("closed")), "self": bool(fix.get("self"))})
    return out


def fix_error(core: Any, key: str, *, task_ref: Any = None, kind: str | None = None, twin: Any = None, done: bool = False,
              source: str = "web") -> dict[str, Any]:
    """Работа над ошибкой: причина (кнопкой), похожая задача (проверяет код) или «разобрался» без похожей."""
    task = session_task(core, task_ref)
    session = session_of(core, task.id)
    err = next((e for e in errors(session) if e["key"] == key), None)
    if err is None:
        raise ArvixError("Такой ошибки в сессии нет")
    payload: dict[str, Any] = {"task_id": task.id, "key": key}
    if kind:
        if kind not in ERROR_KINDS:
            raise ArvixError("Неизвестная причина ошибки")
        payload["kind"] = kind
    if twin is not None:
        q = err["q"].get("twin")
        if not q:
            raise ArvixError("У этой ошибки нет похожей задачи — попроси Arvix в чате")
        if err["twin_given"] is not None:
            raise ArvixError("Похожую уже решал — попроси Arvix дать ещё одну")
        if "options" in q:
            given = twin if isinstance(twin, int) and not isinstance(twin, bool) and 0 <= twin < len(q["options"]) else UNKNOWN
            ok = given == q["answer"]
        else:
            given = _text(twin, 120) or UNKNOWN
            ok = match_short(given, q)
        payload.update(twin_given=given, twin_ok=ok)
        if ok:
            payload["closed"] = True
    if done:
        payload.update(closed=True, self=not err.get("twin_ok"))
    if len(payload) == 2:
        raise ArvixError("Нечего записать")
    with core.tx():
        core.emit("study_fix", payload, source=source, entity_id=task.id)
    return next(e for e in errors(session_of(core, task.id)) if e["key"] == key)


# --- что видит приложение и что видит Arvix -------------------------------------------------------

def _public_question(q: dict[str, Any]) -> dict[str, Any]:
    return {"q": q["q"], "options": q.get("options"), "open": "a" in q, "short": "short" in q, "skill": q.get("skill"),
            "level": q.get("level")}


def public_panel(panel: dict[str, Any], answer: dict[str, Any] | None) -> dict[str, Any]:
    """Окно для приложения: эталоны теста — только после ответа (иначе тест превращается в чтение ответов)."""
    if panel["type"] != "quiz":
        return panel
    questions = []
    for i, q in enumerate(panel["questions"]):
        item = _public_question(q)
        if answer is not None:
            given = answer["answers"][i] if i < len(answer["answers"]) else None
            item.update(answer=q.get("answer"), right=right_text(q), a=q.get("a"), why=q.get("why"), given=given,
                        given_text=_given_text(q, given), unknown=given == UNKNOWN,
                        ok=answer["results"][i] if i < len(answer["results"]) else None)
        questions.append(item)
    return {**{k: v for k, v in panel.items() if k != "questions"}, "questions": questions, "done": answer is not None,
            "score_pct": answer.get("score_pct") if answer else None}


def public_errors(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Ошибки для этапа «Работа над ошибками»: свой ответ, верный, решение; ответ похожей — только после попытки."""
    out = []
    for e in errors(session):
        q, twin = e["q"], e["q"].get("twin")
        item = {"key": e["key"], "stage": e["stage"], "q": q["q"], "skill": q.get("skill"), "given": _given_text(q, e["given"]),
                "unknown": e["unknown"], "right": right_text(q), "why": q.get("why", ""), "kind": e["kind"],
                "closed": e["closed"], "self": e["self"], "twin": None}
        if twin:
            item["twin"] = {"q": twin["q"], "options": twin.get("options"), "short": "short" in twin, "done": e["twin_given"] is not None}
            if e["twin_given"] is not None:
                item["twin"].update(ok=e["twin_ok"], given=_given_text(twin, e["twin_given"]), right=right_text(twin), why=twin.get("why", ""))
        out.append(item)
    return out


def note_excerpt(core: Any, path: str | None, limit: int = 1500) -> str:
    """Начало заметки, которую человек пишет на сессии: Arvix видит, что уже написано своими словами."""
    if not path or not core.cfg.vault:
        return ""
    from arvix.vault import VaultError

    try:
        text = core.vault.read(path)
    except (VaultError, OSError, ArvixError):
        return ""
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def note_own(core: Any, path: str | None) -> dict[str, Any]:
    """Что в заметке урока написано самим человеком: без свойств, заголовков, строк шаблона, вопросов
    самопроверки и источников, которые вписал код. Приложение показывает это вместо целого каркаса."""
    if not path or not core.cfg.vault:
        return {"words": 0, "preview": ""}
    from arvix.vault import VaultError

    try:
        text = core.vault.read(path)
    except (VaultError, OSError, ArvixError):
        return {"words": 0, "preview": ""}
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    template = {line.strip() for line in (core.concept_template() or "").splitlines()}
    own, skip = [], False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("#"):
            skip = t.lstrip("#").strip().lower().startswith(("источники", "самопроверка"))
            continue
        if skip or not t or t in template or re.match(r"^(- \[[ x]\]|> \[!|```|>$|-$|> -$)", t):
            continue
        if re.fullmatch(r"[-*>\s]*[^:]{1,40}:\s*(\[\[\s*\]\])?", t):  # «- Опирается на: [[ ]]» — пустое поле шаблона
            continue
        own.append(re.sub(r"^[>\-*\s]+", "", t))
    words = " ".join(own).split()
    return {"words": len(words), "preview": " ".join(words[:28]) + ("…" if len(words) > 28 else "")}


def _quiz_marks(session: dict[str, Any], p: dict[str, Any], ans: dict[str, Any]) -> list[str]:
    marks = []
    for q, given, ok in zip(p["questions"], ans["answers"], ans["results"]):
        if ok is None:
            marks.append(f"открытый: «{q['q'][:80]}» → {str(given)[:200] or '—'} (эталон: {q.get('a', '')[:120]})")
        else:
            marks.append(f"{'верно' if ok else 'ошибка'}: «{q['q'][:80]}» → {_given_text(q, given)}"
                         + ("" if ok else f" (верно: {right_text(q)[:60]})"))
    return marks


def context_block(core: Any, task_id: str, note_path: str | None = None) -> str:
    """Сессия глазами Arvix — в <lesson>: этап, уровень, ошибки, окна, ответы, заметка.
    Так он может «видеть и управлять»: дать похожую задачу на ошибку, скрыть лишнее, сослаться на ответ."""
    session = session_of(core, task_id)
    stage = current_stage(session)
    lines = [f"Этап сейчас: {STAGE_RU[stage]} ({STAGES.index(stage) + 1}/5) — " + " → ".join(STAGE_RU[s] for s in STAGES) + "."]
    if r := route(session):
        lines.append(f"Диагностика: {r['right']} из {r['total']} ({r['pct']}%) — «{r['label']}»"
                     + (f"; слабые подтемы: {', '.join(r['weak'])}" if r["weak"] else ""))
    errs = errors(session)
    if errs:
        closed = sum(e["closed"] for e in errs)
        lines.append(f"Ошибки: {len(errs)}, закрыто {closed}:" + "".join(
            f"\n    {'✓' if e['closed'] else '·'} «{e['q']['q'][:90]}» → {_given_text(e['q'], e['given'])} (верно: {right_text(e['q'])[:40]})"
            + (f" — причина: {ERROR_KINDS[e['kind']]}" if e.get("kind") else "") for e in errs[:8]))
    for p in visible(session):
        head = (f"[{p['id']}] {STAGE_RU[panel_stage(p, session)]} · {PANEL_RU[p['type']]} «{p['title']}»"
                + (" (поставил человек)" if p.get("by") == "me" else ""))
        ans = session.get("answers", {}).get(p["id"])
        if p["type"] == "quiz":
            if ans is None:
                head += f" — {len(p['questions'])} вопр., ещё не ответил"
            else:
                head += f" — ответил, {ans['score_pct']}%" if ans.get("score_pct") is not None else " — ответил"
                head += "".join(f"\n    {m}" for m in _quiz_marks(session, p, ans))
        elif p["type"] == "video":
            head += f" — {p.get('url') or 'поиск: ' + p.get('query', '')}"
        elif p["type"] == "note":
            head += f" — {p['path']}"
        lines.append(head)
    out = "<study>\nУчебная сессия по этапам в разделе «Обучение» (её видит человек):\n" + "\n".join(lines)
    if excerpt := note_excerpt(core, note_path):
        out += f"\nЗаметка урока {note_path} — что он уже написал сам:\n{excerpt}"
    out += ("\nМожешь добавить окно действием study_panel (поле panel) на текущий этап: ошибка → разбор и похожая задача "
            "(quiz с short и why); «покажи график» → board; «найди видео» → video с query, ролики найдёт код. Тот же id — "
            "заменить окно, hidden=true — скрыть. Прислал фото решения — проверь по шагам, где ошибка. Заметку за него "
            "не пиши: он пишет своими словами.\n</study>")
    return out


def quiz_summary(core: Any, task_id: str) -> str:
    """Тесты и работа над ошибками сессии — для оценки блока (голова №2): открытые она оценивает вместе с проверкой."""
    session = session_of(core, task_id)
    rows = []
    if r := route(session):
        rows.append(f"Диагностика: {r['right']} из {r['total']} ({r['pct']}%)" + (f", слабые: {', '.join(r['weak'])}" if r["weak"] else ""))
    for p in visible(session):
        ans = session.get("answers", {}).get(p["id"])
        if p["type"] != "quiz" or ans is None:
            continue
        rows.append(f"{STAGE_RU[panel_stage(p, session)]} «{p['title']}»:")
        for q, given, ok in zip(p["questions"], ans["answers"], ans["results"]):
            if ok is None:
                rows.append(f"- {q['q']} → «{str(given)[:300]}» (эталон: {q.get('a', '')})")
            else:
                rows.append(f"- {q['q']} → {'верно' if ok else 'неверно'}")
    errs = errors(session)
    if errs:
        rows.append(f"Работа над ошибками: закрыто {sum(e['closed'] for e in errs)} из {len(errs)}"
                    + "".join(f"; «{e['q']['q'][:60]}» — {ERROR_KINDS[e['kind']]}" for e in errs if e.get("kind")))
    return "\n".join(rows)


def open_gaps(core: Any, task_id: str) -> list[str]:
    """Незакрытые ошибки — подтемы для повторения (review.py)."""
    out: list[str] = []
    for e in errors(session_of(core, task_id)):
        if not e["closed"]:
            label = e["q"].get("skill") or e["q"]["q"][:80]
            if label not in out:
                out.append(label)
    return out


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


# --- этапы из плана урока ---------------------------------------------------------------------------

def stage_plan(plan: list[dict[str, Any]], minutes: int) -> dict[str, dict[str, Any]]:
    """План по минутам → этапы: шаги с полем stage; план без него (до D60) раскладывается по порядку:
    первый — диагностика, второй — разбор, последний — проверка, «ошибки» в тексте — работа над ошибками."""
    steps = [s for s in plan or [] if isinstance(s, dict) and s.get("step")]
    n = len(steps)
    tags: list[str] = []
    for i, s in enumerate(steps):
        if s.get("stage") in STAGES:
            tags.append(s["stage"])
        elif i == 0 and n >= 3:
            tags.append("diag")
        elif i == n - 1 and n >= 2:
            tags.append("check")
        elif i == 1 and n >= 4:
            tags.append("learn")
        elif "ошиб" in str(s.get("step", "")).lower():
            tags.append("fix")
        else:
            tags.append("practice" if n >= 3 else "learn")
    out: dict[str, dict[str, Any]] = {}
    for s, tag in zip(steps, tags):
        a, b = int(_num(s.get("from_min"))), int(_num(s.get("to_min")))
        row = out.setdefault(tag, {"from": a, "to": b, "steps": []})
        row["from"], row["to"] = min(row["from"], a), max(row["to"], b)
        row["steps"].append({"step": _text(s.get("step"), 400), "tool": _text(s.get("tool"), 160)})
    for tag in out.values():
        tag["to"] = min(max(tag["to"], tag["from"]), max(minutes, 1))
    return out
