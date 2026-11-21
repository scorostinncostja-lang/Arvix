"""Учебный блок (06-LEARNING §8): задача сферы learning → урок по роадмапу и методу человека.

Голова зовётся дважды за блок: в начале — наполнение этапов сессии (D60: диагностика, разбор, практика,
работа над ошибками, проверка) — задачи с ответами, подтемы с разбором, запрос видео, план по минутам
(LESSON_SCHEMA); в конце — оценка ответов на проверку (CHECK_SCHEMA). Между ними модель не нужна: этапы,
уровень, проверка задач, ошибки, таймер, каркас заметки, поиск видео и запись результата — код. Объяснение
«у доски» — обычный вызов L1 с блоком <lesson> в промпте, когда человек спрашивает.

Здесь — чистые функции: схемы, тексты правил, рендер, каркас заметки, запасной план.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from arvix.study import PANEL_RULES, PANEL_SCHEMA, QUESTION_SCHEMA, STAGE_RU, STAGES
from arvix.vault import render_template

LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "тема блока — конкретная, как узел роадмапа"},
        "why": {"type": "string", "description": "одной строкой: что даёт для цели (номер задания, баллы, этап)"},
        "roadmap_node": {"type": "string", "description": "узел роадмапа и его положение, например «Постоянный ток (3/12)»; пусто — роадмапа нет"},
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "enum": list(STAGES), "description": "этап сессии, к которому шаг относится"},
                    "from_min": {"type": "integer"}, "to_min": {"type": "integer"},
                    "step": {"type": "string", "description": "что делать руками на этом этапе, одной фразой"},
                    "tool": {"type": "string", "description": "инструмент: учебник §, Решу ОГЭ №, Obsidian, Anki…"},
                },
                "required": ["stage", "from_min", "to_min", "step"],
            },
        },
        "diagnostic": {"type": "array", "items": QUESTION_SCHEMA,
                       "description": "диагностика: 4–5 задач от простой к сложной; short или options+answer, why, skill, level, twin"},
        "skills": {
            "type": "array", "description": "2–4 подтемы — для разбора по ошибкам диагностики",
            "items": {"type": "object", "properties": {
                "name": {"type": "string", "description": "подтема — то же имя, что в skill задач"},
                "explain": {"type": "string", "description": "разбор у доски, markdown, до 900 знаков: правило → пример с решением по шагам → ловушка"},
                "source": {"type": "string", "description": "учебник и параграф или документ"},
            }, "required": ["name", "explain"]},
        },
        "practice": {"type": "array", "items": QUESTION_SCHEMA,
                     "description": "практика: 5–6 задач от простой к сложной; short или options+answer, why, skill, level, twin"},
        "video_query": {"type": "string", "description": "запрос для поиска видео-объяснения темы: тема + экзамен и номер задания; ролики найдёт код"},
        "sources": {"type": "array", "items": {"type": "string"}, "description": "первоисточник первым; видео и заметки человека — после"},
        "check": {
            "type": "array",
            "items": {"type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string", "description": "короткий эталон для оценки"}}, "required": ["q", "a"]},
        },
        "note_title": {"type": "string", "description": "название заметки-конспекта для каркаса, 2–5 слов"},
        "panels": {"type": "array", "items": PANEL_SCHEMA, "description": "0–2 окна для разбора: доска или схема"},
    },
    "required": ["topic", "why", "plan", "diagnostic", "skills", "practice", "sources", "check"],
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "is_answer": {"type": "boolean", "description": "сообщение — попытка ответить на вопросы проверки (в том числе «не знаю»)? "
                                                        "Приветствие, вопрос о другом, разговор — false"},
        "score_pct": {"type": "integer", "description": "доля верного 0–100"},
        "feedback": {"type": "string", "description": "для человека: что верно, что нет и почему, что дочитать; абзацы через пустую строку"},
        "gaps": {"type": "array", "items": {"type": "string"}, "description": "пробелы — по одному, формулировкой для карточки"},
        "next_step": {"type": "string", "description": "одно действие на следующий блок"},
    },
    "required": ["is_answer", "score_pct", "feedback", "gaps"],
}

LESSON_RULES = """<lesson_plan>
Ты готовишь учебную сессию на {minutes} минут: задача «{title}», сфера {sphere}, сегодня {date}.
Сначала коротко посмотри в хранилище (Read, Grep, Glob; 2–4 файла, не больше): роадмап предмета ({roadmaps}; файлы
со словом «Роадмап», папка 02_Areas), журнал ошибок, заметки человека о методе обучения ({methods}).
Прошлые уроки по этому предмету: {history}.{gaps}{hint}
Тема — следующий незакрытый узел роадмапа после прошлых уроков; роадмапа нет — ближайшая тема по цели (для ОГЭ —
кодификатор и демоверсия ФИПИ), и скажи в why, что роадмапа нет.

