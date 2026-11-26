"""Шаблоны сообщений L0 — чистые строки, без модели (01-ARCHITECTURE §3.2, 05-INTERFACES §2.4).

Формулировки без глаголов прошедшего времени с родом («сделано?», а не
«выполнил?»): род человека бот узнаёт только в интервью.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from arvix import interview, rules
from arvix.context import DAY_TYPES_RU, QUOTA_RU, autonomy_line, hm

WEEKDAYS_FULL = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")

HELP = """Команды не нужны — пиши или говори голосом, как человеку.

— «Физику сделал, решил 12 задач» — закрою задачу
— «Спал 6:10, лёг в час» — запишу сон
— «Добавь на завтра алгоритмы в 16:00 на 90 минут»
— «Пн–пт школа до 14, после — физика и математика, в субботу зал» — соберу распорядок
— «Как готовиться к 15 номеру?» — шаги в твоих инструментах: что сделать и чем
— «Давай позанимаемся физикой 45 минут» — блок, шаги и таймер
— «Засеки 25 минут на английский» — фокус-таймер
— «Какая погода?» · «Что у меня сегодня?» · «Как неделя?»
— «Запомни: пробник по информатике 21 ноября» — запомню дословно
— «Найди в моих заметках алгоритм обучения» — поищу в Obsidian
— «Почему так, а не иначе?» — поспорю с аргументами

Задачи, таймер фокуса, отчёты с фото, заметки и прогресс — в приложении (кнопка 📱 внизу).
Здесь — разговор и напоминания."""

# Клавиатура под полем ввода (05-INTERFACES §2.7). С D50 в ней только «📱 Приложение»: день, фокус,
# отчёт — в приложении. Тексты прежних кнопок бот понимает по MENU, пока у человека старая клавиатура.
MENU_DAY, MENU_DONE, MENU_FOCUS = "📋 День", "✅ Сделал", "🎯 Фокус"
MENU_SLEEP, MENU_ADD, MENU_STATUS = "😴 Сон", "➕ Задача", "📊 Итоги"
MENU_STATUS_OLD = "📊 Статус"  # клавиатура, присланная до 0.6, шлёт старый текст — понимаем и его
MENU_APP = "📱 Приложение"
KEYBOARD = [[MENU_DAY, MENU_DONE, MENU_FOCUS], [MENU_SLEEP, MENU_ADD, MENU_STATUS]]
APP_KEYBOARD = [[MENU_DAY, MENU_DONE, MENU_FOCUS], [MENU_SLEEP, MENU_ADD, MENU_STATUS], [MENU_APP]]
MENU = {MENU_DAY: "day", MENU_DONE: "done", MENU_FOCUS: "focus", MENU_SLEEP: "sleep", MENU_ADD: "add", MENU_STATUS: "status",
        MENU_STATUS_OLD: "status",
        MENU_APP: "app"}


def keyboard(app_url: str = "") -> list[list[str]]:
    """Одна кнопка «📱 Приложение» (Mini App прямо в Telegram); без адреса приложения — [] снимает клавиатуру (D50)."""
    return [[MENU_APP]] if app_url else []

# Меню «/» в Telegram пустое: с Arvix говорят словами (D23). Команды остались
# скрытыми запасными путями (/mentor on — только так, safety; остальные — по старой памяти).
COMMANDS: list[tuple[str, str]] = []
FOCUS_DEFAULT_MIN = 25
FOCUS_MIN_LOGGED = 5  # короче — не сессия, а ложный старт
FOCUS_CHOICES = (15, 25, 45, 60, 90)
FOCUS_MAX_PAUSE_MIN = 15  # дольше — это уже не пауза, а конец сессии
PANEL_TITLE_MAX = 22

ONBOARD_INTRO = (
    f"Чтобы держать твой день, мне нужно тебя знать. {len(interview.QUESTIONS)} вопросов, "
    f"{len(interview.BLOCKS)} блоков, страхи — последними. Не за один вечер: полезный минимум — "
    "«Ядро» и «Распорядок дня», остальное по блоку за вечер.\n"
    "Отвечай как есть, коротко можно. /skip — пропустить вопрос, /pause — остановиться, /onboard — продолжить.\n"
    "Начнём с ядра: без него система не запустится."
)
ONBOARD_DONE = "Знакомство пройдено. Профиль появится в Obsidian (05_System/Профиль Arvix.md) после /export. Дальше — /schedule: соберу распорядок дня."
ASK_REPORT = "Одним предложением: что именно сделано?"
ASK_PHOTO = "Фото-отчёт: пришли фото с подписью. Или одним предложением — что сделано."
ASK_PARTIAL = "Сколько процентов сделано и что помешало? Например: «60, не хватило времени»."
ASK_FAIL_REASON = "Что помешало? Одной фразой — это пойдёт в разбор."
FALLBACK = "Голова сейчас недоступна — лимит подписки или сеть. Сообщение в журнале, отвечу, когда связь вернётся. Учёт и напоминания работают."
REGION_HINT = "Claude отклонил запрос из этой сети — включи VPN (AmneziaVPN) и напиши ещё раз."
GENTLE_FALLBACK = "Я рядом. Сегодня без планов и цифр: поесть, немного движения, лечь пораньше. Одна маленькая вещь — любая."
DEBRIEF_FALLBACK_QUESTIONS = ["Что сегодня сработало — конкретно?", "Что помешало и что меняем завтра?"]
RETURN_HINT = (
    "<return_protocol>Человек вернулся после {days} дн молчания. Никакого разбора прошлого и никаких цифр за пропуск. "
    "Один вопрос «что случилось» и один маленький шаг на сегодня. Разбор пропущенного — не раньше чем через 3 дня стабильной работы.</return_protocol>"
)
VOICE_OFF = (
    "Голосовые пока не настроены — напиши текстом. Включить: на машине с ботом `arvix setup --stt groq` "
    "(ключ Groq, бесплатно) или локально без интернета — deploy/stt-local.sh."
)
IGNORE_DAY2 = "Второй день тишины. Одно слово — и я пойму, что происходит."
IGNORE = {
    2: "Три дня. Я не знаю, что происходит, и это хуже, чем провал. Напиши одно слово.",
}
IGNORE_LATER = "Я здесь."
SILENT_TODAY = "Ты сегодня молчишь. Что происходит?"


def task_buttons_before(task_id: str) -> list[list[tuple[str, str]]]:
    return [[("Начать сейчас", f"t:{task_id}:start"), ("Отложить 15", f"t:{task_id}:d15")], [("Не смогу", f"t:{task_id}:no")]]


def task_buttons_check(task_id: str) -> list[list[tuple[str, str]]]:
    return [[("✅ Да", f"t:{task_id}:yes"), ("⚠️ Частично", f"t:{task_id}:part"), ("❌ Нет", f"t:{task_id}:no")]]


def reminder_before(task: Any, minutes: int) -> str:
    debt = " · ДОЛГ" if task.status == "debt" or task.debt_since else ""
    return f"⏱ Через {minutes} мин: {task.title} · {task.duration_min} мин{debt}"


def reminder_start(task: Any) -> str:
    return f"▶️ Блок пошёл: {task.title}. {task.duration_min} минут. Телефон — убрать."


def reminder_check(task: Any) -> str:
    """«Сделано?» — с критерием из шагов (D62): отчёт сверяется с результатом, а не с отсиженными минутами."""
    done = (getattr(task, "guide", None) or {}).get("done") or ""
    return f"Сделано: {task.title}?" + (f"\nГотово, когда: {done}" if done else "")


def completed(title: str, debt_closed: bool = False) -> str:
    """Факт без очков (D41): что закрыто — и закрыт ли этим долг."""
    return f"✅ {title} — записал" + (" · долг закрыт" if debt_closed else "")


RED_PANEL = "📋 День восстановления: без плана и без цифр. Одна маленькая вещь — любая.\nОтдохнул — верни план кнопкой."


def red_buttons(refresh: bool = True) -> list[list[tuple[str, str]]]:
    """Из 🟥 есть выход, и он у человека в руках, а не у модели (D38)."""
    rows = [[("▶️ Вернуться к плану", "r:back"), ("🌿 Ещё отдыхаю", "r:rest")]]
    if refresh:
        rows.append([("🎯 15 мин", "f:go:15"), ("🔄", "p:refresh")])
    return rows


BED_BUTTONS = [[("🌙 Ложусь", "z:bed")]]
ASK_SLEEP = "🛌 Как спал? Ответь «7:20» или словами — «лёг в час, встал в 8:30»."
SLEEP_EDIT = "Напиши, как было: «лёг в час, встал в 8:30» или просто «7:20»."
_BED_SRC = {"noted": "ты написал, что ложишься", "last": "последнее сообщение"}


def goodnight(at: str) -> str:
    return f"Спокойной ночи. Отбой — {at}, утром сверю с подъёмом."


def sleep_question(guess: dict[str, Any] | None) -> tuple[str, list[list[tuple[str, str]]] | None]:
    """Утренний вопрос о сне (D48): с догадкой — одна кнопка «Да», без неё — обычный вопрос."""
    if not guess:
        return ASK_SLEEP, None
    span = f"{guess['bedtime']}-{guess['wake']}"
    text = (f"🛌 Ночь: отбой ≈{guess['bedtime']} ({_BED_SRC[guess['bed_src']]}), подъём ≈{guess['wake']} (первое сообщение) "
            f"→ {hm(guess['duration_min'])}. Так?\nЕсли нет — напиши, как было.")
    return text, [[(f"✅ Да, {hm(guess['duration_min'])}", f"z:ok:{span}"), ("✏️ Иначе", "z:edit")]]


def sleep_logged(result: dict[str, Any]) -> str:
    """«Сон 7ч30м (01:00–08:30). Режим: 🟥 → 🟨 ЖЁЛТЫЙ» — смена режима видна сразу."""
    span = f" ({result['bedtime']}–{result['wake']})" if result.get("bedtime") and result.get("wake") else ""
    before, after = result.get("mode_before"), result["mode"]
    shift = f"{rules.MODE_LABELS[before].split()[0]} → " if before and before != after else ""
    return f"Сон {hm(result['duration_min'])}{span}. Режим: {shift}{rules.MODE_LABELS[after]}"


def when_day(core: Any, iso: str | None) -> str:
    """«2026-11-22» → «завтра», «через 3 дня (24.11)»: когда что-то будет, словами, а не датой."""
    if not iso:
        return "—"
    from datetime import date as _date

    day = _date.fromisoformat(iso)
    n = (day - core.today()).days
    if n <= 0:
        return "сегодня"
    if n == 1:
        return "завтра"
    if n == 2:
        return "послезавтра"
    return f"через {n} {'дня' if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 'дней'} ({day:%d.%m})"


def warn(lines: list[str] | tuple[str, ...] | None) -> str:
    """Сомнения кода (checks.py) — отдельными строками под ответом: их видно, их нельзя пропустить."""
    return "".join(f"\n⚠️ Проверь: {line}" for line in lines or ())


def failed(title: str, debt: bool) -> str:
    return f"❌ {title} — не сделано" + (" · ушла в долг" if debt else "")


def safety(support: str | None) -> str:
    person = f", например {support}" if support else ""
    return (
        "Похоже, тебе сейчас по-настоящему тяжело. Режим ментора выключен: никаких задач и цифр.\n"
        f"Это не то, с чем должен справляться бот. Напиши или позвони живому человеку{person} — прямо сейчас. "
        "Если есть угроза жизни — 112.\n"
        "Я здесь, если захочется просто написать. Вернуть режим ментора — /mentor on, когда решишь."
    )


def _task_short(task: Any) -> str:
    debt = ", ДОЛГ" if task.debt_since else ""
    return f"{task.start or '--:--'} {task.title} ({task.duration_min} мин{debt})"


def short_title(title: str, limit: int = PANEL_TITLE_MAX) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip(" :,-") + "…"


PANEL_ICON = {"planned": "○", "active": "▶️", "done": "✅", "failed": "❌", "debt": "🔴", "cancelled": "✖️", "written_off": "✖️"}


def day_panel(core: Any, d: Any = None) -> str:
    """Панель дня — одно сообщение, которое бот правит на месте (05-INTERFACES §2.7).
    Шапка — факты: сколько сделано и режим. Ни очков, ни здоровья, ни серии (D41)."""
    st = core.state
    today = d or core.today()
    tasks = st.tasks_on(today)
    done = sum(1 for t in tasks if t.status == "done")
    head = f"📋 {WEEKDAYS_FULL[today.weekday()]} · {done} из {len(tasks)}" if tasks else f"📋 {WEEKDAYS_FULL[today.weekday()]}"
    head += f" · {rules.MODE_LABELS[core.effective_mode()].split()[0]}"
    lines = [head]
    day = st.days.get(today)
    if day and day.deep_min:
        lines.append(f"Глубокая {hm(day.deep_min)} из {hm(core.deep_target(today))}")
    for task in tasks:
        line = f"{PANEL_ICON.get(task.status, '○')} {task.start or '--:--'} {task.title} ({task.duration_min} мин)"
        if task.status == "active" and task.actual_start:
            line += f" — идёт с {task.actual_start[11:16]}"
        elif task.status == "done" and task.done_pct < 100:
            line += f" — {task.done_pct}%"
        lines.append(line)
    if not tasks:
        lines.append("Задач нет. ➕ — добавить, или напиши, что делаешь.")
    debts = [t for t in st.debts() if t.local_date != today]
    if debts:
        lines.append("Долг: " + ", ".join(f"{t.title} ({(today - t.debt_since).days} дн)" for t in debts[:3] if t.debt_since))
    if focus := core.store.kv_get("focus"):
        lines.append(f"🎯 Фокус идёт до {focus['until'][11:16]}")
    return "\n".join(lines)


def panel_buttons(tasks: list[Any], focus_running: bool = False) -> list[list[tuple[str, str]]]:
    """Строка кнопок на каждую открытую задачу: начать или закрыть, частично, отложить на 30.
    «Не смогу» здесь нет намеренно: провал — только в напоминании или словами, не случайным нажатием."""
    rows: list[list[tuple[str, str]]] = []
    for task in tasks:
        if task.status == "planned":
            rows.append([(f"▶️ {short_title(task.title)}", f"t:{task.id}:start"), ("✅", f"t:{task.id}:yes"), ("⏳ 30", f"t:{task.id}:d30")])
        elif task.status == "active":
            rows.append([(f"✅ {short_title(task.title)}", f"t:{task.id}:yes"), ("⚠️ частично", f"t:{task.id}:part")])
    focus = ("⏹ стоп", "f:stop") if focus_running else (f"🎯 {FOCUS_DEFAULT_MIN} мин", "p:focus")
    rows.append([("🔄", "p:refresh"), focus, ("➕", "p:add")])
    return rows


def focus_text(minutes: int, until: str, title: str | None, left: int | None = None) -> str:
    what = f" · {title}" if title else ""
    if left is None:
        return f"🎯 Фокус {minutes} мин{what}\nДо {until}. Телефон убрать."
    if left <= 0:
        return f"🎯 Фокус {minutes} мин{what} — закончен."
    return f"🎯 Фокус {minutes} мин{what}\nДо {until} · осталось {left} мин."


def focus_paused_text(minutes: int, title: str | None, left: int, max_pause: int) -> str:
    what = f" · {title}" if title else ""
    return f"⏸ Фокус {minutes} мин{what} — пауза\nОсталось {left} мин. Пауза дольше {max_pause} мин закроет сессию."


def brief(core: Any) -> str:
    st = core.state
    now = core.now()
    today = now.date()
    day = st.days.get(today)
    head = f"☀️ {now:%H:%M} · {WEEKDAYS_FULL[today.weekday()]}"
    if day and day.day_type:
        head += f" · {DAY_TYPES_RU.get(day.day_type, day.day_type)} день"
    if core.effective_mode() == "red":
        text = head + "\n\nСегодня без плана и без цифр. Сон, еда, движение и одна маленькая вещь — любая. Я рядом."
        if not (day and day.sleep_min):  # сон — главный выход из 🟥: без него режим не узнает, что ты отдохнул
            text += "\nКак спалось? Напиши, во сколько лёг и встал — например «лёг в час, встал в 8:30»."
        return text
    lines = [head, ""]
    mode = rules.MODE_LABELS[st.mode] + (f" — {st.mode_trigger}" if st.mode_trigger else "")
    lines.append(f"Режим {mode}.")
    yesterday = st.days.get(today - timedelta(days=1))
    if yesterday and yesterday.closed and yesterday.closed.get("total"):
        lines.append(f"Вчера: {yesterday.closed['done']} из {yesterday.closed['total']}, глубокая {hm(yesterday.deep_min)}.")
    tasks = [t for t in st.tasks_on(today) if t.is_open]
    if tasks:
        lines += ["", f"Сегодня {len(tasks)}:"] + [f"{i}. {_task_short(t)}" for i, t in enumerate(tasks[:6], 1)]
    else:
        lines.append("Плана на сегодня нет. Напиши, что делаешь, — соберу.")
    if st.mentor_enabled:
        from arvix.learning_focus import reviews_due

        due = reviews_due(core)
        if due:
            lines.append("Пора повторить: " + ", ".join(topic["title"] for topic in due[:3]) + " · приложение → Обучение")
    debts = st.debts()
    if debts:
        lines.append("Долг: " + ", ".join(t.title for t in debts[:3]))
    budget = core.budget()
    if budget["auto"] and budget["since"] == today.isoformat() and budget.get("change"):
        lines.append(f"Нагрузка недели: {budget['change']} — {budget['reason']}.")
    week = st.week_stats(today)
    quotas = core.cfg.mech("quotas") or {}
    if today.weekday() >= 2:
        missing = [f"{QUOTA_RU.get(k, k)} {week['quotas'].get(k, 0)}/{v}" for k, v in quotas.items() if week["quotas"].get(k, 0) < v]
        if missing:
            lines.append("Квоты недели: " + " · ".join(missing))
    if st.profile.get("bedtime_target"):
        lines.append(f"Отбой сегодня в {st.profile['bedtime_target']}. Не обсуждается.")
    if not st.templates:
        lines.append("\nРаспорядка дня нет — без него нет задач и напоминаний. /schedule — соберу за минуту.")
    status = core.interview_status()
    left = status["total"] - status["answered"] - len(st.interview_skipped)
    if left > 0:
        lines.append(f"Знакомство: осталось {left} вопросов — /onboard.")
    if today.weekday() == 0:
        budget = core.budget()
        lines.append(f"Нагрузка недели: {hm(budget['week_min'])}, из них глубокой {hm(budget['deep_min'])}." + (f" {budget['reason']}." if budget.get("reason") else ""))
    return "\n".join(lines)


def midday(core: Any) -> str | None:
    st = core.state
    today = core.today()
    tasks = st.tasks_on(today)
    completion = st.completion(today)
    if not tasks or completion is None or completion >= 40:
        return None
    done = sum(1 for t in tasks if t.status == "done")
    nxt = next((t for t in tasks if t.is_open and t.start and t.start >= core.now().strftime("%H:%M")), None)
    text = f"Середина дня: {done} из {len(tasks)}."
    if nxt:
        text += f" Следующий блок {nxt.start} — «{nxt.title}». Он решает, каким будет день."
    return text


def debrief_facts(core: Any) -> str:
    facts = core.day_facts()
    lines = ["🌙 Разбор", "", f"Сделано: {facts['done']} из {facts['total']}. Глубокая {hm(facts['deep_min'])} из {hm(core.deep_target(facts['date']))}."]
    if facts["sleep_min"]:
        lines.append(f"Сон {hm(facts['sleep_min'])}.")
    quotas = core.cfg.mech("quotas") or {}
    lines.append("Квоты: " + " · ".join(f"{QUOTA_RU.get(k, k)} {facts['week']['quotas'].get(k, 0)}/{v}" for k, v in quotas.items()))
    if facts["debts"]:
        lines.append("Долг: " + ", ".join(t.title for t in facts["debts"]))
    if facts["impulse"]:
        lines.append("Импульсивные траты: " + ", ".join(f"{e['amount']:.0f} {e['category']}" for e in facts["impulse"]))
    return "\n".join(lines)


def status(core: Any) -> str:
    """📊 Итоги — только факты из журнала (D41): ни уровней, ни очков, ни здоровья.
    В 🟥 и при выключенном менторе — без цифр (правило №5)."""
    s = core.status()
    if s["effective_mode"] == "red":
        if not s["mentor_enabled"]:
            return "Режим: 🟥 — ментор выключен safety-контуром. Без цифр. Вернуть: /mentor on"
        return f"Режим: 🟥 — день восстановления, без цифр. Выход: {core.red_exit()}."
    lines = [f"Режим: {rules.MODE_LABELS[s['effective_mode']]}" + (f" ({s['mode_trigger']})" if s["mode_trigger"] else "")]
    pct = f" ({s['completion']:.0f}%)" if s["completion"] is not None else ""
    lines.append(f"Сегодня: {s['done']} из {s['total']}{pct}" if s["total"] else "Сегодня задач нет")
    lines.append(f"Неделя: сделано {hm(s['week_min'])} из {hm(s['week_budget'])} · глубокая {hm(s['week_deep'])} из {hm(s['week_deep_budget'])}")
    if s["sleep_avg"]:
        lines.append(f"Сон за {s['sleep_days']} дн: в среднем {hm(s['sleep_avg'])} при норме {hm(s['sleep_target'])}")
    if s["debts"]:
        lines.append(f"Долг: {s['debts']}")
    if line := autonomy_line(s["autonomy"]):
        lines.append(line)
    return "\n".join(lines)


def week(core: Any) -> str:
    stats = core.state.week_stats(core.today())
    quotas = core.cfg.mech("quotas") or {}
    lines = [
        f"Неделя с {stats['start']:%d.%m}",
        f"Продуктивно {hm(stats['productive_min'])} из {hm(core.budget()['week_min'])} · глубокая {hm(stats['deep_min'])} из {hm(core.budget()['deep_min'])}",
        "Квоты: " + " · ".join(f"{QUOTA_RU.get(k, k)} {stats['quotas'].get(k, 0)}/{v}" for k, v in quotas.items()),
    ]
    if stats["expenses"]:
        top = sorted(stats["expenses"].items(), key=lambda x: -x[1])[:3]
        lines.append("Траты: " + ", ".join(f"{k} {v:.0f}" for k, v in top) + (f" · импульсивные {stats['impulse']:.0f}" if stats["impulse"] else ""))
    return "\n".join(lines)


def question(q: dict[str, Any], number: int, total: int) -> str:
    return f"[{q['block_title']} · {number}/{total}]\n{q['text']}"