Сессия идёт по алгоритму из пяти этапов — он одинаков для любой темы, ты наполняешь его под тему и человека:
1. diag, Диагностика (~15% времени) — diagnostic: 4–5 задач от простой к сложной, по одной-две на подтему (skill),
   в формате экзамена. Ответ — short (число или слово, как в бланке ОГЭ; другие верные записи — в accept) или
   options + answer. Открытых в диагностике нет: проверяет код. У каждой — why (решение в 1–2 строки), level
   (1–3) и twin — похожая задача с другими числами и своим short (или options + answer) и why.
2. learn, Разбор (~25%) — skills: 2–4 подтемы, те же имена, что в skill задач. explain — разбор у доски, markdown,
   до 900 знаков: правило одной строкой → пример с решением по шагам → типичная ловушка; source — учебник и параграф.
   Человек увидит только подтемы, где ошибся. video_query — запрос для поиска видео-объяснения (ролики найдёт код).
   {panels}
3. practice, Практика (~35%) — practice: 5–6 задач от простой к сложной, как diagnostic (short/options, why, skill,
   level, twin); последние — уровня экзамена. Тема-практика (код, упражнение): short — результат (вывод, число).
4. fix, Работа над ошибками (~15%) — ошибки и похожие задачи соберёт код из diagnostic и practice.
5. check, Проверка (~10%) — check: ровно {questions} вопроса на понимание и применение, один — задача; у каждого эталон a.
plan — по шагу на каждый этап (stage) с минутами на весь блок: что делать руками и чем — инструменты человека из его
заметок и профиля{tools}: тетрадь, учебник с параграфом, NotebookLM (выжимка главы, вопросы на понимание), Решу ОГЭ
или банк ФИПИ с номером задания, Obsidian, Anki; Gemini — только сократовский вопрос при затыке. Новых не навязывай.
{language}Проверь каждое число сам: short проверяет код, ошибка эталона станет ложной ошибкой человека.
sources — первоисточник первым (учебник и параграф, документ ФИПИ, документация), затем заметки человека (путь
в хранилище). Выдуманный адрес хуже отсутствия ссылки. Названия точные, всё по-русски.
</lesson_plan>"""

LANGUAGE_RULES = """Это иностранный язык ({lang_ru}). Метод человека (его заметка об английском): понятный вход i+1, транскрипция
ролика слово в слово, добыча предложений целиком, shadowing, без перевода через русский. Поэтому:
- diagnostic — задания на {lang_ru} по теме и уровню: слово в контексте, паттерн, «что значит фраза» — options или short;
  никакого «переведи на русский». why — по-английски простыми словами.
- skills — 2–3 паттерна или группы фраз; explain по-английски простым языком (A2–B1), 2–3 примера в предложениях;
  русский — одной строкой и только если без него не понять.
- video_query — запрос НА {lang_en} для ролика 2–8 минут под уровень (i+1: понятно 80–90 %): сцена из сериала с
  субтитрами, BBC Learning English, TED-Ed, VOA Learning English; для произношения — Rachel's English. Уровень словом
  (beginner / intermediate). Ищет код на YouTube; субтитры в плеере включатся сами.
- practice — задания на паттерны (fill the gap, выбери верное) — short/options. Диктант по ролику, shadowing и добычу
  слов код соберёт сам из субтитров.
- check — пересказ ролика 3–4 предложениями на {lang_en} (можно голосом) и два вопроса на паттерны; эталон a — суть.
- plan: learn — «ролик без субтитров, потом с субтитрами на языке; понял меньше половины — попроси проще»; practice —
  «диктант 5 фраз и shadowing 3 фраз»; fix — «ошибки диктанта: переслушай и запиши заново».
"""
LANG_EN = {"en": "АНГЛИЙСКОМ", "de": "НЕМЕЦКОМ", "fr": "ФРАНЦУЗСКОМ", "es": "ИСПАНСКОМ"}


def language_rules(lang: str | None) -> str:
    from arvix.media import LANGS

    if not lang:
        return ""
    return LANGUAGE_RULES.format(lang_ru=LANGS[lang], lang_en=LANG_EN.get(lang, "ЯЗЫКЕ УРОКА"))


CHECK_RULES = """<lesson_check>
Человек прошёл учебный блок по теме «{topic}», и это его сообщение в ответ на вопросы проверки.
Вопросы и эталоны:
{pairs}{quiz}
{where}
Оцени каждый ответ по сути, а не по словам: верно / частично / неверно. score_pct — доля верного, 0–100.
feedback — для человека, 2–3 коротких абзаца через пустую строку: что верно; что нет и почему, с правильной
мыслью в одну-две фразы, не целым конспектом; что дочитать — источник и раздел, минут на десять.
gaps — пробелы по одному, формулировкой для карточки Anki и журнала ошибок. next_step — одно действие на следующий блок.
Не льсти. Пустой ответ или «не знаю» — 0 за вопрос. В feedback нет оценок в процентах — их допишет код.
</lesson_check>"""
CHECK_SURE = "Он ответил из окна проверки — это ответ: is_answer = true."
CHECK_MAYBE = ("Сообщение пришло в общий чат, а не в окно проверки. Если это не попытка ответить (приветствие, «проснулся», "
               "вопрос о другом) — is_answer = false, остальные поля пустые: вопрос проверки останется, человек ответит позже.")

LESSON_CONTEXT = """<lesson>
Идёт учебный блок: «{topic}» ({title}, {minutes} мин, прошло {elapsed}).
План блока: {plan}
Вопрос по теме блока — объясняй у доски: по шагам, с одним примером, в конце один вопрос на понимание.
Это обучение, а не подсказка: подробно, но без воды, и не целым параграфом сразу — порцией на 2–3 минуты чтения.
Задачу за него не решай: один шаг и вопрос «что дальше?». Первоисточник называй.
Вопрос не по теме — одной строкой и вернуть к блоку. Отчёт о блоке сам не принимай: в конце будет проверка.
Сессия идёт по этапам (блок <study>): на разборе — объясняй то, где он ошибся на диагностике; на работе над ошибками —
почему ответ неверен и похожая задача (study_panel quiz с short и why), а не готовое решение его задачи.
</lesson>"""

DEFAULT_QUESTIONS = 3
DEFAULT_MINUTES = 45


FALLBACK_STEPS = {  # без головы: те же этапы, но руками — по учебнику и банку задач
    "diag": ("Вспомни с пустого листа всё, что знаешь по теме; реши 2–3 задачи без подсказок — где споткнулся?", "тетрадь"),
    "learn": ("Учебник, параграф по теме: правило и разобранный пример; закрой и запиши суть своими словами", "учебник · Obsidian"),
    "practice": ("Задачи по теме от простых к сложным, не подглядывая в решение", "Решу ОГЭ / банк ФИПИ"),
    "fix": ("Каждую ошибку — в журнал: что не так и правило; одну похожую задачу — заново", "журнал ошибок"),
    "check": ("Ответь, что именно сделано и где споткнулся", "Arvix"),
}
STAGE_SHARE = {"diag": 0.15, "learn": 0.25, "practice": 0.35, "fix": 0.15, "check": 0.10}


def fallback_plan(minutes: int) -> list[dict[str, Any]]:
    """План без головы: те же этапы алгоритма (D60), пропорционально длине блока."""
    m = max(minutes, 15)
    out, at = [], 0
    for stage in STAGES:
        end = m if stage == STAGES[-1] else min(m, at + max(2, round(m * STAGE_SHARE[stage])))
        step, tool = FALLBACK_STEPS[stage]
        out.append({"stage": stage, "from_min": at, "to_min": end, "step": step, "tool": tool})
        at = end
    return out


def render(lesson: dict[str, Any], task: Any, note_path: str | None = None) -> str:
    """Сообщение урока — код, не модель: этапы по минутам, источники, что будет в конце."""
    lines = [f"📚 {task.title} · {task.duration_min} мин", lesson.get("topic", "").strip()]
    if lesson.get("why"):
        lines.append(f"Зачем: {lesson['why'].strip()}")
    if lesson.get("roadmap_node"):
        lines.append(f"Роадмап: {lesson['roadmap_node'].strip()}")
    lines += ["", "Этапы:"]
    for step in lesson.get("plan") or []:
        span = f"{int(step.get('from_min', 0))}–{int(step.get('to_min', 0))}"
        tool = f" · {step['tool']}" if step.get("tool") else ""
        name = f"{STAGE_RU[step['stage']]}: " if step.get("stage") in STAGE_RU else ""
        lines.append(f"{span:>5}  {name}{step.get('step', '').strip()}{tool}")
    if lesson.get("sources"):
        lines += ["", "Источники: " + " · ".join(s.strip() for s in lesson["sources"] if s.strip())]
    if note_path:
        lines.append(f"📝 Каркас заметки: {note_path}")
    if have := windows_line(lesson.get("windows") or []):
        lines.append(f"🪟 В приложении, «Обучение»: {have} — ответы проверяются сразу, ошибки — в работу над ошибками.")
    n = len(lesson.get("check") or [])
    if n:
        lines.append(f"В конце — {n} вопроса, ответ одним сообщением (можно голосом). Это и будет отчёт.")
    else:
        lines.append("В конце — «Сделано?»: одной фразой, что именно сделано.")
    return "\n".join(line for line in lines if line is not None)


def windows_line(windows: list[dict[str, Any]]) -> str:
    """Что ждёт в приложении — по этапам, коротко: «диагностика (5 задач) · разбор (2) · видео · практика (6 задач)»."""
    out = []
    for stage, label in (("diag", "диагностика"), ("learn", "разбор"), ("practice", "практика")):
        mine = [p for p in windows if p.get("stage") == stage]
        quiz = sum(len(p.get("questions") or []) for p in mine if p["type"] == "quiz")
        if stage == "learn":
            texts = sum(1 for p in mine if p["type"] == "text")
            out += ([f"разбор ({texts})"] if texts else []) + (["видео"] if any(p["type"] == "video" for p in mine) else []) \
                + (["чертёж"] if any(p["type"] in ("board", "diagram") for p in mine) else [])
        elif quiz:
            out.append(f"{label} ({quiz} {'задача' if quiz == 1 else 'задачи' if quiz < 5 else 'задач'})")
    return " · ".join(out)


def render_check(lesson: dict[str, Any], *, early: bool = False) -> str:
    questions = [c["q"] for c in lesson.get("check") or []]
    head = ("" if early else "Время вышло. ") + f"Проверка по теме «{lesson.get('topic', '')}» — {len(questions)} вопроса, ответь одним сообщением, можно голосом:"
    return head + "\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))


def check_pairs(lesson: dict[str, Any]) -> str:
    return "\n".join(f"{i}. {c['q']}\n   эталон: {c['a']}" for i, c in enumerate(lesson.get("check") or [], 1))


def skeleton(template: str | None, title: str, subject: str, today: date, questions: list[str], sources: list[str]) -> str:
    """Каркас заметки по шаблону человека (Templates/Concept.md): заполняются только
    название, предмет, дата и вопросы самопроверки; остальное он пишет сам."""
    if template:
        # Те же переменные, что подставил бы Obsidian: {{title}}, {{ date:YYYY-MM-DD }} с пробелами, Templater.
        text = render_template(template, datetime.combine(today, datetime.min.time()), title)
        text = re.sub(r"^(subject:\s*)$", rf"\g<1>{subject}", text, count=1, flags=re.MULTILINE)
        checks = "\n".join(f"- [ ] {q}" for q in questions)
        text, n = re.subn(r"(## Самопроверка\n)(?:- \[ \][^\n]*\n?)*", rf"\g<1>{checks}\n", text, count=1)
        if not n:
            text = text.rstrip("\n") + "\n\n## Самопроверка\n" + checks + "\n"
        if sources:
            text = text.rstrip("\n") + "\n\n## Источники\n" + "\n".join(f"- {s}" for s in sources) + "\n"
        return text
    body = [f"# {title}", "", f"Предмет: {subject} · {today.isoformat()}", "",
            "> Суть одним предложением, своими словами:", ">", "", "## Объяснение по Фейнману", "", "## Пример", "",
            "## Типичные ошибки", "", "## Самопроверка"]
    body += [f"- [ ] {q}" for q in questions]
    if sources:
        body += ["", "## Источники"] + [f"- {s}" for s in sources]
    return "\n".join(body) + "\n"


QUEUE_PREFIXES = ("учить", "практика")  # projects.learn_start: «Учить: тема», «Практика: тема» — это не предмет


def subject_of(title: str) -> str:
    """«Физика: §44 постоянный ток» → «Физика»; «Математика ОГЭ» → «Математика ОГЭ»;
    «Практика: aiogram: хендлер» → «aiogram» (блок из очереди «учиться»: предмет — сама тема)."""
    head, *rest = re.split(r"[:—–-]", title, maxsplit=1)
    head = head.strip()
    if head.lower() in QUEUE_PREFIXES and rest and rest[0].strip():
        return subject_of(rest[0].strip())
    return head or title


def safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip()[:80]
